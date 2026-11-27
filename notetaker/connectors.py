"""Connectors = local MCP servers the user switches on. The app is the MCP client.

Each preset is a stdio MCP server started on demand with the user's secrets injected as env
vars (secrets live in the macOS Keychain; non-secret fields in DATA/connectors.json). Nothing
runs until the user configures it, and write tools are enabled only where a preset needs them.
"""
from __future__ import annotations

import asyncio
import csv
import io
import json
import os
import shutil
import tempfile

from . import history, paths

CONFIG_PATH = paths.DATA / "connectors.json"
KEYCHAIN_SERVICE = "Kiroku"

PRESETS: dict[str, dict] = {
    "slack": {
        "label": "Slack",
        "about": "Post meeting notes to a Slack channel.",
        "server": "slack-mcp-server@1.3.0 (korotovsky, MIT)",
        # Pinned: a connector runs third-party code with your token, so never float the version.
        "command": ["npx", "-y", "slack-mcp-server@1.3.0", "--transport", "stdio"],
        "secrets": {"SLACK_MCP_XOXB_TOKEN": "Bot token (starts with xoxb-)"},
        "fields": {},
        # Posting is off in this server by default; enable it only for the app's own use.
        "env": {"SLACK_MCP_ADD_MESSAGE_TOOL": "true", "SLACK_MCP_LOG_LEVEL": "error",
                "SLACK_MCP_ENABLED_TOOLS": "channels_list,conversations_add_message"},
    },
}

# Slack app manifest the user pastes at api.slack.com/apps -> Create New App -> From a manifest.
SLACK_MANIFEST = {
    "display_information": {"name": "Kiroku", "description": "Meeting notes from your Mac"},
    "features": {"bot_user": {"display_name": "Kiroku", "always_online": False}},
    "oauth_config": {"scopes": {"bot": ["channels:read", "groups:read", "chat:write",
                                        "chat:write.public", "users:read"]}},
    "settings": {"org_deploy_enabled": False, "socket_mode_enabled": False, "token_rotation_enabled": False},
}


class ConnectorError(RuntimeError):
    pass


def _config() -> dict:
    return json.loads(CONFIG_PATH.read_text()) if CONFIG_PATH.exists() else {}


def _get_secret(cid: str, name: str) -> str | None:
    import keyring
    try:
        return keyring.get_password(KEYCHAIN_SERVICE, f"connector:{cid}:{name}")
    except Exception:
        return None


def _set_secret(cid: str, name: str, value: str) -> None:
    import keyring
    account = f"connector:{cid}:{name}"
    if value:
        keyring.set_password(KEYCHAIN_SERVICE, account, value)
    else:
        try:
            keyring.delete_password(KEYCHAIN_SERVICE, account)
        except Exception:
            pass


def listing() -> list[dict]:
    cfg = _config()
    out = []
    for cid, p in PRESETS.items():
        mine = cfg.get(cid, {})
        has = {k: _get_secret(cid, k) is not None for k in p["secrets"]}
        out.append({"id": cid, "label": p["label"], "about": p["about"], "server": p["server"],
                    "secrets": p["secrets"], "fields": p["fields"],
                    "values": {k: mine.get(k, "") for k in p["fields"]},
                    "has_secret": has, "configured": all(has.values()),
                    "needs_node": p["command"][0] == "npx" and shutil.which("npx") is None})
    return out


def save(cid: str, values: dict | None = None, secrets: dict | None = None) -> dict:
    if cid not in PRESETS:
        raise ConnectorError("unknown connector")
    p = PRESETS[cid]
    cfg = _config()
    mine = cfg.setdefault(cid, {})
    for k, v in (values or {}).items():
        if k in p["fields"]:
            mine[k] = str(v).strip()
    for k, v in (secrets or {}).items():
        if k in p["secrets"]:  # write-only; never returned
            _set_secret(cid, k, str(v).strip())
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2))
    return next(c for c in listing() if c["id"] == cid)


# ---- MCP client ------------------------------------------------------------------------

def _server_params(cid: str):
    from mcp import StdioServerParameters
    p = PRESETS[cid]
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin:/opt/homebrew/bin:/usr/local/bin"),
           "HOME": os.environ.get("HOME", ""), **p["env"]}
    for k in p["secrets"]:
        v = _get_secret(cid, k)
        if not v:
            raise ConnectorError(f"{p['label']} isn't connected yet. Add it in Settings → Connectors.")
        env[k] = v
    env.update({k: v for k, v in _config().get(cid, {}).items() if k in p["fields"]})
    if shutil.which(p["command"][0], path=env["PATH"]) is None:
        raise ConnectorError(f"{p['label']} needs Node.js (for npx). Install it from nodejs.org, then retry.")
    return StdioServerParameters(command=p["command"][0], args=p["command"][1:], env=env)


