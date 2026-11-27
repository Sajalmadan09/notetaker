"""Numpy-only audio helpers (no torch)."""
from __future__ import annotations

import numpy as np

SR = 16000


def split_long_turn(wav: np.ndarray, max_s: float = 25.0,
                    min_pause_s: float = 0.25) -> list[np.ndarray]:
    """Cut a long monologue at pauses into <= max_s pieces (ASR chunk cap)."""
    n = len(wav)
    if n <= max_s * SR:
        return [wav]
    frame = int(0.02 * SR)
    m = n // frame
    energy = np.sqrt((wav[: m * frame].reshape(m, frame) ** 2).mean(axis=1))
    thr = max(float(energy.max()) * 0.02, 1e-4)
    silent = energy < thr
    cuts = []
    i = 0
    while i < m:
        if silent[i]:
            j = i
            while j < m and silent[j]:
                j += 1
            if (j - i) * 0.02 >= min_pause_s:
                cuts.append(((i + j) / 2) * 0.02)
            i = j
        else:
            i += 1
    pieces = []
    start = 0.0
    total = n / SR
    while total - start > max_s:
        limit = start + max_s
        cand = [c for c in cuts if start + 1.0 < c <= limit]
        cut = cand[-1] if cand else limit
        pieces.append(wav[int(start * SR):int(cut * SR)])
        start = cut
    pieces.append(wav[int(start * SR):])
    return [p for p in pieces if len(p) >= int(0.3 * SR)]


SILENCE_RMS = 0.003  # below this a clip is silence; speech models invent text ("REDACTED") on it


def is_silent(wav: np.ndarray) -> bool:
    return wav.size == 0 or float(np.sqrt(np.mean(np.square(wav, dtype=np.float64)))) < SILENCE_RMS
