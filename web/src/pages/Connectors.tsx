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
    : c.id === "gmail" ? <Gmail key={c.id} c={c} onSaved={update} toast={toast} />
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

const GCP = "https://console.cloud.google.com";

function Gmail({ c, onSaved, toast }: { c: Connector; onSaved: (c: Connector) => void; toast: (m: string) => void }) {
  const [id, setId] = useState("");
  const [secret, setSecret] = useState("");
  const [busy, setBusy] = useState(false);
  const [waiting, setWaiting] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; msg: string } | null>(null);
  const hasClient = c.has_secret.client_id && c.has_secret.client_secret;
  const redirect = `http://127.0.0.1:${location.port || 80}/api/connectors/gmail/callback`;

  const saveClient = async () => {
    setBusy(true); setResult(null);
    try { onSaved(await api.saveConnector("gmail", { secrets: { client_id: id.trim(), client_secret: secret.trim() } }));
      setId(""); setSecret(""); toast("Google client saved to Keychain"); }
    catch (e) { setResult({ ok: false, msg: (e as Error).message }); }
    finally { setBusy(false); }
  };
  const connect = async () => {
    setResult(null);
    try {
      await api.gmailConnect(); setWaiting(true);
      for (let i = 0; i < 90; i++) {  // the browser tab finishes sign-in; watch for the token
        await new Promise(r => setTimeout(r, 2000));
        const g = (await api.connectors()).connectors.find(x => x.id === "gmail")!;
        if (g.configured) { onSaved(g); toast("Gmail connected"); setWaiting(false); return; }
      }
      setWaiting(false); setResult({ ok: false, msg: "Didn't hear back from Google. Finish signing in in your browser, or click Connect Gmail again." });
    } catch (e) { setWaiting(false); setResult({ ok: false, msg: (e as Error).message }); }
  };
  const test = async () => {
    setBusy(true); setResult(null);
    try { const { tools } = await api.testConnector("gmail");
      setResult({ ok: tools.includes("create_draft"), msg: tools.includes("create_draft")
        ? `Connected to Gmail's MCP server (${tools.length} tools offered). Kiroku only ever uses create_draft.`
        : "Connected, but this server doesn't offer create_draft. Your project may not have Gmail MCP preview access." }); }
    catch (e) { setResult({ ok: false, msg: (e as Error).message }); }
    finally { setBusy(false); }
  };
  const disconnect = async () => { onSaved(await api.disconnectConnector("gmail")); toast("Gmail disconnected and keys removed"); };

  return (
    <div className="panel form">
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <Icon name="plug" size={20} /><b style={{ fontSize: 17 }}>Gmail</b>
        {c.configured ? <span className="chip ok">Connected</span> : hasClient ? <span className="chip">Not signed in</span> : <span className="chip">Not set up</span>}
        <span className="muted" style={{ marginLeft: "auto", fontSize: 12 }}>MCP · {c.server}</span>
      </div>
      <div className="notice cloud">
        Uses Google's own Gmail MCP server with your own Google sign-in. Kiroku asks only for permission to
        write drafts and only ever creates drafts. You read and send them from Gmail. The note text goes to Google
        when you save a draft.
      </div>
      {!c.configured && (
        <ol className="steps">
          <li><a href={`${GCP}/projectcreate`} target="_blank" rel="noreferrer">Create a Google Cloud project</a> (free).</li>
          <li>Enable <a href={`${GCP}/apis/library/gmail.googleapis.com`} target="_blank" rel="noreferrer">Gmail API</a> and{" "}
            <a href={`${GCP}/apis/library/gmailmcp.googleapis.com`} target="_blank" rel="noreferrer">Gmail MCP API</a>.</li>
          <li>In <a href={`${GCP}/auth/overview`} target="_blank" rel="noreferrer">Google Auth Platform</a>, set up the consent screen
            (audience <b>External</b>, add your own address as a <b>test user</b>) and add the scope <code>gmail.compose</code>.</li>
          <li><a href={`${GCP}/auth/clients/create`} target="_blank" rel="noreferrer">Create an OAuth client</a>: type <b>Desktop app</b>,
            tick <b>Use this client for an AI-powered agent</b>. Copy the client ID and secret.
            <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>Using a Web application client instead? Add this redirect URI: <code>{redirect}</code></div></li>
          <li>Paste them below, save, then click <b>Connect Gmail</b> and approve in your browser.</li>
        </ol>
      )}
      {!c.configured && (<>
        <label className="field"><span>OAuth client ID</span>
          <input className="input" value={id} onChange={e => setId(e.target.value)} autoComplete="off"
            placeholder={c.has_secret.client_id ? "Saved in Keychain. Paste to replace." : "….apps.googleusercontent.com"} /></label>
        <label className="field"><span>OAuth client secret</span>
          <div className="line">
            <input className="input" type="password" value={secret} onChange={e => setSecret(e.target.value)} autoComplete="off"
              placeholder={c.has_secret.client_secret ? "Saved in Keychain. Paste to replace." : "GOCSPX-…"} />
            <button className="btn" disabled={busy || !id.trim().endsWith(".apps.googleusercontent.com") || !secret.trim()} onClick={saveClient}>Save</button>
          </div>
          {id && !id.trim().endsWith(".apps.googleusercontent.com") && <small style={{ color: "var(--red)" }}>Client IDs end in .apps.googleusercontent.com</small>}
        </label>
      </>)}
      <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
        {!c.configured && <button className="btn red" disabled={!hasClient || waiting} onClick={connect}>
          {waiting ? <>Waiting for Google <span className="dots"><i /><i /><i /></span></> : "Connect Gmail"}</button>}
        {c.configured && <button className="btn" onClick={test} disabled={busy}>{busy ? <>Testing <span className="dots"><i /><i /><i /></span></> : "Test connection"}</button>}
        {(c.configured || hasClient) && <button className="btn ghost danger" onClick={disconnect}>Disconnect and forget keys</button>}
      </div>
      {waiting && <small className="muted">A Google sign-in page opened in your browser. Approve it there; this page updates by itself.</small>}
      {result && <div className={`notice ${result.ok ? "" : "cloud"}`}>{result.msg}</div>}
      <small className="muted">If Gmail asks you to reconnect every week, your Google app is in Testing mode. That's Google's limit for unpublished apps.</small>
    </div>
  );
}
