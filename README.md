# on-desktop-notetaker

Offline Indic + code-mixed meeting/lecture notetaker. v1 = local web app:
localhost Python server + browser UI, no native app packaging.

Decided stack (2026-11-26):
- ASR: `bodhan-ai/indic-transcribe-core` (Canary-1b-v2 finetune, 25 langs, native script)
- Diarization: sherpa-onnx (VAD + segmentation + speaker embeddings) — the ASR is single-speaker
- Distribution: `uv` / pip one-liner; Mac / Windows / Linux
- Out of scope for v1: OS-wide dictation (browser tech cannot inject into native apps)

All Python tooling uses [astral uv](https://docs.astral.sh/uv/). Python is pinned to 3.12.

## Setup

```bash
uv sync                     # creates .venv from uv.lock
uv run hf auth login        # if not already logged in
```

The model repos are gated. Accept the license on each model page before downloading:
- https://huggingface.co/bodhan-ai/indic-transcribe-core
- https://huggingface.co/hari31416/indic-transcribe-onnx-int8 (ONNX fallback; manual gate)

## Benchmark (step 1 — measure before building)

```bash
uv run python scripts/benchmark_asr.py --minutes 2     # smoke run
uv run python scripts/benchmark_asr.py --minutes 10    # full run
uv run python scripts/benchmark_asr.py --sample rec.wav --lang hi   # your own audio
```

Engines compared, each in its own subprocess (per-engine peak RSS):
- `torch-cpu-fp32` — official weights, CPU (wrapper default)
- `torch-mps-bf16` — official weights, Apple Silicon GPU
- `onnx-int8` — community ONNX export, onnxruntime CPU (skipped until its gate is accepted)

Sample audio: concatenated `google/fleurs` test clips for the chosen language
(default `hi`), with reference transcripts. Reported WER is **strict**, not the
model card's OIWER — spelling variants count as errors, so treat it as an upper
bound. FLEURS is clean read speech; meeting audio will be harder.

Metrics per engine: realtime factor (audio seconds / wall seconds), peak RSS,
load time, WER. Results land in `results/`, transcripts in `results/transcripts/`.

Notes:
- **transformers is pinned to 4.57.x (`<5`)**: with transformers 5.x the custom
  modeling code loads but generation silently degenerates (dash loops, mixed-script
  garbage, WER ≈ 0.99). Do not upgrade past 4.x without re-validating output.
  huggingface-hub must stay `<1` for transformers 4.x compatibility.
- The wrapper refuses single passes > ~45 s; `long_form.transcribe_long` chunks at
  pauses into ≤30 s pieces. Do not raise the 30 s cap.
- Pass `--lang` explicitly; auto language-ID is unreliable for Hindi-belt languages.
- The M2 Air is fanless: long batches thermally throttle. Compare engines on the
  same sample back-to-back and re-run if numbers look off.

## Results (M2 Air 16 GB, 2026-11-26, 10 min FLEURS hi)

| Engine | RTF | RAM | WER (strict) | Verdict |
|---|---|---|---|---|
| onnx-int4 (kazuto098) | **12.78** | 0.8 GB load / 1.8 GB run | 0.100 | **primary candidate** — torch-free, CPU, DirectML/CUDA capable |
| torch-mps-bf16 | 10.34 | 2.8 GB peak | 0.093 | macOS accuracy reference / alternative |
| torch-cpu-fp32 | 0.93 | 5.0 GB peak | 0.093 | last-resort portable fallback |
| onnx-int8 (hari31416) | 3.22 | 2.3 GB | 0.724 | **rejected** — see below |

int4 passed the behavior parity guard: probe transcripts (9.6 s and ~25 s) are
word-identical to torch (WER 0.0); full-sample WER 0.100 vs 0.093 (+0.6 pt strict).
Its encoder cosine is 0.913 — expected drift for genuine int4, harmless to output.
RAM figures for int4 are clean RSS samples; its `peak_rss_mb` includes the torch
reference loaded by the parity guard in the same process.

Recommendation: ship v1 on **onnx-int4** (deps: onnxruntime, numpy, soundfile,
safetensors — no torch), keep torch MPS bf16 as the macOS accuracy alternative.
int4 is measured on M2 ARM only; validate x86/Linux and browser (ort-web) before
relying on it there. Consolidated numbers: `results/benchmark-final.json`.

Why hari31416 was rejected:
- `encoder-model.int8.onnx` is byte-identical (sha256) to `encoder-model.onnx`;
  same for the decoder. The "int8" labeling is not real.
- Its encoder embeddings deviate from the torch model (cosine 0.82 vs the
  claimed 0.996), at every ort optimization level → the export itself is wrong,
  not a runtime bug. WER 0.72 with repetition loops.
- The benchmark now refuses any ONNX export whose encoder cosine vs torch is
  < 0.99 on a probe clip, so a broken export can never report silent garbage.

## Diarization smoke test (2026-11-26)

`uv run python scripts/diarization_smoke.py` — simulated 2-speaker meeting (72 s,
6 FLEURS hi turns) → sherpa-onnx (pyannote segmentation-3.0 + 3D-Speaker
eres2net embeddings, models in `models/`) → merged speaker turns → int4 ASR.

- Boundaries recovered exactly; adjacent same-speaker segments merged (gap ≤1 s)
  before ASR to avoid scoring split fragments.
- Diarization ~3× realtime (23.5 s / 72 s); per-turn ASR ~14× (4.7 s);
  mean turn WER 0.041. Transcript: `results/transcripts/meeting_sim.md`.
- **Speaker identity is NOT validated**: FLEURS has no speaker ids, so ground
  truth was guessed (alternating clips); frame-error numbers are uninterpretable
  and auto-clustering over-split (5 clusters / 6 clips). Validate on a real
  recording with known speakers before trusting labels in production.

## Run the app

```bash
uv sync                     # core install is torch-free (app only)
uv sync --extra bench       # add torch/transformers/etc for benchmarking
uv run uvicorn notetaker.server:app --host 127.0.0.1 --port 8010
```

Open http://127.0.0.1:8010 (redirects to the Kiroku app, `/app/#/record`) — record via mic, capture a Google Meet tab, or upload
audio; the browser converts everything to 16 kHz mono WAV client-side (WebAudio), so
any format the browser can decode works. Pick language (25 Indic + English, or
`auto (detect)`) and speaker count (auto or 2–6). Jobs run sequentially in one worker
thread; poll progress in the UI; download the speaker-labeled notes as Markdown.
Audio never leaves the machine; weights are read from the local HF cache only
(`local_files_only`), so runtime is fully offline.

- **Live preview**: while recording, 10 s timeslices go to `POST /api/quick` and show
  provisional "live" cards; the final job diarizes and replaces them with
  speaker-labeled turns. (Word-level streaming is not possible with this offline
  model; the gated `indic-transcribe-lite` sibling is the streaming option.)
- **Auto language ID**: ported from the official `lid.py` trick — one decoder step on
  the 3-token prompt prefix over the int4 encoder states. Verified hi p=1.0 on clean
  clips; weak for hi/bho/mai/ur in the wild, so explicit labels remain the default.
- **Meet tab capture**: "Capture Meet tab" uses `getDisplayMedia` tab-audio sharing
  (enable "Share tab audio" in the picker) mixed with your mic. Captures web Meet
  only — not the desktop app, and it does not join as a participant.
- **Recordings history**: every completed job persists audio + transcript to
  `data/history/` (local only) and appears on the dashboard (below).
- Overlapping diarization segments are resolved to a single timeline
  (`resolve_overlaps`) before same-speaker merging.
- **Engine toggle**: `int4` (default, fast, torch-free) or `torch` (official 1B
  weights, MPS bf16 on Mac, max accuracy; needs `uv sync --extra bench`).
- **Diarization embedding**: CAM++ default — measured 2.3× faster than
  ERes2Net-base (10.7 s vs 25.0 s on the 72 s simulated meeting) with identical
  turn boundaries. int8 segmentation was tested and **rejected**: ~4% faster but
  it truncates turn onsets. Speaker identity on real Hindi audio remains
  unvalidated for either embedding.

## Recordings dashboard

http://127.0.0.1:8010/app/ (Library) — every completed
recording with **playable audio**, speaker-colored transcript, and per-recording
export in **Markdown, TXT, and PDF**. PDF uses fpdf2 + uharfbuzz with bundled
Noto Sans Devanagari + Noto Sans (OFL) so Hindi matras/conjuncts shape correctly
and Latin labels render (the Devanagari font alone has no Latin glyphs).

Dictation helper sessions are ingested too: after each dictation the helper posts
its WAV + text + insertion verdict to `POST /api/history`, so dictations appear on
the dashboard with a 🎙 badge and verdict, playable audio, and the same exports.

API: `GET /api/history`, `POST /api/history` (helper ingest), `GET /api/history/{id}`,
`GET /api/history/{id}/audio`, `GET /api/history/{id}/export?fmt=md|txt|pdf`.
`PATCH /api/history/{id}` (`{"title": ..., "names": {"0": "Priya"}}`) and
`DELETE /api/history/{id}`. In the dashboard: click the title to rename, name speakers in
the Details tab (names flow into the transcript, timeline, copy, and all exports), and
Export → Delete recording (click twice).
Storage: `data/history/<id>.json` + `<id>.wav`. Tests isolate storage by overriding
`history.HISTORY_DIR`.

## Kiroku app UI (`web/`) + bring-your-own AI

Test setup (verified 2026-11-27): `uv run hf download kazuto098/indic-transcribe-core-int4-onnx`
(667 MB), Ollama >= 0.40 with `ollama pull gemma3:4b` (3.4 GB). Settings → Ollama → gemma3:4b.
Summary of a 72 s meeting: ~40 s cold, ~14 s warm on an M2 Air.

React + Vite + TypeScript, built into `notetaker/static/app/` and served at `/app/`
(build output is gitignored; `package_macos.sh` builds it). Dev: `cd web && npm i && npm run dev`
(proxies `/api` to :8010). Production build: `npm run build`.

- Library (`#/`), meeting page (`#/r/<id>`: player with speaker lanes + chapter marks,
  Summary / Transcript tabs, rename title and speakers inline, Ask panel), Settings (`#/settings`).
- Design: manga ink-on-paper (hard panel borders, screentone, speech-bubble transcript,
  hanko-seal accent, mincho headings with kanji captions). No gradients or glow. Light/dark.
- AI (`notetaker/llm.py`): Claude via the official `anthropic` SDK (default `claude-opus-5-5`,
  server-side refusal fallback on), or any OpenAI-compatible API (OpenAI, Gemini, Ollama,
  LM Studio, OpenRouter...). Keys go to the macOS Keychain via `keyring` and are never returned
  by the API. Only transcript text is sent, and only on Summarize/Ask; the UI says where.
- API: `GET/PUT /api/llm/settings`, `GET /api/llm/models?provider=`,
  `POST /api/history/{id}/summarize`, `POST /api/history/{id}/ask`.
- Local-only guard: requests with a non-localhost `Host` (DNS rebinding) or a cross-site
  `Origin` on writes get 403. Chrome-extension origins are allowed.

## UI system

`notetaker/static/app.css` — shared zero-build design tokens + components (light/dark,
focus states, reduced-motion, skeletons, toasts). Dashboard adds search (`/`), source
filter, stats, verdict badges, copy-transcript. Open-source upgrade paths if a
component library is ever wanted: Pico.css / Open Props / DaisyUI (vendorable, MIT),
shadcn/ui (MIT, needs React build); inspiration: Dribbble/Behance/Refero free tier,
and open-source dashboards (Cal.com, Documenso, Plane, Formbricks).

## Desktop window

The packaged app opens its UI in a native window (pywebview / WKWebView) instead of a
browser tab; the server still runs inside the app on 127.0.0.1 but is invisible to users.
Closing the window quits the app and the dictation helper. `NOTETAKER_BROWSER=1` forces
the old browser-tab mode; if no native window can be created it falls back automatically
(reason in `window-error.log` in the data dir). Tab capture (`getDisplayMedia`) does not
exist in WKWebView — Meet capture belongs to the Chrome extension.

## Packaging — macOS `.app` + first-run wizard

```bash
bash scripts/package_macos.sh     # PyInstaller .app, ad-hoc signed
open dist/Notetaker.app           # first run: right-click > Open (Gatekeeper)
```

Bundles UI, fonts, diarization models, and the Swift helper. On first run the server
redirects to `/setup.html`: license acceptance → model download with progress
(int4 ~700 MB from the open export repo + diarization ~45 MB) → mic test → open app.
Frozen-app data lives in `~/Library/Application Support/Notetaker`; dev checkout uses
`data/`. Entry point: `uv run python -m notetaker` (env `NOTETAKER_PORT`,
`NOTETAKER_NO_HELPER`, `NOTETAKER_DATA`). See `docs/distribution-plan.md` for the
full tech/non-tech matrix, signing caveats, and license flags (pyannote CC-BY-NC).

## Rust spike (`rust/`)

`cargo build --release --manifest-path rust/Cargo.toml` then
`rust/target/release/notetaker-spike data/spike_feats.npy data/spike_hidden.npy
<int4 repo>/onnx/encoder.onnx 9.62` (inputs via `uv run python scripts/dump_spike_inputs.py`).
Purpose: validate the `ort` crate (same ONNX Runtime kernels as Python) as the path
to a single-binary, no-Python distribution. Rust does not speed up the kernels
themselves; its value is packaging, memory control, and concurrency.

Spike results (2026-11-26, ort 2.0.0-rc.15, `load-dynamic` against the same
libonnxruntime 1.32 dylib Python uses; set `ORT_DYLIB_PATH`):
- **Parity verified: cosine 0.9987** vs Python encoder output on identical features.
- Bug found: `np.save` preserves **Fortran order** (Frontend output is F-contiguous);
  a C-order-only npy reader silently feeds transposed garbage (cosine 0.075,
  identical across runtimes — the signature of bad input bytes, not bad kernels).
- Perf gap remains: Rust warm ~0.8–1.2 s vs Python 0.31 s (8 threads) / 0.85 s
  (1 thread). Python's session thread pool scales; ort's environment global-thread
  pool defaults do not. Knobs: `with_global_thread_pool`, spin control, execution
  mode. Open tuning follow-up, not a kernel problem.
- Full port (frontend, decoder loop, diarization) is the real work if we pursue
  single-binary distribution; the spike covers only the encoder.

API: `GET /api/health`, `GET /api/languages`, `POST /api/jobs` (multipart file +
lang + speakers + engine), `POST /api/quick` (<=20 s live chunk), `GET /api/jobs/{id}`.

Tests: `uv run pytest` (split/merge unit tests + server integration over real HTTP
with stdlib urllib; no TestClient/httpx dependency).

Layout: `notetaker/audio.py` (pause-splitting), `diarize.py` (sherpa-onnx + turn
merge), `asr.py` (int4 engine), `pipeline.py` (orchestration), `server.py` (FastAPI
+ job queue), `static/index.html` (UI).

## Swift dictation helper spike (`swift/`)

Hold-to-talk dictation into any app, implementing the mechanisms observed in
`docs/dictation-layer-findings.md` with public macOS APIs only:

```bash
swift build -c release --package-path swift
swift/.build/release/NotetakerHelper --check      # permissions + server status
swift/.build/release/NotetakerHelper --selftest   # insert+verify into scratch TextEdit doc
swift/.build/release/NotetakerHelper              # hold Option+Space to dictate
```

- Carbon hotkey (Option+Space) — no event tap needed for registration. Gestures:
  hold <3 s = push-to-talk; hold ≥3 s = **latched** continuous listening; press
  again = stop + insert (`NOTETAKER_LATCH_SECONDS` tunable).
- Indicators: menu-bar 🎙 idle / 🔴 listening / ⏳ processing, plus a floating
  non-activating pill (top-center, live mic level meter) shown only while active —
  never steals focus from the dictation target.
- **Floating desktop button**: persistent draggable mic circle (position persisted
  in UserDefaults). Click = start latched listening; click again = stop + insert.
  Mirrors hotkey state (🎙 idle / ⏹ active / ⏳ processing); clicks never steal focus.
- AVAudioEngine mic → 16 kHz WAV → local server `/api/quick` (int4 ASR).
- Insertion: AX `kAXSelectedTextAttribute` set, NSPasteboard + Cmd+V fallback with
  pasteboard-update check and restore; **verification by AX read-back before/after**.
- Per-dictation JSONL traces: `~/Library/Logs/NotetakerHelper/dictation.jsonl`.
- Requires Accessibility permission for the binary (System Settings > Privacy &
  Security > Accessibility). Without it, insertion fails safely with an
  `unverified`/`failed` verdict — never silent typing.
- Env: `NOTETAKER_SERVER` (default http://127.0.0.1:8010), `NOTETAKER_LANG` (default hi).

## Roadmap

1. Benchmark runtimes on M2 — done (`results/benchmark-final.json`)
2. Diarization smoke test — done (mechanics validated; identity pending real audio)
3. FastAPI server + minimal browser UI — done (running; e2e verified)
4. Next: validate speaker identity on a real recording; then packaging (`uvx`/pip
   one-liner), and browser-extension feasibility study for v2
