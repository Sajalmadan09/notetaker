// Offscreen document: owns the tab-capture stream, records, sends 10 s live
// previews to /api/quick, and on stop submits the full WAV to /api/jobs.
let recorder = null;
let chunks = [];
let cfg = { server: "http://127.0.0.1:8010", lang: "hi" };

async function toWav16k(blob) {
  const ac = new AudioContext();
  const buf = await ac.decodeAudioData(await blob.arrayBuffer());
  const off = new OfflineAudioContext(1, Math.ceil(buf.duration * 16000), 16000);
  const src = off.createBufferSource();
  src.buffer = buf;
  src.connect(off.destination);
  src.start();
  const data = (await off.startRendering()).getChannelData(0);
  ac.close();
  const n = data.length, ab = new ArrayBuffer(44 + n * 2), v = new DataView(ab);
  const ws = (o, s) => { for (let i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i)); };
  ws(0, "RIFF"); v.setUint32(4, 36 + n * 2, true); ws(8, "WAVEfmt ");
  v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
  v.setUint32(24, 16000, true); v.setUint32(28, 32000, true); v.setUint16(32, 2, true);
  v.setUint16(34, 16, true); ws(36, "data"); v.setUint32(40, n * 2, true);
  for (let i = 0; i < n; i++) v.setInt16(44 + i * 2, Math.max(-1, Math.min(1, data[i])) * 32767, true);
  return new Blob([ab], { type: "audio/wav" });
}

async function preview(blob) {
  try {
    const wav = await toWav16k(blob);
    const fd = new FormData();
    fd.append("file", wav, "chunk.wav");
    fd.append("lang", cfg.lang);
    const r = await fetch(cfg.server + "/api/quick", { method: "POST", body: fd });
    if (!r.ok) return;
    const { text } = await r.json();
    if (text) chrome.runtime.sendMessage({ type: "preview", text });
  } catch (e) { /* previews are best-effort */ }
}

async function submit() {
  const blob = new Blob(chunks, { type: recorder.mimeType });
  chunks = [];
  try {
    const wav = await toWav16k(blob);
    const fd = new FormData();
    fd.append("file", wav, "meet.wav");
    fd.append("lang", cfg.lang);
    fd.append("speakers", "auto");
    fd.append("engine", "int4");
    const r = await fetch(cfg.server + "/api/jobs", { method: "POST", body: fd });
    if (!r.ok) throw new Error((await r.json()).detail || "upload failed");
    const { job_id } = await r.json();
    for (;;) {
      await new Promise(res => setTimeout(res, 1000));
      const j = await (await fetch(cfg.server + "/api/jobs/" + job_id)).json();
      if (j.status === "error") throw new Error(j.error);
      if (j.status === "done") {
        chrome.runtime.sendMessage({ type: "done", jobId: job_id, turns: j.result.length });
        return;
      }
    }
  } catch (e) {
    chrome.runtime.sendMessage({ type: "error", message: String(e.message || e) });
  }
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg.type === "offscreen-start") {
    cfg = { server: msg.server, lang: msg.lang };
    navigator.mediaDevices.getUserMedia({
      audio: {
        mandatory: { chromeMediaSource: "tab", chromeMediaSourceId: msg.streamId }
      }
    }).then(stream => {
      chunks = [];
      recorder = new MediaRecorder(stream);
      recorder.ondataavailable = e => {
        chunks.push(e.data);
        if (recorder.state === "recording" && e.data.size) preview(e.data);
      };
      recorder.onstop = () => {
        stream.getTracks().forEach(t => t.stop());
        submit();
      };
      recorder.start(10000);
      sendResponse({ ok: true });
    }).catch(e => sendResponse({ ok: false, error: String(e.message || e) }));
    return true;
  }
  if (msg.type === "offscreen-stop") {
    if (recorder && recorder.state === "recording") recorder.stop();
    sendResponse({ ok: true });
    return true;
  }
});
