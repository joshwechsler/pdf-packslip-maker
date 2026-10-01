# Overrides pyinstaller-hooks-contrib's hook, which only collects the tkdnd library
# for the build machine's CPU. A universal2 app must carry both: tkinterdnd2 picks
# osx-arm64 or osx-x64 at runtime from platform.machine().
# Collected as data (not binaries) because each dylib is single-arch, and
# PyInstaller rejects thin binaries in a universal2 build.
from pathlib import Path

from PyInstaller.utils.hooks import get_package_paths

_, pkg_dir = get_package_paths("tkinterdnd2")
datas = []
for sub in ("osx-arm64", "osx-x64"):
    src = Path(pkg_dir) / "tkdnd" / sub
    for f in src.iterdir():
        if f.suffix in (".dylib", ".tcl"):
            datas.append((str(f), f"tkinterdnd2/tkdnd/{sub}"))
