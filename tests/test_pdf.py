import time

import pytest
from pypdf import PdfReader

from packslip import template as T
from packslip.layout import fit_text
from packslip.mapping import Mapping, guess_columns
from packslip.pdfgen import GenerateError, default_output_path, generate_pdf
from packslip.spreadsheet import load

HEAD = ["Order No", "Customer", "Order Items", "Qty", "Notes"]


def _setup(make_xlsx, n):
    rows = [HEAD] + [[i, f"Person {i}", "Bowl\nSalad", "1\n2", "note"] for i in range(n)]
    sheet = load(make_xlsx(rows))
    m = Mapping()
    m.columns = guess_columns(m.fields, sheet.headers)
    return sheet, m


def test_one_page_per_customer_with_values(make_xlsx, tmp_path):
    sheet, m = _setup(make_xlsx, 5)
    out = tmp_path / "out.pdf"
    assert generate_pdf(out, T.default_template(), m, sheet) == 5
    reader = PdfReader(out)
    assert len(reader.pages) == 5
    text = reader.pages[3].extract_text()
    assert "Person 3" in text and "Salad" in text and "PACKING SLIP" in text


def test_performance_300_rows_under_30s(make_xlsx, tmp_path):
    sheet, m = _setup(make_xlsx, 300)
    t0 = time.perf_counter()
    generate_pdf(tmp_path / "big.pdf", T.default_template(), m, sheet)
    assert time.perf_counter() - t0 < 30


def test_missing_column_gives_friendly_error(make_xlsx, tmp_path):
    sheet, m = _setup(make_xlsx, 2)
    m.columns["customer_name"] = "Customer Full Name"  # renamed since mapping was saved
    with pytest.raises(GenerateError, match="Remap Fields") as e:
        generate_pdf(tmp_path / "x.pdf", T.default_template(), m, sheet)
    assert "Customer Full Name" in str(e.value)
    assert not (tmp_path / "x.pdf").exists()


def test_logo_and_brand_colors_render(make_xlsx, tmp_path, data_dir):
    from PIL import Image
    from packslip import storage
    Image.new("RGB", (120, 40), (200, 0, 0)).save(storage.assets_dir() / "logo.png")
    sheet, m = _setup(make_xlsx, 1)
    tpl = T.default_template()
    tpl.brand["primary"] = "#00AA00"
    for el in tpl.elements:
        if el["type"] == "logo":
            el["image"] = "logo.png"
    out = tmp_path / "logo.pdf"
    generate_pdf(out, tpl, m, sheet)
    page = PdfReader(out).pages[0]
    assert page["/Resources"]["/XObject"]  # image embedded
    assert b"0 .666667 0 rg" in page.get_contents().get_data()  # brand primary fill


def test_fit_text_shrinks_then_truncates():
    lay = fit_text("word " * 50, "Helvetica", False, False, 20, 100, 30, shrink=True)
    assert lay.size < 20
    assert lay.lines[-1].endswith("...")
    lay2 = fit_text("short", "Helvetica", True, False, 12, 200, 30)
    assert lay2.size == 12 and lay2.lines == ["short"]


def test_default_output_path_never_overwrites(tmp_path):
    src = tmp_path / "orders.xlsx"
    first = default_output_path(src)
    first.write_bytes(b"x")
    second = default_output_path(src)
    assert second != first and second.name.endswith("(2).pdf")
