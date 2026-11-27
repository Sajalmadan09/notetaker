import { useState } from "react";
import { api, type LLMSettings } from "../api";
import { useToast } from "../ui";

const APPS = ["Slack", "Mail", "Notes", "Terminal", "Other app"];

export default function DictationSettings({ s, onSaved }: { s: LLMSettings; onSaved: (s: LLMSettings) => void }) {
  const toast = useToast();
  const [dict, setDict] = useState(s.dictation.dictionary.join("\n"));
  const [sample, setSample] = useState("um so I think we should uh ship the build on Friday no actually Monday");
  const [app, setApp] = useState("Slack");
  const [out, setOut] = useState<{ text: string; ms: number; cleaned: boolean; error: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const prov = s.provider ? s.providers[s.provider] : null;

  const save = async (patch: Partial<LLMSettings["dictation"]>, msg: string) => {
    try { onSaved(await api.saveLlm({ dictation: patch })); toast(msg); } catch (e) { toast((e as Error).message); }
  };
  const tryIt = async () => {
    setBusy(true); setOut(null);
    try { setOut(await api.tryCleanup(sample, app === "Other app" ? "" : app)); } catch (e) { toast((e as Error).message); }
    finally { setBusy(false); }
  };

  return (
    <div className="panel form">
      <label className="toggle">
        <input type="checkbox" checked={s.dictation.cleanup} disabled={!prov}
          onChange={e => save({ cleanup: e.target.checked }, e.target.checked ? "Dictation cleanup on" : "Dictation cleanup off")} />
        <span><b>Clean up what I dictate</b><br />
          <small>Removes ums and repeats, applies your corrections (“Friday, no, Monday” → Monday), fixes punctuation and
            turns spoken lists into lists. Keeps your words, language and Hindi/English mix. Hold ⌥ Space to dictate.</small></span>
      </label>
      {!prov && <div className="notice cloud">Pick an AI model above first. Dictation cleanup uses the same model.</div>}
      {prov && s.dictation.cleanup && <div className={`notice ${prov.local ? "" : "cloud"}`}>
        {prov.local ? `Runs on ${prov.label}. Local models add about 2–4 seconds per dictation.`
          : `Each dictation's text is sent to ${prov.label} before it's typed. Audio stays on this Mac.`}
        {" "}If cleanup is slow or fails, your exact words are typed instead.</div>}
      <label className="toggle">
        <input type="checkbox" checked={s.dictation.match_app}
          onChange={e => save({ match_app: e.target.checked }, "Saved")} />
        <span><b>Match the app</b><br /><small>Casual in Slack and Messages, full sentences in Mail, exact commands in Terminal and code editors.</small></span>
      </label>
      <label className="field"><span>Your words <small>(names, brands, jargon; one per line)</small></span>
        <textarea className="input" rows={4} value={dict} onChange={e => setDict(e.target.value)} placeholder={"Kiroku\nAsha Verma\nKubernetes"} />
        <div><button className="btn" onClick={() => save({ dictionary: dict.split("\n") }, "Dictionary saved")}
          disabled={dict === s.dictation.dictionary.join("\n")}>Save words</button></div>
      </label>
      <div className="field"><span>Try it</span>
        <textarea className="input" rows={2} value={sample} onChange={e => setSample(e.target.value)} />
        <div className="line">
          <select className="input" style={{ maxWidth: 180 }} value={app} onChange={e => setApp(e.target.value)}>
            {APPS.map(a => <option key={a}>{a}</option>)}</select>
          <button className="btn red" onClick={tryIt} disabled={busy || !prov || !s.dictation.cleanup || !sample.trim()}>
            {busy ? <>Cleaning <span className="dots"><i /><i /><i /></span></> : "Clean it up"}</button>
        </div>
        {!s.dictation.cleanup && prov && <small className="muted">Turn cleanup on to try it.</small>}
        {out && <div className={`notice ${out.error ? "cloud" : ""}`}>
          <div style={{ whiteSpace: "pre-wrap", fontSize: 15 }}>{out.text}</div>
          <small className="muted">{out.error ? `Kept your exact words: ${out.error}` : `${out.ms} ms`}</small></div>}
      </div>
    </div>
  );
}
