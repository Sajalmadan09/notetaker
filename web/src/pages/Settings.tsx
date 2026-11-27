import { useEffect, useState } from "react";
import { api, type LLMSettings } from "../api";
import { Icon, useToast } from "../ui";
import Connectors from "./Connectors";
import DictationSettings from "./DictationSettings";
import EngineSettings from "./EngineSettings";

const BLURB: Record<string, string> = {
  ollama: "Free, private, runs on this Mac. Needs Ollama installed.",
  anthropic: "Claude models with your own API key.",
  openai: "GPT models with your own API key.",
  gemini: "Gemini models with your own API key.",
  custom: "LM Studio, llama.cpp, OpenRouter, Groq or any OpenAI-style server.",
  claude_code: "Your Claude Pro/Max plan through the Claude Code app.",
  codex: "Your ChatGPT plan through OpenAI's Codex CLI.",
  gemini_cli: "Your Google account through the Gemini CLI.",
  qwen_code: "Your Qwen account through Qwen Code.",
};
const GROUPS: [string, string[]][] = [
  ["On this Mac", ["ollama"]],
  ["Your chat subscription · no API key", ["claude_code", "codex", "gemini_cli", "qwen_code"]],
  ["API key", ["anthropic", "openai", "gemini", "custom"]],
];
const LANGS = ["English", "Hindi", "Hinglish (Hindi in Latin letters)", "Same language as the meeting"];

