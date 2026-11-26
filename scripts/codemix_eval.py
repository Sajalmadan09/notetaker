"""Code-mix eval: core(native) vs flex(native/mixed/romanized) on MUCS Hindi-English test clips.

Refs are mixed-script (English in Latin). Reports strict WER after light normalisation
plus a Latin-word recall metric (how many reference English words appear in Latin script).
uv run python scripts/codemix_eval.py [N]
"""
from __future__ import annotations
import glob, os, re, sys, time
import jiwer, pandas as pd, soundfile as sf, torch
from huggingface_hub import snapshot_download

latin_pat = re.compile(r"[A-Za-z]{2,}")
N = int(sys.argv[1]) if len(sys.argv) > 1 else 24
hub = os.path.expanduser("~/.cache/huggingface/hub")
ds = f"{hub}/datasets--sajalmadan0909--mucs-hindi-english-codemix-asr/snapshots"
clips = []
for split in ("test", "train"):  # zero-shot eval; only clips whose audio is actually cached
    for mpath in glob.glob(f"{ds}/*/{split}/metadata.csv"):
        meta = pd.read_csv(mpath)
        for _, r in meta.iterrows():
            for root in glob.glob(f"{ds}/*/{split}"):
                p = os.path.join(root, r.file_name)
                if os.path.exists(p):
                    w, sr = sf.read(p, dtype="float32")
                    if sr == 16000 and w.ndim == 1 and 3 * 16000 < len(w) < 25 * 16000 and len(latin_pat.findall(r.sentence)) >= 1:
                        clips.append((w, r.sentence)); break
            if len(clips) >= N: break
    if len(clips) >= N: break
print(f"{len(clips)} code-mixed clips")

norm = lambda s: re.sub(r"[^\w\s]", "", s.lower()).split()
latin = lambda s: [w for w in norm(s) if re.fullmatch(r"[a-z0-9]+", w)]

def load(repo):
    import sys as _s
    d = snapshot_download(repo, ignore_patterns=["nemo/*", "*.png"], local_files_only=True)
    _s.path.insert(0, d)
    import importlib; m = importlib.import_module("indic_transcribe")
    importlib.reload(m)
    return m.IndicTranscribe.from_pretrained(d, device="mps", dtype=torch.bfloat16)

def run(asr, label, **kw):
    hyps, t0 = [], time.time()
    for w, _ in clips:
        hyps.append(asr.transcribe(w, lang="hi", **kw))
    refs = [s for _, s in clips]
    wer = jiwer.wer([" ".join(norm(r)) for r in refs], [" ".join(norm(h)) or "x" for h in hyps])
    rl = [x for r in refs for x in latin(r)]
    hl = {x for h in hyps for x in latin(h)}
    hit = sum(1 for r, h in zip(refs, hyps) for x in latin(r) if x in norm(h))
    print(f"{label:18s} WER {wer:.3f}  latin-recall {hit}/{len(rl)} = {hit/max(1,len(rl)):.2f}  ({time.time()-t0:.0f}s)")
    for i in range(min(3, len(refs))): print("   ref:", refs[i], "\n   hyp:", hyps[i])
    return hyps

flex = load("bodhan-ai/indic-transcribe-flex")
for mode in ("native", "mixed", "romanized"):
    run(flex, f"flex/{mode}", mode=mode)
del flex
core = load("bodhan-ai/indic-transcribe-core")
run(core, "core/native")
