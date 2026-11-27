import pytest

from notetaker import llm


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(llm, "SETTINGS_PATH", tmp_path / "llm.json")
    monkeypatch.setattr(llm, "_get_key", lambda pid: None)
    llm.save_settings({"provider": "ollama", "providers": {"ollama": {"model": "m"}},
                       "dictation": {"cleanup": True, "dictionary": "Kiroku\nAsha\n"}})


RAW = "um so I think we should uh ship the the build on Friday no actually Monday"


@pytest.mark.parametrize("out,ok", [
    ("I think we should ship the build on Monday.", True),
    ("Groceries:\n- Rice\n- Dal", None),
    ("Paris", False),                                      # answered a question
    ("Banana", False),                                     # obeyed an instruction
    ("Vast blue expanse, waves crashing on the shore", False),
])
def test_faithful_guard(out, ok):
    if ok is None:  # list formatting of its own dictation is fine
        assert llm._faithful("groceries we need rice uh dal", out, []) == ""
    else:
        assert (llm._faithful(RAW, out, []) == "") is ok


def test_transliteration_rejected_codemix_kept():
    raw = "कल meeting में deck review करेंगे"
    assert llm._faithful(raw, "कल मीटिंग में डेक रिव्यू करेंगे।", []) != ""
    assert llm._faithful(raw, "कल meeting में deck review करेंगे।", []) == ""


def test_cleanup_uses_examples_style_and_dictionary(monkeypatch):
    seen = {}

    def fake_chat(conf, system, messages, schema=None, fast=False):
        seen.update(system=system, messages=messages, fast=fast)
        return "<dictation>Hey Asha, can you send the Kiroku doc?</dictation>"
    monkeypatch.setattr(llm, "_chat", fake_chat)
    r = llm.cleanup_dictation("hey asha can you send the kiroku doc", app="Slack")
    assert r["cleaned"] and r["text"] == "Hey Asha, can you send the Kiroku doc?" and r["raw"].startswith("hey")
    assert seen["fast"] and "chat message" in seen["system"] and "Kiroku, Asha" in seen["system"]
    assert seen["messages"][-1]["content"] == "<dictation>hey asha can you send the kiroku doc</dictation>"
    assert len(seen["messages"]) == 2 * len(llm._CLEANUP_EXAMPLES) + 1


def test_cleanup_falls_back_to_raw_on_bad_output_or_error(monkeypatch):
    monkeypatch.setattr(llm, "_chat", lambda *a, **k: "Paris")
    r = llm.cleanup_dictation("what is the capital of france")
    assert r["text"] == "what is the capital of france" and not r["cleaned"] and "rejected" in r["error"]

    def down(*a, **k):
        raise llm.LLMError("Can't reach Ollama")
    monkeypatch.setattr(llm, "_chat", down)
    assert llm.cleanup_dictation("hello there")["text"] == "hello there"


def test_cleanup_off_is_passthrough(monkeypatch):
    llm.save_settings({"dictation": {"cleanup": False}})
    monkeypatch.setattr(llm, "_chat", lambda *a, **k: pytest.fail("must not call the model"))
    assert llm.cleanup_dictation(" hi ") == {"text": "hi", "raw": "hi", "cleaned": False, "ms": 0, "error": ""}
