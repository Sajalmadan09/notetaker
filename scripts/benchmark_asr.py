"""Benchmark bodhan-ai/indic-transcribe-core runtimes on this machine.

Engines:
  torch-cpu-fp32   official weights, torch CPU fp32 (the wrapper's CPU default)
  torch-mps-bf16   official weights, torch MPS bf16 (Apple Silicon GPU)
  onnx-int8        community hari31416/indic-transcribe-onnx-int8, onnxruntime CPU
                   (UNTRUSTED: encoder fails parity; kept only with the parity guard)
  onnx-int4        community kazuto098/indic-transcribe-core-int4-onnx, onnxruntime CPU

Each engine runs in its own subprocess so peak RSS is per-engine. Sample audio is
built from google/fleurs test clips (native speech + reference transcripts) unless
--sample is given. WER is strict (not the card's OIWER), so treat it as an upper
bound on errors; spelling variants count against it.

Usage:
  uv run python scripts/benchmark_asr.py --minutes 2            # smoke
  uv run python scripts/benchmark_asr.py --minutes 10           # full
  uv run python scripts/benchmark_asr.py --sample my.wav --lang hi
"""
from __future__ import annotations

import argparse
import json
import platform
import resource
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OFFICIAL_REPO = "bodhan-ai/indic-transcribe-core"
ONNX_REPO = "hari31416/indic-transcribe-onnx-int8"
INT4_REPO = "kazuto098/indic-transcribe-core-int4-onnx"
SAMPLE_RATE = 16000


def peak_rss_mb() -> float:
    usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return usage / 1e6 if platform.system() == "Darwin" else usage / 1e3


def official_dir() -> Path:
    from huggingface_hub import snapshot_download

    return Path(snapshot_download(OFFICIAL_REPO, ignore_patterns=["nemo/*", "banner.png"],
                                  local_files_only=True))


def onnx_dir() -> Path:
    from huggingface_hub import snapshot_download

    return Path(snapshot_download(ONNX_REPO, ignore_patterns=["encoder-model.onnx", "decoder-model.onnx"],
                                  local_files_only=True))


def int4_dir() -> Path:
    from huggingface_hub import snapshot_download

    return Path(snapshot_download(INT4_REPO, local_files_only=True))


