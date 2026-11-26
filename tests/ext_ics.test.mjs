import test from "node:test";
import assert from "node:assert/strict";
import { parseIcs, occurrences, localToUtc } from "../extension/ics.js";

const wrap = body => `BEGIN:VCALENDAR\r\n${body}\r\nEND:VCALENDAR\r\n`;
const ev = lines => `BEGIN:VEVENT\r\n${lines.join("\r\n")}\r\nEND:VEVENT`;
const iso = ms => new Date(ms).toISOString().slice(0, 16) + "Z";
const win = (a, b) => [Date.parse(a), Date.parse(b)];

test("single UTC event with Meet link in X-GOOGLE-CONFERENCE", () => {
  const ics = wrap(ev(["UID:a", "SUMMARY:Design review", "DTSTART:20261127T093000Z", "DTEND:20261127T100000Z",
    "X-GOOGLE-CONFERENCE:https://meet.google.com/abc-defg-hij"]));
  const o = occurrences(parseIcs(ics), ...win("2026-11-27T00:00:00Z", "2026-11-28T00:00:00Z"));
  assert.equal(o.length, 1);
  assert.equal(o[0].meetUrl, "https://meet.google.com/abc-defg-hij");
  assert.equal(iso(o[0].end - o[0].start + Date.parse("2026-11-27T00:00:00Z")), "2026-11-27T00:30Z");
});

test("TZID event: 10:00 Asia/Kolkata = 04:30Z", () => {
  const ics = wrap(ev(["UID:b", "SUMMARY:Stand up", "DTSTART;TZID=Asia/Kolkata:20261127T100000", "DTEND;TZID=Asia/Kolkata:20261127T103000"]));
  const o = occurrences(parseIcs(ics), ...win("2026-11-27T00:00:00Z", "2026-11-28T00:00:00Z"));
  assert.equal(iso(o[0].start), "2026-11-27T04:30Z");
});

test("weekly Mon/Wed in Kolkata, with EXDATE and a moved instance", () => {
  const ics = wrap([
    ev(["UID:w", "SUMMARY:Sync", "DTSTART;TZID=Asia/Kolkata:20261102T100000", "DTEND;TZID=Asia/Kolkata:20261102T103000",
      "RRULE:FREQ=WEEKLY;BYDAY=MO,WE", "EXDATE;TZID=Asia/Kolkata:20261111T100000",
      "X-GOOGLE-CONFERENCE:https://meet.google.com/aaa-bbbb-ccc"]),
    ev(["UID:w", "SUMMARY:Sync (moved)", "RECURRENCE-ID;TZID=Asia/Kolkata:20261116T100000",
      "DTSTART;TZID=Asia/Kolkata:20261116T150000", "DTEND;TZID=Asia/Kolkata:20261116T153000"]),
  ].join("\r\n"));
  const o = occurrences(parseIcs(ics), ...win("2026-11-09T00:00:00Z", "2026-11-19T00:00:00Z"));
  // Nov 9 Mon, (Nov 11 Wed excluded), Nov 16 Mon moved to 15:00, Nov 18 Wed
  assert.deepEqual(o.map(x => iso(x.start)), ["2026-11-09T04:30Z", "2026-11-16T09:30Z", "2026-11-18T04:30Z"]);
  assert.equal(o[0].meetUrl, "https://meet.google.com/aaa-bbbb-ccc");
});

test("daily in New_York follows DST (09:00 local)", () => {
  const ics = wrap(ev(["UID:d", "SUMMARY:Daily", "DTSTART;TZID=America/New_York:20261101T090000", "DTEND;TZID=America/New_York:20261101T093000", "RRULE:FREQ=DAILY"]));
  const ev_ = parseIcs(ics);
  assert.equal(iso(occurrences(ev_, ...win("2026-10-30T00:00:00Z", "2026-10-31T00:00:00Z"))[0]?.start ?? 0), "1970-01-01T00:00Z"); // before DTSTART: none
  assert.equal(iso(occurrences(ev_, ...win("2026-11-02T00:00:00Z", "2026-11-03T00:00:00Z"))[0].start), "2026-11-02T14:00Z"); // EST
  assert.equal(iso(occurrences(ev_, ...win("2027-03-15T00:00:00Z", "2027-03-16T00:00:00Z"))[0].start), "2027-03-15T13:00Z"); // EDT
});

test("COUNT, UNTIL, INTERVAL, monthly ordinal", () => {
  const cnt = parseIcs(wrap(ev(["UID:c", "SUMMARY:C", "DTSTART:20261123T100000Z", "DTEND:20261123T110000Z", "RRULE:FREQ=DAILY;COUNT=3"])));
  assert.equal(occurrences(cnt, ...win("2026-11-20T00:00:00Z", "2026-12-20T00:00:00Z")).length, 3);
  const unt = parseIcs(wrap(ev(["UID:u", "SUMMARY:U", "DTSTART:20261123T100000Z", "DTEND:20261123T110000Z", "RRULE:FREQ=DAILY;UNTIL=20261125T100000Z"])));
  assert.equal(occurrences(unt, ...win("2026-11-20T00:00:00Z", "2026-12-20T00:00:00Z")).length, 3);
  const biw = parseIcs(wrap(ev(["UID:i", "SUMMARY:I", "DTSTART:20261102T100000Z", "DTEND:20261102T110000Z", "RRULE:FREQ=WEEKLY;INTERVAL=2"])));
  assert.deepEqual(occurrences(biw, ...win("2026-11-01T00:00:00Z", "2026-12-01T00:00:00Z")).map(x => iso(x.start).slice(0, 10)), ["2026-11-02", "2026-11-16", "2026-11-30"]);
  const mon = parseIcs(wrap(ev(["UID:m", "SUMMARY:M", "DTSTART:20261103T100000Z", "DTEND:20261103T110000Z", "RRULE:FREQ=MONTHLY;BYDAY=1TU"])));
  assert.deepEqual(occurrences(mon, ...win("2026-11-01T00:00:00Z", "2027-01-31T00:00:00Z")).map(x => iso(x.start).slice(0, 10)), ["2026-11-03", "2026-12-01", "2027-01-05"]);
});

test("cancelled and all-day events are ignored; folded lines are joined", () => {
  const ics = wrap([
    ev(["UID:x", "SUMMARY:Gone", "STATUS:CANCELLED", "DTSTART:20261127T093000Z"]),
    ev(["UID:y", "SUMMARY:Holiday", "DTSTART;VALUE=DATE:20261127"]),
    ev(["UID:z", "SUMMARY:Long title that is", " folded", "DTSTART:20261127T093000Z"]),
  ].join("\r\n"));
  const o = occurrences(parseIcs(ics), ...win("2026-11-27T00:00:00Z", "2026-11-28T00:00:00Z"));
  assert.equal(o.length, 1);
  assert.equal(o[0].summary, "Long title that isfolded");
});

test("localToUtc across a DST gap does not throw", () => {
  assert.ok(Number.isFinite(localToUtc(2027, 3, 14, 2, 30, 0, "America/New_York")));
});
