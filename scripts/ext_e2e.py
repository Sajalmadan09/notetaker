"""E2E: load the extension in Chromium headless-ish Chromium, record a tab playing a known meeting,
check live previews + final transcript + calendar list. Needs the app on :8010 with >=1 history recording.
uv run --with playwright python scripts/ext_e2e.py"""
import json, os, sys, tempfile, time, urllib.request
from playwright.sync_api import sync_playwright

EXT = os.path.abspath("extension"); SERVER = "http://127.0.0.1:8010"
get = lambda p: json.load(urllib.request.urlopen(SERVER + p))
hist = get("/api/history"); assert hist, "need a recording in history for the test audio"
rid = next(h["id"] for h in hist if h.get("source") != "dictation")
before = {h["id"] for h in hist}

# calendar fixture served by the app's static dir (removed at the end)
ics_path = "notetaker/static/_test.ics"
soon = time.gmtime(time.time() + 120); later = time.gmtime(time.time() + 7200)
f = lambda t: time.strftime("%Y%m%dT%H%M%SZ", t)
open(ics_path, "w").write("\r\n".join(["BEGIN:VCALENDAR",
  "BEGIN:VEVENT", "UID:t1", "SUMMARY:Test standup", f"DTSTART:{f(soon)}", f"DTEND:{f(later)}",
  "X-GOOGLE-CONFERENCE:https://meet.google.com/abc-defg-hij", "END:VEVENT", "END:VCALENDAR", ""]))

def launch(p, ext_id=None):
    args = [f"--disable-extensions-except={EXT}", f"--load-extension={EXT}",
            "--autoplay-policy=no-user-gesture-required"]
    if ext_id: args.append(f"--allowlisted-extension-id={ext_id}")  # lets tabCapture run without a toolbar click
    return p.chromium.launch_persistent_context(tempfile.mkdtemp(), headless=False, args=args,
        executable_path=os.environ.get("CHROMIUM") or None)

try:
    with sync_playwright() as p:
        c = launch(p)
        sw = c.service_workers[0] if c.service_workers else c.wait_for_event("serviceworker")
        ext_id = sw.url.split("/")[2]; c.close()
        c = launch(p, ext_id)
        sw = c.service_workers[0] if c.service_workers else c.wait_for_event("serviceworker")
        print("extension", ext_id)
        page = c.new_page(); page.goto(SERVER + "/dashboard.html")
        page.evaluate(f"(async()=>{{window.a=new Audio('/api/history/{rid}/audio');await a.play();}})()")
        ui = c.new_page(); ui.goto(f"chrome-extension://{ext_id}/popup.html")
        send = lambda m: ui.evaluate("m => chrome.runtime.sendMessage(m)", m)
        save = send({"type": "save-settings", "settings": {"server": SERVER, "lang": "hi", "mic": True, "icsUrl": SERVER + "/_test.ics"}})
        up = send({"type": "upcoming", "force": True}); print("upcoming:", [(o["summary"], bool(o["meetUrl"])) for o in up["items"]], up["error"])
        assert up["items"] and up["items"][0]["meetUrl"], "calendar parse failed"
        tab_id = ui.evaluate("async () => (await chrome.tabs.query({url: 'http://127.0.0.1:8010/dashboard.html'}))[0].id")
        r = send({"type": "start", "tabId": tab_id, "title": "e2e"}); print("start:", r); assert r["ok"], r
        for i in range(8):
            time.sleep(5)
            st = send({"type": "status"})["state"]
            if st.get("preview"): break
        print("phase", st["phase"], "| preview:", (st.get("preview") or "")[:90]); assert st["phase"] == "recording"
        time.sleep(10); print("stop:", send({"type": "stop"}))
        for i in range(90):
            time.sleep(2); st = send({"type": "status"})["state"]
            if st["phase"] == "idle": break
        print("final state:", {k: st.get(k) for k in ("phase", "lastJob", "message")})
        assert st["phase"] == "idle" and st.get("lastJob") and not st.get("message"), st
        job = get("/api/jobs/" + st["lastJob"]); print("turns:", len(job["result"]), "| first:", job["result"][0]["text"][:70])
        assert job["result"], "empty transcript"
        new = [h for h in get("/api/history") if h["id"] not in before]; assert new, "not saved to Recordings"
        print("saved to Recordings:", new[0]["id"], "PASS"); c.close()
finally:
    os.path.exists(ics_path) and os.remove(ics_path)
