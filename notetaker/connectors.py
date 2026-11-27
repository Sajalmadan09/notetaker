"""Connectors = MCP servers the user switches on. The app is the MCP client.

Presets are either a local stdio MCP server started on demand with the user's secrets injected
as env vars (Slack), or a vendor-hosted MCP server reached over streamable HTTP with the user's
own OAuth token (Gmail). Secrets live in the macOS Keychain; non-secret fields in
DATA/connectors.json. Nothing runs until the user configures it, and the app calls only the
tools each feature needs.
"""
from __future__ import annotations

import asyncio
import csv
import io
import json
import os
import base64
import hashlib
import re
import secrets as _secrets
import shutil
import tempfile
import time
import urllib.error
import urllib.request
from urllib.parse import urlencode

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
        "transport": "stdio",
        "secrets": {"SLACK_MCP_XOXB_TOKEN": "Bot token (starts with xoxb-)"},
        "fields": {},
        # Posting is off in this server by default; enable it only for the app's own use.
        "env": {"SLACK_MCP_ADD_MESSAGE_TOOL": "true", "SLACK_MCP_LOG_LEVEL": "error",
                "SLACK_MCP_ENABLED_TOOLS": "channels_list,conversations_add_message"},
    },
    "gmail": {
        "label": "Gmail",
        "about": "Save meeting notes as a Gmail draft. You review and send it from Gmail.",
        "server": "Google's official Gmail MCP server (gmailmcp.googleapis.com)",
        "transport": "http",
        "url": "https://gmailmcp.googleapis.com/mcp/v1",
        "oauth": "google",
        # create_draft accepts gmail.compose; the narrowest scope that can write a draft.
        "scope": "https://www.googleapis.com/auth/gmail.compose",
        "api": "Gmail MCP API",
        # The user's own OAuth client from their Google Cloud project (personal use, no app review).
        "secrets": {"client_id": "OAuth client ID", "client_secret": "OAuth client secret"},
        "fields": {},
        "env": {},
    },
    "calendar": {
        "label": "Google Calendar",
        "about": "See today's meetings on the Record page; recordings take the event's title and attendees.",
        "server": "Google's official Calendar MCP server (calendarmcp.googleapis.com)",
        "transport": "http",
        "url": "https://calendarmcp.googleapis.com/mcp/v1",
        "oauth": "google",
        # Read-only: list_events accepts calendar.events.readonly, so Kiroku can't change your calendar.
        "scope": "https://www.googleapis.com/auth/calendar.events.readonly",
        "api": "Calendar MCP API",
        "secrets": {"client_id": "OAuth client ID", "client_secret": "OAuth client secret"},
        "fields": {},
        "env": {},
    },
}
# Google connectors share one OAuth client (one Google Cloud setup); each keeps its own sign-in.
_SHARED_GOOGLE = ("client_id", "client_secret")

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
_PENDING: dict[str, tuple[str, str, str, float]] = {}  # state -> (connector, pkce verifier, redirect_uri, started)
_ACCESS: dict[str, tuple[str, float]] = {}  # connector -> (access token, expires at); memory only

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


def _sget(cid: str, name: str) -> str | None:
    owner = "google" if PRESETS[cid].get("oauth") == "google" and name in _SHARED_GOOGLE else cid
    return _get_secret(owner, name)


def _sset(cid: str, name: str, value: str) -> None:
    owner = "google" if PRESETS[cid].get("oauth") == "google" and name in _SHARED_GOOGLE else cid
    _set_secret(owner, name, value)


def listing() -> list[dict]:
    cfg = _config()
    out = []
    for cid, p in PRESETS.items():
        mine = cfg.get(cid, {})
        has = {k: _sget(cid, k) is not None for k in p["secrets"]}
        signed_in = p.get("oauth") != "google" or _sget(cid, "refresh_token") is not None
        out.append({"id": cid, "label": p["label"], "about": p["about"], "server": p["server"],
                    "secrets": p["secrets"], "fields": p["fields"],
                    "values": {k: mine.get(k, "") for k in p["fields"]},
                    "has_secret": has, "configured": all(has.values()) and signed_in,
                    "needs_node": p.get("command", [""])[0] == "npx" and shutil.which("npx") is None})
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
            _sset(cid, k, str(v).strip())
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2))
    return next(c for c in listing() if c["id"] == cid)


def disconnect(cid: str) -> dict:
    """Forget this connector's sign-in and secrets. A shared Google client is kept while
    another Google connector still uses it."""
    if cid not in PRESETS:
        raise ConnectorError("unknown connector")
    p = PRESETS[cid]
    _sset(cid, "refresh_token", "")
    _ACCESS.pop(cid, None)
    others = [o for o, q in PRESETS.items() if o != cid and q.get("oauth") == "google" and _sget(o, "refresh_token")]
    for k in p["secrets"]:
        if not (p.get("oauth") == "google" and k in _SHARED_GOOGLE and others):
            _sset(cid, k, "")
    return next(c for c in listing() if c["id"] == cid)


