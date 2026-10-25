"""Extra bag slips for big orders (Landscape layout)."""

from pypdf import PdfReader

from packslip import template as T
from packslip.mapping import Mapping, auto_map
from packslip.pdfgen import bag_count, generate_pdf
from packslip.spreadsheet import load


def test_bag_count():
    assert [bag_count(n, 10) for n in (0, 1, 10, 11, 20, 21, 30, 31)] == [1, 1, 1, 2, 2, 3, 3, 4]
    assert bag_count(25, 0) == 1                       # bags off for this layout


def _sheet(tmp_path):
    p = tmp_path / "o.csv"
    p.write_text("Order,Customer,Fulfillment Type,Product,Quantity,Full Address\n"
                 '1,Ann Big,ScheduledDelivery,Oats,9,"1 A St, Milford, CT 06460"\n'
                 '1,Ann Big,ScheduledDelivery,Chili,6,"1 A St, Milford, CT 06460"\n'
                 '2,Bo Small,ScheduledDelivery,Tacos,4,"2 B St, Milford, CT 06460"\n'
                 '3,Cy Pickup,InStorePickup,Pie,12,\n')
    sheet = load(p)
    return sheet, auto_map(Mapping(), sheet.headers, sheet.rows)


def test_big_order_gets_extra_slip_without_order_details(tmp_path):
    sheet, m = _sheet(tmp_path)
    out = tmp_path / "b.pdf"
    n = generate_pdf(out, T.landscape_template(), m, sheet)
    pages = [p.extract_text() for p in PdfReader(out).pages]
    assert n == 3 and len(pages) == 4                  # Ann: 15 items -> 2 bags; Bo 1; Cy (pickup) 1
    ann1, ann2, cy, bo = pages                          # A-Z by last name: Big, Big, Pickup, Small
    assert "Bag: 1/2" in ann1 and "ORDER DETAILS" in ann1 and "Oats" in ann1
    assert "Bag: 2/2" in ann2 and "ORDER DETAILS" not in ann2 and "Oats" not in ann2
    assert "1 A St" in ann2 and "15" in ann2 and "Big" in ann2   # right side repeated, whole-order total
    assert "Cy" in cy and "Bag: 1/1" in cy              # pickup: never split (12 items)
    assert "Bo" in bo and "Bag: 1/1" in bo


def test_layouts_without_bags_are_unchanged(tmp_path):
    sheet, m = _sheet(tmp_path)
    out = tmp_path / "s.pdf"
    assert generate_pdf(out, T.default_template(), m, sheet) == 3
    assert len(PdfReader(out).pages) == 3


def test_bag_settings_round_trip():
    t = T.default_template("X")
    t.bag_size = 10
    t.elements[0]["first_bag_only"] = True
    T.save_template(t)
    again = T.load_template("X")
    assert again.bag_size == 10 and again.elements[0]["first_bag_only"]
    assert T.Template.from_json({"name": "Old"}).bag_size == 0


def test_blank_line_warnings():
    from packslip.pdfgen import blank_line_warnings
    m = Mapping(columns={"fulfillment": "Fulfillment Type"})   # pickups can be told apart
    t = T.landscape_template()                                    # has Bag and Driver lines, bags on
    assert blank_line_warnings(t, m, drivers_matched=3) == []
    t.bag_size = 0
    w = blank_line_warnings(t, m, drivers_matched=0)
    assert len(w) == 2 and "Max items per bag" in w[0] and "driver list" in w[1]
    assert blank_line_warnings(T.default_template(), m, drivers_matched=0)[0].startswith("This layout has a Driver")
    plain = T.default_template()
    plain.elements = [e for e in plain.elements if e.get("field") not in ("driver", "driver_stop")]
    assert blank_line_warnings(plain, m, drivers_matched=0) == []  # no Driver/Bag line: nothing to warn about
