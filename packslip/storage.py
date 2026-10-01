"""Where the app keeps its local files (mapping, templates, logos, settings).

The spec asks for config "alongside the app", but a macOS .app bundle is
read-only once installed (and may be run from a randomized, read-only path by
Gatekeeper), so files live in the standard per-user folder instead:

    ~/Library/Application Support/Pack Slip Maker/
        mapping.json
        settings.json
        templates/<name>.json
        assets/<logo files>

Set PACKSLIP_DATA_DIR to override (used by tests).
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

from . import APP_NAME


def data_dir() -> Path:
    override = os.environ.get("PACKSLIP_DATA_DIR")
    if override:
        base = Path(override)
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / APP_NAME
    else:
        base = Path.home() / ".packslip-maker"
    base.mkdir(parents=True, exist_ok=True)
    return base


def templates_dir() -> Path:
    d = data_dir() / "templates"
    d.mkdir(parents=True, exist_ok=True)
    return d


def assets_dir() -> Path:
    d = data_dir() / "assets"
    d.mkdir(parents=True, exist_ok=True)
    return d


def read_json(path: Path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def write_json(path: Path, data) -> None:
    """Write atomically so a crash mid-save never leaves a corrupt file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def load_settings() -> dict:
    return read_json(data_dir() / "settings.json", {}) or {}


def save_settings(settings: dict) -> None:
    write_json(data_dir() / "settings.json", settings)