async def _session(cid: str, fn, errlog):
    """Start the connector's MCP server, run fn(session), shut it down."""
    # ponytail: one process per call (~2-4 s npx start); keep sessions alive if connectors get chatty.
    from mcp import ClientSession
    from mcp.client.stdio import stdio_client
    async with stdio_client(_server_params(cid), errlog=errlog) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return await fn(session)


def _server_error(log: str) -> str | None:
    """Pull the server's own fatal/error message out of its stderr (JSON log lines)."""
    for line in reversed(log.splitlines()):
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if isinstance(entry, dict) and entry.get("level") in ("fatal", "error"):
            return f"{entry.get('message', '')} ({entry.get('error', '')})".replace(" ()", "")
    return None


def _run(cid: str, fn, timeout: float = 90):
    label = PRESETS[cid]["label"]
    with tempfile.TemporaryFile("w+") as errlog:  # the server's stderr; may echo config, never kept
        try:
            return asyncio.run(asyncio.wait_for(_session(cid, fn, errlog), timeout))
        except ConnectorError:
            raise
        except TimeoutError:
            raise ConnectorError(f"{label} didn't respond in {timeout:.0f} s.")
        except Exception as e:  # process crash, protocol error, auth failure at startup
            errlog.seek(0)
            reason = _server_error(errlog.read())
            if reason and "invalid_auth" in reason:
                raise ConnectorError(f"{label} rejected the token. Copy the Bot User OAuth Token again and save it.")
            raise ConnectorError(f"{label} connector failed: {reason or _root(e)}")


def _root(e: BaseException) -> str:
    while isinstance(e, BaseExceptionGroup) and e.exceptions:
        e = e.exceptions[0]
    return f"{type(e).__name__}: {e}"


def _text(result) -> str:
    text = "\n".join(c.text for c in result.content if getattr(c, "type", "") == "text")
    if result.isError:
        raise ConnectorError(text or "the connector reported an error")
    return text


def tools(cid: str) -> list[str]:
    async def fn(s):
        return [t.name for t in (await s.list_tools()).tools]
    return _run(cid, fn)


# ---- Slack -----------------------------------------------------------------------------

def slack_channels() -> list[dict]:
    async def fn(s):
        return _text(await s.call_tool("channels_list", {"channel_types": "public_channel,private_channel",
                                                         "sort": "popularity", "limit": 500}))
    rows = list(csv.DictReader(io.StringIO(_run("slack", fn))))
    out = [{"id": r.get("ID") or r.get("id", ""), "name": (r.get("Name") or r.get("name", "")).lstrip("#")}
           for r in rows]
    return [c for c in out if c["id"]]


def slack_post(channel_id: str, text: str) -> str:
    if not channel_id or not text.strip():
        raise ConnectorError("Pick a channel and write a message.")

    async def fn(s):
        return _text(await s.call_tool("conversations_add_message",
                                       {"channel_id": channel_id, "payload": text, "content_type": "text/markdown"}))
    return _run("slack", fn)


def notes_markdown(record: dict) -> str:
    """Default Slack message for a recording: title, overview, action items, decisions."""
    title = record.get("title") or "Meeting notes"
    lines = [f"**{title}**", f"_{record.get('ts', '')[:16]} · {round((record.get('duration_s') or 0) / 60)} min_", ""]
    s = record.get("summary")
    if s:
        lines += [s.get("overview", ""), ""]
        if s.get("action_items"):
            lines.append("**Action items**")
            lines += [f"- {'~~' if a.get('done') else ''}{a['text']}{'~~' if a.get('done') else ''}"
                      + (f" ({a['owner']})" if a.get("owner") else "") for a in s["action_items"]]
            lines.append("")
        if s.get("decisions"):
            lines.append("**Decisions**")
            lines += [f"- {d}" for d in s["decisions"]]
    else:
        lines += [f"**{history.speaker(record, t['speaker'])}:** {t['text']}" for t in record.get("turns", [])[:12]]
    return "\n".join(lines).strip() + "\n\n_Notes by Kiroku, made on-device._"
