"""One-row-per-item exports (e.g. an online store's fulfillment CSV)."""

from pypdf import PdfReader

from packslip import template as T
from packslip.mapping import ITEMS_KEY, Mapping, auto_map, load_mapping, save_mapping
from packslip.pdfgen import generate_pdf
from packslip.spreadsheet import load

HEAD = ("Order,Index,Customer,Total Items,Fulfillment Type,Fulfillment Date,Fulfillment Time,Location,SKU,"
        "Product,Variant,Quantity,Price,Modifiers,Fulfillment Notes,Business Name,Full Address,Customer Phone,"
        "Driver Instructions,Delivery Zone,Delivery Window,Created Date")
ROWS = [
    '101,1,"Pat Lee",3,InStorePickup,10/04/2026,4:30 PM,"Gym East",5013,"Custom Salmon","Default",2,31.74,'
    '"Grilled Salmon 4oz (1x); Asparagus 1 cup (2x); ","<div>Calories - 430</div>",,,(203) 555-0100,,,,"9/26/2026"',
    '101,1,"Pat Lee",3,InStorePickup,10/04/2026,4:30 PM,"Gym East",,"Banana Bread","Regular",1,12.50,,,,,'
    '(203) 555-0100,,,,"9/26/2026"',
    '102,2,"Sam Roe",4,ScheduledDelivery,10/04/2026,12PM - 9PM,"Main Kitchen",181,"Cheesecake Oats","Small",3,13.98,,'
    ',,"1 Elm St, Meriden, CT 06450",(203) 555-0199,"Back door",Sunday 2,12PM to 5PM,"9/27/2026"',
    '102,2,"Sam Roe",4,ScheduledDelivery,10/04/2026,12PM - 9PM,"Main Kitchen",182,"Coconut Chicken","Regular",1,9.99,'
    ',,,"1 Elm St, Meriden, CT 06450",(203) 555-0199,"Back door",Sunday 2,12PM to 5PM,"9/27/2026"',
]


def _sheet(tmp_path):
    p = tmp_path / "Fulfillment.csv"
    p.write_text(HEAD + "\n" + "\n".join(ROWS) + "\n", encoding="utf-8")
    return load(p)


def test_detects_one_row_per_item_and_groups_orders(tmp_path):
    sheet = _sheet(tmp_path)
    m = auto_map(Mapping(), sheet.headers, sheet.rows)
    assert (m.items_mode, m.group_by, m.variant_col, m.detail_col) == ("rows", "Order", "Variant", "Modifiers")
    assert m.columns["items"] == "Product" and m.columns["quantity"] == "Quantity"
    assert m.columns["address"] == "Full Address" and m.columns["notes"] == "Driver Instructions"
    assert not m.columns.get("total")  # "Total Items" is a count, not money
    orders = m.records(sheet.rows)
    assert len(orders) == 2


def test_order_values_items_variants_and_details(tmp_path):
    sheet = _sheet(tmp_path)
    m = auto_map(Mapping(), sheet.headers, sheet.rows)
    pickup, delivery = (m.values_for_row(r) for r in m.records(sheet.rows))
    assert pickup[ITEMS_KEY] == [("Custom Salmon", "2", "Grilled Salmon 4oz, Asparagus 1 cup (2x)"),
                                 ("Banana Bread", "1", "")]
    assert pickup["item_count"] == "3" and pickup["fulfillment"] == "In Store Pickup"
    assert pickup["pickup_location"] == "Gym East"
    assert delivery[ITEMS_KEY][0] == ("Cheesecake Oats (Small)", "3", "")   # Regular/Default stay hidden
    assert delivery["pickup_location"] == ""  # a delivery's store is where it ships from
    assert delivery["time_window"] == "12PM to 5PM" and delivery["zone"] == "Sunday 2"


def test_pdf_one_page_per_order(tmp_path):
    sheet = _sheet(tmp_path)
    m = auto_map(Mapping(), sheet.headers, sheet.rows)
    out = tmp_path / "f.pdf"
    assert generate_pdf(out, T.default_template(), m, sheet) == 2
    pages = [p.extract_text() for p in PdfReader(out).pages]
    assert "Pat Lee" in pages[0] and "Grilled Salmon 4oz" in pages[0] and "Pickup at: Gym East" in pages[0]
    assert "Sam Roe" in pages[1] and "Cheesecake Oats (Small)" in pages[1] and "Window: 12PM to 5PM" in pages[1]


def test_rows_mode_saves_and_reports_missing_group_column(tmp_path):
    sheet = _sheet(tmp_path)
    m = auto_map(Mapping(), sheet.headers, sheet.rows)
    save_mapping(m, "Fulfillment")
    m2 = load_mapping("Fulfillment")
    assert (m2.items_mode, m2.group_by, m2.detail_col) == ("rows", "Order", "Modifiers")
    renamed = [h if h != "Order" else "Order ID" for h in sheet.headers]
    assert ("Order grouping", "Order") in m2.missing_columns(renamed)
    assert m2.fit_score(sheet.headers) > 0 and m2.fit_score(renamed) == -1


def test_meal_prep_sheet_is_not_mistaken_for_line_items(tmp_path):
    from pathlib import Path
    sheet = load(Path(__file__).resolve().parent.parent / "sample" / "sample_orders.xlsx")
    assert auto_map(Mapping(), sheet.headers, sheet.rows).items_mode == "columns"
