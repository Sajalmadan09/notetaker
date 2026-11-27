import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { toWav16k, watchLevel } from "../audio";
import { clock, Icon, useToast } from "../ui";

const LANG_NAMES: Record<string, string> = {
  as: "Assamese", bn: "Bengali", bho: "Bhojpuri", brx: "Bodo", doi: "Dogri", en: "English", gu: "Gujarati",
  hi: "Hindi", kn: "Kannada", kok: "Konkani", ks: "Kashmiri", mai: "Maithili", ml: "Malayalam", mni: "Manipuri",
  mr: "Marathi", ne: "Nepali", or: "Odia", pa: "Punjabi", sa: "Sanskrit", sat: "Santali", sd: "Sindhi",
  ta: "Tamil", te: "Telugu", ur: "Urdu",
};
const STAGES: Record<string, [string, string]> = {
  converting: ["Preparing audio", "準備"], uploading: ["Uploading to the local engine", "送信"],
  queued: ["Waiting in line", "待機"], loading: ["Loading audio", "読込"],
  diarizing: ["Telling speakers apart", "話者分離"], transcribing: ["Writing it down", "文字起こし"],
};
type Phase = "idle" | "recording" | "working";
const pref = (k: string, d: string) => localStorage.getItem(`kiroku.${k}`) ?? d;

