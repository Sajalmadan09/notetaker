# Install Notetaker (plain-language guide)

## What you need

- A Mac with Apple Silicon (M1/M2/M3/M4), macOS 13 or newer.
  (Intel Macs, Windows, Linux: not packaged yet — see "Other platforms".)
- ~1 GB free disk: app ~220 MB + one-time model download ~700 MB.
- Internet **once**, for the model download. Afterwards everything is offline.

## Install (non-technical)

1. Unzip `Notetaker-macos-arm64.zip`.
2. Drag **Notetaker.app** into your Applications folder.
3. **Right-click (or Control-click) the app → Open → Open.**
   macOS warns because the app is not notarized yet; right-click-Open is the
   one-time override. (Double-clicking alone will be blocked the first time.)
4. Your browser opens the setup page:
   - tick "I accept the model licenses" → Accept;
   - click **Download models** and wait for the progress bar (~700 MB, one time);
   - click **Test microphone** and allow access;
   - click **Open Notetaker**.
5. Done. Record a meeting, upload audio, or capture a Google Meet tab
   ("Capture Meet tab" → pick the Meet tab → enable "Share tab audio").
   Completed recordings appear under **Recordings** with playback and
   Markdown / Text / PDF export.

## Dictation (optional, built in)

The app also starts a small dictation helper:
- **Hold Option+Space** and speak, release → text appears where your cursor is.
- Hold ≥3 s → latched hands-free mode; press again to stop.
- Or click the floating mic button on your desktop.
- First use: grant **Accessibility** permission to NotetakerHelper when prompted
  (System Settings → Privacy & Security → Accessibility), and microphone access.

## Where your stuff lives

- Packaged app: `~/Library/Application Support/Notetaker` (history, audio, setup).
- Models: `~/.cache/huggingface` (shared, one download for all channels).
- Nothing is uploaded anywhere. Uninstall = delete the app + that folder.

## Troubleshooting

- "App can't be opened": right-click → Open (step 3). If still blocked:
  System Settings → Privacy & Security → "Open Anyway".
- No transcription / silent failure: check microphone permission for the app and
  for your browser; check free disk space (macOS misbehaves when the disk is full).
- Startup problems: read `~/Library/Application Support/Notetaker/startup-error.log`.
- Dictation inserts nothing: click into a text field first; the menu-bar icon and
  the floating pill show whether it heard you and whether insertion verified.

## Technical users (any OS with Python 3.10–3.12)

```bash
uv sync                      # core, torch-free
uv run python -m notetaker   # server + browser + helper (macOS)
# or: uv run uvicorn notetaker.server:app --port 8010
uv sync --extra bench        # optional: torch engine + benchmarking
uv run pytest                # tests
```

## Other platforms

Windows / Linux / Intel Mac builds are planned (PyInstaller per-OS; cannot
cross-compile). The dev channel above works on any OS today.

## License note

Personal/non-commercial use is fine as shipped. The bundled pyannote segmentation
model is CC-BY-NC-4.0; commercial redistribution needs a replacement or a commercial
pyannote license. See NOTICE.md for all attributions.
