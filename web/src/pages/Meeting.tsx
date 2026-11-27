import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { api, audioUrl, exportUrl, type LLMSettings, type Recording, type Summary } from "../api";
import { clock, fmtDur, highlight, Icon, parseTs, speakerColor, speakerName, useToast } from "../ui";

type Msg = { role: "user" | "assistant"; content: string; error?: boolean };

export default function Meeting({ id, llm }: { id: string; llm: LLMSettings | null }) {
  const toast = useToast();
  const [rec, setRec] = useState<Recording | null>(null);
  const [err, setErr] = useState("");
  const [tab, setTab] = useState<"summary" | "transcript">("summary");
  const [find, setFind] = useState("");
  const [busy, setBusy] = useState(false);
  const [sumErr, setSumErr] = useState("");
  const [armed, setArmed] = useState(false);
  const aud = useRef<HTMLAudioElement>(null);
  const [now, setNow] = useState(0);
  const [playing, setPlaying] = useState(false);

  useEffect(() => { api.get(id).then(r => { setRec(r); if (!r.summary && !llm?.provider) setTab("transcript"); }).catch(e => setErr(e.message)); }, [id]);

  const turns = rec?.turns ?? [];
  const dur = rec?.duration_s || turns.at(-1)?.end || 1;
  const speakers = useMemo(() => [...new Set(turns.map(t => t.speaker))].sort((a, b) => a - b), [turns]);
  const talk = (s: number) => turns.filter(t => t.speaker === s).reduce((a, t) => a + t.end - t.start, 0);
  const totalTalk = speakers.reduce((a, s) => a + talk(s), 0) || 1;
  const active = turns.findIndex(t => now >= t.start && now < t.end + 0.3);
  const prov = llm?.provider ? llm.providers[llm.provider] : null;

  useEffect(() => {
    if (playing && active >= 0) document.getElementById(`turn-${active}`)?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [active, playing]);

  if (err) return <div className="page"><div className="burst"><span className="ja">見つからない</span><p>{err}</p><a className="btn" href="#/">Back to Library</a></div></div>;
  if (!rec) return <div className="page"><div className="skel" style={{ height: 44, width: "60%", marginBottom: 16 }} /><div className="skel" style={{ height: 120 }} /></div>;

  const seek = (t: number) => { const a = aud.current; if (!a) return; a.currentTime = t; a.play(); };
  const save = async (patch: Parameters<typeof api.patch>[1], msg = "Saved") => {
    try { setRec(await api.patch(rec.id, patch)); toast(msg); } catch (e) { toast(`Couldn't save: ${(e as Error).message}`); }
  };
  const summarize = async () => {
    setBusy(true); setSumErr("");
    try { setRec(await api.summarize(rec.id)); setTab("summary"); }
    catch (e) { setSumErr((e as Error).message); }
    finally { setBusy(false); }
  };
  const toggleItem = (i: number) => {
    const s = rec.summary!;
    const items = s.action_items.map((a, k) => (k === i ? { ...a, done: !a.done } : a));
    save({ summary: { ...s, action_items: items } }, items[i].done ? "Done ✓" : "Reopened");
  };
  const remove = async () => {
    if (!armed) { setArmed(true); setTimeout(() => setArmed(false), 3000); return; }
    try { await api.remove(rec.id); toast("Recording deleted"); location.hash = "#/"; }
    catch (e) { toast(`Delete failed: ${(e as Error).message}`); }
  };
  const dict = rec.source === "dictation";
  const fallbackTitle = dict ? "Voice note" : "Untitled meeting";
  const d = parseTs(rec.ts);

  return (
    <div className="meeting">
      <div className="mcol">
        <div className="topbar">
          <a className="btn ghost" href="#/"><Icon name="back" />Library</a>
          <span className="sp" />
          <details className="menu">
            <summary className="btn"><Icon name="down" />Export</summary>
            <div className="pop panel">
              <a href={exportUrl(rec.id, "md")} download>Markdown (.md)</a>
              <a href={exportUrl(rec.id, "txt")} download>Plain text (.txt)</a>
              <a href={exportUrl(rec.id, "pdf")} download>PDF</a>
              <button onClick={() => navigator.clipboard.writeText(turns.map(t =>
                `${speakerName(rec.names, t.speaker)} [${clock(t.start)}]: ${t.text}`).join("\n")).then(() => toast("Transcript copied"))}>
                Copy transcript</button>
            </div>
          </details>
          <button className={`btn ${armed ? "red" : "ghost danger"}`} onClick={remove} aria-label="Delete recording">
            <Icon name="trash" />{armed ? "Click again to delete" : ""}</button>
        </div>

        <h1 className="mtitle" contentEditable="plaintext-only" suppressContentEditableWarning spellCheck={false}
          title="Click to rename"
          onKeyDown={e => { if (e.key === "Enter") { e.preventDefault(); e.currentTarget.blur(); } }}
          onBlur={e => { const v = e.currentTarget.textContent?.trim() ?? ""; if (v !== (rec.title || fallbackTitle)) save({ title: v }, "Renamed"); }}>
          {rec.title || fallbackTitle}
        </h1>
        <div className="mmeta">
          <span>{d.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" })} · {rec.ts.slice(11, 16)}</span>
          <span>{fmtDur(dur)}</span>
          <span className="chip">{rec.lang}</span>
          {rec.mode && rec.mode !== "native" && <span className="chip">{rec.mode} script</span>}
          {!dict && <span>{speakers.length} speaker{speakers.length === 1 ? "" : "s"}</span>}
          {rec.verdict && <span className={`chip ${rec.verdict === "verified_before_after" ? "ok" : "red"}`}>{rec.verdict.replace(/_/g, " ")}</span>}
        </div>

        {rec.audio && (
          <div className="panel player">
            <audio ref={aud} src={audioUrl(rec.id)} preload="metadata"
              onTimeUpdate={e => setNow(e.currentTarget.currentTime)}
              onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)} />
            <div className="pctl">
              <button className="play" aria-label={playing ? "Pause" : "Play"}
                onClick={() => (playing ? aud.current?.pause() : aud.current?.play())}>
                <Icon name={playing ? "pause" : "play"} size={18} /></button>
              <span className="mono">{clock(now)}</span>
              <div className="scrub" onClick={e => { const b = e.currentTarget.getBoundingClientRect(); seek(dur * (e.clientX - b.left) / b.width); }}>
                <div className="rail" /><div className="fill" style={{ width: `${100 * now / dur}%` }} />
                {rec.summary?.chapters.map((c, i) => <span key={i} className="chap" style={{ left: `${100 * c.start / dur}%` }} title={c.title} />)}
                <div className="knob" style={{ left: `${100 * now / dur}%` }} />
              </div>
              <span className="mono muted">{clock(dur)}</span>
            </div>
            {!dict && speakers.length > 0 && (
              <div className="lanes">
                {speakers.map(s => (
                  <div className="lane" key={s}>
                    <span className="nm"><i style={{ background: speakerColor(s) }} />
                      <input defaultValue={rec.names?.[s] ?? ""} placeholder={`Speaker ${s + 1}`} title="Rename speaker"
                        aria-label={`Name for speaker ${s + 1}`}
                        onKeyDown={e => { if (e.key === "Enter") e.currentTarget.blur(); }}
                        onBlur={e => { if (e.target.value !== (rec.names?.[s] ?? "")) save({ names: { [s]: e.target.value } }, "Speaker renamed"); }} />
                    </span>
                    <div className="track" onClick={e => { const b = e.currentTarget.getBoundingClientRect(); seek(dur * (e.clientX - b.left) / b.width); }}>
                      {turns.filter(t => t.speaker === s).map((t, i) => (
                        <i key={i} style={{ left: `${100 * t.start / dur}%`, width: `${Math.max(0.6, 100 * (t.end - t.start) / dur)}%`, background: speakerColor(s) }} />))}
                    </div>
                    <span className="pc">{Math.round(100 * talk(s) / totalTalk)}% · {fmtDur(talk(s))}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        <div className="tabs" role="tablist">
          <button className="tab" role="tab" aria-selected={tab === "summary"} onClick={() => setTab("summary")}>Summary <span className="ja">要約</span></button>
          <button className="tab" role="tab" aria-selected={tab === "transcript"} onClick={() => setTab("transcript")}>Transcript <span className="ja">文字起こし</span></button>
          {tab === "transcript" && <input className="input" type="search" placeholder="Find in transcript" value={find} onChange={e => setFind(e.target.value)} />}
        </div>

        {tab === "summary" ? (
          rec.summary ? <SummaryView s={rec.summary} onToggle={toggleItem} onSeek={seek}
            onRedo={summarize} busy={busy} err={sumErr} />
            : <div className="panel cta">
              <h3>Turn this into notes</h3>
              <p>Get an overview, action items with owners, decisions and chapters from the transcript.</p>
              {prov ? <>
                <button className="btn red" onClick={summarize} disabled={busy || !turns.length}>
                  {busy ? <>Writing notes <span className="dots"><i /><i /><i /></span></> : `Summarize with ${prov.label}`}</button>
                <Privacy local={prov.local} label={prov.label} />
              </> : <a className="btn primary" href="#/settings">Connect an AI model</a>}
              {sumErr && <div className="notice cloud">{sumErr}</div>}
            </div>
        ) : (
          <div className="turns">
            {turns.map((t, i) => (
              <div className={`turn ${i === active ? "on" : ""}`} id={`turn-${i}`} key={i}>
                <div className="ava" style={{ background: speakerColor(t.speaker) }}>
                  {rec.names?.[t.speaker]?.slice(0, 1).toUpperCase() || t.speaker + 1}</div>
                <div>
                  <div className="who"><b>{speakerName(rec.names, t.speaker)}</b>
                    <button className="mono" onClick={() => seek(t.start)}>{clock(t.start)}</button></div>
                  <div className="bubble" onClick={() => seek(t.start)}>{highlight(t.text, find)}</div>
                </div>
              </div>
            ))}
            {!turns.length && <div className="burst"><span className="ja">静か</span><p>No speech was detected in this recording.</p></div>}
          </div>
        )}
      </div>
      <Ask rec={rec} llmReady={!!prov} local={!!prov?.local} label={prov?.label ?? ""} />
    </div>
  );
}

function Privacy({ local, label }: { local: boolean; label: string }) {
  return <span className="fine"><Icon name="lock" size={13} />
    {local ? "Runs on this Mac. Nothing leaves your computer."
      : `Sends this transcript (text only, never audio) to ${label}.`}</span>;
}

function SummaryView({ s, onToggle, onSeek, onRedo, busy, err }: {
  s: Summary; onToggle: (i: number) => void; onSeek: (t: number) => void;
  onRedo: () => void; busy: boolean; err: string;
}) {
  return (
    <div>
      <section className="sumsec"><h2 className="kicker">Overview <span className="ja">概要</span></h2><p>{s.overview}</p></section>
      <section className="sumsec">
        <h2 className="kicker">Action items <span className="ja">やること</span></h2>
        {s.action_items.length ? <ul className="todo">{s.action_items.map((a, i) => (
          <li key={i}><label><input type="checkbox" checked={a.done} onChange={() => onToggle(i)} />
            <span className={a.done ? "done" : ""}>{a.text}{a.owner && <span className="own">— {a.owner}</span>}</span></label></li>))}
        </ul> : <p className="muted">No action items came up.</p>}
      </section>
      {s.decisions.length > 0 && <section className="sumsec"><h2 className="kicker">Decisions <span className="ja">決定</span></h2>
        <ul className="bul">{s.decisions.map((d, i) => <li key={i}>{d}</li>)}</ul></section>}
      {s.chapters.length > 0 && <section className="sumsec"><h2 className="kicker">Chapters <span className="ja">章</span></h2>
        <div className="chaps">{s.chapters.map((c, i) => (
          <button key={i} onClick={() => onSeek(c.start)}><span className="mono">{clock(c.start)}</span>{c.title}</button>))}</div></section>}
      <div className="fine" style={{ gap: 12 }}>
        <span>Written by {s.model} · {s.ts.slice(0, 16)}</span>
        <button className="btn ghost" onClick={onRedo} disabled={busy}>{busy ? "Rewriting…" : "Regenerate"}</button>
      </div>
      {err && <div className="notice cloud" style={{ marginTop: 10 }}>{err}</div>}
    </div>
  );
}

function Ask({ rec, llmReady, local, label }: { rec: Recording; llmReady: boolean; local: boolean; label: string }) {
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => { end.current?.scrollIntoView({ behavior: "smooth" }); }, [msgs, busy]);

  const send = async (question: string) => {
    if (!question.trim() || busy) return;
    const prior = msgs.filter(m => !m.error).map(({ role, content }) => ({ role, content }));
    setMsgs(m => [...m, { role: "user", content: question }]); setQ(""); setBusy(true);
    try { const { answer } = await api.ask(rec.id, question, prior); setMsgs(m => [...m, { role: "assistant", content: answer }]); }
    catch (e) { setMsgs(m => [...m, { role: "assistant", content: (e as Error).message, error: true }]); }
    finally { setBusy(false); }
  };
  const submit = (e: FormEvent) => { e.preventDefault(); send(q); };
  const first = rec.names?.[0] || "Speaker 1";
  const suggestions = ["What did we agree on?", "List every follow-up and who owns it.", `What were ${first}'s main points?`];

  return (
    <aside className="rail-ask tone">
      <header><h2>Ask this meeting <span className="ja">質問</span></h2>
        {llmReady && <div style={{ marginTop: 6 }}><Privacy local={local} label={label} /></div>}</header>
      <div className="chat">
        {!llmReady ? <div className="burst" style={{ padding: "36px 16px" }}><span className="ja" style={{ fontSize: 22 }}>未接続</span>
          <p>Connect Claude, ChatGPT, Gemini or a local model to ask questions about this recording.</p>
          <a className="btn primary" href="#/settings">Open Settings</a></div>
          : !msgs.length ? <div className="sugg">{suggestions.map(s => <button key={s} onClick={() => send(s)}>{s}</button>)}</div>
          : msgs.map((m, i) => <div key={i} className={`msg ${m.role === "user" ? "me" : "ai"} ${m.error ? "err" : ""}`}>{m.content}</div>)}
        {busy && <div className="msg ai"><span className="dots"><i /><i /><i /></span></div>}
        <div ref={end} />
      </div>
      <form className="askbox" onSubmit={submit}>
        <textarea className="input" placeholder={llmReady ? "Ask anything about this meeting…" : "Connect a model first"}
          disabled={!llmReady} value={q} onChange={e => setQ(e.target.value)}
          onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(q); } }} />
        <button className="btn primary" disabled={!llmReady || busy || !q.trim()} aria-label="Send"><Icon name="send" /></button>
      </form>
    </aside>
  );
}
