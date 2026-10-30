"""Work out the app version, MAJOR.FEATURES.FIXES (e.g. 2.4.1), from the saved changes' labels.

- MAJOR is the number in MAJOR_VERSION (repo root). Change it by hand only for a big milestone.
- Counting starts after the change that last edited MAJOR_VERSION (that change itself is X.0.0).
- "feat: ..." adds 1 to FEATURES and resets FIXES to 0.
- "fix: ..." and "change: ..." add 1 to FIXES.
- Anything else (refactor:, test:, merges) leaves the number alone.

Run by CI before building; prints the version.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_LABEL = re.compile(r"^(feat|fix|change)(\([^)]*\))?!?:", re.I)


def count(subjects: list[str]) -> tuple[int, int]:
    """(features, fixes) for change subjects in order, oldest first."""
    features = fixes = 0
    for subject in subjects:
        m = _LABEL.match(subject.strip())
        if not m:
            continue
        if m.group(1).lower() == "feat":
            features, fixes = features + 1, 0
        else:
            fixes += 1
    return features, fixes


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout


def version_from_repo(repo: Path = ROOT) -> str:
    repo = Path(repo)
    major = int((repo / "MAJOR_VERSION").read_text().strip())
    base = _git(repo, "log", "-1", "--format=%H", "--", "MAJOR_VERSION").strip()
    subjects = _git(repo, "log", "--reverse", "--format=%s", f"{base}..HEAD").splitlines() if base else []
    features, fixes = count(subjects)
    return f"{major}.{features}.{fixes}"


if __name__ == "__main__":
    print(version_from_repo(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT))
