"""Where Midgar keeps things. Everything is local to this user account."""

from __future__ import annotations

import os
from pathlib import Path


def data_dir() -> Path:
    """``$MIDGAR_DATA_DIR`` if set, else ``$XDG_DATA_HOME/midgar`` (~/.local/share/midgar)."""
    override = os.environ.get("MIDGAR_DATA_DIR")
    if override:
        return Path(override).expanduser()
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return Path(base) / "midgar"


def library_path() -> Path:
    return data_dir() / "library.db"


def snapshot_dir() -> Path:
    return data_dir() / "snapshots"


def safety_dir() -> Path:
    return data_dir() / "safety"
