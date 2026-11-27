"""Local notetaker server: upload/record audio -> speaker-labeled notes.

Run: uv run uvicorn notetaker.server:app --port 8000
Everything stays on this machine; weights are read from the local HF cache only.
"""
from __future__ import annotations

import io
import os
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import soundfile as sf
from fastapi import Body, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from . import connectors, history, llm, setup
from .asr import Int4Asr, available_languages
from .asr_torch import FLEX_REPO, TorchAsr
from .audio import SR
from .diarize import Diarizer
from .pipeline import transcribe_meeting

app = FastAPI(title="on-desktop-notetaker")


_LOCAL_HOSTS = ("127.0.0.1", "localhost", "[::1]")


@app.middleware("http")
async def local_only(request, call_next):
    """Block DNS rebinding (foreign Host) and cross-site writes (foreign Origin): any web page
    can send requests to localhost, and this API holds transcripts and LLM keys."""
    host = request.headers.get("host", "").rsplit(":", 1)[0]
    if host not in _LOCAL_HOSTS and host != "testserver":
        return Response("forbidden host", status_code=403)
    origin = request.headers.get("origin")
    if origin and request.method not in ("GET", "HEAD", "OPTIONS"):
        from urllib.parse import urlparse
        o = urlparse(origin)
        if not (o.scheme == "chrome-extension" or o.hostname in ("127.0.0.1", "localhost", "::1")):
            return Response("forbidden origin", status_code=403)
    return await call_next(request)


@app.middleware("http")
async def no_cache(request, call_next):
    resp = await call_next(request)
    if not request.url.path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-cache"  # UI ships inside the app; always revalidate
    return resp
ASR = Int4Asr()
TORCH_ASR = TorchAsr()
FLEX_ASR = TorchAsr(FLEX_REPO)
ENGINES = {"int4": ASR, "torch": TORCH_ASR, "flex": FLEX_ASR}
MODES = ("native", "mixed", "romanized")
DIARIZER = Diarizer()
JOBS: dict[str, dict] = {}
LOCK = threading.Lock()
EXECUTOR = ThreadPoolExecutor(max_workers=1)


def _set(job_id: str, **fields) -> None:
    with LOCK:
        JOBS[job_id].update(fields)


def _worker(job_id: str, path: Path, lang: str, num_clusters: int, engine: str, mode: str,
            meta: dict | None = None) -> None:
    try:
        _set(job_id, status="running", stage="loading")
        audio, sr = sf.read(path, dtype="float32", always_2d=True)
        audio = audio.mean(axis=1)

        def progress(stage: str, frac: float) -> None:
            _set(job_id, stage=stage, progress=frac)

        doc = transcribe_meeting(audio, lang=lang, num_clusters=num_clusters,
                                 progress=progress, mode=mode,
                                 asr=ENGINES[engine],
                                 diarizer=DIARIZER)
        _set(job_id, status="done", stage="done", progress=1.0,
             result=doc["turns"], detected_lang=doc["lang"])
        history.save({
            "id": job_id,
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            "lang": doc["lang"],
            "engine": engine, "mode": mode,
            "duration_s": round(len(audio) / SR, 1),
            "turn_count": len(doc["turns"]),
            "preview": (doc["turns"][0]["text"][:80] if doc["turns"] else ""),
            "turns": doc["turns"],
            **(meta or {}),  # calendar event title + attendees, when recorded from an event
        }, path)
    except Exception as e:
        _set(job_id, status="error", error=f"{type(e).__name__}: {e}")
    finally:
        path.unlink(missing_ok=True)


@app.on_event("startup")
def warm_default_engine() -> None:
    """Use flex (code-mix) by default when installed, and load it in the background so the
    first dictation doesn't hit the ~60 s cold load."""
    import importlib.util
    if os.environ.get("NOTETAKER_ENGINE") or importlib.util.find_spec("torch") is None:
        return
    if not setup.flex_present():
        return
    os.environ["NOTETAKER_ENGINE"] = "flex"
    os.environ.setdefault("NOTETAKER_MODE", "mixed")
    threading.Thread(target=lambda: FLEX_ASR._load(), daemon=True).start()


@app.get("/api/health")
def health() -> dict:
    import importlib.util
    return {"status": "ok", "asr_loaded": ASR.loaded, "diarizer_loaded": DIARIZER.loaded,
            "torch": importlib.util.find_spec("torch") is not None}


@app.get("/api/languages")
def languages() -> list[str]:
    return available_languages()