# ---- Google OAuth (installed-app flow with PKCE, loopback redirect) ---------------------

def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def google_auth_url(cid: str, redirect_uri: str) -> str:
    if PRESETS.get(cid, {}).get("oauth") != "google":
        raise ConnectorError("not a Google connector")
    client_id = _sget(cid, "client_id")
    if not client_id or not _sget(cid, "client_secret"):
        raise ConnectorError("Save your Google OAuth client ID and secret first.")
    verifier = _secrets.token_urlsafe(64)
    state = _secrets.token_urlsafe(24)
    _PENDING.clear()  # one sign-in at a time; an old tab can't complete a newer flow
    _PENDING[state] = (cid, verifier, redirect_uri, time.time())
    return GOOGLE_AUTH_URL + "?" + urlencode({
        "client_id": client_id, "redirect_uri": redirect_uri, "response_type": "code",
        "scope": PRESETS[cid]["scope"], "access_type": "offline", "prompt": "consent", "state": state,
        "code_challenge": _b64url(hashlib.sha256(verifier.encode()).digest()),
        "code_challenge_method": "S256",
    })


def _token_request(form: dict) -> dict:
    req = urllib.request.Request(GOOGLE_TOKEN_URL, data=urlencode(form).encode(),
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read())
        except ValueError:
            body = {}
        raise ConnectorError(f"Google sign-in failed: {body.get('error', e.code)}"
                             + (f" ({body['error_description']})" if body.get("error_description") else ""))
    except urllib.error.URLError as e:
        raise ConnectorError(f"Can't reach Google: {e.reason}")


def google_callback(state: str, code: str) -> str:
    """Finish sign-in; returns the connector id that was connected."""
    pending = _PENDING.pop(state, None)
    if pending is None or time.time() - pending[3] > 600:
        raise ConnectorError("This sign-in link expired or didn't start in Kiroku. Click Connect again.")
    cid, verifier, redirect_uri, _ = pending
    data = _token_request({"code": code, "grant_type": "authorization_code", "redirect_uri": redirect_uri,
                           "client_id": _sget(cid, "client_id"),
                           "client_secret": _sget(cid, "client_secret"), "code_verifier": verifier})
    if not data.get("refresh_token"):
        raise ConnectorError("Google didn't return a refresh token. Remove Kiroku's access at "
                             "myaccount.google.com/permissions and connect again.")
    _sset(cid, "refresh_token", data["refresh_token"])
    _ACCESS[cid] = (data["access_token"], time.time() + int(data.get("expires_in", 3600)) - 60)
    return cid


def _google_access_token(cid: str) -> str:
    token, expires = _ACCESS.get(cid, ("", 0.0))
    if token and time.time() < expires:
        return token
    label = PRESETS[cid]["label"]
    refresh = _sget(cid, "refresh_token")
    if not refresh:
        raise ConnectorError(f"{label} isn't connected yet. Connect it in Settings → Connectors.")
    try:
        data = _token_request({"grant_type": "refresh_token", "refresh_token": refresh,
                               "client_id": _sget(cid, "client_id"), "client_secret": _sget(cid, "client_secret")})
    except ConnectorError as e:
        if "invalid_grant" in str(e):  # revoked, password change, or 7-day expiry of Testing apps
            _sset(cid, "refresh_token", "")
            raise ConnectorError(f"{label} access expired or was revoked. Connect it again in Settings.")
        raise
    _ACCESS[cid] = (data["access_token"], time.time() + int(data.get("expires_in", 3600)) - 60)
    return data["access_token"]


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


async def _session(cid: str, fn, errlog, statuses: list[int] | None = None):
    """Start the connector's MCP server, run fn(session), shut it down."""
    # ponytail: one process per call (~2-4 s npx start); keep sessions alive if connectors get chatty.
    from mcp import ClientSession
    if PRESETS[cid]["transport"] == "http":
        from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client
        headers = {"Authorization": f"Bearer {_google_access_token(cid)}"}
        async with create_mcp_http_client(headers=headers) as http:
            async def record(resp):  # the SDK reports HTTP failures without their status
                if statuses is not None and resp.status_code >= 400:
                    statuses.append(resp.status_code)
            http.event_hooks = {"response": [record]}
            async with streamable_http_client(PRESETS[cid]["url"], http_client=http) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    return await fn(session)
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
    statuses: list[int] = []
    with tempfile.TemporaryFile("w+") as errlog:  # the server's stderr; may echo config, never kept
        try:
            return asyncio.run(asyncio.wait_for(_session(cid, fn, errlog, statuses), timeout))
        except ConnectorError:
            raise
        except TimeoutError:
            raise ConnectorError(f"{label} didn't respond in {timeout:.0f} s.")
        except Exception as e:  # process crash, protocol error, auth failure at startup
            errlog.seek(0)
            reason = _server_error(errlog.read())
            if reason and "invalid_auth" in reason:
                raise ConnectorError(f"{label} rejected the token. Copy the Bot User OAuth Token again and save it.")
            google = PRESETS[cid].get("oauth") == "google"
            if google and 401 in statuses:
                _ACCESS.pop(cid, None)
                raise ConnectorError(f"Google didn't accept the sign-in. Disconnect {label}, then connect it again.")
            if google and 403 in statuses:
                raise ConnectorError(f"Google refused the request. Check that the {PRESETS[cid]['api']} is enabled in "
                                     "your Google Cloud project and that your OAuth client has “Use this client for "
                                     "an AI-powered agent” ticked.")
            status = f" (HTTP {statuses[-1]})" if statuses else ""
            raise ConnectorError(f"{label} connector failed: {reason or _root(e)}{status}")


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


