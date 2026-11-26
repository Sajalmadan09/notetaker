# Distribution plan — tech and non-tech users, minimal hassle

Goal: anyone can double-click (or one-command) and use Notetaker offline.
Constraints: fully local inference; gated/attributed model licenses; macOS
Gatekeeper / Windows SmartScreen friction; no app-store requirement.

## Audience matrix

| Audience | Channel | Hassle | Status |
|---|---|---|---|
| Technical | `uv sync && uv run uvicorn notetaker.server:app` (or `uvx` once published) | one command + Python | works today |
| Semi-technical | single-file executable per OS (PyInstaller), weights on first run | download + run | planned P1 |
| Non-technical | macOS `.app` / Windows installer / Linux AppImage + first-run wizard | double-click, guided setup | planned P1 |
| Browser-only reach | Chrome extension (v2) talking to localhost server | install extension | planned P3 |

## Options considered

1. **uvx / pip (current)** — zero packaging work; requires Python literacy. Keep as
   the developer channel; publish to PyPI when stable.
2. **PyInstaller per-OS binaries (recommended P1)** — core is torch-free
   (onnxruntime + sherpa-onnx + fastapi ≈ 100–150 MB packed). Bundle `static/` UI +
   fonts; first-run wizard downloads weights (int4 ONNX from the *open* kazuto098
   repo — no gate; diarization models from sherpa-onnx releases) with progress,
   then opens the browser and starts the tray/helper. macOS: wrap in `.app`
   (Info.plist + ad-hoc codesign); Gatekeeper shows "unidentified developer" until
   notarized (Apple Developer $99/yr) — document right-click-open workaround.
   Windows: unsigned exe triggers SmartScreen until code-signing cert; document
   "More info → Run anyway". Linux: AppImage.
3. **Rust single binary (P2)** — spike already proved ort parity (cosine 0.9987).
   Smallest long-term friction (no Python at all), but requires porting frontend,
   decoder loop, and diarization; do after P1 validates the wizard flow.
4. **Tauri/Electron shell** — heavier than PyInstaller for a server+browser product;
   rejected. **Docker** — technical-only; rejected for non-tech.

## First-run wizard (the "just use it" piece)

1. Language pick (hi default) + license acceptance screen (attribution text).
2. Weight download with progress + checksum (int4 ONNX ~700 MB, diarization ~45 MB).
3. Permission grants: microphone (browser + helper), Accessibility (helper only),
   with deep links into System Settings and a re-check button.
4. Start server + helper, open dashboard, show a 10-second guided demo recording.

## License checks before shipping binaries

- Bodhan Indic Open Model License: attribution + share-alike; hosted-API use needs
  written approval (we are local-only). Verify redistribution terms for bundling.
- kazuto098 ONNX export repo: open, but inherits upstream model license — confirm.
- pyannote segmentation-3.0 weights: **CC-BY-NC-4.0** (non-commercial) — flag before
  any commercial distribution; consider swapping to a permissive segmentation model.
- 3D-Speaker / CAM++ embeddings: check ModelScope license terms.
- Noto fonts: OFL (bundle with license file). fpdf2/uharfbuzz/sherpa-onnx: permissive.

## P3 — Google Meet auto-trigger (deferred, user-confirmed later)

Chrome extension (MV3): calendar access via user-pasted **secret ICS URL** (no
OAuth consent screen) or `chrome.identity` OAuth for Calendar API; at event start,
notify + one-click capture of the Meet tab (`chrome.tabCapture` / offscreen
document) streamed to the localhost server; auto-start without a user gesture is
a design risk to validate (capture APIs may require gesture). Needs calendar +
capture permissions; keep manual capture as fallback.

## Recommendation

P1 now: PyInstaller macOS `.app` + first-run wizard (validate with non-tech user),
then Windows/Linux packagers; P2 Rust binary once ported; P3 Meet extension.
