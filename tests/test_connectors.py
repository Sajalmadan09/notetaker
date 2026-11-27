import pytest

from notetaker import connectors


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    keys = {}
    monkeypatch.setattr(connectors, "CONFIG_PATH", tmp_path / "connectors.json")
    monkeypatch.setattr(connectors, "_get_secret", lambda cid, k: keys.get((cid, k)))
    monkeypatch.setattr(connectors, "_set_secret", lambda cid, k, v: keys.update({(cid, k): v}) if v else keys.pop((cid, k), None))
    return keys


def test_secret_is_write_only_and_marks_configured(isolated):
    assert not connectors.listing()[0]["configured"]
    c = connectors.save("slack", secrets={"SLACK_MCP_XOXB_TOKEN": "xoxb-secret", "EVIL": "x"})
    assert c["configured"] and "xoxb-secret" not in str(c)
    assert ("slack", "EVIL") not in isolated  # only declared secrets are stored
    assert "xoxb-secret" not in connectors.CONFIG_PATH.read_text()
    with pytest.raises(connectors.ConnectorError):
        connectors.save("nope")


def test_unconfigured_connector_refuses_to_start():
    with pytest.raises(connectors.ConnectorError, match="isn't connected"):
        connectors._server_params("slack")


def test_server_env_gets_token_and_only_the_post_tool(isolated):
    connectors.save("slack", secrets={"SLACK_MCP_XOXB_TOKEN": "xoxb-1"})
    if connectors.shutil.which("npx") is None:
        pytest.skip("npx not installed")
    p = connectors._server_params("slack")
    assert p.env["SLACK_MCP_XOXB_TOKEN"] == "xoxb-1"
    assert p.env["SLACK_MCP_ENABLED_TOOLS"] == "channels_list,conversations_add_message"
    assert "@1.3.0" in " ".join(p.args)  # pinned


def test_channels_parse_csv(monkeypatch):
    monkeypatch.setattr(connectors, "_run", lambda cid, fn: "ID,Name,Topic,Purpose,MemberCount,Cursor\nC1,#general,,,5,\nC2,#launch,,,3,\n")
    assert connectors.slack_channels() == [{"id": "C1", "name": "general"}, {"id": "C2", "name": "launch"}]


def test_post_validates_and_notes_include_summary(monkeypatch):
    sent = {}
    monkeypatch.setattr(connectors, "_run", lambda cid, fn: sent.setdefault("ok", "posted"))
    with pytest.raises(connectors.ConnectorError):
        connectors.slack_post("", "x")
    assert connectors.slack_post("C1", "hello") == "posted"
    md = connectors.notes_markdown({"title": "Standup", "ts": "2026-11-27 10:00:00", "duration_s": 600,
                                    "summary": {"overview": "We shipped.", "decisions": ["Ship Monday"],
                                                "action_items": [{"text": "Send deck", "owner": "Asha", "done": True}]}})
    assert md.startswith("**Standup**") and "~~Send deck (Asha)~~" in md and "- Ship Monday" in md


def test_server_error_is_extracted_from_stderr():
    log = ('{"level":"info","message":"Using Bot token"}\nnode noise\n'
           '{"level":"fatal","message":"Authentication failed - check your Slack tokens","error":"invalid_auth"}\n')
    assert connectors._server_error(log) == "Authentication failed - check your Slack tokens (invalid_auth)"
    assert connectors._server_error("plain text") is None


# ---- Gmail -----------------------------------------------------------------------------
import asyncio
import base64
import hashlib
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse


def _gmail_creds(isolated):
    isolated[("gmail", "client_id")] = "cid.apps.googleusercontent.com"
    isolated[("gmail", "client_secret")] = "shh"


def test_gmail_needs_client_and_sign_in(isolated):
    with pytest.raises(connectors.ConnectorError, match="client ID"):
        connectors.google_auth_url("http://127.0.0.1:8010/cb")
    _gmail_creds(isolated)
    gmail = next(c for c in connectors.listing() if c["id"] == "gmail")
    assert not gmail["configured"]  # credentials alone aren't a connection


def test_google_auth_url_uses_pkce_and_compose_scope(isolated):
    _gmail_creds(isolated)
    q = {k: v[0] for k, v in parse_qs(urlparse(connectors.google_auth_url("http://127.0.0.1:8010/cb")).query).items()}
    assert q["scope"] == "https://www.googleapis.com/auth/gmail.compose"
    assert q["code_challenge_method"] == "S256" and q["access_type"] == "offline"
    verifier = connectors._PENDING[q["state"]][0]
    assert q["code_challenge"] == base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


def test_google_callback_checks_state_and_stores_refresh_token(isolated, monkeypatch):
    _gmail_creds(isolated)
    q = parse_qs(urlparse(connectors.google_auth_url("http://127.0.0.1:8010/cb")).query)
    with pytest.raises(connectors.ConnectorError, match="expired"):
        connectors.google_callback("forged-state", "code")
    q = parse_qs(urlparse(connectors.google_auth_url("http://127.0.0.1:8010/cb")).query)
    sent = {}
    monkeypatch.setattr(connectors, "_token_request", lambda form: sent.update(form) or
                        {"access_token": "at", "refresh_token": "rt", "expires_in": 3600})
    connectors.google_callback(q["state"][0], "the-code")
    assert sent["code_verifier"] and sent["redirect_uri"] == "http://127.0.0.1:8010/cb"
    assert isolated[("gmail", "refresh_token")] == "rt"
    assert next(c for c in connectors.listing() if c["id"] == "gmail")["configured"]
    with pytest.raises(connectors.ConnectorError):  # state is single-use
        connectors.google_callback(q["state"][0], "the-code")


def test_revoked_refresh_token_is_forgotten(isolated, monkeypatch):
    _gmail_creds(isolated)
    isolated[("gmail", "refresh_token")] = "rt"
    connectors._ACCESS.clear()

    def boom(form):
        raise connectors.ConnectorError("Google sign-in failed: invalid_grant")
    monkeypatch.setattr(connectors, "_token_request", boom)
    with pytest.raises(connectors.ConnectorError, match="Connect Gmail again"):
        connectors._google_access_token()
    assert ("gmail", "refresh_token") not in isolated


def test_gmail_draft_only_calls_create_draft(monkeypatch):
    calls = []

    class FakeSession:
        async def call_tool(self, name, args):
            calls.append((name, args))
            return SimpleNamespace(isError=False, content=[SimpleNamespace(type="text", text='{"id": "r-123"}')])
    monkeypatch.setattr(connectors, "_run", lambda cid, fn: asyncio.run(fn(FakeSession())))
    with pytest.raises(connectors.ConnectorError, match="plain email"):
        connectors.gmail_draft(["Asha <asha@x.com>"], "s", "b")
    assert connectors.gmail_draft(["asha@x.com", " "], "Notes", "body") == "r-123"
    assert calls == [("create_draft", {"to": ["asha@x.com"], "subject": "Notes", "body": "body"})]


def test_plain_notes_have_no_markdown():
    txt = connectors.notes_markdown({"title": "Sync", "ts": "2026-11-27 10:00", "duration_s": 60,
                                     "summary": {"overview": "o", "decisions": [],
                                                 "action_items": [{"text": "Do it", "owner": "Asha", "done": True}]}},
                                    plain=True)
    assert "**" not in txt and "_" not in txt and "- [x] Do it (Asha)" in txt
