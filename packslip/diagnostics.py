"""Freeze diagnostics: a breadcrumb log plus an automatic stack dump if the app hangs.

Everything is written to "diagnostics.txt" in the app's data folder (no customer data:
only which screen/action happened when). The "Show Diagnostics" button reveals it in Finder.
"""

from __future__ import annotations

import datetime as dt
import faulthandler
import sys
import threading

from . import __version__, storage

HANG_SECONDS = 10
MAX_BYTES = 1_000_000
_file = None
_lock = threading.Lock()


def path():
    return storage.data_dir() / "diagnostics.txt"


def _open():
    global _file
    if _file is None:
        p = path()
        try:
            if p.exists() and p.stat().st_size > MAX_BYTES:
                p.replace(p.with_name("diagnostics.old.txt"))
            _file = open(p, "a", encoding="utf-8", buffering=1)
        except OSError:
            return None
    return _file


def note(msg: str) -> None:
    """Append a timestamped breadcrumb (e.g. 'matching screen opened')."""
    f = _open()
    if f is None:
        return
    with _lock:
        try:
            f.write(f"{dt.datetime.now():%Y-%m-%d %H:%M:%S}  {msg}\n")
        except OSError:
            pass


def start_watchdog(root) -> None:
    """If the Tk main loop stops for HANG_SECONDS, dump every thread's stack to the file."""
    from . import updater
    f = _open()
    if f is None:
        return
    note(f"--- app started: v{__version__} {updater.describe_current()} on {sys.platform}")

    def heartbeat():
        try:
            faulthandler.dump_traceback_later(HANG_SECONDS, repeat=False, file=f, exit=False)
        except (OSError, ValueError, RuntimeError):
            return
        root.after(1000, heartbeat)

    heartbeat()


def stop_watchdog() -> None:
    try:
        faulthandler.cancel_dump_traceback_later()
    except Exception:  # noqa: BLE001
        pass
