import { useEffect, useState } from "react";
import { api, type Connector } from "../api";
import { Icon, useToast } from "../ui";

export default function Connectors() {
  const toast = useToast();
  const [list, setList] = useState<Connector[] | null>(null);
  const [manifest, setManifest] = useState<unknown>(null);
  const [err, setErr] = useState("");
  useEffect(() => { api.connectors().then(r => { setList(r.connectors); setManifest(r.slack_manifest); }).catch(e => setErr(e.message)); }, []);
  if (err) return <div className="notice cloud">{err}</div>;
  if (!list) return <div className="skel" style={{ height: 200 }} />;
  const update = (c: Connector) => setList(l => l!.map(x => (x.id === c.id ? c : x)));
  return <>{list.map(c => c.id === "slack"
    ? <Slack key={c.id} c={c} manifest={manifest} onSaved={update} toast={toast} />
    : null)}</>;
}

function Slack({ c, manifest, onSaved, toast }: { c: Connector; manifest: unknown; onSaved: (c: Connector) => void; toast: (m: string) => void }) {
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; msg: string } | null>(null);
  const save = async (value: string) => {
    setBusy(true); setResult(null);
    try { onSaved(await api.saveConnector("slack", { secrets: { SLACK_MCP_XOXB_TOKEN: value } })); setToken(""); toast(value ? "Slack token saved to Keychain" : "Slack disconnected"); }
    catch (e) { setResult({ ok: false, msg: (e as Error).message }); }
    finally { setBusy(false); }
  };
  const test = async () => {
    setBusy(true); setResult(null);
    try { const { tools } = await api.testConnector("slack"); setResult({ ok: true, msg: `Connected. Tools available: ${tools.join(", ")}.` }); }
    catch (e) { setResult({ ok: false, msg: (e as Error).message }); }
    finally { setBusy(false); }
  };
  return (
    <div className="panel form">
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <Icon name="plug" size={20} /><b style={{ fontSize: 17 }}>Slack</b>
        {c.configured ? <span className="chip ok">Connected</span> : <span className="chip">Not set up</span>}
        <span className="muted" style={{ marginLeft: "auto", fontSize: 12 }}>MCP · {c.server}</span>
      </div>
      <div className="notice">
        Runs a local MCP server on this Mac with your token. Kiroku turns on only two of its tools:
        listing channels and posting a message you've reviewed. It never reads your Slack messages.
      </div>
      {c.needs_node && <div className="notice cloud">Needs Node.js. Install it from nodejs.org, then reopen this page.</div>}
      {!c.configured && (
        <ol className="steps">
          <li>Open <a href="https://api.slack.com/apps?new_app=1" target="_blank" rel="noreferrer">Slack app setup</a>,
            choose <b>From a manifest</b>, pick your workspace, and paste this:
            <div style={{ marginTop: 6 }}><button className="btn" onClick={() => navigator.clipboard.writeText(JSON.stringify(manifest, null, 2)).then(() => toast("Manifest copied"))}>Copy app manifest</button></div></li>
          <li>Click <b>Install to Workspace</b>, then open <b>OAuth &amp; Permissions</b> and copy the <b>Bot User OAuth Token</b>.</li>
          <li>Paste it below. It goes straight into the macOS Keychain.</li>
        </ol>
      )}
      <label className="field"><span>Bot token</span>
        <div className="line">
          <input className="input" type="password" autoComplete="off" value={token} onChange={e => setToken(e.target.value)}
            placeholder={c.configured ? "Saved in Keychain. Paste a new token to replace it." : "xoxb-…"} />
          <button className="btn red" disabled={busy || !token.startsWith("xoxb-")} onClick={() => save(token)}>Save</button>
        </div>
        {token && !token.startsWith("xoxb-") && <small style={{ color: "var(--red)" }}>Bot tokens start with xoxb-.</small>}
      </label>
      {c.configured && (
        <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
          <button className="btn" onClick={test} disabled={busy}>{busy ? <>Testing <span className="dots"><i /><i /><i /></span></> : "Test connection"}</button>
          <button className="btn ghost danger" onClick={() => save("")} disabled={busy}>Disconnect</button>
        </div>
      )}
      {result && <div className={`notice ${result.ok ? "" : "cloud"}`}>{result.msg}</div>}
      <small className="muted">Public channels work right away. For a private channel, type <code>/invite @Kiroku</code> in it first.</small>
    </div>
  );
}
