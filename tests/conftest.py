import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    d = tmp_path / "appdata"
    monkeypatch.setenv("PACKSLIP_DATA_DIR", str(d))
    return d


@pytest.fixture
def make_xlsx(tmp_path):
    from openpyxl import Workbook

    def _make(rows, name="orders.xlsx", title_row=None, sheet_title="Orders"):
        wb = Workbook()
        ws = wb.active
        ws.title = sheet_title
        if title_row:
            ws.append([title_row])
        for r in rows:
            ws.append(list(r))
        path = tmp_path / name
        wb.save(path)
        return path

    return _make
