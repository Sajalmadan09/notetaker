// Runs inside Google Meet. Detects joining and leaving a call, shows the "recording starts in…"
// bar, and tells the background script. Recording itself is done by the Kiroku app (or the
// extension's tab capture as a fallback); this script never touches audio.
(() => {
  const ROOM = /^\/([a-z]{3}-[a-z]{4}-[a-z]{3})(?:$|[/?])/i;
  // Meet's "Leave call" button exists only while you're in a call (English aria-label + stable jsname).
  const inCall = () => !!document.querySelector('[aria-label*="Leave call" i], [data-tooltip*="Leave call" i], button[jsname="CQylAd"]');
  const ended = () => /you left the meeting|the meeting has ended|you've been removed|you have been removed|call ended/i
    .test(document.body?.innerText?.slice(0, 4000) || "");
  let joinedCode = null, outSince = 0, bar = null, timer = null;
  const send = m => chrome.runtime.sendMessage(m).catch(() => ({}));

  function removeBar() { clearInterval(timer); bar?.remove(); bar = null; }

  function showBar(seconds) {
    removeBar();
    bar = document.createElement("div");
    const root = bar.attachShadow({ mode: "closed" });
    root.innerHTML = `
      <style>
        .b { position: fixed; top: 16px; left: 50%; transform: translateX(-50%); z-index: 2147483647;
             font: 600 14px -apple-system, "Avenir Next", system-ui, sans-serif; color: #1a1714;
             background: #fbf7ef; border: 2px solid #1a1714; border-radius: 6px; box-shadow: 4px 4px 0 #1a1714;
             padding: 10px 12px 12px; min-width: 330px; }
        .row { display: flex; align-items: center; gap: 10px; }
        .seal { width: 24px; height: 24px; background: #d23a2a; color: #fff8ec; border-radius: 4px; display: grid;
                place-items: center; font: 600 14px "Hiragino Mincho ProN", serif; transform: rotate(-4deg); }
        .t { flex: 1; }
        button { font: inherit; font-size: 13px; border: 2px solid #1a1714; border-radius: 4px; padding: 4px 10px;
                 background: #fbf7ef; cursor: pointer; box-shadow: 2px 2px 0 #1a1714; }
        button.go { background: #1a1714; color: #f3ede2; }
        .bar { margin-top: 9px; height: 8px; border: 2px solid #1a1714; border-radius: 3px; overflow: hidden; }
        .bar i { display: block; height: 100%; width: 0; background: #d23a2a; transition: width 1s linear; }
        .note { font-weight: 500; font-size: 12px; color: #4f4840; margin-top: 6px; }
      </style>
      <div class="b" role="status">
        <div class="row"><span class="seal">記</span><span class="t">Kiroku will record this meeting in <b id="n">${seconds}</b> s</span>
          <button id="cancel">Cancel</button><button class="go" id="now">Record now</button></div>
        <div class="bar"><i id="p"></i></div>
        <div class="note">Transcribed on your Mac. Let others know they're being recorded.</div>
      </div>`;
    document.documentElement.appendChild(bar);
    const $ = id => root.getElementById(id);
    let left = seconds;
    requestAnimationFrame(() => { $("p").style.transition = `width ${seconds}s linear`; $("p").style.width = "100%"; });
    const go = () => { removeBar(); send({ type: "auto-start", title: document.title }); };
    $("now").onclick = go;
    $("cancel").onclick = () => { removeBar(); send({ type: "auto-cancel" }); };
    timer = setInterval(() => { left -= 1; if (left <= 0) go(); else $("n").textContent = left; }, 1000);
  }

  function showHint(text) {
    removeBar();
    bar = document.createElement("div");
    const root = bar.attachShadow({ mode: "closed" });
    root.innerHTML = `<style>.b{position:fixed;top:16px;left:50%;transform:translateX(-50%);z-index:2147483647;
      font:600 14px -apple-system,system-ui,sans-serif;color:#1a1714;background:#fbf7ef;border:2px solid #d23a2a;
      border-radius:6px;box-shadow:4px 4px 0 #d23a2a;padding:10px 14px}</style><div class="b" role="status">${text}</div>`;
    document.documentElement.appendChild(bar);
    setTimeout(removeBar, 12000);
  }

  chrome.runtime.onMessage.addListener(msg => {
    if (msg.type === "meet-hint") showHint(msg.text);
  });

  setInterval(async () => {
    const code = (location.pathname.match(ROOM) || [])[1];
    const here = code && inCall() && !ended();
    if (here && joinedCode !== code) {  // just joined
      joinedCode = code; outSince = 0;
      const r = await send({ type: "meet-joined", code });
      if (r?.countdown) showBar(r.countdown);
    } else if (joinedCode && !here) {  // left, ended, removed, or navigated away
      outSince ||= Date.now();
      if (ended() || !code || Date.now() - outSince > 4000) {
        removeBar();
        send({ type: "meet-ended", code: joinedCode });
        joinedCode = null; outSince = 0;
      }
    } else outSince = 0;
  }, 1000);

  addEventListener("pagehide", () => { if (joinedCode) send({ type: "meet-ended", code: joinedCode }); });
})();
