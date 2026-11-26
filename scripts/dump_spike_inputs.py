"""Dump frontend features + Python-ORT encoder output for the Rust ort spike."""
import sys
import time
from pathlib import Path

import numpy as np
import onnxruntime as ort
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent))
from benchmark_asr import int4_dir

d = int4_dir()
sys.path.insert(0, str(d))
from inference import Frontend

wav, sr = sf.read("data/fleurs_hi_10min.wav", dtype="float32", always_2d=True)
wav = wav[:, 0][: int(9.62 * sr)]
feats = Frontend(d / "preprocessor")(wav)
np.save("data/spike_feats.npy", feats)

sess = ort.InferenceSession(str(d / "onnx" / "encoder.onnx"), providers=["CPUExecutionProvider"])
t0 = time.perf_counter()
(hidden,) = sess.run(None, {"feats": feats})
wall = time.perf_counter() - t0
np.save("data/spike_hidden.npy", hidden)
print(f"python encoder wall={wall:.3f}s feats={feats.shape} audio_s=9.62")
