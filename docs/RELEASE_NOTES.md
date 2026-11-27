# Kiroku 0.4.0 (preview)

Kiroku turns your meetings and voice into notes. It understands Hindi, English, Hinglish and
23 more Indian languages, and it does the listening **on your Mac**. Your recordings never
leave your computer.

---

## What you need

- A Mac with an Apple chip (M1 or newer) and **macOS 14.4 or newer**.
- About 2 GB of free space (7 GB if you add the Hinglish engine).
- Google Chrome, if you want to record Google Meet calls.

## 1. Install the app (5 minutes)

1. Download **Kiroku-0.4.0-macOS-AppleSilicon.zip** below.
2. Double-click it. A **Kiroku** app appears.
3. Drag **Kiroku** into your **Applications** folder. If you had an older Kiroku, replace it.
4. Open Kiroku. The first time, your Mac says it **can't verify the app** (this preview isn't
   registered with Apple yet). Click **Done**, then go to **System Settings → Privacy &
   Security**, scroll down and click **Open Anyway**.

## 2. Allow three things (once per version)

Your Mac will ask for these. Click **Allow** each time:

- **Microphone**, to hear your voice.
- **Accessibility**, so dictation can type into other apps (System Settings → Privacy &
  Security → Accessibility → switch on Kiroku).
- **System Audio Recording**, so Kiroku can hear the other people in your meetings (System
  Settings → Privacy & Security → Screen & System Audio Recording → "System Audio Recording
  Only" → switch on Kiroku).

Then quit Kiroku (click 🎙 in the menu bar → **Quit Kiroku**) and open it again.

> Each new version of this preview asks again, because it isn't signed with an Apple
> developer certificate yet. That goes away in a future version.

## 3. Add the Chrome extension (for Google Meet)

1. Download **Kiroku-chrome-extension.zip** below and double-click it to unzip.
2. Move the unzipped folder somewhere it can stay, like your Documents folder.
3. In Chrome, open **chrome://extensions** and switch on **Developer mode** (top right).
4. Click **Load unpacked** and choose that folder.
5. Click the puzzle-piece icon in Chrome and pin **Kiroku**.

To update the extension later, replace the folder's contents and click the **reload ↻** button
on Kiroku in chrome://extensions. Don't remove it, so it remembers your settings.

## Using Kiroku

- **Meetings record themselves.** Join a Google Meet in Chrome and a bar appears:
  "Kiroku will record this meeting in 5 s". Let it run, or click **Cancel**. When you leave
  the call (or the meeting ends), recording stops and you get a "Transcript ready" message.
- **In the notes, your own words are labelled "You"**; other people are Speaker 2, 3 and so
  on. Click a name to rename it.
- **Record anything else:** open Kiroku and press the big red button, or **Upload audio**.
- **Dictate anywhere:** hold **Option + Space**, speak, and let go. The text is typed where
  your cursor is.
- **Closing the window doesn't quit Kiroku.** Click **🎙** in the menu bar → **Open Kiroku**
  to bring it back, or **Quit Kiroku** to stop it.
- **Tip:** wear headphones in meetings so other people's voices aren't picked up twice.

## Optional extras (Kiroku → Settings)

- **AI notes:** summaries, to-do lists and "ask this meeting". Use your Claude or ChatGPT
  subscription (through Claude Code or Codex), an API key, or a free model on your Mac.
- **Dictation cleanup:** removes "um", applies your corrections and fixes punctuation,
  keeping your Hindi and English words as you said them.
- **Hinglish engine:** much better when you mix Hindi and English. A free 4.9 GB download in
  **Settings → Speech engine** (needs a free Hugging Face account; the steps are on that page).
- **Connectors:** post notes to Slack, save them as a Gmail draft, see your Google Calendar.

## Your privacy

- Audio is recorded and transcribed on your Mac and never uploaded.
- Recordings stay in your user folder (Library → Application Support → Kiroku). Delete a
  recording from its page and it's gone from disk.
- Passwords, keys and tokens are kept in your Mac's Keychain.
- Text only goes online if you switch on an online AI or a connector, and Kiroku says so.
- Let people know when you record a meeting.

## If something doesn't work

- **No meeting bar appears:** reload the extension at chrome://extensions, and make sure the
  Kiroku app is open. Pressing **Option + Shift + R** on the Meet tab also starts recording.
- **Only your voice is in the notes:** turn on System Audio Recording for Kiroku (step 2),
  then quit and reopen Kiroku.
- **Your voice is missing:** check Chrome uses your Mac's microphone at
  chrome://settings/content/microphone, not an iPhone.

## Uninstall

Drag Kiroku from Applications to the Bin, and remove the extension at chrome://extensions.
To also delete your recordings, delete the **Kiroku** folder in your user folder →
Library → Application Support.

## What's new in 0.4.0

- Meetings record automatically when you join a Google Meet, with a 5-second countdown to
  cancel, and stop when the meeting ends.
- The Kiroku app records the meeting itself: your voice from your Mac's microphone and the
  other people from Chrome, labelled "You" and Speaker 2, 3…
- Always uses your Mac's built-in microphone (not a nearby iPhone).
- AI notes through your Claude Code, Codex, Gemini CLI or Qwen Code subscription.
- The Hinglish engine as an in-app download; dictation cleanup; Slack, Gmail and Calendar.
- Fixes: silent recordings, made-up words on silence, "Detect automatically" errors.
