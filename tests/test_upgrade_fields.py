"""Layouts and matches saved by older versions pick up fields added later."""

from pypdf import PdfReader

from packslip import template as T
from packslip.mapping import Mapping, auto_map
from packslip.pdfgen import generate_pdf
from packslip.spreadsheet import load

HEAD = ("Order,Customer,Fulfillment Type,Fulfillment Time,Location,Product,Variant,Quantity,Modifiers,"
        "Full Address,Customer Phone,Building Address Code,Driver Instructions,Delivery Window")
ROWS = ['1,Pat Lee,InStorePickup,4:30 PM,Gym East,Salmon Bowl,Regular,2,,,(203) 555-0100,,,',
        '2,Sam Roe,ScheduledDelivery,12PM - 9PM,Main Kitchen,Oats,Small,1,,"1 Elm St, Meriden",(203) 555-0199,'
        'Backdoor upstairs,Ring twice,12PM to 9PM']


def _old_saved_state(sheet):
    """Matches and layout as an older app version saved them (no pickup time / access code)."""
    m = auto_map(Mapping(), sheet.headers, sheet.rows)
    data = m.to_json()
    data["fields"] = [f for f in data["fields"] if f["key"] not in ("pickup_time", "access_code")]
    data["columns"] = {k: v for k, v in data["columns"].items() if k not in ("pickup_time", "access_code")}
    tpl = T.default_template("Fulfillment Co").to_json()
    tpl["elements"] = [e for e in tpl["elements"] if e.get("field") not in ("pickup_time", "access_code")]
    tpl.pop("upgrades")
    return Mapping.from_json(data), T.Template.from_json(tpl)


def test_old_layout_and_matches_gain_pickup_time_and_access_code(tmp_path):
    p = tmp_path / "f.csv"
    p.write_text(HEAD + "\n" + "\n".join(ROWS) + "\n")
    sheet = load(p)
    m, tpl = _old_saved_state(sheet)
    assert m.fill_new_fields(sheet.headers) is True
    assert m.columns["pickup_time"] == "Fulfillment Time" and m.columns["access_code"] == "Building Address Code"
    assert m.fill_new_fields(sheet.headers) is False  # only once
    out = tmp_path / "o.pdf"
    generate_pdf(out, tpl, m, sheet)
    pickup, delivery = (pg.extract_text() for pg in PdfReader(out).pages)
    assert "Pickup time: 4:30 PM" in pickup and "Pickup at: Gym East" in pickup
    assert "Access: Backdoor upstairs" in delivery and "Window: 12PM to 9PM" in delivery
    assert "Pickup time" not in delivery  # a delivery's "Fulfillment Time" is its window, not a pickup time


def test_not_used_choice_is_respected():
    m = Mapping()
    m.columns = {f["key"]: "" for f in m.fields if f["key"] not in ("pickup_time",)}
    m.columns.update({"time_window": "Delivery Window", "access_code": ""})  # user chose "(not used)"
    m.fill_new_fields(["Building Address Code", "Fulfillment Time", "Delivery Window"])
    assert m.columns["access_code"] == "" and m.columns["pickup_time"] == "Fulfillment Time"


def test_deleted_upgrade_elements_stay_deleted():
    t = T.Template.from_json({"name": "x", "elements": [{"type": "field", "field": "fulfillment"}]})
    assert {e["field"] for e in t.elements} >= {"pickup_time", "access_code"}
    t.elements = [e for e in t.elements if e["field"] != "access_code"]   # user deletes it and saves
    again = T.Template.from_json(t.to_json())
    assert "access_code" not in {e["field"] for e in again.elements}
