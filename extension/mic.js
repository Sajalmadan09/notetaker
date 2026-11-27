// Opened by "Record this tab" when the extension's mic permission isn't granted yet (or from
// Settings → allow mic). Chrome remembers the grant for the extension, so this is a one-time step.
const q = new URLSearchParams(location.search), tabId = +q.get("tab") || null, title = q.get("title") || "";
const $ = id => document.getElementById(id);
const startAndClose = async () => {
  if (!tabId) return setTimeout(() => window.close(), 1200);
  $("m").textContent = "Starting the recording…";
  const r = await chrome.runtime.sendMessage({ type: "start", tabId, title });
  if (r?.ok) { await chrome.tabs.update(tabId, { active: true }).catch(() => {}); window.close(); }
  else $("m").textContent = (r?.error || "Couldn't start.") + " Click the Kiroku icon on the Meet tab → Record this tab.";
};
navigator.mediaDevices.getUserMedia({ audio: true }).then(async s => {
  s.getTracks().forEach(t => t.stop());
  await chrome.storage.local.set({ micGranted: true });
  $("m").textContent = "Microphone allowed. Kiroku will remember this.";
  startAndClose();
}).catch(e => {
  $("m").textContent = `Microphone blocked (${e.name}). To fix: chrome://settings/content/microphone → allow Kiroku.`;
  if (tabId) { $("anyway").hidden = false; $("anyway").onclick = startAndClose; }
});
