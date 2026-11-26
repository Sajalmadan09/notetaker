"""sherpa-onnx offline speaker diarization (pyannote seg + 3D-Speaker embeddings)."""
from __future__ import annotations

from pathlib import Path

import numpy as np

from . import paths

SEG_MODEL = paths.MODELS / "sherpa-onnx-pyannote-segmentation-3-0" / "model.onnx"
# CAM++ measured 2.3x faster than ERes2Net-base with identical turn boundaries
# (10.7s vs 25.0s on the 72s simulated meeting); speaker identity on real Hindi
# audio is unvalidated for either — see README.
EMB_MODEL = paths.MODELS / "3dspeaker_speech_campplus_sv_zh-cn_16k-common.onnx"
EMB_MODEL_ERES2NET = paths.MODELS / "3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx"


def resolve_overlaps(segs: list[tuple[float, float, int]],
                     min_dur: float = 0.3) -> list[tuple[float, float, int]]:
    """Segmentation can emit overlapping turns; notes want a single timeline."""
    out: list[tuple[float, float, int]] = []
    for start, end, spk in sorted(segs, key=lambda s: s[0]):
        if out and start < out[-1][1]:
            start = out[-1][1]
        if end - start >= min_dur:
            out.append((start, end, spk))
    return out


def merge_segments(segs: list[tuple[float, float, int]],
                   gap: float = 1.0) -> list[tuple[float, float, int]]:
    """Join adjacent same-speaker segments so one utterance stays one turn."""
    merged: list[tuple[float, float, int]] = []
    for start, end, spk in segs:
        if merged and merged[-1][2] == spk and start - merged[-1][1] <= gap:
            merged[-1] = (merged[-1][0], end, spk)
        else:
            merged.append((start, end, spk))
    return merged


class Diarizer:
    def __init__(self, seg_model: Path = SEG_MODEL, emb_model: Path = EMB_MODEL):
        self.seg_model = seg_model
        self.emb_model = emb_model
        self._by_clusters: dict[int, object] = {}

    @property
    def loaded(self) -> bool:
        return bool(self._by_clusters)

    def _load(self, num_clusters: int):
        if num_clusters not in self._by_clusters:
            import sherpa_onnx
            config = sherpa_onnx.OfflineSpeakerDiarizationConfig(
                segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
                    pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(
                        model=str(self.seg_model), window_shift_ratio=0.1)),
                embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(
                    model=str(self.emb_model)),
                clustering=sherpa_onnx.FastClusteringConfig(
                    num_clusters=num_clusters, threshold=0.5),
                min_duration_on=0.3, min_duration_off=0.5)
            if not config.validate():
                raise RuntimeError(
                    "diarization models missing; download them into models/ "
                    "(see README diarization section)")
            self._by_clusters[num_clusters] = sherpa_onnx.OfflineSpeakerDiarization(config)
        return self._by_clusters[num_clusters]

    def process(self, audio: np.ndarray, num_clusters: int = -1) -> list[tuple[float, float, int]]:
        sd = self._load(num_clusters)
        result = sd.process(audio).sort_by_start_time()
        segs = resolve_overlaps([(r.start, r.end, r.speaker) for r in result])
        return merge_segments(segs)