@app.post("/api/jobs")
async def create_job(file: UploadFile = File(...), lang: str = Form("hi"),
                     speakers: str = Form("auto"), engine: str = Form(""),
                     title: str = Form(""), attendees: str = Form(""),
                     mode: str = Form("")) -> dict:
    engine = engine or os.environ.get("NOTETAKER_ENGINE", "int4")  # extension/helper send none
    mode = mode or os.environ.get("NOTETAKER_MODE", "native")
    if engine not in ENGINES:
        raise HTTPException(400, "engine must be int4, torch or flex")
    if mode not in MODES:
        raise HTTPException(400, "mode must be native, mixed or romanized")
    if engine in ("torch", "flex"):
        try:
            import torch  # noqa: F401
        except Exception:
            raise HTTPException(400, "torch/flex engines unavailable here (packaged app is int4-only; "
                                     "use a dev checkout with the bench extra)")
    try:
        num_clusters = -1 if speakers == "auto" else int(speakers)
    except ValueError:
        raise HTTPException(400, "speakers must be 'auto' or an integer")
    data = await file.read()
    try:
        audio, sr = sf.read(io.BytesIO(data), dtype="float32", always_2d=True)
    except Exception:
        raise HTTPException(400, "unreadable audio; send a WAV file")
    if sr != SR:
        raise HTTPException(400, f"expected {SR} Hz WAV, got {sr} Hz (the web UI converts automatically)")
    if len(audio) < SR // 2:
        raise HTTPException(400, "audio shorter than 0.5 s")
    tmp = Path(tempfile.mkstemp(suffix=".wav")[1])
    sf.write(tmp, audio.mean(axis=1), SR)
    job_id = uuid.uuid4().hex[:12]
    with LOCK:
        JOBS[job_id] = {"status": "queued", "stage": "queued", "progress": 0.0,
                        "lang": lang, "speakers": speakers, "engine": engine, "mode": mode,
                        "result": None, "error": None, "detected_lang": None}
    meta = {}
    if title.strip():
        meta["title"] = title.strip()[:120]
    emails = [a.strip() for a in attendees.split(",") if connectors._EMAIL.match(a.strip())][:50]
    if emails:
        meta["attendees"] = emails
    EXECUTOR.submit(_worker, job_id, tmp, lang, num_clusters, engine, mode, meta)
    return {"job_id": job_id}


@app.post("/api/quick")
def quick(file: UploadFile = File(...), lang: str = Form("hi"),
          engine: str = Form(""), mode: str = Form("")) -> dict:
    """Provisional live transcription of a <=20 s chunk; diarization happens later."""
    data = file.file.read()
    try:
        audio, sr = sf.read(io.BytesIO(data), dtype="float32", always_2d=True)
    except Exception:
        raise HTTPException(400, "unreadable audio; send a WAV file")
    if sr != SR:
        raise HTTPException(400, f"expected {SR} Hz WAV, got {sr} Hz")
    audio = audio.mean(axis=1)
    if len(audio) > 20 * SR:
        raise HTTPException(400, "quick chunks must be <= 20 s")
    engine = engine or os.environ.get("NOTETAKER_ENGINE", "int4")
    mode = mode or os.environ.get("NOTETAKER_MODE", "native")
    if engine not in ENGINES or mode not in MODES:
        raise HTTPException(400, "bad engine or mode")
    if lang == "auto":
        lang = ASR.identify(audio)[0][0]
    text = ENGINES[engine].transcribe(audio, lang, mode=mode) if len(audio) >= SR // 2 else ""
    return {"text": text, "lang": lang}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    with LOCK:
        job = JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, "unknown job")
    return job


@app.post("/api/history")
async def history_add(file: UploadFile = File(...), lang: str = Form("hi"),
                      text: str = Form(...), verdict: str = Form(""),
                      insert_path: str = Form(""), asr_ms: int = Form(0),
                      source: str = Form("dictation")) -> dict:
    """Ingest a dictation (or other single-utterance recording) from the helper."""
    data = await file.read()
    try:
        audio, sr = sf.read(io.BytesIO(data), dtype="float32", always_2d=True)
    except Exception:
        raise HTTPException(400, "unreadable audio; send a WAV file")
    if sr != SR:
        raise HTTPException(400, f"expected {SR} Hz WAV, got {sr} Hz")
    duration = round(len(audio) / SR, 1)
    rid = uuid.uuid4().hex[:12]
    tmp = Path(tempfile.mkstemp(suffix=".wav")[1])
    sf.write(tmp, audio.mean(axis=1), SR)
    history.save({
        "id": rid,
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "lang": lang,
        "engine": "int4",
        "duration_s": duration,
        "turn_count": 1,
        "preview": text[:80],
        "source": source,
        "verdict": verdict,
        "insert_path": insert_path,
        "asr_ms": asr_ms,
        "turns": [{"start": 0.0, "end": duration, "speaker": 0, "text": text}],
    }, tmp)
    return {"id": rid}


