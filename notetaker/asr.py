"""Parity-verified int4 ONNX ASR engine (kazuto098 export), torch-free."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import numpy as np

INT4_REPO = "kazuto098/indic-transcribe-core-int4-onnx"
_LANG_TOKEN = re.compile(r"^<\|([a-z]{2,3})\|>$")
_NOT_LANGUAGES = frozenset({"itn", "pnc"})


def cached_int4_dir() -> Path:
    from huggingface_hub import snapshot_download
    try:
        return Path(snapshot_download(INT4_REPO, local_files_only=True))
    except Exception as e:
        raise RuntimeError(
            "int4 weights not cached; download once with "
            "`uv run python scripts/benchmark_asr.py --engines onnx-int4 --minutes 2` "
            "or `uv run hf download kazuto098/indic-transcribe-core-int4-onnx`") from e


def available_languages() -> list[str]:
    tables = json.loads((cached_int4_dir() / "tokenizer" / "prompts.json").read_text())
    return sorted(tables["prompts"])


class Int4Asr:
    def __init__(self):
        self._pipe = None

    @property
    def loaded(self) -> bool:
        return self._pipe is not None

    def _load(self):
        if self._pipe is None:
            directory = cached_int4_dir()
            sys.path.insert(0, str(directory))
            from inference import IndicTranscribeONNX
            self._pipe = IndicTranscribeONNX(folder=directory)
        return self._pipe

    def identify(self, wav: np.ndarray, topk: int = 3) -> list[tuple[str, float]]:
        """Language ID via one decoder step on the 3-token prompt prefix.

        Same trick as the official lid.py, ported to the ONNX sessions. Weak for
        the Hindi belt (hi/bho/mai/ur confusable) — prefer explicit labels when known.
        """
        pipe = self._load()
        if wav.size < 16000:
            padded = np.zeros(16000, dtype=np.float32)
            off = (16000 - wav.size) // 2
            padded[off:off + wav.size] = wav
            wav = padded
        (hidden,) = pipe.encoder.run(None, {"feats": pipe.frontend(wav)})
        (cross_kv,) = pipe.cross.run(None, {"hidden": hidden})
        prefix = np.asarray([pipe.prompts["hi"]["native"][:3]], dtype=np.int64)
        past = np.zeros((24, 2, 8, 0, 128), dtype=np.float32)
        logits, _ = pipe.decoder.run(
            None, {"input_ids": prefix, "past_kv": past, "cross_kv": cross_kv})
        step = logits[0].astype(np.float64)
        probs = np.exp(step - np.logaddexp.reduce(step))
        lang_ids = {i: m.group(1) for i, t in enumerate(pipe.vocab)
                    if (m := _LANG_TOKEN.match(t)) and m.group(1) not in _NOT_LANGUAGES
                    and m.group(1) in pipe.prompts}
        ids = sorted(lang_ids)
        order = np.argsort(probs[ids])[::-1][:topk]
        return [(lang_ids[ids[j]], float(probs[ids[j]])) for j in order]

    def transcribe(self, wav: np.ndarray, lang: str = "hi") -> str:
        pipe = self._load()
        if lang not in pipe.prompts:
            raise ValueError(f"unsupported language {lang!r}; choose from {sorted(pipe.prompts)}")
        return pipe.transcribe(wav, lang=lang, mode="native", max_new_tokens=512)["text"]
