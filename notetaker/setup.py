"""First-run setup: license acceptance + weight/model download with progress."""
from __future__ import annotations

import json
import tarfile
import threading
import urllib.request
from pathlib import Path

from . import paths
from .asr import INT4_REPO, cached_int4_dir
from .asr_torch import FLEX_REPO

STATE_PATH = paths.DATA / "setup.json"
SEG_URL = ("https://github.com/k2-fsa/sherpa-onnx/releases/download/"
           "speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2")
EMB_URL = ("https://github.com/k2-fsa/sherpa-onnx/releases/download/"
           "speaker-recongition-models/3dspeaker_speech_campplus_sv_zh-cn_16k-common.onnx")

PROGRESS = {"state": "idle", "percent": 0, "detail": ""}
LOCK = threading.Lock()


def _set(**fields) -> None:
    with LOCK:
        PROGRESS.update(fields)


def accepted() -> bool:
    if STATE_PATH.exists():
        return bool(json.loads(STATE_PATH.read_text()).get("accepted"))
    return False


def accept() -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps({"accepted": True}))


def weights_present() -> bool:
    try:
        cached_int4_dir()
    except Exception:
        return False
    from .diarize import EMB_MODEL, SEG_MODEL
    return SEG_MODEL.exists() and EMB_MODEL.exists()


def _weights_ready(repo: str) -> bool:
    """True only once model.safetensors is complete. Config files land first, and the weights
    only appear in the snapshot when fully downloaded, so a partial download isn't 'installed'."""
    from .asr_torch import cached_official_dir
    try:
        return (cached_official_dir(repo) / "model.safetensors").exists()
    except Exception:
        return False


def _repo_bytes_on_disk(repo: str) -> int:
    from huggingface_hub.constants import HF_HUB_CACHE
    blobs = Path(HF_HUB_CACHE) / f"models--{repo.replace('/', '--')}" / "blobs"
    return sum(f.stat().st_size for f in blobs.glob("*") if f.is_file()) if blobs.exists() else 0


def flex_present() -> bool:
    return _weights_ready(FLEX_REPO)


def core_present() -> bool:
    from .asr_torch import OFFICIAL_REPO
    return _weights_ready(OFFICIAL_REPO)


def needs_setup() -> bool:
    return not weights_present()


def status() -> dict:
    with LOCK:
        progress = dict(PROGRESS)
    if progress["state"] == "running" and progress["detail"].startswith("code-mix"):
        # Per-byte progress isn't exposed (and Xet writes in bursts): report what's on disk.
        progress["detail"] = f"code-mix model: {_repo_bytes_on_disk(FLEX_REPO) / 1e9:.1f} of 4.9 GB on disk"
    return {"needs_setup": needs_setup(), "accepted": accepted(),
            "weights_present": weights_present(), "flex_present": flex_present(), "hf_token": hf_token_saved(),
            "download": progress}


def _download_file(url: str, dest: Path, base_percent: float, span: float, label: str) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)

    def hook(count: int, block: int, total: int) -> None:
        if total > 0:
            frac = min(1.0, count * block / total)
            _set(percent=base_percent + span * frac, detail=f"{label} {frac * 100:.0f}%")

    tmp = dest.with_suffix(dest.suffix + ".part")
    urllib.request.urlretrieve(url, tmp, reporthook=hook)
    tmp.rename(dest)


def _download_weights() -> None:
    from huggingface_hub import HfApi, hf_hub_download
    _set(state="running", percent=0, detail="listing int4 files")
    files = [f for f in HfApi().list_repo_tree(INT4_REPO, recursive=True) if hasattr(f, "size")]
    total = sum(f.size for f in files) or 1
    done = 0
    for f in files:
        hf_hub_download(INT4_REPO, f.rfilename)
        done += f.size
        _set(percent=90 * done / total, detail=f"int4 {done / 1e6:.0f}/{total / 1e6:.0f} MB")
    from .diarize import EMB_MODEL, SEG_MODEL
    if not SEG_MODEL.exists():
        archive = paths.DATA / "seg.tar.bz2"
        _download_file(SEG_URL, archive, 90, 5, "segmentation")
        with tarfile.open(archive) as tar:
            tar.extractall(paths.DATA / "seg-extract", filter="data")
        extracted = next((paths.DATA / "seg-extract").rglob("model.onnx"))
        SEG_MODEL.parent.mkdir(parents=True, exist_ok=True)
        extracted.rename(SEG_MODEL)
    if not EMB_MODEL.exists():
        _download_file(EMB_URL, EMB_MODEL, 95, 5, "speaker embeddings")
    _set(state="done", percent=100, detail="ready")


def _download_flex() -> None:
    from huggingface_hub import HfApi, hf_hub_download
    _set(state="running", percent=0, detail="listing flex files")
    skip = ("nemo/", "banner.png", "model-diagram.png")
    files = [f for f in HfApi().list_repo_tree(FLEX_REPO, recursive=True)
             if hasattr(f, "size") and not f.rfilename.startswith(skip)]
    total = sum(f.size for f in files) or 1
    done = 0
    for f in files:
        hf_hub_download(FLEX_REPO, f.rfilename)
        done += f.size
        _set(percent=100 * done / total, detail=f"code-mix model {done / 1e9:.1f}/{total / 1e9:.1f} GB")
    _set(state="done", percent=100, detail="ready")


def hf_token_saved() -> bool:
    from huggingface_hub import get_token
    return bool(get_token())


def save_hf_token(token: str) -> str:
    from huggingface_hub import login, whoami
    if not token.startswith("hf_"):
        raise ValueError("Hugging Face tokens start with hf_. Create one at huggingface.co/settings/tokens (Read access).")
    try:
        name = whoami(token=token).get("name", "")
    except Exception:
        raise ValueError("Hugging Face didn't accept that token.")
    login(token=token, add_to_git_credential=False)  # standard HF token file, read by downloads
    return name


def start_flex_download() -> None:
    with LOCK:
        if PROGRESS["state"] == "running":
            return
        PROGRESS.update(state="running", percent=0, detail="starting")

    def run() -> None:
        try:
            _download_flex()
        except Exception as e:
            msg = str(e)
            if "401" in msg or "403" in msg or "gated" in msg.lower() or "GatedRepo" in type(e).__name__:
                msg = ("Hugging Face refused the download. Open huggingface.co/bodhan-ai/indic-transcribe-flex, "
                       "accept the license while signed in, then try again.")
            _set(state="error", detail=msg)

    threading.Thread(target=run, daemon=True).start()


def start_download() -> None:
    with LOCK:
        if PROGRESS["state"] == "running":
            return
        PROGRESS.update(state="running", percent=0, detail="starting")

    def run() -> None:
        try:
            _download_weights()
        except Exception as e:
            _set(state="error", detail=f"{type(e).__name__}: {e}")

    threading.Thread(target=run, daemon=True).start()
