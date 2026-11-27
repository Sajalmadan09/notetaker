"""Bridge from the server to the native app process, set by __main__ when it runs the app.
Lets the menu-bar helper (and Finder/Dock reopen) bring the hidden window back or quit, and lets
the server send commands to the native helper (meeting recording)."""
from __future__ import annotations

from typing import Callable

show: Callable[[], None] | None = None
quit: Callable[[], None] | None = None
helper_send: Callable[[str], bool] | None = None  # one-line command to the helper's stdin
