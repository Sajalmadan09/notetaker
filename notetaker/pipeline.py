"""Meeting audio -> diarized turns -> per-turn ASR -> speaker-labeled transcript."""
from __future__ import annotations

from typing import Callable

import numpy as np

from .asr import Int4Asr
from .audio import SR, is_silent, split_long_turn
from .diarize import Diarizer

Progress = Callable[[str, float], None]


def transcribe_meeting(audio: np.ndarray, lang: str = "hi", num_clusters: int = -1, mode: str = "native",
                       progress: Progress | None = None,
                       asr=None, diarizer: Diarizer | None = None,
                       lid: Int4Asr | None = None) -> dict:
    """asr: any engine with transcribe(); lid: the engine that detects language (only int4 can)."""
    asr = asr if asr is not None else Int4Asr()
    lid = lid if lid is not None else (asr if hasattr(asr, "identify") else Int4Asr())
    diarizer = diarizer if diarizer is not None else Diarizer()
    if lang == "auto":
        mid = max(0, len(audio) // 2 - 5 * SR)
        probe = audio[mid:mid + 10 * SR]
        lang, prob = lid.identify(probe)[0]
        if progress:
            progress(f"language: {lang} (p={prob:.2f})", 0.0)
    if progress:
        progress("diarizing", 0.0)
    segs = diarizer.process(audio, num_clusters)
    turns = []
    for i, (start, end, spk) in enumerate(segs):
        piece = audio[int(start * SR):int(end * SR)]
        text = " ".join(asr.transcribe(c, lang, mode=mode).strip()
                        for c in split_long_turn(piece) if not is_silent(c)).strip()
        turns.append({"start": round(start, 2), "end": round(end, 2),
                      "speaker": int(spk), "text": text})
        if progress:
            progress("transcribing", (i + 1) / (len(segs) or 1))
    if progress:
        progress("done", 1.0)
    return {"lang": lang, "turns": turns}
