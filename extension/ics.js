// Minimal iCalendar reader for Google Calendar "secret address in iCal format" feeds.
// Pure functions (no chrome.* APIs) so they can be tested in Node: tests/ext_ics.test.mjs.
// Handles: UTC / TZID / floating times, all-day skip, RRULE (DAILY/WEEKLY/MONTHLY/YEARLY with
// INTERVAL, BYDAY incl. ordinals, BYMONTHDAY, UNTIL, COUNT), EXDATE, RECURRENCE-ID overrides, CANCELLED.
// Not handled: RDATE, BYSETPOS, BYWEEKNO, sub-daily frequencies (ponytail: add if a real feed needs them).

const DAY = 864e5;
const WD = ["SU", "MO", "TU", "WE", "TH", "FR", "SA"];
const MEET_RE = /https:\/\/meet\.google\.com\/[a-z]{3}-[a-z]{4}-[a-z]{3}/i;

export function unfold(text) {
  return text.replace(/\r?\n[ \t]/g, "");
}

function tzParts(ts, tz) {
  const f = new Intl.DateTimeFormat("en-US", {
    timeZone: tz, hourCycle: "h23", year: "numeric", month: "numeric", day: "numeric",
    hour: "numeric", minute: "numeric", second: "numeric",
  });
  const p = Object.fromEntries(f.formatToParts(new Date(ts)).map(x => [x.type, +x.value]));
  return { y: p.year, mo: p.month, d: p.day, h: p.hour, mi: p.minute, s: p.second };
}

function validTz(tz) {
  try { new Intl.DateTimeFormat("en-US", { timeZone: tz }); return true; } catch { return false; }
}

// wall-clock time in `tz` -> UTC ms (tz undefined = system zone)
export function localToUtc(y, mo, d, h, mi, s, tz) {
  const guess = Date.UTC(y, mo - 1, d, h, mi, s);
  const off = ts => {
    const p = tzParts(ts, tz);
    return Date.UTC(p.y, p.mo - 1, p.d, p.h, p.mi, p.s) - ts;
  };
  let utc = guess - off(guess);
  utc = guess - off(utc);
  return utc;
}

function parseDt(line) {
  // "DTSTART;TZID=Asia/Kolkata:20260126T100000" | "DTSTART:20260126T100000Z" | "DTSTART;VALUE=DATE:20260126"
  const i = line.indexOf(":");
  const head = line.slice(0, i), val = line.slice(i + 1).trim();
  const m = val.match(/^(\d{4})(\d{2})(\d{2})(?:T(\d{2})(\d{2})(\d{2})(Z)?)?$/);
  if (!m) return null;
  if (!m[4]) return { allDay: true };
  const [y, mo, d, h, mi, s] = [+m[1], +m[2], +m[3], +m[4], +m[5], +m[6]];
  let tz = (head.match(/TZID=([^;:]+)/) || [])[1];
  if (tz && !validTz(tz)) tz = "UTC";
  if (m[7]) return { ms: Date.UTC(y, mo - 1, d, h, mi, s), tz: "UTC", local: { y, mo, d, h, mi, s } };
  return { ms: localToUtc(y, mo, d, h, mi, s, tz), tz, local: { y, mo, d, h, mi, s } };
}

export function parseIcs(ics) {
  const events = [];
  for (const block of unfold(ics).split("BEGIN:VEVENT").slice(1)) {
    const body = block.split("END:VEVENT")[0];
    const lines = body.split(/\r?\n/);
    const get = key => lines.find(l => l.startsWith(key + ":") || l.startsWith(key + ";"));
    const val = key => { const l = get(key); return l ? l.slice(l.indexOf(":") + 1).trim() : ""; };
    if (/CANCELLED/i.test(val("STATUS"))) continue;
    const st = get("DTSTART") && parseDt(get("DTSTART"));
    if (!st || st.allDay) continue;
    const en = get("DTEND") && parseDt(get("DTEND"));
    const rid = get("RECURRENCE-ID") && parseDt(get("RECURRENCE-ID"));
    const exdates = new Set();
    // EXDATE may carry TZID: parse each value with the line's own head
    for (const l of lines.filter(l => l.startsWith("EXDATE"))) {
      const head = l.slice(0, l.indexOf(":"));
      for (const v of l.slice(l.indexOf(":") + 1).split(","))
        { const d = parseDt(head + ":" + v.trim()); if (d?.ms) exdates.add(d.ms); }
    }
    const text = val("X-GOOGLE-CONFERENCE") + " " + val("LOCATION") + " " + val("DESCRIPTION") + " " + val("URL");
    events.push({
      uid: val("UID"), summary: val("SUMMARY").replace(/\\,/g, ",").replace(/\\n/g, " "),
      start: st.ms, end: en?.ms ?? st.ms + 3600000, tz: st.tz, local: st.local,
      rrule: val("RRULE") ? Object.fromEntries(val("RRULE").split(";").map(p => p.split("="))) : null,
      exdates, recurrenceId: rid?.ms ?? null,
      meetUrl: (text.match(MEET_RE) || [""])[0] || "",
      // Invitees by email; meeting rooms and people who declined aren't recipients for the notes.
      attendees: lines.filter(l => l.startsWith("ATTENDEE") && !/CUTYPE=(RESOURCE|ROOM)|PARTSTAT=DECLINED/i.test(l))
        .map(l => (l.match(/mailto:([^\s;]+)/i) || [])[1]).filter(Boolean),
    });
  }
  return events;
}

