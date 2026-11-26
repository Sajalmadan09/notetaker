"""Path resolution for dev checkouts and frozen (PyInstaller) bundles."""
from __future__ import annotations

import os
import sys
from pathlib import Path

FROZEN = bool(getattr(sys, "frozen", False))
PROJECT = Path(__file__).resolve().parent.parent
BUNDLE = Path(getattr(sys, "_MEIPASS", PROJECT))

if os.environ.get("NOTETAKER_DATA"):
    DATA = Path(os.environ["NOTETAKER_DATA"])
elif FROZEN:
    DATA = Path.home() / "Library" / "Application Support" / "Notetaker"
else:
    DATA = PROJECT / "data"

MODELS = BUNDLE / "models" if FROZEN else PROJECT / "models"
