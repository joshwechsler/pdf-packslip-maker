import datetime as dt
from pathlib import Path

from pypdf import PdfReader

from packslip import template as T
from packslip.datepicker import default_delivery_date
from packslip.mapping import Mapping, auto_map, load_mapping, save_mapping
from packslip.pdfgen import default_output_path, format_delivery_date, generate_pdf
from packslip.spreadsheet import load

WED = dt.date(2026, 9, 30)  # a Wednesday


def test_default_delivery_date_uses_usual_weekday():
    assert default_delivery_date(None, WED) == dt.date(2026, 10, 1)          # tomorrow
    assert default_delivery_date(3, WED) == dt.date(2026, 10, 1)             # Thu -> tomorrow
    assert default_delivery_date(6, WED) == dt.date(2026, 10, 4)             # next Sunday
    assert default_delivery_date(2, WED) == dt.date(2026, 10, 7)             # Wed -> next week, not today


def test_format_and_filename():
    d = dt.date(2026, 10, 2)
    assert format_delivery_date(d) == "Fri, Oct 2, 2026"
    assert default_output_path(Path("/tmp/x/orders.xlsx"), d).name == \
        "Pack Slips - orders - delivery 2026-10-02.pdf"


def test_chosen_delivery_date_prints_on_every_slip(make_xlsx, tmp_path):
    sheet = load(make_xlsx([["Order Received", "Customer Name", "Address", "Pasta", "Chili", "Delivery Fee"],
                            [dt.datetime(2026, 9, 8, 19, 29), "Pat", "1 Main", 1, 2, 0],
                            [dt.datetime(2026, 9, 9, 9, 0), "Lee", "2 Oak", None, 1, 0]]))
    m = auto_map(Mapping(), sheet.headers, sheet.rows)
    out = tmp_path / "d.pdf"
    generate_pdf(out, T.default_template(), m, sheet, extra={"delivery_date": "Fri, Oct 2, 2026"})
    for page in PdfReader(out).pages:
        text = page.extract_text()
        assert "Delivery Date: Fri, Oct 2, 2026" in text
        assert "Sep 8" not in text and "Sep 9" not in text  # order date no longer shown


def test_old_saved_mapping_with_delivery_column_field_is_cleaned():
    m = Mapping()
    data = m.to_json()
    data["fields"] = data["fields"] + [{"key": "delivery_date", "label": "Delivery Date"}]
    save_mapping(Mapping.from_json(data))
    keys = [f["key"] for f in load_mapping().all_fields()]
    assert keys.count("delivery_date") == 1
