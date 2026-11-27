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


def test_cli_providers_run_without_tools_in_empty_dir(monkeypatch, tmp_path):
    import subprocess
    monkeypatch.setattr(llm, "cli_path", lambda b: f"/bin/{b}")
    llm.save_settings({"provider": "claude_code"})
    seen = {}

    def fake_run(cmd, **kw):
        seen.update(cmd=cmd, **kw)
        return subprocess.CompletedProcess(cmd, 0, stdout="  Hello.  \n", stderr="")
    monkeypatch.setattr(llm.subprocess, "run", fake_run)
    conf = llm.active()
    out = llm._chat(conf, "SYS", [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "ok"},
                                 {"role": "user", "content": "<dictation>x</dictation>"}])
    assert out == "Hello."
    cmd = seen["cmd"]
    assert cmd[:2] == ["/bin/claude", "-p"] and cmd[cmd.index("--tools") + 1] == ""  # no tools at all
    assert "--strict-mcp-config" in cmd and cmd[cmd.index("--system-prompt") + 1] == "SYS"
    assert seen["input"].endswith("User: <dictation>x</dictation>\n\nWrite only the Assistant's reply to the last User message.")
    assert seen["cwd"] != str(tmp_path) and "kiroku-cli-" in seen["cwd"]

    qwen = {**llm.PROVIDERS["qwen_code"], "id": "qwen_code", "model": ""}
    qcmd = llm._cli_command(qwen, "SYS")
    assert qcmd[qcmd.index("--approval-mode") + 1] == "plan" and "run_shell_command" in qcmd


def test_cli_errors_are_actionable(monkeypatch):
    import subprocess
    monkeypatch.setattr(llm, "cli_path", lambda b: None)
    llm.save_settings({"provider": "codex"})
    with pytest.raises(llm.LLMError, match="isn't installed"):
        llm.active()
    monkeypatch.setattr(llm, "cli_path", lambda b: "/bin/x")
    monkeypatch.setattr(llm.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 1, "", "Error: not logged in"))
    with pytest.raises(llm.LLMError, match="codex login"):
        llm._chat(llm.active(), "s", [{"role": "user", "content": "x"}])

    def hang(*a, **k):
        raise subprocess.TimeoutExpired("x", 1)
    monkeypatch.setattr(llm.subprocess, "run", hang)
    with pytest.raises(llm.LLMError, match="sign-in expired"):
        llm._chat(llm.active(), "s", [{"role": "user", "content": "x"}], fast=True)
