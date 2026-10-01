import datetime as dt

import pytest

from packslip.spreadsheet import SpreadsheetError, format_value, load


def test_reads_headers_and_rows_skipping_title_and_blank_rows(make_xlsx):
    path = make_xlsx([
        ["Customer", "Items", None, "Qty"],
        ["Jane", "Bowl", None, 2],
        [None, None, None, None],
        ["Tom", "Salad", None, 1.0],
    ], title_row="Orders – week of Sep 28")
    s = load(path)
    assert s.header_row == 2
    assert s.headers == ["Customer", "Items", "Column C", "Qty"]
    assert [r["Customer"] for r in s.rows] == ["Jane", "Tom"]
    assert s.rows[1]["Qty"] == "1"


def test_duplicate_headers_are_made_unique(make_xlsx):
    s = load(make_xlsx([["Name", "Name"], ["a", "b"]]))
    assert s.headers == ["Name", "Name (2)"]


def test_value_formatting():
    assert format_value(dt.datetime(2026, 10, 1)) == "Oct 1, 2026"
    assert format_value(dt.date(2026, 1, 9)) == "Jan 9, 2026"
    assert format_value(3.0) == "3"
    assert format_value(2.50) == "2.5"
    assert format_value(None) == ""
    assert format_value("  a\r\nb ") == "a\nb"


@pytest.mark.parametrize("name,needle", [
    ("old.xls", ".xls"), ("data.csv", ".csv"), ("notes.txt", "isn't an Excel"), ("~$lock.xlsx", "temporary"),
])
def test_friendly_errors_for_wrong_files(tmp_path, name, needle):
    p = tmp_path / name
    p.write_bytes(b"junk")
    with pytest.raises(SpreadsheetError) as e:
        load(p)
    assert needle in str(e.value)


def test_corrupt_xlsx(tmp_path):
    p = tmp_path / "bad.xlsx"
    p.write_bytes(b"not a zip")
    with pytest.raises(SpreadsheetError, match="couldn't be opened"):
        load(p)


def test_missing_file(tmp_path):
    with pytest.raises(SpreadsheetError, match="couldn't be found"):
        load(tmp_path / "nope.xlsx")


def test_empty_and_header_only(make_xlsx):
    with pytest.raises(SpreadsheetError, match="empty"):
        load(make_xlsx([], name="empty.xlsx"))
    with pytest.raises(SpreadsheetError, match="no customer rows"):
        load(make_xlsx([["Customer", "Items"]], name="hdr.xlsx"))