def notes_markdown(record: dict, plain: bool = False) -> str:
    """Shareable notes: title, overview, action items, decisions. plain=True for email bodies."""
    b = (lambda s: s) if plain else (lambda s: f"**{s}**")
    i = (lambda s: s) if plain else (lambda s: f"_{s}_")
    title = record.get("title") or "Meeting notes"
    lines = [b(title), i(f"{record.get('ts', '')[:16]} · {round((record.get('duration_s') or 0) / 60)} min"), ""]
    s = record.get("summary")
    if s:
        lines += [s.get("overview", ""), ""]
        if s.get("action_items"):
            lines.append(b("Action items"))
            for a in s["action_items"]:
                text = a["text"] + (f" ({a['owner']})" if a.get("owner") else "")
                lines.append(f"- [{'x' if a.get('done') else ' '}] {text}" if plain
                             else f"- {'~~' + text + '~~' if a.get('done') else text}")
            lines.append("")
        if s.get("decisions"):
            lines.append(b("Decisions"))
            lines += [f"- {d}" for d in s["decisions"]]
    else:
        lines += [f"{b(history.speaker(record, t['speaker']) + ':')} {t['text']}" for t in record.get("turns", [])[:12]]
    return "\n".join(lines).strip() + "\n\n" + i("Notes by Kiroku, made on-device.")


# ---- Gmail -----------------------------------------------------------------------------

_EMAIL = re.compile(r"^[^@\s,<>]+@[^@\s,<>]+\.[^@\s,<>]+$")


def gmail_draft(to: list[str], subject: str, body: str) -> str:
    """Create a draft (never send). Only create_draft is ever called on the Gmail server."""
    to = [a.strip() for a in to if a.strip()]
    bad = [a for a in to if not _EMAIL.match(a)]
    if bad:
        raise ConnectorError(f"Not a plain email address: {', '.join(bad)}")
    if not body.strip():
        raise ConnectorError("The email body is empty.")

    async def fn(s):
        return _text(await s.call_tool("create_draft", {"to": to, "subject": subject, "body": body}))
    out = _run("gmail", fn)
    try:
        return str(json.loads(out).get("id", ""))
    except (ValueError, AttributeError):
        return ""


# ---- Google Calendar -------------------------------------------------------------------

def _structured(result) -> dict:
    if getattr(result, "structuredContent", None):
        return result.structuredContent
    try:
        return json.loads(_text(result))
    except ValueError:
        raise ConnectorError("Calendar returned something Kiroku can't read.")


def calendar_upcoming(hours: int = 24) -> list[dict]:
    """Events from 30 min ago to `hours` ahead on the primary calendar (read-only)."""
    from datetime import datetime, timedelta
    now = datetime.now()
    fmt = "%Y-%m-%dT%H:%M:%S"  # local time, no offset, as the tool expects

    async def fn(s):
        r = await s.call_tool("list_events", {"startTime": (now - timedelta(minutes=30)).strftime(fmt),
                                              "endTime": (now + timedelta(hours=hours)).strftime(fmt),
                                              "orderBy": "startTime", "pageSize": 15})
        if r.isError:
            _text(r)
        return _structured(r)
    out = []
    for e in _run("calendar", fn).get("events", []):
        start = (e.get("start") or {}).get("dateTime")
        if not start or e.get("status") == "cancelled":  # all-day events and cancellations aren't meetings
            continue
        attendees = [a["email"] for a in e.get("attendees", [])
                     if a.get("email") and not a.get("resource") and not a.get("self")
                     and a.get("responseStatus") != "declined"]
        out.append({"id": e.get("id", ""), "title": e.get("summary") or "(no title)", "start": start,
                    "end": (e.get("end") or {}).get("dateTime", ""), "attendees": attendees,
                    "meet": ((e.get("conferenceData") or {}).get("videoEntryPoint") or {}).get("uri", "")})
    return out
