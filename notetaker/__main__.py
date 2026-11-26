"""Entry point: `uv run python -m notetaker` and the frozen macOS app binary."""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

import uvicorn


def _log_startup_error() -> None:
    try:
        import notetaker.server  # noqa: F401
    except Exception:
        import traceback

        from notetaker import paths
        paths.DATA.mkdir(parents=True, exist_ok=True)
        (paths.DATA / "startup-error.log").write_text(traceback.format_exc())


def main() -> None:
    _log_startup_error()
    port = int(os.environ.get("NOTETAKER_PORT", "8010"))
    server = uvicorn.Server(uvicorn.Config(
        "notetaker.server:app", host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(80):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1)
            break
        except Exception:
            time.sleep(0.25)
    url = f"http://127.0.0.1:{port}/"
    helper = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "NotetakerHelper"
    proc = None
    if helper.exists() and not os.environ.get("NOTETAKER_NO_HELPER"):
        proc = subprocess.Popen([str(helper)])
    try:
        if os.environ.get("NOTETAKER_BROWSER"):
            raise ImportError("browser mode requested")
        import webview
        webview.settings["ALLOW_DOWNLOADS"] = True  # dashboard exports (md/txt/pdf)
        webview.create_window("Notetaker", url, width=1100, height=820, min_size=(720, 560))
        webview.start()  # blocks until the window closes; closing the window quits the app
    except Exception:
        if not os.environ.get("NOTETAKER_BROWSER"):  # browser mode is a request, not an error
            import traceback
            from notetaker import paths
            paths.DATA.mkdir(parents=True, exist_ok=True)
            (paths.DATA / "window-error.log").write_text(traceback.format_exc())
        webbrowser.open(url)  # fallback: no native window available
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass
    server.should_exit = True
    if proc:
        proc.terminate()


if __name__ == "__main__":
    main()
