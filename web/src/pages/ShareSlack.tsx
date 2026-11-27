import { useEffect, useState } from "react";
import { api } from "../api";
import { useToast } from "../ui";

export default function ShareSlack({ rid, onClose }: { rid: string; onClose: () => void }) {
  const toast = useToast();
  const [channels, setChannels] = useState<{ id: string; name: string }[] | null>(null);
  const [channel, setChannel] = useState(localStorage.getItem("kiroku.slackChannel") ?? "");
  const [text, setText] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.slackPreview(rid).then(r => setText(r.text)).catch(e => setErr(e.message));
    api.slackChannels().then(cs => { setChannels(cs); if (!cs.some(c => c.id === channel)) setChannel(cs[0]?.id ?? ""); })
      .catch(e => { setChannels([]); setErr(e.message); });
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    addEventListener("keydown", esc); return () => removeEventListener("keydown", esc);
  }, [rid]);

  const name = channels?.find(c => c.id === channel)?.name;
  const post = async () => {
    setBusy(true); setErr("");
    try { await api.slackPost(rid, channel, text); localStorage.setItem("kiroku.slackChannel", channel); toast(`Posted to #${name}`); onClose(); }
    catch (e) { setErr((e as Error).message); }
    finally { setBusy(false); }
  };
  return (
    <div className="scrim" onClick={onClose}>
      <div className="panel dialog" role="dialog" aria-modal="true" aria-labelledby="share-h" onClick={e => e.stopPropagation()}>
        <h2 id="share-h" className="kicker">Share to Slack <span className="ja">共有</span></h2>
        <label className="field"><span>Channel</span>
          <select className="input" value={channel} onChange={e => setChannel(e.target.value)} disabled={!channels?.length}>
            {!channels && <option>Loading channels…</option>}
            {channels?.length === 0 && <option>No channels found</option>}
            {channels?.map(c => <option key={c.id} value={c.id}>#{c.name}</option>)}
          </select></label>
        <label className="field"><span>Message <small>(edit before posting)</small></span>
          <textarea className="input" rows={12} value={text} onChange={e => setText(e.target.value)} /></label>
        {err && <div className="notice cloud">{err}{/connected yet/.test(err) && <> <a href="#/settings" onClick={onClose}>Open Settings</a></>}</div>}
        <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
          <button className="btn ghost" onClick={onClose}>Cancel</button>
          <button className="btn red" onClick={post} disabled={busy || !channel || !name || !text.trim()}>
            {busy ? "Posting…" : name ? `Post to #${name}` : "Post"}</button>
        </div>
      </div>
    </div>
  );
}