export default function Record() {
  const toast = useToast();
  const [phase, setPhase] = useState<Phase>("idle");
  const [langs, setLangs] = useState<string[]>([]);
  const [torch, setTorch] = useState(false);
  const [lang, setLang] = useState(pref("lang", "hi"));
  const [spk, setSpk] = useState(pref("speakers", "auto"));
  const [engine, setEngine] = useState(pref("engine", "int4"));
  const [mode, setMode] = useState(pref("mode", "mixed"));
  const [status, setStatus] = useState("");
  const [err, setErr] = useState("");
  const [elapsed, setElapsed] = useState(0);
  const [bars, setBars] = useState<number[]>(() => Array(48).fill(0));
  const [live, setLive] = useState<string[]>([]);
  const [stage, setStage] = useState(["", ""]);
  const [progress, setProgress] = useState(0);
  const rec = useRef<{ mr: MediaRecorder; cleanup: () => void } | null>(null);
  const canTab = !!navigator.mediaDevices?.getDisplayMedia;

  useEffect(() => {
    api.languages().then(setLangs).catch(() => setErr("The local engine isn't ready. Finish setup or restart the app."));
    api.health().then(h => { setTorch(h.torch); if (!h.torch) setEngine("int4"); }).catch(() => {});
  }, []);
  useEffect(() => {
    for (const [k, v] of Object.entries({ lang, speakers: spk, engine, mode })) localStorage.setItem(`kiroku.${k}`, v);
  }, [lang, spk, engine, mode]);
  useEffect(() => () => rec.current?.cleanup(), []);

  const opts = () => ({ lang, speakers: spk, engine, mode: engine === "int4" ? "native" : mode });

  async function submit(blob: Blob) {
    setPhase("working"); setErr(""); setStage(STAGES.converting); setProgress(0);
    let wav: Blob;
    try { wav = await toWav16k(blob); } catch (e) { fail(`Couldn't read that audio (${(e as Error).message}).`); return; }
    setStage(STAGES.uploading);
    let jobId: string;
    try { jobId = (await api.createJob(wav, opts())).job_id; } catch (e) { fail((e as Error).message); return; }
    for (;;) {
      await new Promise(r => setTimeout(r, 1000));
      let j;
      try { j = await api.job(jobId); } catch (e) { fail(`Lost contact with the engine: ${(e as Error).message}`); return; }
      if (j.status === "error") { fail(`Transcription failed: ${j.error}`); return; }
      if (STAGES[j.stage]) setStage(STAGES[j.stage]);
      setProgress(j.progress || 0);
      if (j.status === "done") {
        toast("Transcript ready");
        location.hash = `#/r/${jobId}`;  // job id is the recording id
        return;
      }
    }
  }
  const fail = (msg: string) => { setPhase("idle"); setErr(msg); };

  function start(stream: MediaStream, cleanupExtra: () => void, label: string) {
    const mr = new MediaRecorder(stream);
    const chunks: Blob[] = [];
    const stopLevel = watchLevel(stream, v => setBars(b => [...b.slice(1), v]));
    const t0 = Date.now();
    const tick = setInterval(() => setElapsed((Date.now() - t0) / 1000), 250);
    const cleanup = () => {
      clearInterval(tick); stopLevel(); stream.getTracks().forEach(t => t.stop()); cleanupExtra();
    };
    mr.ondataavailable = e => {
      chunks.push(e.data);
      // Later timeslices lack a container header, so decode everything and keep the last 10 s.
      // ponytail: re-decodes the whole recording every 10 s; AudioWorklet PCM (as the extension does) if long meetings lag.
      if (mr.state === "recording" && e.data.size) {
        toWav16k(new Blob(chunks, { type: mr.mimeType }), 10)
          .then(w => api.quick(w, lang))
          .then(({ text }) => { if (text && rec.current) setLive(l => [...l, text]); })
          .catch(() => { /* provisional only */ });
      }
    };
    mr.onstop = () => { cleanup(); rec.current = null; submit(new Blob(chunks, { type: mr.mimeType })); };
    mr.start(10000);
    rec.current = { mr, cleanup };
    setLive([]); setElapsed(0); setErr(""); setPhase("recording"); setStatus(label);
  }

  async function recordMic() {
    if (rec.current) { rec.current.mr.stop(); return; }
    try {
      const s = await navigator.mediaDevices.getUserMedia({ audio: true });
      start(s, () => {}, "Listening. Live text appears every 10 seconds; speaker names come when you stop.");
    } catch (e) {
      setErr(`Microphone blocked (${(e as Error).name}). Allow microphone access for Kiroku in System Settings › Privacy & Security.`);
    }
  }

  async function recordTab() {
    let disp: MediaStream;
    try { disp = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: true }); }
    catch (e) { setErr(`Tab capture cancelled (${(e as Error).name}).`); return; }
    const tracks = disp.getAudioTracks();
    if (!tracks.length) {
      disp.getTracks().forEach(t => t.stop());
      setErr("No tab audio. Pick the Meet tab and switch on “Also share tab audio”.");
      return;
    }
    disp.getVideoTracks().forEach(t => t.stop());
    let mic: MediaStream | null = null;
    try { mic = await navigator.mediaDevices.getUserMedia({ audio: true }); } catch { /* remote voices only */ }
    const ctx = new AudioContext();
    const dest = ctx.createMediaStreamDestination();
    ctx.createMediaStreamSource(new MediaStream(tracks)).connect(dest);
    if (mic) ctx.createMediaStreamSource(mic).connect(dest);
    start(dest.stream, () => { disp.getTracks().forEach(t => t.stop()); mic?.getTracks().forEach(t => t.stop()); ctx.close(); },
      mic ? "Recording the Meet tab and your mic." : "Recording the Meet tab only (mic unavailable).");
  }

  const level = bars[bars.length - 1];
  return (
    <div className="page record">
      <div className="phead"><div>
        <h1>Capture the meeting<span className="ja">録音</span></h1>
        <div className="muted" style={{ marginTop: 6 }}>Hindi, English and 23 more Indian languages, transcribed on this Mac. Audio never leaves it.</div>
      </div></div>

      <div className={`panel stage ${phase}`} style={{ ["--lvl" as string]: level }}>
        <div className="burstwrap">
          {phase === "recording" && <div className="speedlines" aria-hidden="true" />}
          <button className="bigrec" onClick={recordMic} disabled={phase === "working"}
            aria-label={phase === "recording" ? "Stop recording" : "Start recording"}>
            {phase === "recording" ? <span className="stopsq" /> : <Icon name="mic" size={40} />}
          </button>
        </div>
        <div className="bigclock mono">{clock(elapsed)}</div>
        <div className="meter" aria-hidden="true">
          {bars.map((b, i) => <i key={i} style={{ height: `${Math.max(6, b * 100)}%` }} />)}
        </div>
        {phase === "working" ? (
          <div className="job">
            <div className="jobline"><b>{stage[0]}</b><span className="ja">{stage[1]}</span>
              <span className="muted mono">{progress > 0 ? `${Math.round(progress * 100)}%` : ""}</span></div>
            <div className={`bar ${progress > 0 ? "" : "busy"}`}><i style={{ width: `${Math.max(progress, 0.04) * 100}%` }} /></div>
          </div>
        ) : (
          <div className="hint">{phase === "recording" ? status : "Press the seal to record from your microphone."}</div>
        )}
        {err && <div className="notice cloud" role="alert">{err}</div>}
        {phase === "idle" && (
          <div className="actions">
            {canTab && <button className="btn" onClick={recordTab}><Icon name="screen" />Record a Meet tab</button>}
            <label className="btn"><Icon name="up" />Upload audio
              <input type="file" accept="audio/*,video/webm,video/mp4" hidden
                onChange={e => { const f = e.target.files?.[0]; if (f) submit(f); e.target.value = ""; }} /></label>
          </div>
        )}
        {phase === "recording" && <button className="btn primary" onClick={() => rec.current?.mr.stop()}>Stop and transcribe</button>}
      </div>

      {phase === "idle" && (
        <details className="opts">
          <summary>Language and options</summary>
          <div className="optgrid">
            <label className="field"><span>Language</span>
              <select className="input" value={lang} onChange={e => setLang(e.target.value)}>
                <option value="auto">Detect automatically</option>
                {langs.map(l => <option key={l} value={l}>{LANG_NAMES[l] ?? l}</option>)}
              </select><small>Pick it when you know it. Detection mixes up Hindi, Bhojpuri, Maithili and Urdu.</small></label>
            <label className="field"><span>Speakers</span>
              <select className="input" value={spk} onChange={e => setSpk(e.target.value)}>
                <option value="auto">Figure it out</option>{[2, 3, 4, 5, 6].map(n => <option key={n} value={n}>{n} people</option>)}
              </select></label>
            <label className="field"><span>Engine</span>
              <select className="input" value={engine} onChange={e => setEngine(e.target.value)}>
                <option value="int4">Fast (Indian scripts only)</option>
                <option value="flex" disabled={!torch}>Code-mix, best quality{torch ? "" : " (not installed)"}</option>
                <option value="torch" disabled={!torch}>Max accuracy{torch ? "" : " (not installed)"}</option>
              </select></label>
            {engine !== "int4" && <label className="field"><span>English words</span>
              <select className="input" value={mode} onChange={e => setMode(e.target.value)}>
                <option value="mixed">Keep English words in English</option>
                <option value="native">Write everything in the native script</option>
                <option value="romanized">Romanized (Latin letters)</option>
              </select></label>}
          </div>
        </details>
      )}

      {live.length > 0 && (
        <section style={{ marginTop: 28 }}>
          <h2 className="kicker">Live preview <span className="ja">速報</span></h2>
          <div className="turns">{live.map((t, i) => (
            <div className="turn" key={i}><div className="ava live">…</div>
              <div><div className="who"><b>Live</b><span className="mono muted">~{clock(i * 10 + 10)}</span></div>
                <div className="bubble live">{t}</div></div></div>))}</div>
        </section>
      )}
    </div>
  );
}
