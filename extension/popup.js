const $ = id => document.getElementById(id);
const send = m => chrome.runtime.sendMessage(m);
const clock = ms => { const s = Math.floor(ms / 1000); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`; };
const hhmm = ms => new Date(ms).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
let st = { phase: "idle" }, cfg = {}, timer = null;

// Ask Chrome for the extension's real mic permission (a saved flag goes stale if the extension
// is reinstalled); keep the flag the recorder reads in sync.
async function micAllowed() {
  const ok = (await navigator.permissions.query({ name: "microphone" }).catch(() => ({ state: "prompt" }))).state === "granted";
  await chrome.storage.local.set({ micGranted: ok });
  return ok;
}

function banner(msg) { $("banner").hidden = !msg; $("banner").textContent = msg || ""; }

function render() {
  $("rec").hidden = st.phase !== "recording";
  $("proc").hidden = st.phase !== "processing";
  $("idle").hidden = st.phase !== "idle";
  $("pill").textContent = st.phase === "recording" ? "● REC" : st.phase === "processing" ? "processing" : "idle";
  $("pill").className = "pill" + (st.phase === "recording" ? " rec" : "");
  if (st.phase === "recording") {
    $("rtitle").textContent = (st.title || "") + (st.mic === false ? " · mic off" : " · mic on");
    banner(st.mic === false ? "Your own voice isn't being recorded, only the meeting audio. To include it: stop, open Settings → allow mic, then start again." : "");
    $("live").textContent = st.preview || "Listening… live text appears every ~10 s";
    $("live").scrollTop = 1e6;
  }
  if (st.phase === "processing") {
    $("stage").textContent = ({ uploading: "Uploading", queued: "Waiting", loading: "Loading audio", diarizing: "Separating speakers", transcribing: "Transcribing" })[st.stage] || "Working…";
    $("pbar").style.width = ((st.progress || 0) * 100) + "%";
  }
  if (st.message && st.phase === "idle") banner(st.message);
  clearInterval(timer);
  if (st.phase === "recording") { const tick = () => $("timer").textContent = clock(Date.now() - st.startedAt); tick(); timer = setInterval(tick, 500); }
}

async function refresh() {
  ({ state: st, settings: cfg } = await send({ type: "status" }));
  render();
  if (st.phase === "idle" && !st.message) {  // say it before recording, not after a silent meeting
    banner(!cfg.mic ? "Your own voice won't be recorded: “Include my microphone” is off in Settings."
      : !(await micAllowed()) ? "First recording asks once for the microphone so your own voice is included." : "");
  }
}

async function loadUpcoming(force) {
  if (!cfg.icsUrl) return;
  $("up").textContent = "Loading…";
  const { items, error } = await send({ type: "upcoming", force });
  if (error) { $("up").textContent = "Calendar: " + error; if (!items.length) return; }
  if (!items.length) { $("up").textContent = "No meetings in the next 12 hours."; return; }
  $("up").innerHTML = "";
  for (const o of items) {
    const row = document.createElement("div"); row.className = "ev";
    const live = o.start <= Date.now();
    row.innerHTML = `<span class="w">${live ? "now" : hhmm(o.start)}</span><span class="t"></span>${o.meetUrl ? '<span class="meet">Meet</span>' : ""}`;
    row.querySelector(".t").textContent = o.summary || "(no title)";
    if (o.meetUrl) { const b = document.createElement("button"); b.className = "btn"; b.textContent = "Join";
      b.onclick = () => send({ type: "join", url: o.meetUrl }); row.appendChild(b); }
    $("up").appendChild(row);
  }
}

async function init() {
  await refresh();
  $("server").value = cfg.server; $("lang").value = cfg.lang; $("mode").value = cfg.mode || "";
  $("mic").checked = cfg.mic; $("auto").checked = cfg.autoCapture; $("suggest").checked = cfg.suggest; $("ics").value = cfg.icsUrl;
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  $("atitle").textContent = tab ? (tab.title || tab.url || "").slice(0, 60) : "";
  $("start").onclick = async () => {
    banner(""); $("start").disabled = true;
    if (cfg.mic && !(await micAllowed())) {  // one-time: grant the mic, then the window starts recording
      const url = chrome.runtime.getURL(`mic.html?tab=${tab.id}&title=${encodeURIComponent(tab.title || "")}`);
      await chrome.windows.create({ url, type: "popup", width: 460, height: 300, focused: true });
      return window.close();
    }
    const r = await send({ type: "start", tabId: tab.id, title: tab.title });
    $("start").disabled = false;
    if (!r.ok) banner(r.error); await refresh();
  };
  fetch(cfg.server + "/api/health").catch(() => banner("Kiroku app isn't running. Open Kiroku.app first."));
  loadUpcoming(false);
}

$("stop").onclick = async () => { await send({ type: "stop" }); await refresh(); };
$("instant").onclick = () => { send({ type: "instant-meet" }); window.close(); };
$("dash").onclick = () => { chrome.tabs.create({ url: cfg.server + "/app/" }); window.close(); };
$("join").onclick = async () => { const r = await send({ type: "join", url: $("link").value }); if (r.ok) window.close(); else banner(r.error); };
$("link").onkeydown = e => { if (e.key === "Enter") $("join").click(); };
$("refresh").onclick = () => loadUpcoming(true);
$("grant").onclick = e => { e.preventDefault(); send({ type: "grant-mic" }); };
$("save").onclick = async () => {
  const settings = { server: $("server").value.trim().replace(/\/$/, ""), lang: $("lang").value, mode: $("mode").value,
    mic: $("mic").checked, autoCapture: $("auto").checked, icsUrl: $("ics").value.trim(), suggest: $("suggest").checked };
  await send({ type: "save-settings", settings });
  $("saved").textContent = "Saved"; setTimeout(() => $("saved").textContent = "", 1500);
  await refresh(); loadUpcoming(true);
};
chrome.storage.session.onChanged.addListener(c => { if (c.st) { st = c.st.newValue; render(); } });
init();