const dayIdx = (y, mo, d) => Math.floor(Date.UTC(y, mo - 1, d) / DAY);
const weekday = idx => (new Date(idx * DAY).getUTCDay());

function matchesRule(r, startLocal, c) {
  // c = {y,mo,d,idx} candidate calendar date; startLocal = {y,mo,d} of DTSTART in its tz
  const interval = +(r.INTERVAL || 1);
  const sIdx = dayIdx(startLocal.y, startLocal.mo, startLocal.d);
  if (c.idx < sIdx) return false;
  const byday = r.BYDAY ? r.BYDAY.split(",") : null;
  switch (r.FREQ) {
    case "DAILY":
      return (c.idx - sIdx) % interval === 0;
    case "WEEKLY": {
      const days = byday ? byday.map(x => WD.indexOf(x.slice(-2))) : [weekday(sIdx)];
      if (!days.includes(weekday(c.idx))) return false;
      const wk = i => Math.floor((i - ((weekday(i) + 6) % 7)) / 7);  // weeks start Monday
      return (wk(c.idx) - wk(sIdx)) % interval === 0;
    }
    case "MONTHLY": {
      const months = (c.y - startLocal.y) * 12 + (c.mo - startLocal.mo);
      if (months < 0 || months % interval !== 0) return false;
      if (byday) return byday.some(b => {
        const n = parseInt(b, 10), wd = WD.indexOf(b.slice(-2));
        if (weekday(c.idx) !== wd) return false;
        if (Number.isNaN(n)) return true;
        const dim = new Date(Date.UTC(c.y, c.mo, 0)).getUTCDate();
        return n > 0 ? Math.ceil(c.d / 7) === n : Math.ceil((dim - c.d + 1) / 7) === -n;
      });
      const bmd = r.BYMONTHDAY ? r.BYMONTHDAY.split(",").map(Number) : [startLocal.d];
      const dim = new Date(Date.UTC(c.y, c.mo, 0)).getUTCDate();
      return bmd.some(x => (x > 0 ? x : dim + 1 + x) === c.d);
    }
    case "YEARLY":
      return c.mo === startLocal.mo && c.d === startLocal.d && (c.y - startLocal.y) % interval === 0;
    default:
      return false;
  }
}

// All meeting occurrences with start in [from, to] (ms), sorted. Occurrence = {summary,start,end,meetUrl,uid}.
export function occurrences(events, from, to) {
  const overrides = new Map();  // uid -> Set(original start ms)
  for (const e of events) if (e.recurrenceId != null) {
    if (!overrides.has(e.uid)) overrides.set(e.uid, new Set());
    overrides.get(e.uid).add(e.recurrenceId);
  }
  const out = [];
  const push = (e, start) => out.push({ uid: e.uid, summary: e.summary, start, end: start + (e.end - e.start), meetUrl: e.meetUrl, attendees: e.attendees || [] });
  for (const e of events) {
    if (!e.rrule) {
      if (e.start >= from && e.start <= to) push(e, e.start);
      continue;
    }
    const r = e.rrule, until = r.UNTIL ? parseDt("X:" + r.UNTIL)?.ms : Infinity;
    const skip = new Set([...(overrides.get(e.uid) || []), ...e.exdates]);
    const L = e.local;
    // walk calendar days (in the event's zone) covering the window ± 1 day
    const p0 = tzParts(from - DAY, e.tz), startIdx = dayIdx(p0.y, p0.mo, p0.d);
    const endIdx = Math.ceil((to + DAY) / DAY) + 1;
    let counted = null;
    if (r.COUNT) {  // enumerate from DTSTART to find which date is the COUNT-th
      let n = 0, i = dayIdx(L.y, L.mo, L.d);
      for (let k = 0; k < 4000 && n < +r.COUNT; k++, i++) {
        const dt = new Date(i * DAY), c = { y: dt.getUTCFullYear(), mo: dt.getUTCMonth() + 1, d: dt.getUTCDate(), idx: i };
        if (matchesRule(r, L, c)) { n++; counted = i; }
      }
    }
    for (let i = startIdx; i <= endIdx; i++) {
      if (counted != null && i > counted) break;
      const dt = new Date(i * DAY), c = { y: dt.getUTCFullYear(), mo: dt.getUTCMonth() + 1, d: dt.getUTCDate(), idx: i };
      if (!matchesRule(r, L, c)) continue;
      const start = localToUtc(c.y, c.mo, c.d, L.h, L.mi, L.s, e.tz === "UTC" ? "UTC" : e.tz);
      if (start > until || skip.has(start) || start < from || start > to) continue;
      push(e, start);
    }
  }
  return out.sort((a, b) => a.start - b.start);
}
