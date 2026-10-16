"""Landscape pages, the built-in Landscape layout, and first/last names."""

from pypdf import PdfReader

from packslip import storage
from packslip import template as T
from packslip.mapping import Mapping, auto_map, load_mapping, save_mapping
from packslip.pdfgen import generate_pdf
from packslip.spreadsheet import load


def test_orientation_swaps_page_and_round_trips():
    t = T.default_template("X")
    t.landscape = True
    assert t.page_size == (792.0, 612.0)
    T.save_template(t)
    assert T.load_template("X").landscape and T.load_template("X").orientation == "Landscape"
    assert T.Template.from_json({"name": "Old"}).page_size == (612.0, 792.0)   # old files stay portrait


def test_landscape_layout_installed_once_with_current_matches():
    save_mapping(Mapping(columns={"customer_name": "Customer"}), "Standard")
    T.save_template(T.default_template())
    assert T.ensure_default_template() == ["Landscape", "Standard"]
    assert load_mapping("Landscape").columns == {"customer_name": "Customer"}
    assert "template" not in storage.load_settings()            # an option, not the new default
    T.delete_template("Landscape")
    assert T.ensure_default_template() == ["Standard"]          # deleting it is respected


def test_landscape_layout_fits_the_page():
    t = T.landscape_template()
    w, h = t.page_size
    assert (w, h) == (792.0, 612.0)
    assert all(e["x"] + e["w"] <= w and e["y"] + e["h"] <= h for e in t.elements)


def test_names_split_or_joined():
    m = Mapping(columns={"customer_name": "Name"})
    assert {k: m.values_for_row({"Name": "Jane Q. Smith"})[k] for k in ("first_name", "last_name")} == \
        {"first_name": "Jane Q.", "last_name": "Smith"}
    assert m.values_for_row({"Name": "Smith, Jane"})["first_name"] == "Jane"
    m2 = Mapping(columns={"first_name": "First", "last_name": "Last"})
    assert m2.values_for_row({"First": "Ann", "Last": "Lee"})["customer_name"] == "Ann Lee"


def test_landscape_pdf(tmp_path):
    p = tmp_path / "o.csv"
    p.write_text('Order,Customer,Product,Quantity,Full Address,Driver Instructions\n'
                 '1,Ann Lee,Oats,2,"9 Oak St, Wallingford, CT 06492",Side door\n'
                 '1,Ann Lee,Chili,1,"9 Oak St, Wallingford, CT 06492",Side door\n')
    sheet = load(p)
    m = auto_map(Mapping(), sheet.headers, sheet.rows)
    out = tmp_path / "l.pdf"
    generate_pdf(out, T.landscape_template(), m, sheet, extra={"delivery_date": "Sat, Oct 17, 2026"},
                 drivers={0: "Mike"})
    page = PdfReader(out).pages[-1]
    assert (float(page.mediabox.width), float(page.mediabox.height)) == (792.0, 612.0)
    text = page.extract_text()
    for s in ("ORDER DETAILS", "Oats", "Chili", "9 Oak St", "Side door", "TOTAL ITEMS", "3", "Lee", "Ann",
              "Delivery: Sat, Oct 17, 2026", "Driver: Mike"):
        assert s in text, s
