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


def has_speech(track: np.ndarray, win_s: float = 1.0, thr: float = 0.01) -> bool:
    """Any 1 s window loud enough to be speech (a long meeting's overall RMS can be tiny)."""
    w = int(win_s * SR)
    return any(float(np.sqrt(np.mean(np.square(track[i:i + w], dtype=np.float64)))) >= thr
               for i in range(0, max(len(track) - w + 1, 1), w))


def _drop_echo(turns: list[dict]) -> list[dict]:
    """Without headphones the mic also hears the other people. Drop a 'You' turn that overlaps a
    near-identical turn from the meeting audio (echo cancellation catches most of it first)."""
    from difflib import SequenceMatcher
    others = [t for t in turns if t["track"] == "others"]

    def echo(t: dict) -> bool:
        for o in others:
            overlap = min(t["end"], o["end"]) - max(t["start"], o["start"])
            if overlap > 0.5 * (t["end"] - t["start"]) and \
                    SequenceMatcher(None, t["text"].lower(), o["text"].lower()).ratio() > 0.6:
                return True
        return False
    return [t for t in turns if t["track"] != "mic" or not echo(t)]


def transcribe_two_tracks(mic: np.ndarray, others: np.ndarray, lang: str = "hi", mode: str = "native",
                          progress: Progress | None = None, asr=None, diarizer: Diarizer | None = None,
                          lid: Int4Asr | None = None) -> dict:
    """Meeting recorded as two tracks: the user's mic (speaker 0, 'You') and the meeting audio
    (other participants, diarized as speakers 1..n). Turns are merged in time order."""
    asr = asr if asr is not None else Int4Asr()
    diarizer = diarizer if diarizer is not None else Diarizer()
    lid = lid if lid is not None else (asr if hasattr(asr, "identify") else Int4Asr())
    mic_on, others_on = has_speech(mic), has_speech(others)
    if lang == "auto":
        louder = mic if float(np.abs(mic).mean()) >= float(np.abs(others).mean()) else others
        mid = max(0, len(louder) // 2 - 5 * SR)
        lang = lid.identify(louder[mid:mid + 10 * SR])[0][0]
    if progress:
        progress("diarizing", 0.0)
    segs = []
    if mic_on:
        segs += [(s, e, 0, "mic") for s, e, _ in diarizer.process(mic, 1)]
    if others_on:
        segs += [(s, e, spk + 1, "others") for s, e, spk in diarizer.process(others, -1)]
    segs.sort(key=lambda x: x[0])
    turns = []
    for i, (start, end, spk, src) in enumerate(segs):
        track = mic if src == "mic" else others
        piece = track[int(start * SR):int(end * SR)]
        text = " ".join(asr.transcribe(c, lang, mode=mode).strip()
                        for c in split_long_turn(piece) if not is_silent(c)).strip()
        if text:
            turns.append({"start": round(start, 2), "end": round(end, 2), "speaker": int(spk),
                          "text": text, "track": src})
        if progress:
            progress("transcribing", (i + 1) / (len(segs) or 1))
    if progress:
        progress("done", 1.0)
    return {"lang": lang, "turns": _drop_echo(turns)}
