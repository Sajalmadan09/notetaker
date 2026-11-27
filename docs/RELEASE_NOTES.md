# Kiroku 0.3.0 (preview)

Kiroku turns your meetings and voice into notes. It listens in Hindi, English and 23 more
Indian languages, including Hinglish, and it does the listening **on your Mac**. Your
recordings never leave your computer.

---

## What you need

- A Mac with an Apple chip (M1, M2, M3 or newer). Older Intel Macs are not supported yet.
- About 2 GB of free space (7 GB if you add the Hinglish engine, see below).
- Tested on macOS 26 on a MacBook Air (M2, 16 GB). Older macOS versions haven't been tested yet.

## Install the app (5 minutes)

1. Download **Kiroku-0.3.0-macOS-AppleSilicon.zip** from this page.
2. Double-click the zip. A **Kiroku** app appears.
3. Drag **Kiroku** into your **Applications** folder.
4. Open Kiroku. The first time, your Mac says it **can't verify the app**. That's because
   this preview isn't registered with Apple yet. Click **Done**, then:
   - open **System Settings → Privacy & Security**,
   - scroll down to the message about Kiroku and click **Open Anyway**,
   - confirm with your password or Touch ID.

   You only do this once.

## First launch

- Kiroku asks you to accept the speech model's license and downloads it (about 700 MB).
  Keep the Mac online until it finishes.
- When you first record, your Mac asks for **Microphone** access. Click **Allow**.
- For dictation (typing with your voice into any app), your Mac asks for **Accessibility**
  access: **System Settings → Privacy & Security → Accessibility**, switch on Kiroku.

## Using it

- **Record a meeting:** press the big red button. Press again to stop. Kiroku writes down
  who said what and opens the notes.
- **Upload audio:** any recording your browser can play works.
- **Library:** all your recordings. Click one to read it, play it back, rename people
  ("Speaker 1" → "Asha"), and export it as a document, text or PDF.
- **Closing the window doesn't quit Kiroku.** It keeps running, so recordings, downloads
  and dictation carry on. Click **🎙** in the menu bar (top right of your screen) →
  **Open Kiroku** to bring it back, or click Kiroku in the Dock. To quit completely:
  **🎙 → Quit Kiroku**, or press **⌘Q** while Kiroku is in front.
- **Dictate anywhere:** hold **Option + Space**, speak, let go. The text is typed where
  your cursor is. Hold for 3 seconds to keep listening hands-free; press again to stop.

## Optional extras (in Settings)

**AI notes**: summaries, to-do lists, and "ask this meeting" questions. Pick one:
- **On this Mac**: free and fully private, using Ollama. Can make an older Mac slow.
- **Your chat subscription**: Claude Code, Codex, Gemini CLI or Qwen Code, if you
  already use one. Fast, and your Mac stays cool.
- **An API key**: Claude, OpenAI, Gemini, or any compatible service.

Kiroku always tells you where text goes. Audio is never sent anywhere.

**Dictation cleanup**: removes "um" and repeats, applies your corrections ("Friday,
no, Monday" → Monday) and fixes punctuation, keeping your Hindi and English words as you
said them. Needs AI notes. If cleanup ever fails, your exact words are typed instead.

**Hinglish engine (code-mix)**: much better when you mix Hindi and English. It's a free
4.9 GB download that needs a free Hugging Face account:
1. Sign in at huggingface.co/bodhan-ai/indic-transcribe-flex and accept the license.
2. Create a **Read** token at huggingface.co/settings/tokens.
3. In Kiroku: **Settings → Speech engine** → paste the token → **Download**.
It becomes the default automatically. After you open Kiroku it needs about a minute to
warm up.

**Connectors**: post notes to **Slack**, save them as a **Gmail draft** (Kiroku never
sends email itself), and see your **Google Calendar** meetings on the Record page.
Setup takes 10–15 minutes and is explained step by step in Settings → Connectors.

## Chrome extension (for Google Meet in Chrome)

1. Download **Kiroku-chrome-extension.zip** and double-click it to unzip.
2. In Chrome, go to **chrome://extensions** and switch on **Developer mode** (top right).
3. Click **Load unpacked** and choose the unzipped folder.
4. Click the puzzle-piece icon and pin **Kiroku**.
5. Open the Kiroku icon → **Settings → Allow microphone**, so your own voice is included.

In a Meet call, click the Kiroku icon → **Record this tab** (or press **Option + Shift + R**).
The Kiroku app must be open. Use headphones to avoid echo.

## Your privacy

- Audio is recorded and transcribed on your Mac and never uploaded.
- Recordings are stored in your user folder (Library → Application Support → Kiroku).
  Delete a recording from its page and it's gone from disk.
- Passwords, keys and tokens are kept in your Mac's Keychain.
- Text only goes online if you switch on an online AI or a connector, and Kiroku says so
  each time.

## Known issues in this preview

- The "can't verify" message on first open (see Install). It goes away once Kiroku is
  registered with Apple.
- Speaker separation sometimes splits one person into two. Rename them to fix the notes.
- Gmail drafts and Calendar use Google features that are still in preview. Some Google
  accounts may not have access yet.
- Codex and Gemini CLI haven't been tested yet.

## Uninstall

Drag Kiroku from Applications to the Bin. To also remove your recordings and settings,
delete the **Kiroku** folder in your user folder → Library → Application Support.

## What's new in 0.3.0

- New look and new name: Kiroku (記録, "the record").
- AI notes with your choice of model, including your chat subscription.
- Dictation cleanup that keeps Hindi and English as spoken.
- The Hinglish (code-mix) engine as an in-app download.
- Slack, Gmail and Google Calendar connectors.
- The Chrome extension names recordings after your calendar event.
- Closing the window keeps Kiroku running in the menu bar (🎙 → Open / Quit).
- Fixed: "Detect automatically" no longer fails with the higher-quality engines.
- Fixed: the Hinglish engine is only switched on once its download has fully finished.
