"""Filesystem path resolution.

Handles two scenarios:
  - Run from source (dev): paths are relative to the project root
  - Run from a PyInstaller bundle: paths resolve via sys._MEIPASS for read-only
    resources, and platform-standard user-data dir for the user DB.

We don't pull in `platformdirs` to keep the dependency surface small for AV-friendly
PyInstaller builds. Instead, we hand-resolve the standard directories per-OS.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "MoonScan"


def _is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def static_db_path() -> Path:
    """Path to the read-only eve_static.db shipped with the app."""
    if _is_frozen():
        # PyInstaller --onefile extracts to sys._MEIPASS
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        return base / "data" / "eve_static.db"
    # Dev: relative to project root (this file is moonscan/paths.py)
    return Path(__file__).resolve().parent.parent / "data" / "eve_static.db"


def user_data_dir() -> Path:
    """OS-appropriate per-user directory for user.db, settings, etc.

    Override with MOONSCAN_DATA_DIR for portable mode (next to the .exe).
    """
    override = os.environ.get("MOONSCAN_DATA_DIR")
    if override:
        return Path(override)

    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / APP_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    # Linux + everything else: XDG_DATA_HOME
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / APP_NAME.lower()


def user_db_path() -> Path:
    d = user_data_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d / "user.db"
