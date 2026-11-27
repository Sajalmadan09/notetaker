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
    assert md.startswith("**Standup**") and "~~Send deck~~ (Asha)" in md and "- Ship Monday" in md
