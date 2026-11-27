"""Bridge from the server to the native window, set by __main__ when a window exists.
Lets the menu-bar helper (and Finder/Dock reopen) bring the hidden window back, or quit."""
from __future__ import annotations

from typing import Callable

show: Callable[[], None] | None = None
quit: Callable[[], None] | None = None
