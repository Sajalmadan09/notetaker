"""Diarization smoke test: simulated 2-speaker meeting -> sherpa-onnx turns -> int4 ASR.

Builds a pseudo-meeting from FLEURS hi clips with known turn ground truth (speaker
ids when the dataset provides them, else alternating pseudo-speakers), runs
sherpa-onnx offline diarization (pyannote segmentation + 3D-Speaker embeddings),
scores frame-level speaker error after best label mapping, then transcribes each
predicted turn with the parity-verified int4 ONNX engine and reports per-turn WER.

Usage:
  uv run python scripts/diarization_smoke.py
  uv run python scripts/diarization_smoke.py --clips-per-speaker 4
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from benchmark_asr import SAMPLE_RATE, int4_dir, normalize

MODELS = ROOT / "models"
SEG_MODEL = MODELS / "sherpa-onnx-pyannote-segmentation-3-0" / "model.onnx"
EMB_MODEL = MODELS / "3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx"
HOP = 0.1


def prepare_meeting(out_dir: Path, clips_per_speaker: int) -> tuple[Path, Path, str]:
    wav_path = out_dir / f"meeting_sim_2spk_{clips_per_speaker}c.wav"
    truth_path = out_dir / f"meeting_sim_2spk_{clips_per_speaker}c.truth.json"
    if wav_path.exists() and truth_path.exists():
        return wav_path, truth_path, json.loads(truth_path.read_text())["mode"]

    from datasets import load_dataset
    ds = load_dataset("google/fleurs", "hi_in", split="test", streaming=True,
                      trust_remote_code=True)
    picks, counts, mode = [], {}, "unknown"
    for row in ds:
        has_id = "speaker_id" in row and row["speaker_id"] is not None
        mode = "speaker_id" if has_id else "alternating-pseudo"
        spk = str(row["speaker_id"]) if has_id else ("A" if len(picks) % 2 == 0 else "B")
        if counts.get(spk, 0) >= clips_per_speaker:
            continue
        audio = row["audio"]
        arr = np.asarray(audio["array"], dtype=np.float32)
        if audio["sampling_rate"] != SAMPLE_RATE:
            import torch
            import torchaudio
            arr = torchaudio.functional.resample(
                torch.from_numpy(arr), audio["sampling_rate"], SAMPLE_RATE).numpy()
        picks.append((spk, arr, row["raw_transcription"]))
        counts[spk] = counts.get(spk, 0) + 1
        if len(counts) >= 2 and all(c >= clips_per_speaker for c in counts.values()):
            break
    gap = np.zeros(int(0.8 * SAMPLE_RATE), dtype=np.float32)
    chunks, turns, t = [], [], 0.0
    for spk, arr, text in picks:
        turns.append({"start": t, "end": t + len(arr) / SAMPLE_RATE,
                      "speaker": spk, "text": text})
        chunks.append(arr)
        t += len(arr) / SAMPLE_RATE
        chunks.append(gap)
        t += len(gap) / SAMPLE_RATE
    sf.write(wav_path, np.concatenate(chunks), SAMPLE_RATE)
    truth_path.write_text(json.dumps({"mode": mode, "turns": turns}, ensure_ascii=False, indent=2))
    print(f"meeting: {wav_path} ({t / 60:.1f} min, {len(turns)} turns, mode={mode})", flush=True)
    return wav_path, truth_path, mode


def diarize(audio: np.ndarray, num_clusters: int) -> tuple[list, float]:
    import sherpa_onnx
    config = sherpa_onnx.OfflineSpeakerDiarizationConfig(
        segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
            pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(
                model=str(SEG_MODEL), window_shift_ratio=0.1)),
        embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(EMB_MODEL)),
        clustering=sherpa_onnx.FastClusteringConfig(num_clusters=num_clusters, threshold=0.5),
        min_duration_on=0.3, min_duration_off=0.5)
    if not config.validate():
        raise RuntimeError("diarization config invalid; check model files")
    sd = sherpa_onnx.OfflineSpeakerDiarization(config)
    t0 = time.perf_counter()
    result = sd.process(audio).sort_by_start_time()
    wall = time.perf_counter() - t0
    return [(r.start, r.end, r.speaker) for r in result], wall


def frame_labels(spans, total_s: float) -> np.ndarray:
    labels = np.full(int(total_s / HOP) + 1, -1, dtype=int)
    for start, end, spk in spans:
        labels[int(start / HOP):int(end / HOP)] = spk
    return labels


def speaker_error(truth_spans, pred_spans, total_s: float) -> tuple[float, dict]:
    truth = frame_labels(truth_spans, total_s)
    pred = frame_labels(pred_spans, total_s)
    mapping = {}
    for spk in set(pred[pred >= 0]):
        overlap = truth[(pred == spk) & (truth >= 0)]
        mapping[int(spk)] = int(np.bincount(overlap).argmax()) if len(overlap) else -1
    speech = truth >= 0
    mapped = np.vectorize(lambda p: mapping.get(int(p), -1))(pred)
    err = float(((mapped != truth) & speech).sum() / speech.sum())
    return err, mapping


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clips-per-speaker", type=int, default=3)
    parser.add_argument("--lang", default="hi")
    parser.add_argument("--out", type=Path, default=ROOT / "results")
    args = parser.parse_args()

    import jiwer
    wav_path, truth_path, mode = prepare_meeting(ROOT / "data", args.clips_per_speaker)
    truth = json.loads(truth_path.read_text())["turns"]
    audio, sr = sf.read(wav_path, dtype="float32", always_2d=True)
    audio = audio[:, 0]
    total_s = len(audio) / sr
    truth_spans = [(t["start"], t["end"], i) for i, t in enumerate(truth)]

    runs = {}
    for name, n in [("known-2", 2), ("auto", -1)]:
        segs, wall = diarize(audio, n)
        err, mapping = speaker_error(truth_spans, segs, total_s)
        runs[name] = {"num_clusters_arg": n, "wall_s": wall,
                      "num_speakers_found": len({s for _, _, s in segs}),
                      "num_segments": len(segs), "frame_speaker_error": err,
                      "segments": segs}
        print(f"== {name}: {len(segs)} segments, "
              f"{runs[name]['num_speakers_found']} speakers, "
              f"frame error {err:.3f}, {wall:.1f}s", flush=True)

    sys.path.insert(0, str(int4_dir()))
    from inference import IndicTranscribeONNX
    pipe = IndicTranscribeONNX(folder=int4_dir())
    segs = runs["known-2"]["segments"]
    # Over-split turns: merge adjacent same-speaker segments before ASR so a
    # single utterance is not scored as two fragments against the full text.
    merged = []
    for start, end, spk in segs:
        if merged and merged[-1][2] == spk and start - merged[-1][1] <= 1.0:
            merged[-1] = (merged[-1][0], end, spk)
        else:
            merged.append((start, end, spk))
    t0 = time.perf_counter()
    lines, turn_wers = [], []
    for start, end, spk in merged:
        piece = audio[int(start * sr):int(end * sr)]
        if len(piece) < int(0.3 * sr):
            continue
        text = pipe.transcribe(piece, lang=args.lang, mode="native", max_new_tokens=512)["text"]
        best = max(truth, key=lambda t: max(0.0, min(end, t["end"]) - max(start, t["start"])))
        wer = jiwer.wer(normalize(best["text"]), normalize(text))
        turn_wers.append(wer)
        lines.append(f"**speaker_{spk:02d}** [{start:6.1f}-{end:6.1f}] (WER {wer:.2f}): {text}")
    asr_wall = time.perf_counter() - t0

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "transcripts").mkdir(exist_ok=True)
    (args.out / "transcripts" / "meeting_sim.md").write_text("\n\n".join(lines) + "\n")
    summary = {"when": time.strftime("%Y%m%d-%H%M%S"), "sample": str(wav_path),
               "truth_mode": mode, "audio_s": total_s, "diarization": runs,
               "asr_wall_s": asr_wall, "per_turn_wer": turn_wers,
               "mean_turn_wer": float(np.mean(turn_wers)) if turn_wers else None}
    (args.out / "diarization-smoke.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\nASR on {len(turn_wers)} turns: {asr_wall:.1f}s, mean turn WER {summary['mean_turn_wer']:.3f}")
    print(f"saved: {args.out / 'diarization-smoke.json'}")


if __name__ == "__main__":
    main()
