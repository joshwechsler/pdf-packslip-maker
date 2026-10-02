"""Self-update from GitHub Releases (macOS app only).

Each CI build publishes a release tagged ``build-<N>`` with the app zip attached, and
stamps N into ``packslip/_build.py``. On launch the app asks GitHub for the latest
release; if its build number is higher, it can download the zip, check it, and swap
itself in place:

  1. download with /usr/bin/curl (uses the Mac's own certificates; files it saves
     don't get the "downloaded from the internet" flag, so no Gatekeeper prompt)
  2. check the SHA-256 GitHub reports for the file, unzip with ditto, and confirm the
     new app's code signature is intact
  3. a small shell script waits for this app to quit, moves the old app aside, moves
     the new one in (restoring the old one if that fails) and reopens it

Only the version number is requested from GitHub; no spreadsheet or customer data
is ever sent. Offline, the check silently does nothing.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from . import APP_NAME

REPO = "joshwechsler/pdf-packslip-maker"
ASSET_NAME = "Packs-Be-Slippin-mac.zip"
LATEST_URL = f"https://api.github.com/repos/{REPO}/releases/latest"

try:
    from ._build import BUILD  # written by CI; absent when running from source
except ImportError:  # pragma: no cover
    BUILD = 0


class UpdateError(Exception):
    """A problem updating, worded for a non-technical reader."""


@dataclass
class UpdateInfo:
    build: int
    url: str
    size: int
    sha256: str  # "" if GitHub didn't report one
    notes: str = ""


def parse_release(data: dict, current_build: int = BUILD) -> UpdateInfo | None:
    """UpdateInfo if `data` (GitHub's latest-release JSON) is newer than current_build."""
    m = re.fullmatch(r"build-(\d+)", str(data.get("tag_name", "")))
    if not m or data.get("draft") or data.get("prerelease"):
        return None
    build = int(m.group(1))
    if build <= current_build:
        return None
    for asset in data.get("assets") or []:
        if asset.get("name") == ASSET_NAME and asset.get("browser_download_url"):
            digest = str(asset.get("digest") or "")
            return UpdateInfo(build=build, url=asset["browser_download_url"], size=int(asset.get("size") or 0),
                              sha256=digest[7:] if digest.startswith("sha256:") else "",
                              notes=(data.get("body") or "").strip())
    return None


def running_app_bundle(executable: str | None = None) -> Path | None:
    """The .app bundle this process runs from, or None when not running as a Mac app."""
    exe = Path(executable or sys.executable).resolve()
    if len(exe.parents) < 3:
        return None
    bundle = exe.parents[2]
    if bundle.suffix == ".app" and exe.parent.name == "MacOS" and exe.parents[1].name == "Contents":
        return bundle
    return None


def can_self_update() -> bool:
    return sys.platform == "darwin" and BUILD > 0 and running_app_bundle() is not None


def _curl(*args: str, timeout: int) -> bytes:
    cmd = ["/usr/bin/curl", "-fsSL", "--max-time", str(timeout), "-H", f"User-Agent: {APP_NAME} updater", *args]
    try:
        return subprocess.run(cmd, check=True, capture_output=True, timeout=timeout + 5).stdout
    except (OSError, subprocess.SubprocessError) as e:
        raise UpdateError("Couldn't reach the update server. Check the internet connection and try again.") from e


def check_for_update(timeout: int = 8) -> UpdateInfo | None:
    """Ask GitHub for the latest release. Returns None if up to date, offline, or not applicable."""
    if not can_self_update():
        return None
    try:
        data = json.loads(_curl("-H", "Accept: application/vnd.github+json", LATEST_URL, timeout=timeout))
    except (UpdateError, ValueError):
        return None
    return parse_release(data)


def install_problem(bundle: Path) -> str | None:
    """Why the running app can't replace itself, in plain words (None if it can)."""
    if "AppTranslocation" in str(bundle):
        return ("macOS is running this copy of the app from a temporary location, so it can't update "
                "itself. Drag Packs Be Slippin' into your Applications folder, open it from there, and "
                "try again.")
    if not os.access(bundle.parent, os.W_OK):
        return (f"This Mac account doesn't have permission to change apps in “{bundle.parent}”. "
                "Ask the Mac's administrator to install the update.")
    return None


def download(info: UpdateInfo, dest_dir: Path, timeout: int = 600) -> Path:
    zip_path = dest_dir / ASSET_NAME
    _curl("-o", str(zip_path), info.url, timeout=timeout)
    if info.size and zip_path.stat().st_size != info.size:
        raise UpdateError("The update didn't download completely. Please try again.")
    if info.sha256:
        h = hashlib.sha256()
        with open(zip_path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        if h.hexdigest() != info.sha256.lower():
            raise UpdateError("The downloaded update didn't pass its safety check, so it wasn't installed.")
    return zip_path


def unpack(zip_path: Path, dest_dir: Path) -> Path:
    """Unzip with ditto (keeps the app bundle intact) and return the new .app, checked."""
    out = dest_dir / "unzipped"
    try:
        subprocess.run(["/usr/bin/ditto", "-x", "-k", str(zip_path), str(out)], check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError) as e:
        raise UpdateError("The update file couldn't be opened. Please try again later.") from e
    apps = sorted(out.rglob(f"{APP_NAME}.app"))
    if not apps:
        raise UpdateError("The update file doesn't contain the app. Please try again later.")
    new_app = apps[0]
    subprocess.run(["/usr/bin/xattr", "-dr", "com.apple.quarantine", str(new_app)], capture_output=True)
    check = subprocess.run(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(new_app)],
                           capture_output=True)
    if check.returncode != 0:
        raise UpdateError("The downloaded app failed its integrity check, so it wasn't installed.")
    return new_app


SWAP_SCRIPT = r'''#!/bin/sh
# Replace the app once the running copy has quit, then reopen it.
PID=$1; OLD=$2; NEW=$3; WORK=$4; OPEN_CMD=${OPEN_CMD:-/usr/bin/open}
i=0
while kill -0 "$PID" 2>/dev/null; do
  i=$((i + 1)); [ "$i" -gt 300 ] && exit 1   # give up after ~60s
  sleep 0.2
done
BACKUP="$OLD.previous-version"
rm -rf "$BACKUP"
if mv "$OLD" "$BACKUP"; then
  if mv "$NEW" "$OLD"; then
    rm -rf "$BACKUP"
  else
    mv "$BACKUP" "$OLD"          # put the old version back
  fi
fi
rm -rf "$WORK"
rm -f "$0"
$OPEN_CMD "$OLD"
'''


def start_swap(new_app: Path, bundle: Path, work_dir: Path, pid: int | None = None) -> subprocess.Popen:
    """Launch the swap script in the background. The caller must quit right after."""
    script = work_dir.parent / f".{work_dir.name}-swap.sh"  # outside work_dir, which the script deletes
    script.write_text(SWAP_SCRIPT)
    return subprocess.Popen(["/bin/sh", str(script), str(pid or os.getpid()), str(bundle), str(new_app), str(work_dir)],
                     start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def prepare_update(info: UpdateInfo) -> tuple[Path, Path, Path]:
    """Download and check an update. Returns (new_app, running_bundle, work_dir)."""
    bundle = running_app_bundle()
    if bundle is None:
        raise UpdateError("Updates can only be installed in the Mac app.")
    problem = install_problem(bundle)
    if problem:
        raise UpdateError(problem)
    # Work next to the installed app so the final move is on the same disk (instant, atomic).
    try:
        work = Path(tempfile.mkdtemp(prefix=".packs-update-", dir=bundle.parent))
    except OSError:
        work = Path(tempfile.mkdtemp(prefix="packs-update-"))
    try:
        new_app = unpack(download(info, work), work)
    except BaseException:
        shutil.rmtree(work, ignore_errors=True)
        raise
    return new_app, bundle, work


def describe_current() -> str:
    return f"build {BUILD}" if BUILD else "development copy"
