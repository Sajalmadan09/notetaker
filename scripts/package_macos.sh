#!/usr/bin/env bash
# Build the macOS .app (PyInstaller) with bundled UI, fonts, diarization models,
# and the Swift dictation helper. Weights download on first run via the wizard.
set -euo pipefail
cd "$(dirname "$0")/.."
(cd web && npm ci && npm run build)   # React UI -> notetaker/static/app (bundled below)
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
  --hidden-import keyring.backends.macOS \
  --collect-all webview \
  --collect-binaries sherpa_onnx \
  --collect-binaries onnxruntime \
  --collect-all torch --collect-all torchaudio --collect-all transformers \
  --collect-all sentencepiece \
  --hidden-import safetensors.torch \
  --exclude-module accelerate \
  --exclude-module datasets --exclude-module librosa \
  --exclude-module jiwer \
  --exclude-module numba --exclude-module llvmlite \
  --exclude-module pandas --exclude-module pyarrow \
  --exclude-module matplotlib \
  notetaker/__main__.py
# macOS kills mic access from a bundle whose Info.plist lacks the usage string;
# the helper's responsible process is this app, so the key must live here.
/usr/libexec/PlistBuddy -c "Add :NSMicrophoneUsageDescription string 'Notetaker uses the microphone to transcribe your speech locally on this Mac.'" dist/Notetaker.app/Contents/Info.plist 2>/dev/null \
  || /usr/libexec/PlistBuddy -c "Set :NSMicrophoneUsageDescription 'Notetaker uses the microphone to transcribe your speech locally on this Mac.'" dist/Notetaker.app/Contents/Info.plist
# A stable signing identity keeps macOS permissions (Accessibility, Microphone) across rebuilds;
# ad-hoc ("-") gets a new identity every build, so TCC re-prompts each time.
ID="${NOTETAKER_SIGN_ID:-Notetaker Local Signing}"
security find-identity -v -p codesigning | grep -q "$ID" || { echo "no '$ID' identity; falling back to ad-hoc"; ID="-"; }
codesign --force --sign "$ID" --identifier com.notetaker.helper dist/Notetaker.app/Contents/Frameworks/NotetakerHelper
codesign --force --deep --sign "$ID" --identifier com.notetaker.app dist/Notetaker.app
echo "built: dist/Notetaker.app (signed: $ID; Gatekeeper: right-click > Open first time)"
