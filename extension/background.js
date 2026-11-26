// Service worker: capture lifecycle, calendar (secret iCal URL) watcher, notifications, shortcut.
import { parseIcs, occurrences } from "./ics.js";

const DEFAULTS = { server: "http://127.0.0.1:8010", lang: "hi", icsUrl: "", autoCapture: false, mic: true, engine: "", mode: "" };
const MEET_CODE = /meet\.google\.com\/([a-z]{3}-[a-z]{4}-[a-z]{3})/i;
const ICON = "icon128.png";
const ICS_TTL = 5 * 60 * 1000;

const settings = async () => ({ ...DEFAULTS, ...(await chrome.storage.local.get(DEFAULTS)) });
const getState = async () => (await chrome.storage.session.get({ st: { phase: "idle" } })).st;
const setState = async patch => {
  const st = { ...(await getState()), ...patch };
  await chrome.storage.session.set({ st });
  chrome.action.setBadgeText({ text: st.phase === "recording" ? "REC" : st.phase === "processing" ? "…" : "" });
  chrome.action.setBadgeBackgroundColor({ color: st.phase === "recording" ? "#c4483d" : "#8a8a8a" });
  return st;
};
const notify = (title, message, id, buttons) =>
  chrome.notifications.create(id || "", { type: "basic", iconUrl: ICON, title, message, buttons, requireInteraction: !!buttons });

async function ensureOffscreen() {
  if (await chrome.offscreen.hasDocument()) return;
  await chrome.offscreen.createDocument({
    url: "offscreen.html", reasons: ["USER_MEDIA"],
    justification: "Record meeting tab audio for local transcription",
  });
}

async function startCapture(tabId, title) {
  if ((await getState()).phase === "recording") return { ok: false, error: "already recording" };
  const s = await settings();
  try {
    const tab = await chrome.tabs.get(tabId);
    // Needs the extension to have been invoked on this tab (icon click, popup, or the shortcut).
    await ensureOffscreen();  // must exist before the stream id is minted, or getUserMedia can't find it
    const streamId = await chrome.tabCapture.getMediaStreamId({ targetTabId: tabId });
    const { micGranted } = await chrome.storage.local.get("micGranted");  // set by mic.html after the prompt
    const res = await chrome.runtime.sendMessage({
      type: "offscreen-start", streamId, server: s.server, lang: s.lang, engine: s.engine, mode: s.mode, mic: s.mic && !!micGranted,
    });
    if (!res?.ok) throw new Error(res?.error || "recorder unavailable");
    await setState({ phase: "recording", tabId, title: title || tab.title || "Meeting", startedAt: Date.now(), preview: "", mic: res.mic, message: "" });
    return { ok: true, mic: res.mic };
  } catch (e) {
    const msg = String(e.message || e);
    await setState({ phase: "idle", message: msg });
    return { ok: false, error: /invoked|activeTab|Extension has not been/i.test(msg)
      ? "Chrome only allows capture after you click the Notetaker icon on that tab (or press the shortcut)." : msg };
  }
}

async function stopCapture() {
  if ((await getState()).phase !== "recording") return { ok: false, error: "not recording" };
  await setState({ phase: "processing", stage: "uploading", progress: 0 });
  await chrome.runtime.sendMessage({ type: "offscreen-stop" });
  return { ok: true };
}

const toggleOnActiveTab = async () => {
  if ((await getState()).phase === "recording") return stopCapture();
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab ? startCapture(tab.id, tab.title) : { ok: false, error: "no active tab" };
};
chrome.commands.onCommand.addListener(c => { if (c === "toggle-capture") toggleOnActiveTab(); });

// ---- calendar -------------------------------------------------------------

async function loadEvents(force) {
  const s = await settings();
  if (!s.icsUrl) return { events: [], error: "" };
  const { ics } = await chrome.storage.local.get("ics");
  if (!force && ics && Date.now() - ics.at < ICS_TTL && ics.url === s.icsUrl) return { events: parseIcs(ics.text) };
  try {
    const r = await fetch(s.icsUrl, { cache: "no-store" });
    if (!r.ok) throw new Error(`calendar HTTP ${r.status}`);
    const text = await r.text();
    if (!text.includes("BEGIN:VCALENDAR")) throw new Error("that URL is not an iCal feed");
    await chrome.storage.local.set({ ics: { at: Date.now(), url: s.icsUrl, text } });
    return { events: parseIcs(text) };
  } catch (e) {
    return { events: ics?.url === s.icsUrl ? parseIcs(ics.text) : [], error: String(e.message || e) };
  }
}

