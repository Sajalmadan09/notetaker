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
    webbrowser.open(f"http://127.0.0.1:{port}/")
    helper = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "NotetakerHelper"
    if helper.exists() and not os.environ.get("NOTETAKER_NO_HELPER"):
        subprocess.Popen([str(helper)])
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        server.should_exit = True


if __name__ == "__main__":
    main()