@app.get("/api/history")
def history_list() -> list[dict]:
    return history.listing()


@app.get("/api/history/{rid}")
def history_get(rid: str) -> dict:
    record = history.get(rid)
    if record is None:
        raise HTTPException(404, "unknown recording")
    return record


@app.patch("/api/history/{rid}")
def history_patch(rid: str, payload: dict = Body(...)) -> dict:
    """{"title": str, "names": {"0": "Priya"}} — either key optional."""
    summary = payload.get("summary")
    if summary is not None and not isinstance(summary, dict):
        raise HTTPException(400, "summary must be an object")
    names = payload.get("names")
    if names is not None and not (isinstance(names, dict) and all(str(k).isdigit() for k in names)):
        raise HTTPException(400, "names must map speaker numbers to names")
    title = payload.get("title")
    record = history.update(rid, title=str(title) if title is not None else None, names=names,
                            summary=summary)
    if record is None:
        raise HTTPException(404, "unknown recording")
    return record


@app.post("/api/history/{rid}/summarize")
def history_summarize(rid: str) -> dict:
    record = history.get(rid)
    if record is None:
        raise HTTPException(404, "unknown recording")
    try:
        summary = llm.summarize(record)
    except llm.LLMError as e:
        raise HTTPException(400, str(e))
    return history.update(rid, summary=summary)


@app.post("/api/history/{rid}/ask")
def history_ask(rid: str, payload: dict = Body(...)) -> dict:
    record = history.get(rid)
    if record is None:
        raise HTTPException(404, "unknown recording")
    question = str(payload.get("question", "")).strip()
    if not question:
        raise HTTPException(400, "question is required")
    try:
        return {"answer": llm.ask(record, question, payload.get("prior") or [])}
    except llm.LLMError as e:
        raise HTTPException(400, str(e))


@app.get("/api/connectors")
def connectors_list() -> dict:
    return {"connectors": connectors.listing(), "slack_manifest": connectors.SLACK_MANIFEST}


@app.put("/api/connectors/{cid}")
def connectors_save(cid: str, payload: dict = Body(...)) -> dict:
    try:
        return connectors.save(cid, payload.get("values"), payload.get("secrets"))
    except connectors.ConnectorError as e:
        raise HTTPException(400, str(e))


@app.post("/api/connectors/{cid}/test")
def connectors_test(cid: str) -> dict:
    if cid not in connectors.PRESETS:
        raise HTTPException(404, "unknown connector")
    try:
        return {"tools": connectors.tools(cid)}
    except connectors.ConnectorError as e:
        raise HTTPException(400, str(e))


@app.post("/api/connectors/{cid}/connect")
def google_connect(cid: str, request: Request) -> dict:
    """Start Google sign-in in the system browser (Google blocks sign-in inside embedded webviews)."""
    import webbrowser
    redirect = f"http://127.0.0.1:{request.url.port or 80}/api/connectors/google/callback"
    try:
        url = connectors.google_auth_url(cid, redirect)
    except connectors.ConnectorError as e:
        raise HTTPException(400, str(e))
    webbrowser.open(url)
    return {"url": url, "redirect_uri": redirect}


@app.get("/api/calendar/upcoming")
def calendar_upcoming() -> list[dict]:
    try:
        return connectors.calendar_upcoming()
    except connectors.ConnectorError as e:
        raise HTTPException(400, str(e))


@app.post("/api/connectors/{cid}/disconnect")
def connectors_disconnect(cid: str) -> dict:
    try:
        return connectors.disconnect(cid)
    except connectors.ConnectorError as e:
        raise HTTPException(400, str(e))


@app.get("/api/connectors/google/callback")
def google_callback(state: str = "", code: str = "", error: str = "") -> HTMLResponse:
    import html
    try:
        if error:
            raise connectors.ConnectorError(f"Google sign-in was cancelled ({error}).")
        cid = connectors.google_callback(state, code)
        title, msg, ok = f"{connectors.PRESETS[cid]['label']} connected", "You can close this tab and go back to Kiroku.", True
    except connectors.ConnectorError as e:
        title, msg, ok = "Not connected", str(e), False
    color = "#4f7a34" if ok else "#d23a2a"
    return HTMLResponse(f"""<!doctype html><meta charset="utf-8"><title>{title}</title>
<body style="font:16px -apple-system,sans-serif;background:#f3ede2;color:#1a1714;display:grid;place-items:center;height:100vh;margin:0">
<div style="border:2px solid #1a1714;box-shadow:5px 5px 0 #1a1714;background:#fbf7ef;padding:28px 32px;max-width:440px">
<div style="width:34px;height:34px;background:#d23a2a;color:#fff8ec;display:grid;place-items:center;font:600 20px serif;border-radius:5px;transform:rotate(-4deg)">記</div>
<h1 style="font:600 24px Georgia,serif;margin:16px 0 8px;color:{color}">{html.escape(title)}</h1>
<p style="margin:0">{html.escape(msg)}</p></div></body>""", status_code=200 if ok else 400)


