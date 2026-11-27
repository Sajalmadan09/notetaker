import io
import json
import threading
import time
import urllib.error
import urllib.request

import numpy as np
import pytest
import soundfile as sf
import uvicorn

from notetaker import setup
from notetaker.server import app

needs_weights = pytest.mark.skipif(not setup.weights_present(), reason="int4/diarization weights not downloaded")

PORT = 8765
BASE = f"http://127.0.0.1:{PORT}"


@pytest.fixture(scope="module", autouse=True)
def server(tmp_path_factory):
    from notetaker import history
    old_dir = history.HISTORY_DIR
    history.HISTORY_DIR = tmp_path_factory.mktemp("history")
    config = uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="error")
    srv = uvicorn.Server(config)
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    for _ in range(100):
        try:
            urllib.request.urlopen(BASE + "/api/health", timeout=1)
            break
        except Exception:
            time.sleep(0.1)
    else:
        raise RuntimeError("server did not start")
    yield
    srv.should_exit = True
    thread.join(timeout=5)
    history.HISTORY_DIR = old_dir


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=10) as r:
        return r.status, json.loads(r.read())


def wav_bytes(seconds=2.0, sr=16000):
    buf = io.BytesIO()
    sf.write(buf, np.zeros(int(seconds * sr), dtype=np.float32), sr, format="WAV")
    return buf.getvalue()


def post_job(wav, lang="hi", speakers="auto"):
    boundary = "----notetakerboundary"
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
            f"filename=\"a.wav\"\r\nContent-Type: audio/wav\r\n\r\n").encode() + wav + b"\r\n"
    for key, val in [("lang", lang), ("speakers", speakers)]:
        body += (f"--{boundary}\r\nContent-Disposition: form-data; "
                 f"name=\"{key}\"\r\n\r\n{val}\r\n").encode()
    body += f"--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        BASE + "/api/jobs", data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_health():
    status, body = get("/api/health")
    assert status == 200
    assert body["status"] == "ok"


@needs_weights
def test_languages_include_hindi():
    _, langs = get("/api/languages")
    assert "hi" in langs


def test_ui_served():
    with urllib.request.urlopen(BASE + "/", timeout=10) as r:
        assert r.status == 200
        assert "/app/" in r.url and "Kiroku" in r.read().decode()


def test_wrong_sample_rate_rejected():
    status, _ = post_job(wav_bytes(sr=8000))
    assert status == 400


@needs_weights
def test_silence_job_completes():
    status, body = post_job(wav_bytes())
    assert status == 200
    job_id = body["job_id"]
    for _ in range(120):
        _, job = get(f"/api/jobs/{job_id}")
        if job["status"] in ("done", "error"):
            break
        time.sleep(0.5)
    assert job["status"] == "done", job
    assert isinstance(job["result"], list)


@needs_weights
def test_quick_chunk_transcribes():
    boundary = "----notetakerboundary"
    wav = wav_bytes()
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
            f"filename=\"c.wav\"\r\nContent-Type: audio/wav\r\n\r\n").encode() + wav + b"\r\n"
    body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"lang\"\r\n\r\nhi\r\n").encode()
    body += f"--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        BASE + "/api/quick", data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        out = json.loads(r.read())
    assert "text" in out and out["lang"] == "hi"


def test_quick_rejects_long_chunks():
    boundary = "----notetakerboundary"
    wav = wav_bytes(seconds=25)
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
            f"filename=\"c.wav\"\r\nContent-Type: audio/wav\r\n\r\n").encode() + wav + b"\r\n"
    body += f"--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        BASE + "/api/quick", data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        urllib.request.urlopen(req, timeout=10)
        raise AssertionError("expected 400")
    except urllib.error.HTTPError as e:
        assert e.code == 400


@needs_weights
def test_quick_auto_language_returns_known_lang():
    boundary = "----notetakerboundary"
    wav = wav_bytes()
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
            f"filename=\"c.wav\"\r\nContent-Type: audio/wav\r\n\r\n").encode() + wav + b"\r\n"
    body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"lang\"\r\n\r\nauto\r\n").encode()
    body += f"--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        BASE + "/api/quick", data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        out = json.loads(r.read())
    _, langs = get("/api/languages")
    assert out["lang"] in langs


def test_unknown_engine_rejected():
    boundary = "----notetakerboundary"
    wav = wav_bytes()
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
            f"filename=\"a.wav\"\r\nContent-Type: audio/wav\r\n\r\n").encode() + wav + b"\r\n"
    body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"engine\"\r\n\r\nnope\r\n").encode()
    body += f"--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        BASE + "/api/jobs", data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        urllib.request.urlopen(req, timeout=10)
        raise AssertionError("expected 400")
    except urllib.error.HTTPError as e:
        assert e.code == 400


