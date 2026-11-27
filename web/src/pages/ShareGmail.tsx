import { useEffect, useState } from "react";
import { api } from "../api";
import { useToast } from "../ui";

const EMAIL = /^[^@\s,<>]+@[^@\s,<>]+\.[^@\s,<>]+$/;

export default function ShareGmail({ rid, onClose }: { rid: string; onClose: () => void }) {
  const toast = useToast();
  const [to, setTo] = useState(localStorage.getItem("kiroku.gmailTo") ?? "");
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);

  useEffect(() => {
    api.gmailPreview(rid).then(p => { setSubject(p.subject); setBody(p.body); if (p.to.length) setTo(p.to.join(", ")); }).catch(e => setErr(e.message));
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    addEventListener("keydown", esc); return () => removeEventListener("keydown", esc);
  }, [rid]);

  const list = to.split(/[,\s;]+/).filter(Boolean);
  const bad = list.filter(a => !EMAIL.test(a));
  const save = async () => {
    setBusy(true); setErr("");
    try { await api.gmailDraft(rid, list, subject, body); localStorage.setItem("kiroku.gmailTo", to); setDone(true); toast("Draft saved in Gmail"); }
    catch (e) { setErr((e as Error).message); }
    finally { setBusy(false); }
  };
  return (
    <div className="scrim" onClick={onClose}>
      <div className="panel dialog" role="dialog" aria-modal="true" aria-labelledby="gm-h" onClick={e => e.stopPropagation()}>
        <h2 id="gm-h" className="kicker">Email as a Gmail draft <span className="ja">下書き</span></h2>
        {done ? <>
          <div className="notice">Draft saved. Nothing has been sent. Open Gmail to check it and press Send.</div>
          <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
            <button className="btn ghost" onClick={onClose}>Close</button>
            <a className="btn red" href="https://mail.google.com/mail/#drafts" target="_blank" rel="noreferrer">Open Gmail drafts</a>
          </div>
        </> : <>
          <label className="field"><span>To <small>(optional; plain addresses, separated by commas)</small></span>
            <input className="input" value={to} onChange={e => setTo(e.target.value)} placeholder="asha@example.com, ravi@example.com" />
            {bad.length > 0 && <small style={{ color: "var(--red)" }}>Not an email address: {bad.join(", ")}</small>}</label>
          <label className="field"><span>Subject</span>
            <input className="input" value={subject} onChange={e => setSubject(e.target.value)} /></label>
          <label className="field"><span>Body <small>(edit before saving)</small></span>
            <textarea className="input" rows={12} value={body} onChange={e => setBody(e.target.value)} /></label>
          {err && <div className="notice cloud">{err}{/isn't connected/.test(err) && <> <a href="#/settings" onClick={onClose}>Open Settings</a></>}</div>}
          <div style={{ display: "flex", gap: 10, justifyContent: "flex-end", alignItems: "center" }}>
            <span className="fine" style={{ marginRight: "auto" }}>Saves a draft only. Kiroku never sends email.</span>
            <button className="btn ghost" onClick={onClose}>Cancel</button>
            <button className="btn red" onClick={save} disabled={busy || bad.length > 0 || !body.trim()}>{busy ? "Saving…" : "Save draft"}</button>
          </div>
        </>}
      </div>
    </div>
  );
}