def prepare_sample(minutes: float, lang: str, out_dir: Path) -> tuple[Path, Path]:
    import numpy as np
    import soundfile as sf
    from datasets import load_dataset

    out_dir.mkdir(parents=True, exist_ok=True)
    wav_path = out_dir / f"fleurs_{lang}_{minutes:g}min.wav"
    refs_path = out_dir / f"fleurs_{lang}_{minutes:g}min.refs.json"
    if wav_path.exists() and refs_path.exists():
        return wav_path, refs_path

    config = {"hi": "hi_in", "bn": "bn_in", "ta": "ta_in", "te": "te_in", "mr": "mr_in"}[lang]
    ds = load_dataset("google/fleurs", config, split="test", streaming=True,
                      trust_remote_code=True)
    target = minutes * 60
    chunks, refs, total = [], [], 0.0
    gap = np.zeros(SAMPLE_RATE // 2, dtype=np.float32)
    for row in ds:
        audio = row["audio"]
        arr = np.asarray(audio["array"], dtype=np.float32)
        if audio["sampling_rate"] != SAMPLE_RATE:
            import torch
            import torchaudio
            arr = torchaudio.functional.resample(
                torch.from_numpy(arr), audio["sampling_rate"], SAMPLE_RATE).numpy()
        start = total
        chunks.append(arr)
        refs.append({"text": row["raw_transcription"], "start": start,
                     "end": start + len(arr) / SAMPLE_RATE})
        total += len(arr) / SAMPLE_RATE
        chunks.append(gap)
        total += len(gap) / SAMPLE_RATE
        if total >= target:
            break
    wav = np.concatenate(chunks)
    sf.write(wav_path, wav, SAMPLE_RATE)
    refs_path.write_text(json.dumps(refs, ensure_ascii=False, indent=2))
    print(f"sample: {wav_path} ({total / 60:.1f} min, {len(refs)} clips)", flush=True)
    return wav_path, refs_path


def normalize(text: str) -> str:
    import re
    text = text.lower()
    text = re.sub(r"[।॥.,!?;:\"'()\-–—…\[\]{}]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def run_torch(engine: str, sample: Path, lang: str) -> dict:
    import torch

    device, dtype = ("cpu", torch.float32) if engine == "torch-cpu-fp32" else ("mps", torch.bfloat16)
    if device == "mps" and not torch.backends.mps.is_available():
        raise RuntimeError("MPS not available on this machine")
    sys.path.insert(0, str(official_dir()))
    from indic_transcribe import IndicTranscribe
    from long_form import transcribe_long

    t0 = time.perf_counter()
    asr = IndicTranscribe.from_pretrained(str(official_dir()), device=device, dtype=dtype)
    load_s = time.perf_counter() - t0

    import soundfile as sf
    wav, _ = sf.read(sample, dtype="float32")
    asr.transcribe(wav[: 5 * SAMPLE_RATE], lang=lang)  # warmup, untimed

    t0 = time.perf_counter()
    text = transcribe_long(asr, str(sample), lang=lang)
    wall_s = time.perf_counter() - t0
    return {"device": device, "dtype": str(dtype), "load_s": load_s, "wall_s": wall_s,
            "text": text, "torch": torch.__version__}


def run_onnx(sample: Path, lang: str) -> dict:
    import tempfile

    import numpy as np
    import onnxruntime
    import soundfile as sf
    import torch

    directory = onnx_dir()
    sys.path.insert(0, str(directory))
    from pipeline_onnx import IndicTranscribeONNX
    sys.path.insert(0, str(official_dir()))
    from long_form import split_on_silence

    t0 = time.perf_counter()
    pipeline = IndicTranscribeONNX(directory, use_int8=True)
    load_s = time.perf_counter() - t0

    wav, _ = sf.read(sample, dtype="float32", always_2d=True)
    wav_t = torch.from_numpy(wav.mean(axis=1))
    with tempfile.TemporaryDirectory() as td:
        warm = Path(td) / "warm.wav"
        sf.write(warm, wav_t[: 5 * SAMPLE_RATE].numpy(), SAMPLE_RATE)

        # Community exports have shipped encoders that deviate from the torch
        # model (cosine 0.82); refuse to benchmark an export that fails parity.
        from indic_transcribe import IndicTranscribe
        ref = IndicTranscribe.from_pretrained(str(official_dir()), device="cpu")
        feats, lens = pipeline.extract_features(warm)
        warm_wav, _ = sf.read(warm, dtype="float32", always_2d=True)
        feats_t, mask_t = ref._features(torch.from_numpy(warm_wav.mean(axis=1)))
        with torch.inference_mode():
            ref_emb = ref.model.model.encoder(
                feats_t, attention_mask=mask_t
            ).last_hidden_state.float().numpy()
        emb, _ = pipeline.encoder_session.run(
            ["encoder_embeddings", "encoder_mask"],
            {"audio_signal": feats, "length": lens})
        cosine = float((ref_emb * emb).sum()
                       / (np.linalg.norm(ref_emb) * np.linalg.norm(emb)))
        if cosine < 0.99:
            raise RuntimeError(f"ONNX encoder fails parity vs torch (cosine {cosine:.3f}); export untrusted")

        pipeline.transcribe(warm, lang=lang, mode="native", max_new_tokens=512)

        t0 = time.perf_counter()
        texts = []
        for i, (a, b) in enumerate(split_on_silence(wav_t)):
            piece = wav_t[a:b]
            if piece.numel() < 1600:
                continue
            chunk = Path(td) / f"chunk{i}.wav"
            sf.write(chunk, piece.numpy(), SAMPLE_RATE)
            texts.append(pipeline.transcribe(chunk, lang=lang, mode="native",
                                             max_new_tokens=512))
        wall_s = time.perf_counter() - t0
    text = " ".join(t.strip() for t in texts if t and t.strip())
    return {"device": "cpu", "dtype": "int8", "load_s": load_s, "wall_s": wall_s,
            "text": text, "onnxruntime": onnxruntime.__version__}


def run_onnx_int4(sample: Path, lang: str) -> dict:
    import tempfile

    import numpy as np
    import onnxruntime
    import soundfile as sf
    import torch

    directory = int4_dir()
    sys.path.insert(0, str(directory))
    from inference import IndicTranscribeONNX as Int4Pipeline
    sys.path.insert(0, str(official_dir()))
    from indic_transcribe import IndicTranscribe
    from long_form import split_on_silence

    import psutil

    t0 = time.perf_counter()
    pipeline = Int4Pipeline(folder=directory)
    load_s = time.perf_counter() - t0
    rss_after_load_mb = psutil.Process().memory_info().rss / 1e6

    wav, _ = sf.read(sample, dtype="float32", always_2d=True)
    wav_t = torch.from_numpy(wav.mean(axis=1))
    warm = wav_t[: 5 * SAMPLE_RATE].numpy()

    import jiwer

    ref = IndicTranscribe.from_pretrained(str(official_dir()), device="cpu")
    feats, mask = ref._features(torch.from_numpy(warm))
    with torch.inference_mode():
        ref_emb = ref.model.model.encoder(feats, attention_mask=mask).last_hidden_state.float().numpy()
    (emb,) = pipeline.encoder.run(None, {"feats": pipeline.frontend(warm)})
    cosine = float((ref_emb * emb).sum() / (np.linalg.norm(ref_emb) * np.linalg.norm(emb)))

    # Quantized encoders drift numerically; judge them on behaviour, not cosine:
    # transcribe probes with both engines and require near-identical text.
    segs = split_on_silence(wav_t)
    long_seg = next(s for s in segs if (s[1] - s[0]) / SAMPLE_RATE >= 24)
    probes = [wav_t[: int(9.62 * SAMPLE_RATE)], wav_t[long_seg[0]:long_seg[1]]]
    probe_wers = []
    for probe in probes:
        ref_text = ref.transcribe(probe, lang=lang)
        got_text = pipeline.transcribe(probe.numpy(), lang=lang, mode="native",
                                       max_new_tokens=512)["text"]
        probe_wers.append(jiwer.wer(normalize(ref_text), normalize(got_text)))
    del ref
    if max(probe_wers) > 0.10:
        raise RuntimeError(f"int4 export fails text parity vs torch (probe WERs {probe_wers}, "
                           f"encoder cosine {cosine:.3f}); export untrusted")

    pipeline.transcribe(warm, lang=lang, mode="native", max_new_tokens=512)
    t0 = time.perf_counter()
    texts = []
    for a, b in split_on_silence(wav_t):
        piece = wav_t[a:b]
        if piece.numel() < 1600:
            continue
        texts.append(pipeline.transcribe(piece.numpy(), lang=lang, mode="native",
                                         max_new_tokens=512)["text"])
    wall_s = time.perf_counter() - t0
    rss_after_run_mb = psutil.Process().memory_info().rss / 1e6
    text = " ".join(t.strip() for t in texts if t and t.strip())
    return {"device": "cpu", "dtype": "int4", "load_s": load_s, "wall_s": wall_s,
            "encoder_cosine": cosine, "probe_wers_vs_torch": probe_wers,
            "rss_after_load_mb": rss_after_load_mb, "rss_after_run_mb": rss_after_run_mb,
            "text": text, "onnxruntime": onnxruntime.__version__}


def run_engine(engine: str, sample: Path, refs_path: Path | None, lang: str, out_dir: Path) -> None:
    import soundfile as sf

    audio_s = len(sf.read(sample, dtype="float32")[0]) / SAMPLE_RATE
    if engine.startswith("torch"):
        result = run_torch(engine, sample, lang)
    elif engine == "onnx-int8":
        result = run_onnx(sample, lang)
    elif engine == "onnx-int4":
        result = run_onnx_int4(sample, lang)
    else:
        raise ValueError(f"unknown engine {engine}")

    result.update({
        "engine": engine,
        "audio_s": audio_s,
        "rtf": audio_s / result["wall_s"],
        "peak_rss_mb": peak_rss_mb(),
        "platform": platform.machine(),
    })
    if refs_path:
        import jiwer
        refs = json.loads(refs_path.read_text())
        reference = normalize(" ".join(r["text"] for r in refs))
        result["wer"] = jiwer.wer(reference, normalize(result["text"]))
    (out_dir / "transcripts").mkdir(parents=True, exist_ok=True)
    (out_dir / "transcripts" / f"{engine}.txt").write_text(result["text"])
    (out_dir / f"{engine}.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps({k: v for k, v in result.items() if k != "text"}, indent=2), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--minutes", type=float, default=10)
    parser.add_argument("--lang", default="hi")
    parser.add_argument("--sample", type=Path, help="existing 16k-compatible wav; skips FLEURS prep")
    parser.add_argument("--refs", type=Path, help="reference json matching --sample; WER skipped if absent")
    parser.add_argument("--engines", default="torch-cpu-fp32,torch-mps-bf16,onnx-int4")
    parser.add_argument("--engine", help="internal: run a single engine in this process")
    parser.add_argument("--out", type=Path, default=ROOT / "results")
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    if args.sample:
        sample, refs_path = args.sample, args.refs
    else:
        sample, refs_path = prepare_sample(args.minutes, args.lang, ROOT / "data")

    if args.engine:
        run_engine(args.engine, sample, refs_path, args.lang, args.out)
        return

    results = []
    for engine in args.engines.split(","):
        engine = engine.strip()
        print(f"== {engine}", flush=True)
        proc = subprocess.run(
            [sys.executable, __file__, "--engine", engine, "--sample", str(sample),
             "--lang", args.lang, "--out", str(args.out)]
            + (["--refs", str(refs_path)] if refs_path else []),
            capture_output=True, text=True)
        sys.stdout.write(proc.stdout)
        if proc.returncode != 0:
            print(proc.stderr[-3000:], flush=True)
            print(f"-- {engine} FAILED (see above); continuing", flush=True)
            continue
        results.append(json.loads((args.out / f"{engine}.json").read_text()))

    stamp = time.strftime("%Y%m%d-%H%M%S")
    summary = {"when": stamp, "sample": str(sample), "lang": args.lang, "results": results}
    (args.out / f"benchmark-{stamp}.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\n{'engine':18s} {'RTF':>8s} {'peak MB':>9s} {'WER':>7s} {'load s':>8s}")
    for r in results:
        print(f"{r['engine']:18s} {r['rtf']:8.2f} {r['peak_rss_mb']:9.0f} "
              f"{r.get('wer', float('nan')):7.3f} {r['load_s']:8.1f}")
    print(f"\nsaved: {args.out / f'benchmark-{stamp}.json'}")


if __name__ == "__main__":
    main()
