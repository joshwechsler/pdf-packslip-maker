"""Save a copy of a finished PDF into a Google Drive folder.

Google Drive for desktop shows Drive as an ordinary folder on the Mac
(~/Library/CloudStorage/GoogleDrive-<account>/My Drive), so a plain file copy is all it takes:
the Drive app uploads it. No sign-in, and it works offline (it syncs later)."""

from __future__ import annotations

import shutil
from pathlib import Path


def drive_roots(home: Path | None = None) -> list[Path]:
    """The "My Drive" folder of each signed-in Google Drive account (empty if Drive isn't installed)."""
    cloud = (home or Path.home()) / "Library" / "CloudStorage"
    if not cloud.is_dir():
        return []
    found = []
    for acct in sorted(cloud.glob("GoogleDrive-*")):
        my = acct / "My Drive"
        found.append(my if my.is_dir() else acct)
    return found


def save_copy(src: Path, folder: Path) -> Path:
    """Copy src into folder; never replaces a file there: adds " (2)", " (3)"… instead."""
    dest = folder / src.name
    n = 2
    while dest.exists():
        dest = folder / f"{src.stem} ({n}){src.suffix}"
        n += 1
    shutil.copy2(src, dest)
    return dest
