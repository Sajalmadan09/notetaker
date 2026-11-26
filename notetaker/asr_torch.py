"""Optional max-accuracy engine: official 1B weights via torch (MPS bf16 on Mac).

Requires the bench extra: uv sync --extra bench. Slower install, best WER.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

OFFICIAL_REPO = "bodhan-ai/indic-transcribe-core"
FLEX_REPO = "bodhan-ai/indic-transcribe-flex"  # native / mixed-script (code-mix) / romanized


def cached_official_dir(repo: str = OFFICIAL_REPO) -> Path:
    from huggingface_hub import snapshot_download
    try:
        return Path(snapshot_download(repo, ignore_patterns=["nemo/*", "banner.png"],
                                      local_files_only=True))
    except Exception as e:
        raise RuntimeError(
            f"weights not cached; download once with `uv run hf download {repo}`") from e


class TorchAsr:
    def __init__(self, repo: str = OFFICIAL_REPO):
        self.repo = repo
        self.has_modes = repo == FLEX_REPO
        self._asr = None

    @property
    def loaded(self) -> bool:
        return self._asr is not None

    def _load(self):
        if self._asr is None:
            directory = cached_official_dir(self.repo)
            import importlib
            import torch
            sys.path.insert(0, str(directory))
            sys.modules.pop("indic_transcribe", None)  # core and flex ship same-named modules
            IndicTranscribe = importlib.import_module("indic_transcribe").IndicTranscribe
            device = "mps" if torch.backends.mps.is_available() else "cpu"
            dtype = torch.bfloat16 if device == "mps" else torch.float32
            self._asr = IndicTranscribe.from_pretrained(str(directory), device=device, dtype=dtype)
        return self._asr

    def transcribe(self, wav: np.ndarray, lang: str = "hi", mode: str = "native") -> str:
        asr = self._load()
        kw = {"mode": mode} if self.has_modes else {}  # core is native-only
        return asr.transcribe(wav, lang=None if lang == "auto" else lang, **kw)
