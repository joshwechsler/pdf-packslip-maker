"""Address / Pickup Location: deliveries show the address, pickups show their pickup location."""

from pypdf import PdfReader

from packslip import template as T
from packslip.mapping import Mapping, auto_map
from packslip.pdfgen import blank_line_warnings, generate_pdf
from packslip.spreadsheet import load

CSV = ("Order,Customer,Fulfillment Type,Location,Product,Quantity,Full Address\n"
       '1,Rae Pick,InStorePickup,Chapel Haven- RESIDENTS ONLY,Oats,1,\n'
       '2,Dee Liver,ScheduledDelivery,Main (West Haven),Chili,1,"1040 Whalley Ave, New Haven, CT 06515"\n'
       '3,Nolo Cation,InStorePickup,,Pie,1,\n')


def _vals(tmp_path):
    p = tmp_path / "f.csv"
    p.write_text(CSV)
    sheet = load(p)
    m = auto_map(Mapping(), sheet.headers, sheet.rows)
    return sheet, m, [m.values_for_row(r) for r in m.records(sheet.rows)]


def test_pickup_shows_location_delivery_shows_address(tmp_path):
    _, m, (pick, deliv, blank) = _vals(tmp_path)
    assert m.columns["pickup_location"] == "Location" and m.columns["fulfillment"] == "Fulfillment Type"
    assert (pick["ship_to_heading"], pick["ship_to"]) == ("PICKUP LOCATION", "Chapel Haven- RESIDENTS ONLY")
    assert (deliv["ship_to_heading"], deliv["ship_to"]) == ("DELIVERY ADDRESS", "1040 Whalley Ave, New Haven, CT 06515")
    assert "Main (West Haven)" not in deliv["ship_to"]           # shipped-from location never shows on deliveries
    assert blank["ship_to"] == "Pickup"                           # pickup with no location: still says Pickup


def test_landscape_layout_uses_it(tmp_path):
    sheet, m, _ = _vals(tmp_path)
    out = tmp_path / "s.pdf"
    generate_pdf(out, T.landscape_template(), m, sheet)
    pages = [p.extract_text() for p in PdfReader(out).pages]
    dee = next(t for t in pages if "Dee" in t)
    rae = next(t for t in pages if "Rae" in t)
    assert "DELIVERY ADDRESS" in dee and "1040 Whalley Ave" in dee and "West Haven)" not in dee
    assert "PICKUP LOCATION" in rae and "Chapel Haven- RESIDENTS ONLY" in rae and "DELIVERY ADDRESS" not in rae


def test_warns_when_pickups_cant_be_told_apart():
    m = Mapping(columns={"customer_name": "Customer", "address": "Full Address"})   # Delivery / Pickup not matched
    w = blank_line_warnings(T.landscape_template(), m, drivers_matched=1)
    assert any("Delivery / Pickup" in x for x in w)