export default function Settings({ onSaved }: { onSaved: (s: LLMSettings) => void }) {
  const toast = useToast();
  const [s, setS] = useState<LLMSettings | null>(null);
  const [pick, setPick] = useState("");
  const [model, setModel] = useState("");
  const [base, setBase] = useState("");
  const [key, setKey] = useState("");
  const [lang, setLang] = useState("English");
  const [models, setModels] = useState<string[]>([]);
  const [modelErr, setModelErr] = useState("");
  const [saving, setSaving] = useState(false);
  const [test, setTest] = useState<{ ok: boolean; msg: string } | null>(null);
  const [testing, setTesting] = useState(false);

  const load = (x: LLMSettings, pid?: string) => {
    setS(x); const p = pid || x.provider || "ollama"; setPick(p);
    setModel(x.providers[p].model); setBase(x.providers[p].base_url); setLang(x.summary_language);
    setKey(""); setModels([]); setModelErr(""); setTest(null);
  };
  useEffect(() => { api.llm().then(x => load(x)); }, []);
  if (!s) return <div className="page"><div className="skel" style={{ height: 300 }} /></div>;

  const p = s.providers[pick];
  const choose = (pid: string) => load(s, pid);
  const persist = async (activate = true) => {
    const conf: Record<string, string> = { model, base_url: base };
    if (key) conf.api_key = key;
    const next = await api.saveLlm({ ...(activate ? { provider: pick, summary_language: lang } : {}), providers: { [pick]: conf } });
    load(next, pick); onSaved(next); return next;
  };
  const save = async () => {
    setSaving(true);
    try { await persist(); toast("Saved. AI notes are ready."); } catch (e) { toast((e as Error).message); }
    finally { setSaving(false); }
  };
  const fetchModels = async () => {
    setModelErr("");
    try { if (key || base !== p.base_url) await persist(false); setModels(await api.models(pick)); }
    catch (e) { setModelErr((e as Error).message); }
  };
  const runTest = async () => {
    setTesting(true); setTest(null);
    try { const r = await api.testLlm(); setTest({ ok: true, msg: `${p.label} answered in ${(r.ms / 1000).toFixed(1)} s.` }); }
    catch (e) { setTest({ ok: false, msg: (e as Error).message }); }
    finally { setTesting(false); }
  };
  const cli = p?.kind === "cli";
  const forgetKey = async () => {
    const next = await api.saveLlm({ providers: { [pick]: { api_key: "" } } });
    load(next, pick); onSaved(next); toast("Key removed from Keychain");
  };
  const disconnect = async () => {
    const next = await api.saveLlm({ provider: "" }); load(next); onSaved(next); toast("AI notes turned off");
  };

  return (
    <div className="page">
      <div className="phead"><div><h1>Settings<span className="ja">設定</span></h1>
        <div className="muted" style={{ marginTop: 6 }}>Bring your own AI for summaries and questions. Recording and transcription never need it.</div></div></div>

      <h2 className="kicker">AI model <span className="ja">頭脳</span></h2>
      {GROUPS.map(([title, ids]) => (
        <div key={title}>
          <div className="group" style={{ marginTop: 12 }}>{title}</div>
          <div className="provs">
            {ids.filter(pid => s.providers[pid]).map(pid => { const v = s.providers[pid]; return (
              <button key={pid} className="prov" aria-pressed={pick === pid} onClick={() => choose(pid)}>
                <b>{v.label}</b><span>{BLURB[pid]}</span>
                <span style={{ marginTop: 4 }}>{v.local ? <span className="chip ok">On this Mac</span> : pid === "custom" ? <span className="chip">Your server</span> : <span className="chip red">Cloud</span>}
                  {v.kind === "cli" && !v.installed && <span className="chip" style={{ marginLeft: 6 }}>Not installed</span>}
                  {s.provider === pid && <span className="chip" style={{ marginLeft: 6 }}>In use</span>}</span>
              </button>); })}
          </div>
        </div>
      ))}

      <div className="panel form">
        <div className={`notice ${p.local ? "" : "cloud"}`}>
          {p.local ? "Everything stays on this Mac: transcripts are sent only to the model running locally."
            : cli ? `Uses ${p.label} signed in with ${p.plan}. When you summarize, ask or dictate with cleanup on, that text (never audio) goes to ${p.vendor}. Kiroku runs ${p.label} with every tool switched off in an empty folder, so it can only answer with text. It takes a few seconds to start each time.`
            : `When you summarize or ask a question, that recording's transcript text is sent to ${pick === "custom" ? base || "your server" : p.label}. Audio never leaves this Mac. Your key is stored in the macOS Keychain.`}
        </div>
        {cli && !p.installed && <div className="notice cloud">{p.label} isn't installed. Get it from{" "}
          <a href={p.install} target="_blank" rel="noreferrer">{p.install}</a>, then run <code>{p.login}</code> in Terminal once to sign in.</div>}
        {cli && p.installed && <small className="muted">Signed out or expired? Run <code>{p.login}</code> in Terminal once.</small>}
        {p.needs_key || pick === "custom" ? (
          <label className="field"><span>API key {pick === "custom" && <small>(if your server needs one)</small>}</span>
            <div className="line">
              <input className="input" type="password" autoComplete="off" value={key} onChange={e => setKey(e.target.value)}
                placeholder={p.has_key ? "Saved in Keychain. Paste a new key to replace it." : "Paste your key"} />
              {p.has_key && <button className="btn ghost danger" onClick={forgetKey}>Remove</button>}
            </div>
            {p.has_key && <small><Icon name="lock" size={12} /> A key is saved for {p.label}.</small>}
          </label>
        ) : null}
        {(pick === "custom" || pick === "ollama") && (
          <label className="field"><span>Server URL</span>
            <input className="input" value={base} onChange={e => setBase(e.target.value)} placeholder="http://127.0.0.1:1234/v1" />
            <small>{pick === "ollama" ? "Default Ollama address. Change only if you moved it." : "Must end in /v1 for most servers."}</small>
          </label>
        )}
        <label className="field"><span>Model{cli && <small> (optional; empty uses {p.label}'s default)</small>}</span>
          <div className="line">
            <input className="input" list="models" value={model} onChange={e => setModel(e.target.value)}
              placeholder={pick === "ollama" ? "e.g. qwen3:8b" : cli ? (pick === "claude_code" ? "Default, or haiku / sonnet / opus" : "Default") : "Load the list or type a model id"} />
            {!cli && <button className="btn" onClick={fetchModels}>Load models</button>}
          </div>
          <datalist id="models">{(pick === "claude_code" ? ["haiku", "sonnet", "opus"] : models).map(m => <option key={m} value={m} />)}</datalist>
          {pick === "claude_code" && <small>Haiku is fastest for dictation cleanup.</small>}
          {models.length > 0 && <small>{models.length} models available. Pick one from the field.</small>}
          {modelErr && <small style={{ color: "var(--red)" }}>{modelErr}</small>}
        </label>
        <label className="field"><span>Write notes in</span>
          <select className="input" value={lang} onChange={e => setLang(e.target.value)}>
            {LANGS.map(l => <option key={l}>{l}</option>)}</select>
        </label>
        <div style={{ display: "flex", gap: 10 }}>
          <button className="btn red" onClick={save} disabled={saving || (!model && !cli) || (cli && !p.installed)}>{saving ? "Saving…" : `Use ${p.label}`}</button>
          {s.provider === pick && <button className="btn" onClick={runTest} disabled={testing}>
            {testing ? <>Testing <span className="dots"><i /><i /><i /></span></> : "Test"}</button>}
          {s.provider && <button className="btn ghost" onClick={disconnect}>Turn off AI notes</button>}
        </div>
        {test && <div className={`notice ${test.ok ? "" : "cloud"}`}>{test.msg}</div>}
      </div>

      <h2 className="kicker">Speech engine <span className="ja">音声認識</span></h2>
      <EngineSettings />

      <h2 className="kicker">Dictation <span className="ja">音声入力</span></h2>
      <DictationSettings s={s} onSaved={x => { setS(x); onSaved(x); }} />

      <h2 className="kicker">Connectors <span className="ja">連携</span></h2>
      <Connectors />

      <h2 className="kicker">Privacy <span className="ja">秘密</span></h2>
      <div className="panel form" style={{ gap: 8 }}>
        <div>Audio is recorded, separated into speakers and transcribed on this Mac. It is never uploaded.</div>
        <div>Recordings live in your app data folder. Delete one from its page and it's gone from disk.</div>
        <div>The app only listens on 127.0.0.1 and rejects requests from other websites.</div>
      </div>
    </div>
  );
}