def test_history_ingest_dictation():
    boundary = "----notetakerboundary"
    wav = wav_bytes(seconds=2)
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
            f"filename=\"d.wav\"\r\nContent-Type: audio/wav\r\n\r\n").encode() + wav + b"\r\n"
    for key, val in [("lang", "hi"), ("text", "नमस्ते दुनिया"),
                     ("verdict", "verified_before_after"), ("source", "dictation")]:
        body += (f"--{boundary}\r\nContent-Disposition: form-data; "
                 f"name=\"{key}\"\r\n\r\n{val}\r\n").encode()
    body += f"--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        BASE + "/api/history", data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=10) as r:
        rid = json.loads(r.read())["id"]
    _, rows = get("/api/history")
    assert any(x["id"] == rid and x["source"] == "dictation" for x in rows)
    with urllib.request.urlopen(BASE + f"/api/history/{rid}/export?fmt=md", timeout=10) as r:
        assert "नमस्ते दुनिया" in r.read().decode()


def test_setup_status_and_wizard_page():
    status, body = get("/api/setup/status")
    assert status == 200
    assert {"needs_setup", "accepted", "weights_present", "download"} <= set(body)
    with urllib.request.urlopen(BASE + "/setup.html", timeout=10) as r:
        assert r.status == 200
        assert "setup" in r.read().decode().lower()


def test_unknown_job_404():
    try:
        get("/api/jobs/nope")
        raise AssertionError("expected 404")
    except urllib.error.HTTPError as e:
        assert e.code == 404


def test_history_patch_and_delete():
    from notetaker import history
    history.save({"id": "patchme", "ts": "2026-11-27 10:00:00", "turns": []}, None)

    def call(method, body=None):
        req = urllib.request.Request(BASE + "/api/history/patchme", method=method,
                                     data=json.dumps(body).encode() if body else None,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, None

    assert call("PATCH", {"names": {"x": "bad"}})[0] == 400
    status, rec = call("PATCH", {"title": "Sync", "names": {"0": "Asha"}})
    assert status == 200 and rec["title"] == "Sync" and rec["names"] == {"0": "Asha"}
    assert call("DELETE")[0] == 200
    assert call("DELETE")[0] == 404


def test_cross_site_writes_and_foreign_hosts_blocked():
    req = urllib.request.Request(BASE + "/api/llm/settings", method="PUT", data=b'{"provider": ""}',
                                 headers={"Content-Type": "application/json", "Origin": "https://evil.example"})
    try:
        urllib.request.urlopen(req, timeout=10)
        raise AssertionError("expected 403")
    except urllib.error.HTTPError as e:
        assert e.code == 403
    req = urllib.request.Request(BASE + "/api/history", headers={"Host": "evil.example"})
    try:
        urllib.request.urlopen(req, timeout=10)
        raise AssertionError("expected 403")
    except urllib.error.HTTPError as e:
        assert e.code == 403
    status, _ = get("/api/llm/settings")
    assert status == 200


@needs_weights
def test_job_keeps_calendar_title_and_attendees():
    boundary = "----notetakerboundary"
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
            f"filename=\"a.wav\"\r\nContent-Type: audio/wav\r\n\r\n").encode() + wav_bytes() + b"\r\n"
    for key, val in [("lang", "hi"), ("title", "Weekly sync"), ("attendees", "asha@x.com, bad, ravi@x.com")]:
        body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\"\r\n\r\n{val}\r\n").encode()
    body += f"--{boundary}--\r\n".encode()
    req = urllib.request.Request(BASE + "/api/jobs", data=body,
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=10) as r:
        job_id = json.loads(r.read())["job_id"]
    for _ in range(120):
        _, job = get(f"/api/jobs/{job_id}")
        if job["status"] in ("done", "error"):
            break
        time.sleep(0.5)
    _, rec = get(f"/api/history/{job_id}")
    assert rec["title"] == "Weekly sync" and rec["attendees"] == ["asha@x.com", "ravi@x.com"]
    _, preview = get(f"/api/history/{job_id}/share/gmail")
    assert preview["to"] == ["asha@x.com", "ravi@x.com"]


def test_dictation_cleanup_endpoint_passthrough_and_history_keeps_raw(monkeypatch):
    from notetaker import llm
    monkeypatch.setattr(llm, "settings", lambda: {"dictation": {"cleanup": False, "match_app": True, "dictionary": []}})
    req = urllib.request.Request(BASE + "/api/dictation/cleanup", data=json.dumps({"text": " um hi ", "app": "Slack"}).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=10) as r:
        out = json.loads(r.read())
    assert out["text"] == "um hi" and not out["cleaned"]

    boundary = "----notetakerboundary"
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
            f"filename=\"d.wav\"\r\nContent-Type: audio/wav\r\n\r\n").encode() + wav_bytes() + b"\r\n"
    for key, val in [("text", "Ship it on Monday."), ("raw", "um ship it on friday no monday"),
                     ("app_name", "Slack"), ("cleanup_ms", "2100")]:
        body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\"\r\n\r\n{val}\r\n").encode()
    body += f"--{boundary}--\r\n".encode()
    req = urllib.request.Request(BASE + "/api/history", data=body,
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=10) as r:
        rid = json.loads(r.read())["id"]
    _, rec = get(f"/api/history/{rid}")
    assert rec["turns"][0]["text"] == "Ship it on Monday." and rec["raw_text"].startswith("um ship")
    assert rec["app"] == "Slack" and rec["cleanup_ms"] == 2100
