from pypdf import PdfReader

from packslip import template as T
from packslip.drivers import UNASSIGNED, DriverBook, make_plan, town
from packslip.mapping import Mapping, auto_map
from packslip.pdfgen import generate_pdf
from packslip.spreadsheet import load

HEAD = ("Order,Customer,Fulfillment Type,Fulfillment Time,Location,Product,Variant,Quantity,Full Address,"
        "Customer Phone,Driver Instructions,Delivery Window,Delivery Zone")
ROWS = [
    '1,Ann,ScheduledDelivery,12PM - 9PM,Main,Oats,Regular,2,"9 Oak St, Wallingford, CT 06492",(203) 555-0101,Side door,12PM to 9PM,Sunday Only',
    '2,Bob,ScheduledDelivery,12PM - 9PM,Main,Chili,Regular,1,"5 Elm St, Meriden, CT 06450",(203) 555-0102,,12PM to 9PM,Sunday Only',
    '3,Cat,InStorePickup,4:30 PM,Gym East,Salmon,Small,3,,(203) 555-0103,,,',
    '4,Dan,ScheduledDelivery,12PM - 5PM,Main,Tacos,Regular,4,"1 Main St, West Haven, CT 06516",(203) 555-0104,,12PM to 5PM,Sunday 2',
]


def _setup(tmp_path):
    p = tmp_path / "f.csv"
    p.write_text(HEAD + "\n" + "\n".join(ROWS) + "\n")
    sheet = load(p)
    m = auto_map(Mapping(), sheet.headers, sheet.rows)
    return sheet, m, [m.values_for_row(r) for r in m.records(sheet.rows)]


def test_town_from_address():
    assert town("141 WOODLAND ST APT 2, Meriden, CT 06450") == "Meriden"


def test_plan_orders_stops_and_separates_pickups(tmp_path):
    _, _, vals = _setup(tmp_path)
    plan = make_plan(vals, {0: "Mike", 1: "Mike"}, ["Mike"])
    assert plan.routes == [("Mike", [1, 0]), (UNASSIGNED, [3])]   # Meriden 06450 before Wallingford 06492
    assert plan.pickups == [("Gym East", [2])]
    assert plan.stop_of() == {1: ("Mike", 1), 0: ("Mike", 2)}
    assert plan.order() == [1, 0, 3, 2]


def test_book_keeps_driver_list_columns(tmp_path):
    book = DriverBook.load("Fulfillment")
    book.route_columns = {"order": "Order #", "driver": "Driver"}
    book.save()
    assert DriverBook.load("Fulfillment").route_columns == {"order": "Order #", "driver": "Driver"}


def test_pdf_starts_with_delivery_list_and_slips_show_driver(tmp_path):
    sheet, m, _ = _setup(tmp_path)
    out = tmp_path / "d.pdf"
    n = generate_pdf(out, T.default_template("F"), m, sheet, extra={"delivery_date": "Sun, Oct 4, 2026"},
                     drivers={0: "Mike", 1: "Mike", 3: "Sara"}, driver_order=["Mike", "Sara"])
    pages = [p.extract_text() for p in PdfReader(out).pages]
    assert n == 4 and len(pages) == 3 + 4                  # Mike, Sara, Gym East pickups + 4 slips
    assert pages[0].startswith("Driver: Mike") and "2 stops" in pages[0] and "Side door" in pages[0]
    assert pages[1].startswith("Driver: Sara") and pages[2].startswith("Pickups: Gym East")
    # slips A-Z by name
    assert "Ann" in pages[3] and "Driver: Mike" in pages[3] and "Stop" not in pages[3]   # no stops in the file
    assert "Bob" in pages[4] and "Driver: Mike" in pages[4]
    assert "Cat" in pages[5] and "Driver:" not in pages[5]
    assert "Dan" in pages[6] and "Driver: Sara" in pages[6]


def test_no_drivers_means_no_list(tmp_path):
    sheet, m, _ = _setup(tmp_path)
    out = tmp_path / "n.pdf"
    generate_pdf(out, T.default_template("F"), m, sheet)
    assert len(PdfReader(out).pages) == 4


def test_slip_shows_stop_only_when_the_driver_list_has_one(tmp_path):
    sheet, m, _ = _setup(tmp_path)
    out = tmp_path / "s.pdf"
    generate_pdf(out, T.default_template("F"), m, sheet, drivers={0: "Mike", 1: "Mike"}, stops={0: 5})
    slips = [p.extract_text() for p in PdfReader(out).pages][-4:]
    ann = next(t for t in slips if "Ann" in t)
    bob = next(t for t in slips if "Bob" in t)
    assert "Driver: Mike · Stop 5" in ann and "Stop" not in bob


def test_slips_print_a_to_z_by_last_name(tmp_path):
    p = tmp_path / "names.csv"
    p.write_text("Order,Customer,Product,Quantity\n"
                 "1,John Hale,Oats,1\n2,deven iannone,Chili,1\n3,Ann Hale,Tacos,1\n4,,Salad,1\n5,Zoe Adams,Pie,1\n")
    sheet = load(p)
    m = auto_map(Mapping(), sheet.headers, sheet.rows)
    out = tmp_path / "abc.pdf"
    generate_pdf(out, T.default_template("F"), m, sheet, drivers={0: "Mike", 1: "Sara"})
    pages = [pg.extract_text() for pg in PdfReader(out).pages]
    assert pages[0].startswith("Driver: Mike")                       # delivery list keeps route order
    slips = [t for t in pages if "PACKING SLIP" in t]
    names = ["Zoe Adams", "Ann Hale", "John Hale", "deven iannone"]
    assert [next(n for n in names if n in t) for t in slips[:4]] == names   # same last name -> first name
    assert "Salad" in slips[4]                                        # no name: last
