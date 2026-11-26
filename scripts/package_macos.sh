#!/usr/bin/env bash
# Build the macOS .app (PyInstaller) with bundled UI, fonts, diarization models,
# and the Swift dictation helper. Weights download on first run via the wizard.
set -euo pipefail
cd "$(dirname "$0")/.."
uv run pyinstaller --noconfirm --windowed --name Notetaker \
  --osx-bundle-identifier com.notetaker.app \
  --add-data "NOTICE.md:." \
  --add-data "notetaker/static:notetaker/static" \
  --add-data "notetaker/assets:notetaker/assets" \
  --add-data "models:models" \
  --add-binary "swift/.build/release/NotetakerHelper:." \
  --collect-all _soundfile_data \
  --collect-binaries sherpa_onnx \
  --collect-binaries onnxruntime \
  --exclude-module torch --exclude-module torchaudio \
  --exclude-module transformers --exclude-module accelerate \
  --exclude-module datasets --exclude-module librosa \
  --exclude-module jiwer --exclude-module sentencepiece \
  --exclude-module numba --exclude-module llvmlite \
  --exclude-module pandas --exclude-module pyarrow \
  --exclude-module matplotlib \
  notetaker/__main__.py
codesign --force --deep --sign - dist/Notetaker.app
echo "built: dist/Notetaker.app (ad-hoc signed; Gatekeeper: right-click > Open first time)"
