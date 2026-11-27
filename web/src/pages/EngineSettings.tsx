import { useEffect, useState } from "react";
import { api } from "../api";
import { useToast } from "../ui";

const REPO = "https://huggingface.co/bodhan-ai/indic-transcribe-flex";

export default function EngineSettings() {
  const toast = useToast();
  const [h, setH] = useState<Awaited<ReturnType<typeof api.health>> | null>(null);
  const [st, setSt] = useState<Awaited<ReturnType<typeof api.setupStatus>> | null>(null);
  const [token, setToken] = useState("");
  const [err, setErr] = useState("");
  const refresh = () => { api.health().then(setH); api.setupStatus().then(setSt); };
  useEffect(refresh, []);
  useEffect(() => {  // follow a running download
    if (st?.download.state !== "running") return;
    const t = setTimeout(() => api.setupStatus().then(s => { setSt(s); if (s.download.state === "done") { refresh(); toast("Code-mix engine installed"); } }), 1500);
    return () => clearTimeout(t);
  }, [st]);
  if (!h || !st) return <div className="skel" style={{ height: 120 }} />;

  const saveToken = async () => {
    setErr("");
    try { const { user } = await api.saveHfToken(token); setToken(""); toast(`Signed in to Hugging Face as ${user}`); refresh(); }
    catch (e) { setErr((e as Error).message); }
  };
  const download = async () => { setErr(""); try { await api.downloadFlex(); refresh(); } catch (e) { setErr((e as Error).message); } };
  const dl = st.download;

  return (
    <div className="panel form">
      <div><b>In use: </b>{h.default_engine === "flex"
        ? <>Code-mix engine <span className="chip ok">{h.default_mode === "mixed" ? "Hindi + English words kept as spoken" : h.default_mode}</span></>
        : <>Fast engine <span className="chip">Indian scripts only</span></>}
        {h.default_engine === "flex" && !h.flex_loaded && <small className="muted"> (warming up, about a minute after launch)</small>}</div>
      <small className="muted">Meetings, dictation and the Chrome extension all use this. On the Record page you can pick per recording.</small>
      {!h.flex && (<>
        <div className="notice">
          <b>Code-mix engine</b> (bodhan-ai/indic-transcribe-flex): keeps English words in English inside Hindi speech
          (“kal meeting में deck review”) and follows switches between languages. Runs on this Mac's GPU. 4.9 GB download.
        </div>
        {!h.torch ? <div className="notice cloud">This build doesn't include PyTorch, which the code-mix engine needs. Install the full build of Kiroku.</div> : (
          <ol className="steps">
            <li>Sign in at <a href={REPO} target="_blank" rel="noreferrer">huggingface.co/bodhan-ai/indic-transcribe-flex</a> and accept the model license (instant).</li>
            <li>{st.hf_token ? <>Hugging Face token saved. <span className="chip ok">Ready</span></> : <>
              Create a <b>Read</b> token at <a href="https://huggingface.co/settings/tokens" target="_blank" rel="noreferrer">huggingface.co/settings/tokens</a> and paste it:
              <div className="line" style={{ marginTop: 6 }}>
                <input className="input" type="password" autoComplete="off" value={token} onChange={e => setToken(e.target.value)} placeholder="hf_…" />
                <button className="btn" onClick={saveToken} disabled={!token.startsWith("hf_")}>Save</button></div></>}</li>
            <li>{dl.state === "running" ? <div className="job" style={{ width: "100%" }}>
                <div className="jobline"><b>Downloading</b><span className="muted mono">{dl.detail}</span></div>
                <div className="bar"><i style={{ width: `${Math.max(dl.percent, 2)}%` }} /></div></div>
              : <button className="btn red" onClick={download} disabled={!st.hf_token}>Download code-mix engine (4.9 GB)</button>}</li>
          </ol>)}
        {(err || dl.state === "error") && <div className="notice cloud">{err || dl.detail}</div>}
      </>)}
    </div>
  );
}
