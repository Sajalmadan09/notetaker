# Dictation layer findings — Wispr Flow observation study

Date: 2026-11-26. Target: `~/Applications/Wispr Flow.app` (user-owned install),
Electron `com.electron.wispr-flow` v1.6.1631 + Swift helper v1.6.1628
(`Contents/Resources/swift-helper-app-dist`). Method: static inspection only
(asar listing, string tables, shipped debug-tool schemas). Purpose: lawful
interoperability research — observe mechanisms, re-implement with public APIs.
No proprietary code or assets copied. Wispr Flow's EULA may restrict reverse
engineering; this document records behavior-level observations, not expressions.

## Architecture observed

- **Electron main/renderer** (webpack bundle in `app.asar`) + **Swift helper app**
  for all OS-level work + native node modules (`panel_activation.node`,
  `node_sqlite3`, Jabra headset connector).
- **Cloud ASR + formatting**: WebSocket endpoints `wss://api.wisprflow.ai/` and
  `wss://api-east.wisprflow.ai/`; `incrementalOpusEncoder.worker.js` streams Opus
  chunks upward. History metadata provenance tags: `asrText`, `formattedText`,
  `serverFinalizedText` = server-side; `pastedText` = client post-processed.
  `toneMatchedText` implies server-side tone/style matching.
- **Local ONNX**: `onnxruntime-node` shipped in `app.asar.unpacked` — local models
  run on-device too (likely VAD/spotting; exact models not inspected).
- **Local state**: unencrypted `flow.sqlite` (History: audio, opusChunks, axText,
  axHTML, screenshot…) + dev JSONL trace sidecars per dictation uuid:
  paste-formatting, proper-noun, textbox-context, insertion-verification,
  dictation-event, edited-text, context-capture; meeting mode adds
  `meeting-ax.jsonl` / `meeting-ax-helper.jsonl`.

## Dictation pipeline (stage order inferred from traces + provenance)

1. Keybind/hold-to-talk gesture (JS state machine `holdToTalk.handle/release`;
   native side uses **CGEventTap** — `CGEventTapLocation/Options`, `CGEventFlags`).
2. Context capture: focused app + textbox contents via AX (`axText`, `axHTML`;
   terminals pad with NUL bytes — their inspector hex-decodes to avoid truncation).
3. Mic audio → incremental Opus → cloud ASR → cloud formatting/finalization.
4. Client post-processing → `pastedText` handed to the Swift helper.
5. Insertion via **AXUIElement/AXValue** (incl. `AXUIElementForTextMarker`,
   `_AXUIElementGetWindow`, `_systemAXUIElement`), with **NSPasteboard** paste as
   fallback (`generalPasteboard`, `writableTypesForPasteboard`, explicit
   "Pasteboard content was not updated" failure detection).
6. **Insertion verification**: read focused element contents before/after
   (`VerifiedBeforeAfter` verdict, `insertionVerificationTimeMs`, drop reasons) —
   the non-obvious trick worth adopting: never trust a paste, verify by read-back.
7. Edit/undo tracking (`edited-text` traces) + history persistence.

Other native APIs observed: `AXObserver` (focus/value change notifications),
CoreAudio `AudioObjectPropertyAddress` (device selection/properties),
MediaRemote `NowPlaying` cache (media state/keys). Meeting mode has translation
telemetry and a recording-lock confirm flow; its audio capture path was not
identified in this pass (no ScreenCaptureKit strings in the Swift helper).

## Mapping to our offline product

| Stage | Wispr Flow | Our offline equivalent |
|---|---|---|
| Hotkey | CGEventTap + hold-to-talk FSM | CGEventTap or Carbon hotkeys in a small Swift helper; same FSM shape |
| Context | AX focused-element capture | AXUIElement read of focused value (public API) |
| ASR | cloud WS + Opus streaming | local int4 ONNX (12.8× RTF); live 10 s preview already built |
| Formatting | cloud LLM tone match | rules first; optional local LLM later |
| Insertion | AX set-value + pasteboard fallback | same two-path design, public APIs |
| Verification | before/after AX read-back | adopt verbatim as a design idea |
| Debug | per-dictation JSONL traces | adopt: per-job trace sidecars (we already retain job audio) |
| System audio | not identified | ScreenCaptureKit / CoreAudio loopback in native layer (v2+) |

## Lessons ranked by value to us

1. **Verify insertion by AX read-back** (before/after), with explicit failure
   verdicts — turns "paste sometimes silently fails" into a measurable, retryable
   step.
2. **Two-path insertion** (AX direct value set, pasteboard fallback) covers
   native apps, web views, and terminals differently; text-marker APIs handle
   rich text.
3. **Hold-to-talk as an explicit state machine** with per-keybind registration,
   not ad-hoc key handlers.
4. **Trace sidecars per dictation** make insertion bugs debuggable offline.
5. Cloud quality is a product trade-off we deliberately don't copy; our offline
   stack already matches their *local* components (ONNX on-device).

## Open questions (not pursued)

- Meeting-mode system audio capture mechanism (no SCK strings in helper).
- Which local ONNX models they ship (VAD? spotting?).
- Windows/Linux insertion equivalents (SendInput/UIA, uinput/AT-SPI) — public API
  knowledge, no RE needed.
