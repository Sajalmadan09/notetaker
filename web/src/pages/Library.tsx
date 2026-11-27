import { useEffect, useMemo, useState } from "react";
import { api, type Row } from "../api";
import { dayGroup, fmtDur, highlight } from "../ui";

export default function Library() {
  const [rows, setRows] = useState<Row[] | null>(null);
  const [err, setErr] = useState("");
  const [q, setQ] = useState("");
  const [src, setSrc] = useState<"all" | "meeting" | "dictation">("all");

  useEffect(() => { api.list().then(setRows).catch(e => setErr(e.message)); }, []);
  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      if (e.key === "/" && !/INPUT|TEXTAREA/.test((e.target as HTMLElement).tagName)) {
        e.preventDefault(); document.getElementById("q")?.focus();
      }
    };
    addEventListener("keydown", on); return () => removeEventListener("keydown", on);
  }, []);

  const shown = useMemo(() => (rows ?? []).filter(r =>
    (src === "all" || (r.source || "meeting") === src) &&
    (!q || `${r.title ?? ""} ${r.preview}`.toLowerCase().includes(q.toLowerCase()))), [rows, q, src]);
  const minutes = (rows ?? []).reduce((a, r) => a + (r.duration_s || 0), 0) / 60;

  let last = "";
  return (
    <div className="page">
      <div className="phead">
        <div>
          <h1>Library<span className="ja">記録帳</span></h1>
          {rows && <div className="muted" style={{ marginTop: 6 }}>
            {rows.length} recording{rows.length === 1 ? "" : "s"} · {minutes.toFixed(0)} min captured</div>}
        </div>
        <a className="btn primary" href="#/record">New recording</a>
      </div>
      <div className="tools">
        <input id="q" className="input" type="search" placeholder="Search titles and notes  ( / )"
          value={q} onChange={e => setQ(e.target.value)} aria-label="Search recordings" />
        <div className="seg" role="group" aria-label="Filter by source">
          {(["all", "meeting", "dictation"] as const).map(v => (
            <button key={v} aria-pressed={src === v} onClick={() => setSrc(v)}>
              {v === "all" ? "All" : v === "meeting" ? "Meetings" : "Dictations"}</button>))}
        </div>
      </div>

      {err && <div className="burst"><span className="ja">通信エラー</span><p>Can't reach the local server: {err}</p></div>}
      {!rows && !err && [0, 1, 2].map(i => <div key={i} className="skel" style={{ height: 74, marginBottom: 10 }} />)}
      {rows && !shown.length && (
        <div className="burst">
          <span className="ja">{rows.length ? "見つからない" : "まだ何もない"}</span>
          <p>{rows.length ? "Nothing matches that search." : "Record a meeting or a voice note. It's transcribed on this Mac and shows up here."}</p>
          {!rows.length && <a className="btn red" href="#/record">Start recording</a>}
        </div>
      )}
      {shown.map(r => {
        const g = dayGroup(r.ts); const head = g !== last; last = g;
        const dict = r.source === "dictation";
        return (
          <div key={r.id}>
            {head && <div className="group">{g}</div>}
            <a className="row" href={`#/r/${r.id}`}>
              <div className="t">
                <span>{highlight(r.title || (dict ? "Voice note" : "Untitled meeting"), q)}</span>
                <span className="meta">{r.ts.slice(11, 16)} · {fmtDur(r.duration_s || 0)}</span>
              </div>
              <div className="p">{r.preview ? highlight(r.preview, q) : <span className="muted">No speech detected</span>}</div>
              <div className="chips">
                <span className="chip">{dict ? "Dictation" : "Meeting"}</span>
                <span className="chip">{r.lang}</span>
                {!dict && <span className="chip">{r.turn_count} turns</span>}
              </div>
            </a>
          </div>
        );
      })}
    </div>
  );
}
