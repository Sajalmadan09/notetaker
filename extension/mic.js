navigator.mediaDevices.getUserMedia({ audio: true }).then(s => {
  s.getTracks().forEach(t => t.stop());
  document.getElementById("m").textContent = "Microphone allowed. You can close this tab.";
  chrome.storage.local.set({ micGranted: true });
  setTimeout(() => window.close(), 1200);
}).catch(e => { document.getElementById("m").textContent = "Blocked (" + e.name + "). Allow it in Chrome's site settings for this extension."; });
