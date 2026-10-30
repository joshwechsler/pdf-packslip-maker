"""Automatic version numbers: MAJOR.FEATURES.FIXES from the labels on saved changes."""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
from version import count, version_from_repo  # noqa: E402


def test_count_features_and_fixes():
    subjects = ["feat: bag labels", "fix: button cut off", "change: pickup bags hold 6",
                "refactor: tidy", "test: more tests", "Merge branch x", "feat(labels): edit button",
                "fix: another"]
    # feat -> 1.0 ; fix -> 1.1 ; change -> 1.2 ; refactor/test/merge -> no change ; feat -> 2.0 ; fix -> 2.1
    assert count(subjects) == (2, 1)
    assert count([]) == (0, 0)


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _commit(repo, msg, file="x.txt", text=None):
    p = repo / file
    p.write_text(text if text is not None else (p.read_text() if p.exists() else "") + msg + "\n")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", msg)


def test_version_from_git_history(tmp_path):
    _git(tmp_path, "init", "-q")
    _commit(tmp_path, "feat: before the fresh start (not counted)")
    _commit(tmp_path, "change: start versions at 2", "MAJOR_VERSION", "2\n")
    assert version_from_repo(tmp_path) == "2.0.0"
    _commit(tmp_path, "fix: a fix")
    assert version_from_repo(tmp_path) == "2.0.1"
    _commit(tmp_path, "feat: a feature")
    assert version_from_repo(tmp_path) == "2.1.0"
    _commit(tmp_path, "refactor: tidy")
    assert version_from_repo(tmp_path) == "2.1.0"
    _commit(tmp_path, "fix: x\n\nbody mentioning feat: should not count")
    assert version_from_repo(tmp_path) == "2.1.1"
    _commit(tmp_path, "change: big milestone", "MAJOR_VERSION", "3\n")
    assert version_from_repo(tmp_path) == "3.0.0"
