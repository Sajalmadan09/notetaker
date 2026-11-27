"""Bring-your-own LLM: summaries, action items and Q&A over a recording's transcript.

Providers: Claude (official anthropic SDK), and anything OpenAI-compatible (OpenAI, Gemini's
OpenAI endpoint, Ollama / LM Studio / llama.cpp locally). API keys live in the macOS
Keychain via `keyring`, never in settings files. Non-secret settings: DATA/llm.json.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

from . import history, paths

SETTINGS_PATH = paths.DATA / "llm.json"
KEYCHAIN_SERVICE = "Kiroku"

PROVIDERS = {
    "ollama": {"label": "Ollama (on this Mac)", "kind": "openai", "local": True, "needs_key": False,
               "base_url": "http://127.0.0.1:11434/v1", "model": ""},
    "anthropic": {"label": "Claude (Anthropic)", "kind": "anthropic", "local": False, "needs_key": True,
                  "base_url": "", "model": "claude-opus-5-5"},
    "openai": {"label": "OpenAI", "kind": "openai", "local": False, "needs_key": True,
               "base_url": "https://api.openai.com/v1", "model": ""},
    "gemini": {"label": "Google Gemini", "kind": "openai", "local": False, "needs_key": True,
               "base_url": "https://generativelanguage.googleapis.com/v1beta/openai", "model": ""},
    "custom": {"label": "Custom (OpenAI-compatible)", "kind": "openai", "local": False, "needs_key": False,
               "base_url": "", "model": ""},
}
# Server-side refusal fallback is only accepted on these Claude models.
_FALLBACK_MODELS = {"claude-fable-5-2", "claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"}


class LLMError(RuntimeError):
    pass


# ---- settings + keychain -------------------------------------------------------------

def settings() -> dict:
    saved = json.loads(SETTINGS_PATH.read_text()) if SETTINGS_PATH.exists() else {}
    provider = saved.get("provider", "")
    out = {"provider": provider, "summary_language": saved.get("summary_language", "English"),
           "providers": {}}
    for pid, spec in PROVIDERS.items():
        mine = saved.get("providers", {}).get(pid, {})
        base = mine.get("base_url") or spec["base_url"]
        out["providers"][pid] = {**spec, "model": mine.get("model") or spec["model"], "base_url": base,
                                 "local": spec["local"] or urlparse(base).hostname in ("127.0.0.1", "localhost", "::1"),
                                 "has_key": _get_key(pid) is not None}
    return out


def save_settings(patch: dict) -> dict:
    saved = json.loads(SETTINGS_PATH.read_text()) if SETTINGS_PATH.exists() else {}
    if "provider" in patch:
        if patch["provider"] not in PROVIDERS and patch["provider"] != "":
            raise LLMError("unknown provider")
        saved["provider"] = patch["provider"]
    if "summary_language" in patch:
        saved["summary_language"] = str(patch["summary_language"])[:40]
    for pid, conf in (patch.get("providers") or {}).items():
        if pid not in PROVIDERS:
            raise LLMError("unknown provider")
        mine = saved.setdefault("providers", {}).setdefault(pid, {})
        for k in ("model", "base_url"):
            if k in conf:
                mine[k] = str(conf[k]).strip()
        if "api_key" in conf:  # write-only: never returned by settings()
            _set_key(pid, str(conf["api_key"]).strip())
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(saved, indent=2))
    return settings()


def _get_key(pid: str) -> str | None:
    import keyring
    try:
        return keyring.get_password(KEYCHAIN_SERVICE, pid)
    except Exception:
        return None


def _set_key(pid: str, key: str) -> None:
    import keyring
    if key:
        keyring.set_password(KEYCHAIN_SERVICE, pid, key)
    else:
        try:
            keyring.delete_password(KEYCHAIN_SERVICE, pid)
        except Exception:
            pass


def active() -> dict:
    s = settings()
    pid = s["provider"]
    if not pid:
        raise LLMError("No AI provider set up yet. Open Settings to connect one.")
    conf = {**s["providers"][pid], "id": pid}
    if not conf["model"]:
        raise LLMError(f"Pick a model for {conf['label']} in Settings.")
    if conf["kind"] == "openai" and not conf["base_url"]:
        raise LLMError("Set a base URL for the custom provider in Settings.")
    if conf["needs_key"] and not conf["has_key"]:
        raise LLMError(f"Add your {conf['label']} API key in Settings.")
    return conf


# ---- transport ------------------------------------------------------------------------

def _chat(conf: dict, system: str, messages: list[dict], schema: dict | None = None) -> str:
    if conf["kind"] == "anthropic":
        return _chat_anthropic(conf, system, messages, schema)
    return _chat_openai(conf, system, messages, schema)


def _chat_anthropic(conf: dict, system: str, messages: list[dict], schema: dict | None) -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=_get_key(conf["id"]))
    out_cfg: dict = {"format": {"type": "json_schema", "schema": schema}} if schema else {}
    if conf["model"] in _FALLBACK_MODELS or conf["model"] == "claude-haiku-5-5":
        out_cfg["effort"] = "medium"  # older models (e.g. Haiku 4.5) reject effort
    kwargs: dict = {"model": conf["model"], "max_tokens": 16000, "system": system, "messages": messages,
                    **({"output_config": out_cfg} if out_cfg else {})}
    try:
        if conf["model"] in _FALLBACK_MODELS:
            resp = client.beta.messages.create(betas=["server-side-fallback-2026-07-01"],
                                               fallbacks="default", **kwargs)
        else:
            resp = client.messages.create(**kwargs)
    except anthropic.AuthenticationError:
        raise LLMError("Claude rejected the API key. Check it in Settings.")
    except anthropic.NotFoundError:
        raise LLMError(f"Claude doesn't know the model {conf['model']!r}.")
    except anthropic.RateLimitError:
        raise LLMError("Claude rate limit hit. Try again in a minute.")
    except anthropic.APIStatusError as e:
        raise LLMError(f"Claude error {e.status_code}: {e.message}")
    except anthropic.APIConnectionError:
        raise LLMError("Can't reach Claude. Check your internet connection.")
    if resp.stop_reason == "refusal":
        raise LLMError("Claude declined this request.")
    return next((b.text for b in resp.content if b.type == "text"), "")


def _http(conf: dict, path: str, body: dict | None = None, timeout: float = 600) -> dict:
    headers = {"Content-Type": "application/json"}
    key = _get_key(conf["id"])
    if key:
        headers["Authorization"] = f"Bearer {key}"
    req = urllib.request.Request(conf["base_url"].rstrip("/") + path, headers=headers,
                                 data=json.dumps(body).encode() if body is not None else None)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:300]
        raise LLMError(f"{conf['label']} error {e.code}: {detail}")
    except (urllib.error.URLError, TimeoutError) as e:
        hint = " Is Ollama running?" if conf["id"] == "ollama" else ""
        raise LLMError(f"Can't reach {conf['label']} at {conf['base_url']}.{hint} ({e})")


def _chat_openai(conf: dict, system: str, messages: list[dict], schema: dict | None) -> str:
    body: dict = {"model": conf["model"], "messages": [{"role": "system", "content": system}, *messages]}
    if schema:  # json_object is the widely supported subset (Ollama, Gemini, OpenAI)
        body["response_format"] = {"type": "json_object"}
    data = _http(conf, "/chat/completions", body)
    try:
        return data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        raise LLMError(f"Unexpected reply from {conf['label']}.")


def list_models(pid: str) -> list[str]:
    conf = {**settings()["providers"][pid], "id": pid}
    if conf["kind"] == "anthropic":
        import anthropic
        if not conf["has_key"]:
            raise LLMError("Add your Claude API key first.")
        try:
            return [m.id for m in anthropic.Anthropic(api_key=_get_key(pid)).models.list()]
        except anthropic.AuthenticationError:
            raise LLMError("Claude rejected the API key.")
        except anthropic.APIError as e:
            raise LLMError(f"Claude error: {e}")
    if not conf["base_url"]:
        raise LLMError("Set a base URL first.")
    data = _http(conf, "/models", timeout=15)
    return sorted(m["id"] for m in data.get("data", []))


# ---- features -------------------------------------------------------------------------

SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "overview": {"type": "string"},
        "action_items": {"type": "array", "items": {
            "type": "object",
            "properties": {"text": {"type": "string"}, "owner": {"type": "string"}},
            "required": ["text", "owner"], "additionalProperties": False}},
        "decisions": {"type": "array", "items": {"type": "string"}},
        "chapters": {"type": "array", "items": {
            "type": "object",
            "properties": {"title": {"type": "string"}, "start": {"type": "number"}},
            "required": ["title", "start"], "additionalProperties": False}},
    },
    "required": ["title", "overview", "action_items", "decisions", "chapters"],
    "additionalProperties": False,
}


def transcript_text(record: dict) -> str:
    return "\n".join(f"[{int(t['start'] // 60)}:{int(t['start'] % 60):02d}] "
                     f"{history.speaker(record, t['speaker'])}: {t['text']}"
                     for t in record.get("turns", []))


def _parse_json(text: str) -> dict:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise LLMError("The model didn't return a summary. Try again or pick a stronger model.")
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        raise LLMError("The model returned malformed JSON. Try again or pick a stronger model.")


def summarize(record: dict) -> dict:
    conf = active()
    lang = settings()["summary_language"]
    system = (
        "You turn meeting transcripts into notes. The transcript may be in Hindi, another Indian "
        "language, or code-mixed with English, and comes from speech recognition, so expect "
        f"misheard words. Write every field in {lang}. Keep the overview to 2-5 sentences. "
        "Action items are concrete follow-ups someone committed to or was asked to do; owner is "
        "the speaker's name as written in the transcript, or an empty string if unclear. "
        "Decisions are things the group agreed on. Chapters mark topic changes; start is the "
        "chapter's start time in seconds (timestamps in the transcript are minutes:seconds). "
        "Use empty lists when there is nothing to report; never invent content. "
        "Reply with only a JSON object with keys title, overview, action_items "
        "([{text, owner}]), decisions ([string]), chapters ([{title, start}]).")
    text = transcript_text(record)
    if not text.strip():
        raise LLMError("This recording has no transcript to summarize.")
    data = _parse_json(_chat(conf, system, [{"role": "user", "content": text}], SUMMARY_SCHEMA))
    return {
        "title": str(data.get("title", ""))[:120],
        "overview": str(data.get("overview", "")),
        "action_items": [{"text": str(a.get("text", "")), "owner": str(a.get("owner", "")), "done": False}
                         for a in data.get("action_items", []) if isinstance(a, dict) and a.get("text")],
        "decisions": [str(d) for d in data.get("decisions", []) if d],
        "chapters": [{"title": str(c.get("title", "")), "start": float(c.get("start", 0) or 0)}
                     for c in data.get("chapters", []) if isinstance(c, dict) and c.get("title")],
        "provider": conf["id"], "model": conf["model"],
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


def ask(record: dict, question: str, prior: list[dict]) -> str:
    conf = active()
    system = ("You answer questions about one meeting, using only its transcript below. The "
              "transcript comes from speech recognition and may be Hindi, another Indian language, "
              "or code-mixed. Answer in the language of the question, briefly, and cite timestamps "
              "like [12:34] when useful. If the transcript doesn't say, say so.\n\n<transcript>\n"
              + transcript_text(record) + "\n</transcript>")
    msgs = [{"role": m["role"], "content": str(m["content"])} for m in prior[-10:]
            if m.get("role") in ("user", "assistant")]
    return _chat(conf, system, [*msgs, {"role": "user", "content": question}]).strip()
