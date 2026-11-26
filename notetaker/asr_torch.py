"""Optional max-accuracy engine: official 1B weights via torch (MPS bf16 on Mac).

Requires the bench extra: uv sync --extra bench. Slower install, best WER.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

OFFICIAL_REPO = "bodhan-ai/indic-transcribe-core"


def cached_official_dir() -> Path:
    from huggingface_hub import snapshot_download
    try:
        return Path(snapshot_download(OFFICIAL_REPO, ignore_patterns=["nemo/*", "banner.png"],
                                      local_files_only=True))
    except Exception as e:
        raise RuntimeError(
            "official weights not cached; download once with "
            "`uv run hf download bodhan-ai/indic-transcribe-core`") from e


class TorchAsr:
    def __init__(self):
        self._asr = None

    @property
    def loaded(self) -> bool:
        return self._asr is not None

    def _load(self):
        if self._asr is None:
            directory = cached_official_dir()
            sys.path.insert(0, str(directory))
            import torch
            from indic_transcribe import IndicTranscribe
            device = "mps" if torch.backends.mps.is_available() else "cpu"
            dtype = torch.bfloat16 if device == "mps" else torch.float32
            self._asr = IndicTranscribe.from_pretrained(str(directory), device=device, dtype=dtype)
        return self._asr

    def transcribe(self, wav: np.ndarray, lang: str = "hi") -> str:
        asr = self._load()
        return asr.transcribe(wav, lang=None if lang == "auto" else lang)
