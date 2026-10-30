from pathlib import Path

from packslip.drive import drive_roots, save_copy


def test_copy_never_replaces_a_file_already_there(tmp_path: Path):
    src = tmp_path / "Bag_Labels_2026-11-01.pdf"
    src.write_bytes(b"one")
    folder = tmp_path / "Drive" / "Labels"
    folder.mkdir(parents=True)
    first = save_copy(src, folder)
    src.write_bytes(b"two")
    second = save_copy(src, folder)
    assert first.name == "Bag_Labels_2026-11-01.pdf"
    assert second.name == "Bag_Labels_2026-11-01 (2).pdf"
    assert first.read_bytes() == b"one" and second.read_bytes() == b"two"
    assert save_copy(src, folder).name == "Bag_Labels_2026-11-01 (3).pdf"


def test_finds_google_drive_folders_on_a_mac(tmp_path: Path):
    (tmp_path / "Library/CloudStorage/GoogleDrive-josh@example.com/My Drive").mkdir(parents=True)
    (tmp_path / "Library/CloudStorage/Dropbox").mkdir(parents=True)
    assert drive_roots(tmp_path) == [tmp_path / "Library/CloudStorage/GoogleDrive-josh@example.com/My Drive"]
    assert drive_roots(tmp_path / "nothing") == []
