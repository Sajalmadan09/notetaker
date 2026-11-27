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


def _keep_running_when_closed(window) -> None:
    """Closing the window (red button / ⌘W) only hides it: recordings, downloads and dictation
    keep running, reachable from the menu-bar 🎙 or by reopening Kiroku. ⌘Q and Quit really quit."""
    import AppKit
    import objc
    from webview.platforms.cocoa import BrowserView

    from notetaker import appshell
    quitting = False

    def is_quit_request() -> bool:
        ev = AppKit.NSApp.currentEvent()  # closing handlers run on the main thread, mid-event
        if ev is None:
            return True  # logout/shutdown/AppleEvent: let it quit
        if ev.type() == AppKit.NSEventTypeKeyDown:
            return (ev.charactersIgnoringModifiers() or "").lower() == "q"  # ⌘Q quits, ⌘W hides
        w = ev.window()  # a click on our own window's close button hides; a menu click (Quit) quits
        return not (w is not None and w.isKindOfClass_(BrowserView.WindowHost))

    def on_closing():
        if quitting or is_quit_request():
            return True
        window.hide()
        return False  # cancel the close

    def really_quit():
        nonlocal quitting
        quitting = True
        window.destroy()

    window.events.closing += on_closing
    appshell.show, appshell.quit = window.show, really_quit

    # Dock icon click / opening Kiroku again from Finder while it's hidden: show the window.
    def reopen(self, app, has_visible):
        if not has_visible:
            window.show()
        return True
    objc.classAddMethods(BrowserView.AppDelegate, [objc.selector(
        reopen, selector=b"applicationShouldHandleReopen:hasVisibleWindows:", signature=b"Z@:@Z")])


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
        proc = subprocess.Popen([str(helper)], stdin=subprocess.PIPE, text=True)
        from notetaker import appshell

        def send(line: str) -> bool:  # meeting-start / meeting-stop for the native recorder
            try:
                proc.stdin.write(line + "\n")
                proc.stdin.flush()
                return proc.poll() is None
            except (OSError, ValueError):
                return False
        appshell.helper_send = send
    try:
        if os.environ.get("NOTETAKER_BROWSER"):
            raise ImportError("browser mode requested")
        import webview
        webview.settings["ALLOW_DOWNLOADS"] = True  # dashboard exports (md/txt/pdf)
        window = webview.create_window("Kiroku", url, width=1100, height=820, min_size=(720, 560))
        _keep_running_when_closed(window)
        webview.start()  # blocks until the app quits (⌘Q, or Quit Kiroku in the menu bar)
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
