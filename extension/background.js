// Service worker: capture lifecycle, calendar (secret ICS) watcher, notifications.
const DEFAULTS = {
  server: "http://127.0.0.1:8010",
  lang: "hi",
  icsUrl: "",
  autoCapture: false,
};
let capturing = false;
let lastPreview = "";
let notifiedEvents = {};

async function settings() {
  const s = await chrome.storage.local.get(DEFAULTS);
  return { ...DEFAULTS, ...s };
}

async function ensureOffscreen() {
  const has = await chrome.offscreen.hasDocument();
  if (!has) {
    await chrome.offscreen.createDocument({
      url: "offscreen.html",
      reasons: ["USER_MEDIA"],
      justification: "Record Google Meet tab audio for local transcription",
    });
  }
}

async function findMeetTab() {
  const tabs = await chrome.tabs.query({ url: "*://meet.google.com/*" });
  return tabs[0] || null;
}

async function startCapture(tabId) {
  if (capturing) return { ok: false, error: "already capturing" };
  const s = await settings();
  try {
    const streamId = await chrome.tabCapture.getMediaStreamId({ targetTabId: tabId });
    await ensureOffscreen();
    const res = await chrome.runtime.sendMessage({
      type: "offscreen-start", streamId, server: s.server, lang: s.lang,
    });
    if (!res || !res.ok) throw new Error(res ? res.error : "offscreen unavailable");
    capturing = true;
    lastPreview = "";
    chrome.action.setBadgeText({ text: "REC" });
    chrome.action.setBadgeBackgroundColor({ color: "#c4483d" });
    return { ok: true };
  } catch (e) {
    return { ok: false, error: String(e.message || e) };
  }
}

async function stopCapture() {
  if (!capturing) return { ok: false, error: "not capturing" };
  await chrome.runtime.sendMessage({ type: "offscreen-stop" });
  capturing = false;
  chrome.action.setBadgeText({ text: "" });
  return { ok: true };
}

// --- calendar watcher (secret ICS URL; no OAuth) ---

function unfold(text) {
  return text.replace(/\r\n[ \t]/g, "").replace(/\n[ \t]/g, "");
}

function parseEvents(ics) {
  const events = [];
  for (const block of unfold(ics).split("BEGIN:VEVENT").slice(1)) {
    const body = block.split("END:VEVENT")[0];
    const get = (key) => {
      const line = body.split("\n").find(l => l.startsWith(key + ":") || l.startsWith(key + ";"));
      return line ? line.slice(line.indexOf(":") + 1).trim() : "";
    };
    const dt = (v) => {
      const m = v.match(/(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})/);
      if (!m) return null;
      return Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +m[6]);
    };
    const start = dt(get("DTSTART")), end = dt(get("DTEND"));
    if (start) {
      events.push({
        start, end: end || start + 3600000,
        summary: get("SUMMARY"),
        meet: /meet\.google\.com/.test(get("DESCRIPTION") + get("URL") + get("LOCATION")),
      });
    }
  }
  return events;
}

async function checkCalendar() {
  const s = await settings();
  if (!s.icsUrl) return;
  try {
    const ics = await (await fetch(s.icsUrl)).text();
    const now = Date.now();
    for (const ev of parseEvents(ics)) {
      const id = ev.start + ev.summary;
      const starting = now >= ev.start - 60000 && now <= ev.start + 120000;
      const live = now >= ev.start && now <= ev.end;
      if (!ev.meet || notifiedEvents[id] || !(starting || live)) continue;
      notifiedEvents[id] = true;
      const tab = await findMeetTab();
      if (s.autoCapture && tab && !capturing) {
        const res = await startCapture(tab.id);
        if (res.ok) {
          chrome.notifications.create({
            type: "basic", title: "Notetaker",
            message: `Auto-capturing: ${ev.summary || "Meet meeting"}`,
          });
          continue;
        }
      }
      chrome.notifications.create({
        type: "basic", title: "Meet starting — capture?",
        message: `${ev.summary || "Meeting"} ${tab ? "(Meet tab found)" : "(open the Meet tab)"}. Click to capture.`,
      });
    }
  } catch (e) { /* calendar fetch is best-effort */ }
}

chrome.alarms.create("calendar", { periodInMinutes: 1 });
chrome.alarms.onAlarm.addListener((a) => { if (a.name === "calendar") checkCalendar(); });

chrome.notifications.onClicked.addListener(async () => {
  const tab = await findMeetTab();
  if (tab) startCapture(tab.id);
});

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  (async () => {
    if (msg.type === "status") {
      sendResponse({ capturing, lastPreview, settings: await settings() });
    } else if (msg.type === "start") {
      const tab = msg.tabId ? { id: msg.tabId } : await findMeetTab();
      sendResponse(tab ? await startCapture(tab.id) : { ok: false, error: "no Meet tab open" });
    } else if (msg.type === "stop") {
      sendResponse(await stopCapture());
    } else if (msg.type === "save-settings") {
      await chrome.storage.local.set(msg.settings);
      sendResponse({ ok: true });
    } else if (msg.type === "preview") {
      lastPreview = msg.text;
    } else if (msg.type === "done") {
      capturing = false;
      chrome.action.setBadgeText({ text: "" });
      chrome.notifications.create({
        type: "basic", title: "Notetaker",
        message: `Meeting transcribed (${msg.turns} turns). Open the dashboard to read/export.`,
      });
    } else if (msg.type === "error") {
      capturing = false;
      chrome.action.setBadgeText({ text: "" });
      chrome.notifications.create({ type: "basic", title: "Notetaker error", message: msg.message });
    }
  })();
  return true;
});