@app.get("/api/history/{rid}/share/gmail")
def gmail_preview(rid: str) -> dict:
    record = history.get(rid)
    if record is None:
        raise HTTPException(404, "unknown recording")
    return {"subject": f"Notes: {record.get('title') or 'meeting'} ({record.get('ts', '')[:10]})",
            "body": connectors.notes_markdown(record, plain=True), "to": record.get("attendees", [])}


@app.post("/api/history/{rid}/share/gmail")
def gmail_share(rid: str, payload: dict = Body(...)) -> dict:
    """Creates a Gmail draft from exactly what the user reviewed; never sends."""
    if history.get(rid) is None:
        raise HTTPException(404, "unknown recording")
    to = payload.get("to") or []
    if not isinstance(to, list):
        raise HTTPException(400, "to must be a list of email addresses")
    try:
        return {"draft_id": connectors.gmail_draft([str(a) for a in to], str(payload.get("subject", "")),
                                                   str(payload.get("body", "")))}
    except connectors.ConnectorError as e:
        raise HTTPException(400, str(e))


@app.get("/api/connectors/slack/channels")
def slack_channels() -> list[dict]:
    try:
        return connectors.slack_channels()
    except connectors.ConnectorError as e:
        raise HTTPException(400, str(e))


@app.get("/api/history/{rid}/share/slack")
def slack_preview(rid: str) -> dict:
    record = history.get(rid)
    if record is None:
        raise HTTPException(404, "unknown recording")
    return {"text": connectors.notes_markdown(record)}


@app.post("/api/history/{rid}/share/slack")
def slack_share(rid: str, payload: dict = Body(...)) -> dict:
    """Posts exactly the text the user reviewed in the share dialog."""
    if history.get(rid) is None:
        raise HTTPException(404, "unknown recording")
    try:
        return {"result": connectors.slack_post(str(payload.get("channel_id", "")), str(payload.get("text", "")))}
    except connectors.ConnectorError as e:
        raise HTTPException(400, str(e))


@app.get("/api/llm/settings")
def llm_settings() -> dict:
    return llm.settings()


@app.put("/api/llm/settings")
def llm_save(payload: dict = Body(...)) -> dict:
    try:
        return llm.save_settings(payload)
    except llm.LLMError as e:
        raise HTTPException(400, str(e))


@app.get("/api/llm/models")
def llm_models(provider: str) -> list[str]:
    if provider not in llm.PROVIDERS:
        raise HTTPException(400, "unknown provider")
    try:
        return llm.list_models(provider)
    except llm.LLMError as e:
        raise HTTPException(400, str(e))


@app.delete("/api/history/{rid}")
def history_delete(rid: str) -> dict:
    if not history.delete(rid):
        raise HTTPException(404, "unknown recording")
    return {"deleted": rid}


@app.get("/api/history/{rid}/audio")
def history_audio(rid: str) -> FileResponse:
    record = history.get(rid)
    if record is None or not record.get("audio"):
        raise HTTPException(404, "no audio for this recording")
    return FileResponse(history.HISTORY_DIR / record["audio"], media_type="audio/wav")


@app.get("/api/history/{rid}/export")
def history_export(rid: str, fmt: str = "md") -> Response:
    record = history.get(rid)
    if record is None:
        raise HTTPException(404, "unknown recording")
    if fmt == "md":
        content, media, ext = history.as_md(record).encode(), "text/markdown", "md"
    elif fmt == "txt":
        content, media, ext = history.as_txt(record).encode(), "text/plain", "txt"
    elif fmt == "pdf":
        content, media, ext = history.as_pdf(record), "application/pdf", "pdf"
    else:
        raise HTTPException(400, "fmt must be md, txt, or pdf")
    return Response(content=content, media_type=media,
                    headers={"Content-Disposition": f'attachment; filename="notetaker-{rid}.{ext}"'})


@app.get("/api/setup/status")
def setup_status() -> dict:
    return setup.status()


@app.post("/api/setup/accept")
def setup_accept() -> dict:
    setup.accept()
    return {"accepted": True}


@app.post("/api/setup/download")
def setup_download() -> dict:
    setup.start_download()
    return {"started": True}


@app.post("/api/setup/download-flex")
def setup_download_flex() -> dict:
    setup.start_flex_download()
    return {"started": True}


@app.get("/")
def root() -> Response:
    if setup.needs_setup():
        return RedirectResponse("/setup.html")
    return RedirectResponse("/app/#/record")


app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="ui")
