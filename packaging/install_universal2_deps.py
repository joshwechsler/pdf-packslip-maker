"""Install requirements.txt into the running Python as universal2 (arm64 + x86_64) wheels.

PyInstaller can only build a universal2 app if every compiled extension is
"fat". Some packages (e.g. Pillow) publish separate arm64 and x86_64 wheels
only, so we download both and fuse them with delocate-merge.

Must run on macOS, with a universal2 Python (the python.org installer).
Usage: python packaging/install_universal2_deps.py requirements.txt
"""

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PLATFORMS = {"arm64": "macosx_11_0_arm64", "x86_64": "macosx_11_0_x86_64"}


def run(*cmd):
    print("+", " ".join(map(str, cmd)), flush=True)
    subprocess.check_call([str(c) for c in cmd])


def project(wheel: Path) -> str:
    return re.sub(r"[-_.]+", "_", wheel.name.split("-")[0]).lower()


def main(req: str) -> None:
    pyver = f"{sys.version_info.major}{sys.version_info.minor}"
    work = Path(tempfile.mkdtemp(prefix="u2wheels-"))
    for arch, plat in PLATFORMS.items():
        run(sys.executable, "-m", "pip", "download", "-r", req, "--only-binary=:all:",
            "--platform", plat, "--python-version", pyver, "--implementation", "cp",
            "-d", work / arch)
    arm = {project(p): p for p in (work / "arm64").glob("*.whl")}
    x86 = {project(p): p for p in (work / "x86_64").glob("*.whl")}
    if arm.keys() != x86.keys():
        sys.exit(f"Different dependency sets per arch: {sorted(arm.keys() ^ x86.keys())}")
    final = work / "final"
    final.mkdir()
    for name in sorted(arm):
        a, x = arm[name], x86[name]
        if a.name == x.name:  # pure-Python or already universal2
            shutil.copy(a, final)
        else:
            run("delocate-merge", a, x, "-w", final)
    wheels = sorted(final.glob("*.whl"))
    print("Installing:", *[w.name for w in wheels], sep="\n  ")
    run(sys.executable, "-m", "pip", "install", "--no-deps", "--force-reinstall", *wheels)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "requirements.txt")
