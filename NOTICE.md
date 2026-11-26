# Notetaker — attributions and third-party licenses

Notetaker application code © 2026 Sajal Madan. Third-party components below keep
their own licenses; this file must accompany any redistribution of the app or bundle.

## Models (downloaded on first run or bundled)

- **Bodhan `indic-transcribe-core`** (ASR), used via the community ONNX export
  `kazuto098/indic-transcribe-core-int4-onnx`: Indic Open Model License —
  attribution required, share-alike; local/offline use permitted; hosted-API use
  requires written approval from Bodhan AI. https://huggingface.co/bodhan-ai/indic-transcribe-core
- **NVIDIA Canary-1b-v2** (base architecture/weights lineage of the above):
  see NVIDIA model card license. https://huggingface.co/nvidia/canary-1b-v2
- **pyannote segmentation-3.0** (speaker segmentation, bundled): **CC-BY-NC-4.0 —
  non-commercial only**. Commercial distribution requires replacing this model or
  obtaining a commercial license from pyannote. https://huggingface.co/pyannote/segmentation-3.0
- **3D-Speaker CAM++ / ERes2Net** (speaker embeddings, bundled): Apache-2.0 per
  ModelScope model repos. https://github.com/modelscope/3D-Speaker
- **sherpa-onnx** (diarization runtime, bundled): Apache-2.0.
  https://github.com/k2-fsa/sherpa-onnx

## Fonts (bundled)

- **Noto Sans Devanagari / Noto Sans** (PDF export): SIL Open Font License 1.1.
  https://github.com/notofonts/notofonts.github.io

## Software libraries (bundled in the macOS app)

- ONNX Runtime: MIT · FastAPI: MIT · Uvicorn: BSD-3 · NumPy: BSD-3 ·
  soundfile/_soundfile: BSD-3 · fpdf2: LGPL-3.0 · uharfbuzz: MIT ·
  huggingface_hub: Apache-2.0 · PyInstaller: GPL-2-with-exception (bundled apps
  may be distributed under any license).

## Your data

Audio, transcripts, and history stay on the user's machine
(`~/Library/Application Support/Notetaker` for the packaged app). No telemetry.
