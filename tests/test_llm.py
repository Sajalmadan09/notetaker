import json

import pytest

from notetaker import llm

REC = {"id": "r1", "names": {"0": "Asha"}, "turns": [
    {"start": 0.0, "end": 5.0, "speaker": 0, "text": "कल तक deck भेज दूंगी"},
    {"start": 65.0, "end": 70.0, "speaker": 1, "text": "ठीक है, launch Monday को"}]}


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    keys = {}
    monkeypatch.setattr(llm, "SETTINGS_PATH", tmp_path / "llm.json")
    monkeypatch.setattr(llm, "_get_key", keys.get)
    monkeypatch.setattr(llm, "_set_key", lambda pid, k: keys.update({pid: k}) if k else keys.pop(pid, None))
    return keys


def test_key_is_write_only(isolated):
    s = llm.save_settings({"provider": "anthropic", "providers": {"anthropic": {"api_key": "sk-secret"}}})
    assert isolated["anthropic"] == "sk-secret"
    assert s["providers"]["anthropic"]["has_key"] is True
    assert "sk-secret" not in json.dumps(s) and "sk-secret" not in llm.SETTINGS_PATH.read_text()
    s = llm.save_settings({"providers": {"anthropic": {"api_key": ""}}})
    assert s["providers"]["anthropic"]["has_key"] is False


def test_active_explains_what_is_missing():
    with pytest.raises(llm.LLMError, match="Settings"):
        llm.active()
    llm.save_settings({"provider": "openai", "providers": {"openai": {"model": "m"}}})
    with pytest.raises(llm.LLMError, match="API key"):
        llm.active()
    llm.save_settings({"provider": "ollama", "providers": {"ollama": {"model": "qwen3:8b"}}})
    assert llm.active()["base_url"].startswith("http://127.0.0.1")
    with pytest.raises(llm.LLMError):
        llm.save_settings({"provider": "nope"})


def test_summarize_parses_and_uses_speaker_names(monkeypatch):
    llm.save_settings({"provider": "ollama", "providers": {"ollama": {"model": "m"}}})
    seen = {}

    def fake_chat(conf, system, messages, schema=None):
        seen["text"] = messages[0]["content"]
        return 'Sure! {"title": "Launch sync", "overview": "o", "decisions": ["Monday"],' \
               ' "action_items": [{"text": "Send deck", "owner": "Asha"}, {"text": ""}],' \
               ' "chapters": [{"title": "Launch", "start": 65}, {"title": "Invented", "start": 999}]}'
    monkeypatch.setattr(llm, "_chat", fake_chat)
    s = llm.summarize(REC)
    assert "[0:00] Asha:" in seen["text"] and "[1:05] Speaker 2:" in seen["text"]
    assert s["title"] == "Launch sync"
    assert s["action_items"] == [{"text": "Send deck", "owner": "Asha", "done": False}]
    assert [c["start"] for c in s["chapters"]] == [65.0] and s["model"] == "m"  # 999 > duration dropped


def test_summarize_rejects_garbage(monkeypatch):
    llm.save_settings({"provider": "ollama", "providers": {"ollama": {"model": "m"}}})
    monkeypatch.setattr(llm, "_chat", lambda *a, **k: "I cannot do that")
    with pytest.raises(llm.LLMError, match="didn't return"):
        llm.summarize(REC)
