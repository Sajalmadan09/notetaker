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
  --hidden-import safetensors.numpy \
  --hidden-import scipy.signal \
  --hidden-import onnxruntime \
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
# macOS kills mic access from a bundle whose Info.plist lacks the usage string;
# the helper's responsible process is this app, so the key must live here.
/usr/libexec/PlistBuddy -c "Add :NSMicrophoneUsageDescription string 'Notetaker uses the microphone to transcribe your speech locally on this Mac.'" dist/Notetaker.app/Contents/Info.plist 2>/dev/null \
  || /usr/libexec/PlistBuddy -c "Set :NSMicrophoneUsageDescription 'Notetaker uses the microphone to transcribe your speech locally on this Mac.'" dist/Notetaker.app/Contents/Info.plist
codesign --force --deep --sign - dist/Notetaker.app
echo "built: dist/Notetaker.app (ad-hoc signed; Gatekeeper: right-click > Open first time)"
