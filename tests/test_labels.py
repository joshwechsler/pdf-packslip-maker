"""Bag labels: one small label per bag, pickup orders only, A-Z by last name."""

import pytest
from pypdf import PdfReader

from packslip import template as T
from packslip.mapping import Mapping, auto_map, save_mapping
from packslip.pdfgen import GenerateError, generate_labels
from packslip.spreadsheet import load

CSV = ("Order,Customer,Fulfillment Type,Product,Quantity,Full Address\n"
       '1,Megan Aguilera,InStorePickup,Oats,9,\n'
       '1,Megan Aguilera,InStorePickup,Chili,6,\n'
       '2,Bo Small,ScheduledDelivery,Tacos,25,"2 B St, Milford, CT 06460"\n'
       '3,Ann Zed,InStorePickup,Pie,2,\n'
       '4,Cy Brown,InStorePickup,Soup,10,\n')


def _sheet(tmp_path, text=CSV):
    p = tmp_path / "o.csv"
    p.write_text(text)
    sheet = load(p)
    return sheet, auto_map(Mapping(), sheet.headers, sheet.rows)


def test_pickup_labels_one_per_bag_a_to_z(tmp_path):
    sheet, m = _sheet(tmp_path)
    out = tmp_path / "labels.pdf"
    n = generate_labels(out, T.pickup_label_template(), m, sheet)
    pages = [p.extract_text() for p in PdfReader(out).pages]
    assert n == 6 == len(pages)                      # 6 per bag: Aguilera 15 -> 3; Brown 10 -> 2; Zed 2 -> 1; Small (delivery) none
    assert all("Aguilera, Megan" in p for p in pages[:3])
    assert ["Bag 1/3" in pages[0], "Bag 2/3" in pages[1], "Bag 3/3" in pages[2]] == [True] * 3
    assert "Brown, Cy" in pages[3] and "Bag 1/2" in pages[3] and "Bag 2/2" in pages[4]
    assert "Zed, Ann" in pages[5] and "Bag 1/1" in pages[5]
    assert not any("Small" in p for p in pages)
    box = PdfReader(out).pages[0].mediabox
    assert (float(box.width), float(box.height)) == (162.0, 72.0)   # 2.25 x 1 in


def test_label_settings_round_trip_and_kinds():
    T.ensure_default_template()
    assert "Pickup Bag Label" in T.list_templates()
    assert "Pickup Bag Label" not in T.list_templates("slip")
    assert T.list_templates("label") == ["Pickup Bag Label"]
    t = T.load_template("Pickup Bag Label")
    assert t.kind == "label" and t.label_orders == "pickup" and t.page_size == (162.0, 72.0) and t.bag_size == 6
    t.label_orders = "all"
    T.save_template(t)
    assert T.load_template("Pickup Bag Label").label_orders == "all"


def test_no_pickups_is_a_friendly_error(tmp_path):
    sheet, m = _sheet(tmp_path, "Order,Customer,Fulfillment Type,Product,Quantity\n1,Bo Small,ScheduledDelivery,Tacos,2\n")
    with pytest.raises(GenerateError, match="pickup"):
        generate_labels(tmp_path / "x.pdf", T.pickup_label_template(), m, sheet)
    m.columns["fulfillment"] = ""
    with pytest.raises(GenerateError, match="Delivery / Pickup"):
        generate_labels(tmp_path / "x.pdf", T.pickup_label_template(), m, sheet)


def test_last_first_field():
    v = Mapping(columns={"customer_name": "Name"}).values_for_row({"Name": "Megan Aguilera"})
    assert v["last_first"] == "Aguilera, Megan"
    assert Mapping(columns={"customer_name": "Name"}).values_for_row({"Name": "Cher"})["last_first"] == "Cher"


def test_pickup_bags_hold_6():
    from packslip.pdfgen import bag_count
    assert T.pickup_label_template().bag_size == 6
    assert [bag_count(n, 6) for n in (6, 7, 12, 13)] == [1, 2, 2, 3]
    # A saved pickup label still on the old placeholder (10) becomes 6 once; a number the user chose is kept.
    old = T.pickup_label_template().to_json()
    old["bag_size"], old["upgrades"] = 10, ["pickup_access", "driver"]
    assert T.Template.from_json(old).bag_size == 6
    chosen = dict(old, bag_size=8)
    assert T.Template.from_json(chosen).bag_size == 8
    again = T.Template.from_json(old)
    again.bag_size = 10                                   # set back to 10 on purpose after the upgrade
    assert T.Template.from_json(again.to_json()).bag_size == 10
