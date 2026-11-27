// Offscreen document: owns the capture streams. Tab audio (+ optional mic) is mixed at 16 kHz and
// collected as raw PCM — no webm re-decoding, so every 10 s live preview is a valid standalone WAV.
// On stop the whole recording goes to /api/jobs (diarization + transcript) and is polled to completion.
const SR = 16000, PREVIEW_S = 10;
let cfg = {}, ctx = null, streams = [], blocks = [], previewFrom = 0, total = 0, active = false;

function wav(int16) {
  const n = int16.length, ab = new ArrayBuffer(44 + n * 2), v = new DataView(ab);
  const ws = (o, s) => { for (let i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i)); };
  ws(0, "RIFF"); v.setUint32(4, 36 + n * 2, true); ws(8, "WAVEfmt ");
  v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
  v.setUint32(24, SR, true); v.setUint32(28, SR * 2, true); v.setUint16(32, 2, true);
  v.setUint16(34, 16, true); ws(36, "data"); v.setUint32(40, n * 2, true);
  new Int16Array(ab, 44).set(int16);
  return new Blob([ab], { type: "audio/wav" });
}

function concat(from = 0) {
  const parts = blocks.slice(from), n = parts.reduce((a, b) => a + b.length, 0), out = new Int16Array(n);
  let o = 0;
  for (const p of parts) { out.set(p, o); o += p.length; }
  return out;
}

async function post(path, fd) {
  const r = await fetch(cfg.server + path, { method: "POST", body: fd });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || `${path} -> HTTP ${r.status}`);
  return r.json();
}

async function preview() {
  const from = previewFrom, pcm = concat(from);
  previewFrom = blocks.length;
  if (pcm.length < SR) return;
  try {
    const fd = new FormData();
    fd.append("file", wav(pcm), "chunk.wav");
    fd.append("lang", cfg.lang);
    const { text } = await post("/api/quick", fd);
    if (text) chrome.runtime.sendMessage({ type: "preview", text });
  } catch { /* previews are best-effort */ }
}

async function finish() {
  const pcm = concat(0);
  blocks = [];
  try {
    if (pcm.length < SR / 2) throw new Error("nothing was recorded");
    const fd = new FormData();
    fd.append("file", wav(pcm), "meet.wav");
    fd.append("lang", cfg.lang);
    fd.append("speakers", "auto");
    if (cfg.engine) fd.append("engine", cfg.engine);
    if (cfg.mode) fd.append("mode", cfg.mode);
    if (cfg.title) fd.append("title", cfg.title);  // calendar event -> recording title + Gmail recipients
    if (cfg.attendees?.length) fd.append("attendees", cfg.attendees.join(","));
    const { job_id } = await post("/api/jobs", fd);
    chrome.runtime.sendMessage({ type: "processing", jobId: job_id });
    for (;;) {
      await new Promise(r => setTimeout(r, 1500));
      const j = await (await fetch(cfg.server + "/api/jobs/" + job_id)).json();
      if (j.status === "error") throw new Error(j.error);
      if (j.status === "done") { chrome.runtime.sendMessage({ type: "done", jobId: job_id, turns: j.result.length }); return; }
      chrome.runtime.sendMessage({ type: "progress", stage: j.stage, progress: j.progress });
    }
  } catch (e) {
    chrome.runtime.sendMessage({ type: "error", message: String(e.message || e) });
  }
}

async function start(msg) {
  cfg = { server: msg.server, lang: msg.lang, engine: msg.engine, mode: msg.mode, title: msg.title, attendees: msg.attendees };
  let tab;
  try {
    tab = await navigator.mediaDevices.getUserMedia({
      audio: { mandatory: { chromeMediaSource: "tab", chromeMediaSourceId: msg.streamId } },
    });
  } catch (e) { throw new Error("tab capture: " + (e.message || e.name)); }
  streams = [tab];
  ctx = new AudioContext({ sampleRate: SR });
  const mix = ctx.createGain();
  const tabSrc = ctx.createMediaStreamSource(tab);
  tabSrc.connect(mix);
  // Capturing a tab silences it for the user; route it back to the speakers.
  const playback = new AudioContext();
  playback.createMediaStreamSource(tab).connect(playback.destination);
  streams.push({ getTracks: () => [], close: () => playback.close() });
  let micOn = false;
  if (msg.mic) {
    try {  // permission is granted once from the popup ("Allow microphone"); offscreen docs cannot prompt
      const mic = await Promise.race([navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true } }),
        new Promise((_, rej) => setTimeout(() => rej(new Error("mic timeout")), 4000))]);
      streams.push(mic);
      ctx.createMediaStreamSource(mic).connect(mix);
      micOn = true;
    } catch { /* remote voices only */ }
  }
  await ctx.audioWorklet.addModule("pcm-worklet.js");
  const node = new AudioWorkletNode(ctx, "pcm");
  node.port.onmessage = e => {
    if (!active) return;
    const f = e.data, i16 = new Int16Array(f.length);
    for (let i = 0; i < f.length; i++) i16[i] = Math.max(-1, Math.min(1, f[i])) * 32767;
    blocks.push(i16); total += f.length;
    if ((blocks.length - previewFrom) * 4000 >= PREVIEW_S * SR) preview();
  };
  mix.connect(node);
  blocks = []; previewFrom = 0; total = 0; active = true;
  return { ok: true, mic: micOn };
}

function stop() {
  if (!active) return;
  active = false;
  for (const s of streams) { s.getTracks().forEach(t => t.stop()); s.close?.(); }
  streams = [];
  ctx?.close(); ctx = null;
  finish();
}

chrome.runtime.onMessage.addListener((msg, _s, sendResponse) => {
  if (msg.type === "offscreen-start") { start(msg).then(sendResponse, e => sendResponse({ ok: false, error: String(e.message || e) })); return true; }
  if (msg.type === "offscreen-stop") { stop(); sendResponse({ ok: true }); }
});
