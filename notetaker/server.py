"""Local notetaker server: upload/record audio -> speaker-labeled notes.

Run: uv run uvicorn notetaker.server:app --port 8000
Everything stays on this machine; weights are read from the local HF cache only.
"""
from __future__ import annotations

import io
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import soundfile as sf
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from . import history, setup
from .asr import Int4Asr, available_languages
from .asr_torch import TorchAsr
from .audio import SR
from .diarize import Diarizer
from .pipeline import transcribe_meeting

app = FastAPI(title="on-desktop-notetaker")


@app.middleware("http")
async def no_cache(request, call_next):
    resp = await call_next(request)
    if not request.url.path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-cache"  # UI ships inside the app; always revalidate
    return resp
ASR = Int4Asr()
TORCH_ASR = TorchAsr()
DIARIZER = Diarizer()
JOBS: dict[str, dict] = {}
LOCK = threading.Lock()
EXECUTOR = ThreadPoolExecutor(max_workers=1)


def _set(job_id: str, **fields) -> None:
    with LOCK:
        JOBS[job_id].update(fields)


def _worker(job_id: str, path: Path, lang: str, num_clusters: int, engine: str) -> None:
    try:
        _set(job_id, status="running", stage="loading")
        audio, sr = sf.read(path, dtype="float32", always_2d=True)
        audio = audio.mean(axis=1)

        def progress(stage: str, frac: float) -> None:
            _set(job_id, stage=stage, progress=frac)

        doc = transcribe_meeting(audio, lang=lang, num_clusters=num_clusters,
                                 progress=progress,
                                 asr=TORCH_ASR if engine == "torch" else ASR,
                                 diarizer=DIARIZER)
        _set(job_id, status="done", stage="done", progress=1.0,
             result=doc["turns"], detected_lang=doc["lang"])
        history.save({
            "id": job_id,
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            "lang": doc["lang"],
            "engine": engine,
            "duration_s": round(len(audio) / SR, 1),
            "turn_count": len(doc["turns"]),
            "preview": (doc["turns"][0]["text"][:80] if doc["turns"] else ""),
            "turns": doc["turns"],
        }, path)
    except Exception as e:
        _set(job_id, status="error", error=f"{type(e).__name__}: {e}")
    finally:
        path.unlink(missing_ok=True)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "asr_loaded": ASR.loaded, "diarizer_loaded": DIARIZER.loaded}


@app.get("/api/languages")
def languages() -> list[str]:
    return available_languages()


@app.post("/api/jobs")
async def create_job(file: UploadFile = File(...), lang: str = Form("hi"),
                     speakers: str = Form("auto"), engine: str = Form("int4")) -> dict:
    if engine not in ("int4", "torch"):
        raise HTTPException(400, "engine must be 'int4' or 'torch'")
    if engine == "torch":
        try:
            import torch  # noqa: F401
        except Exception:
            raise HTTPException(400, "torch engine unavailable here (packaged app is int4-only; "
                                     "use a dev checkout with the bench extra for torch)")
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
                        "lang": lang, "speakers": speakers, "engine": engine,
                        "result": None, "error": None, "detected_lang": None}
    EXECUTOR.submit(_worker, job_id, tmp, lang, num_clusters, engine)
    return {"job_id": job_id}


@app.post("/api/quick")
def quick(file: UploadFile = File(...), lang: str = Form("hi")) -> dict:
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
    if lang == "auto":
        lang = ASR.identify(audio)[0][0]
    text = ASR.transcribe(audio, lang) if len(audio) >= SR // 2 else ""
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


@app.get("/")
def root() -> Response:
    if setup.needs_setup():
        return RedirectResponse("/setup.html")
    return FileResponse(Path(__file__).parent / "static" / "index.html")


app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="ui")
