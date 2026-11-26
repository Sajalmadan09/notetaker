# Notetaker for Google Meet (Chrome extension)

Records a Meet (or any) tab into your local Notetaker app. Audio goes only to the app on this
Mac (`http://127.0.0.1:8010`); the calendar feed goes only to Google.

## Install (load unpacked)

1. Start the Notetaker app.
2. Chrome → `chrome://extensions` → turn on **Developer mode** → **Load unpacked** → pick this `extension/` folder.
3. Pin the Notetaker icon (puzzle-piece menu → pin).
4. Popup → Settings → **allow mic**. A tab opens; click Allow. Without this, only the other
   participants are recorded, not your own voice.

## Use

- **Record a meeting:** on the Meet tab, click the icon → **Record this tab**, or press
  **Alt+Shift+R**. Stop from the popup (or the same shortcut). Live text shows every ~10 s.
  On stop, the app runs speaker separation + transcription and you get a notification; the
  recording appears in Recordings.
- **Instant meeting:** popup → **Instant meeting** (opens `meet.new`).
- **Join a link:** paste a `meet.google.com/abc-defg-hij` link in the popup → **Join**.
- **Calendar:** Google Calendar → Settings → your calendar → *Integrate calendar* → copy
  **Secret address in iCal format** → paste in popup Settings → Save. The popup lists the next
  12 hours. When a meeting with a Meet link starts, you get a notification (with an
  **Open meeting** button if its tab isn't open).
- **Auto-record:** with the setting on, if the Meet tab is open when the meeting starts,
  recording starts by itself.

## Limits (Chrome rules, not bugs)

- Chrome lets an extension capture a tab only after you've **invoked the extension on that tab**
  (icon click, popup, or the shortcut). Auto-record tries anyway; when Chrome refuses, the start
  notification asks you for one click or Alt+Shift+R. (Whether an earlier click on the same Meet
  tab is enough is untested — Chrome drops that grant when the tab navigates.)
- Tab capture records what the tab plays (the other participants) and your mic separately mixed
  in. Use headphones to avoid echo.
- The secret iCal address is a password for your calendar. It is stored only in this browser's
  extension storage. Reset it in Google Calendar if it leaks.
- Calendar parsing covers time zones, DST, recurring meetings (daily/weekly/monthly/yearly),
  cancelled and moved instances. `RDATE`/`BYSETPOS` rules are not handled.

## Tests

```bash
node --test tests/ext_ics.test.mjs                                   # calendar parser
CHROMIUM=<path to Chrome for Testing> uv run --with playwright python scripts/ext_e2e.py
```

The e2e test loads the extension in Chromium, plays a saved recording in a tab, records it
through the extension, and checks: calendar list, live preview, final transcript, saved to
Recordings. It needs the app running with at least one recording. Don't add
`--use-fake-ui-for-media-stream` / `--use-fake-device-for-media-stream`: they break tab capture.
