import numpy as np

from notetaker.audio import SR, split_long_turn
from notetaker.diarize import merge_segments, resolve_overlaps


def test_short_turn_not_split():
    wav = np.ones(10 * SR, dtype=np.float32)
    assert split_long_turn(wav) == [wav] or len(split_long_turn(wav)) == 1


def test_long_monologue_split_at_pauses():
    rng = np.random.default_rng(0)
    burst = rng.normal(0, 0.2, 4 * SR).astype(np.float32)
    gap = np.zeros(SR // 2, dtype=np.float32)
    wav = np.concatenate([burst, gap] * 12)  # 54 s
    pieces = split_long_turn(wav, max_s=25.0)
    assert len(pieces) >= 3
    assert all(len(p) <= 25.0 * SR + 1 for p in pieces)
    assert abs(sum(len(p) for p in pieces) - len(wav)) < SR  # only trailing silence dropped


def test_merge_adjacent_same_speaker():
    segs = [(0.0, 5.0, 0), (5.5, 9.0, 0), (10.0, 14.0, 1), (14.5, 18.0, 1)]
    assert merge_segments(segs, gap=1.0) == [(0.0, 9.0, 0), (10.0, 18.0, 1)]


def test_merge_respects_gap_and_speaker():
    segs = [(0.0, 5.0, 0), (7.0, 9.0, 0), (9.5, 12.0, 1)]
    assert merge_segments(segs, gap=1.0) == segs


def test_resolve_overlaps_trims_and_drops_slivers():
    segs = [(4.3, 6.12, 0), (4.37, 4.86, 1), (6.5, 9.0, 2)]
    assert resolve_overlaps(segs) == [(4.3, 6.12, 0), (6.5, 9.0, 2)]


def test_resolve_overlaps_keeps_disjoint():
    segs = [(0.0, 2.0, 0), (3.0, 5.0, 1)]
    assert resolve_overlaps(segs) == segs
