import os
import subprocess
import time
from pathlib import Path

from packslip import updater


def _release(tag="build-12", name=updater.ASSET_NAME, **extra):
    data = {"tag_name": tag, "draft": False, "prerelease": False, "body": "notes",
            "assets": [{"name": name, "browser_download_url": "https://example.com/x.zip", "size": 123,
                        "digest": "sha256:" + "ab" * 32}]}
    data.update(extra)
    return data


def test_parse_release_newer_older_and_odd_cases():
    info = updater.parse_release(_release(), current_build=11)
    assert (info.build, info.size, info.sha256) == (12, 123, "ab" * 32)
    assert updater.parse_release(_release(), current_build=12) is None          # same build
    assert updater.parse_release(_release(tag="v1.0.0"), current_build=1) is None
    assert updater.parse_release(_release(name="other.zip"), current_build=1) is None
    assert updater.parse_release(_release(prerelease=True), current_build=1) is None


def test_running_app_bundle_detection():
    exe = "/Applications/Packs Be Slippin'.app/Contents/MacOS/Packs Be Slippin'"
    assert updater.running_app_bundle(exe) == Path("/Applications/Packs Be Slippin'.app")
    assert updater.running_app_bundle("/usr/bin/python3") is None


def test_translocated_app_explains_what_to_do():
    msg = updater.install_problem(Path("/private/var/folders/x/AppTranslocation/ABC/d/Packs Be Slippin'.app"))
    assert "Applications folder" in msg


def test_swap_script_replaces_app_after_process_quits(tmp_path):
    old = tmp_path / "App.app"
    (old / "Contents").mkdir(parents=True)
    (old / "Contents" / "v").write_text("old")
    work = tmp_path / ".work"
    new = work / "unzipped" / "App.app"
    (new / "Contents").mkdir(parents=True)
    (new / "Contents" / "v").write_text("new")
    sleeper = subprocess.Popen(["sleep", "1"])
    os.environ["OPEN_CMD"] = "true"
    try:
        proc = updater.start_swap(new, old, work, pid=sleeper.pid)
        time.sleep(0.3)
        assert (old / "Contents" / "v").read_text() == "old"  # still waiting for the app to quit
        sleeper.wait()
        proc.wait(timeout=20)
    finally:
        os.environ.pop("OPEN_CMD", None)
    assert (old / "Contents" / "v").read_text() == "new"
    assert not work.exists() and not list(tmp_path.glob("*.previous-version")) and not list(tmp_path.glob("*.sh"))


def test_swap_script_restores_old_app_if_new_one_is_missing(tmp_path):
    old = tmp_path / "App.app"
    (old / "Contents").mkdir(parents=True)
    (old / "Contents" / "v").write_text("old")
    work = tmp_path / ".work"
    work.mkdir()
    os.environ["OPEN_CMD"] = "true"
    try:
        updater.start_swap(work / "missing.app", old, work, pid=999999).wait(timeout=20)
    finally:
        os.environ.pop("OPEN_CMD", None)
    assert (old / "Contents" / "v").read_text() == "old"


def test_check_is_skipped_outside_the_mac_app():
    assert updater.can_self_update() is False  # tests run from source, BUILD == 0
    assert updater.check_for_update() is None


def test_manual_check_reports_connection_problems(monkeypatch):
    import pytest
    monkeypatch.setattr(updater, "can_self_update", lambda: True)

    def boom(*a, **k):
        raise updater.UpdateError("Couldn't reach the update server.\n\nDetails: curl: (6) Could not resolve host")
    monkeypatch.setattr(updater, "_fetch", boom)
    assert updater.check_for_update() is None                 # automatic check at launch stays quiet
    with pytest.raises(updater.UpdateError, match="Could not resolve host"):
        updater.check_for_update(raise_errors=True)           # "Check for Updates" shows the reason


def test_pretend_build_finds_newer_release(monkeypatch):
    import json
    monkeypatch.setattr(updater, "can_self_update", lambda: True)
    monkeypatch.setattr(updater, "_fetch", lambda *a, **k: json.dumps({"build": 12, "sha256": "", "size": 1}).encode())
    monkeypatch.setenv("PACKSLIP_PRETEND_BUILD", "11")
    assert updater.check_for_update(raise_errors=True).build == 12
    monkeypatch.setenv("PACKSLIP_PRETEND_BUILD", "12")
    assert updater.check_for_update(raise_errors=True) is None


def test_parse_manifest():
    m = {"build": 19, "asset": updater.ASSET_NAME, "sha256": "cd" * 32, "size": 99}
    info = updater.parse_manifest(m, current_build=18)
    assert info.build == 19 and info.size == 99 and info.sha256 == "cd" * 32
    assert info.url.endswith("/releases/download/build-19/" + updater.ASSET_NAME)
    assert updater.parse_manifest(m, current_build=19) is None
    assert updater.parse_manifest({"oops": 1}, current_build=1) is None