async function upcoming(force) {
  const { events, error } = await loadEvents(force);
  const now = Date.now();
  return { error: error || "", items: occurrences(events, now - 30 * 60000, now + 12 * 3600000)
    .filter(o => o.end > now).slice(0, 12) };
}

async function findMeetTab(meetUrl) {
  const tabs = await chrome.tabs.query({ url: "*://meet.google.com/*" });
  const code = meetUrl && (meetUrl.match(MEET_CODE) || [])[1];
  return tabs.find(t => code && t.url.includes(code)) || (code ? null : tabs[0]) || null;
}

async function checkCalendar() {
  const s = await settings();
  if (!s.icsUrl) return;
  const { events } = await loadEvents(false);
  const now = Date.now();
  const { handled = {} } = await chrome.storage.session.get("handled");
  for (const o of occurrences(events, now - 3 * 60000, now + 60000)) {
    const key = o.uid + o.start;
    if (!o.meetUrl || handled[key]) continue;
    handled[key] = true;
    await chrome.storage.session.set({ handled });
    const tab = await findMeetTab(o.meetUrl);
    if (s.autoCapture && tab && (await getState()).phase !== "recording") {
      const res = await startCapture(tab.id, o.summary);
      if (res.ok) { notify("Recording started", o.summary || "Meet meeting"); continue; }
    }
    notify(`Starting: ${o.summary || "Meet meeting"}`,
      tab ? "Click the Notetaker icon on the Meet tab (or press the shortcut) to record."
          : "Open the meeting, then click the Notetaker icon on its tab to record.",
      "meet:" + o.meetUrl, tab ? undefined : [{ title: "Open meeting" }]);
  }
}

chrome.alarms.create("tick", { periodInMinutes: 1 });
chrome.alarms.onAlarm.addListener(a => { if (a.name === "tick") checkCalendar(); });
chrome.runtime.onStartup.addListener(() => setState({ phase: "idle" }));

const openDashboard = async () => chrome.tabs.create({ url: (await settings()).server + "/dashboard.html" });
chrome.notifications.onClicked.addListener(async id => {
  if (id.startsWith("done:")) openDashboard();
  else if (id.startsWith("meet:")) { const t = await findMeetTab(id.slice(5)); if (t) chrome.tabs.update(t.id, { active: true }); }
});
chrome.notifications.onButtonClicked.addListener(id => { if (id.startsWith("meet:")) chrome.tabs.create({ url: id.slice(5) }); });

// ---- messages ---------------------------------------------------------------

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  (async () => {
    switch (msg.type) {
      case "status": return sendResponse({ state: await getState(), settings: await settings() });
      case "start": return sendResponse(await startCapture(msg.tabId, msg.title));
      case "stop": return sendResponse(await stopCapture());
      case "save-settings": await chrome.storage.local.set(msg.settings); return sendResponse({ ok: true });
      case "upcoming": return sendResponse(await upcoming(!!msg.force));
      case "instant-meet": await chrome.tabs.create({ url: "https://meet.new" }); return sendResponse({ ok: true });
      case "join": {
        const code = (msg.url.match(MEET_CODE) || [])[1];
        if (!code) return sendResponse({ ok: false, error: "that doesn't look like a Meet link (meet.google.com/abc-defg-hij)" });
        await chrome.tabs.create({ url: "https://meet.google.com/" + code });
        return sendResponse({ ok: true });
      }
      case "grant-mic": await chrome.tabs.create({ url: chrome.runtime.getURL("mic.html") }); return sendResponse({ ok: true });
      // from the offscreen recorder
      case "preview": await setState({ preview: msg.text }); return;
      case "processing": return void await setState({ phase: "processing", stage: "queued", jobId: msg.jobId });
      case "progress": return void await setState({ stage: msg.stage, progress: msg.progress });
      case "done":
        await setState({ phase: "idle", lastJob: msg.jobId, message: "" });
        chrome.offscreen.closeDocument().catch(() => {});
        return void notify("Transcript ready", `${msg.turns} turns. Click to open Recordings.`, "done:" + msg.jobId);
      case "error":
        await setState({ phase: "idle", message: msg.message });
        chrome.offscreen.closeDocument().catch(() => {});
        return void notify("Notetaker error", msg.message);
    }
  })();
  return true;
});
