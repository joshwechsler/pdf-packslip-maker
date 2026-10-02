from packslip import template as T
from packslip.mapping import Mapping, guess_columns, load_mapping, save_mapping


def test_guess_columns_matches_common_headers():
    m = Mapping()
    headers = ["Order No", "Client Name", "Shipping Address", "Mobile", "Order Items",
               "QTY", "Special Instructions", "Unrelated"]
    cols = guess_columns(m.fields, headers)
    assert cols == {"order_number": "Order No", "customer_name": "Client Name", "address": "Shipping Address", "phone": "Mobile", "items": "Order Items",
                    "quantity": "QTY", "notes": "Special Instructions"}


def test_mapping_roundtrip_and_custom_field():
    m = Mapping()
    key = m.add_field("Route")
    m.columns = {"customer_name": "Customer", key: "Route #"}
    save_mapping(m, "Standard")
    loaded = load_mapping("Standard")
    assert loaded.columns == m.columns
    assert loaded.field_label(key) == "Route"
    assert loaded.missing_columns(["Customer"]) == [("Route", "Route #")]
    assert loaded.missing_columns(["Customer"], used_keys={"customer_name"}) == []


def test_template_roundtrip_and_management():
    names = T.ensure_default_template()
    assert names == ["Standard"]
    t = T.load_template("Standard")
    t2 = t.copy("Label 4x6")
    t2.page = "Label (4 × 6 in)"
    T.save_template(t2)
    assert T.list_templates() == ["Label 4x6", "Standard"]
    assert T.load_template("Label 4x6").page_size == (288.0, 432.0)
    T.delete_template("Label 4x6")
    assert T.list_templates() == ["Standard"]


def test_placeholders_and_split_lines():
    m = Mapping()
    vals = {"customer_name": "Jane", "items": "A, B; C"}
    text_el = T.make_element("text", 0, 0, 10, 10, text="Hi {Customer Name}! {Unknown}")
    assert T.element_text(text_el, vals, m) == "Hi Jane! {Unknown}"
    field_el = T.make_element("field", 0, 0, 10, 10, field="items", split_lines=True, bullets=True)
    assert T.element_text(field_el, vals, m) == "• A\n• B\n• C"
    tpl = T.Template(elements=[text_el])
    assert tpl.used_field_keys(m) == {"customer_name"}


def test_bad_template_json_is_normalized():
    t = T.Template.from_json({"name": "x", "page": "bogus",
                              "elements": [{"type": "field", "x": "5", "w": 0, "font": "Comic"}]})
    el = t.elements[0]
    assert t.page == T.DEFAULT_PAGE
    assert el["x"] == 5.0 and el["w"] == 1.0 and el["font"] == "Helvetica" and el["id"]


REAL_HEADERS = ["Order Received", "Customer Name", "Phone Number", "Address", "Backyard Italian Pasta",
                "Orange Chicken", "Insulated Cooler Bag", "Delivery Fee", "Total Cost", "Paid",
                "Delivery Instructions"]


def _real_rows():
    vals = [["Sep 8, 2026 7:29 PM", "Pat", "2035550147", "1 Main St", "1", "", "2", "0", "$89.50", "No", ""],
            ["Sep 8, 2026 8:00 PM", "Lee", "2035550100", "2 Oak St", "", "3", "", "5", "$40.00", "Yes", "Side door"]]
    return [dict(zip(REAL_HEADERS, v)) for v in vals]


def test_auto_map_detects_menu_item_columns():
    from packslip.mapping import auto_map
    m = auto_map(Mapping(), REAL_HEADERS, _real_rows())
    assert m.items_mode == "columns"
    assert (m.items_after, m.items_before) == ("Address", "Delivery Fee")
    assert m.item_headers(REAL_HEADERS) == ["Backyard Italian Pasta", "Orange Chicken", "Insulated Cooler Bag"]
    assert m.columns["order_date"] == "Order Received" and m.columns["notes"] == "Delivery Instructions"
    assert "order_number" not in m.columns  # "Order Received" must not be taken as an order number


def test_item_rows_skip_unordered_and_compute_totals():
    from packslip.mapping import ITEMS_KEY, auto_map
    m = auto_map(Mapping(), REAL_HEADERS, _real_rows())
    v = m.values_for_row(_real_rows()[0])
    assert v[ITEMS_KEY] == [("Backyard Italian Pasta", "1", ""), ("Insulated Cooler Bag", "2", "")]
    assert v["item_count"] == "3" and v["phone"] == "(203) 555-0147"
    assert v["items"] == "Backyard Italian Pasta\nInsulated Cooler Bag"


def test_menu_change_next_week_still_works():
    from packslip.mapping import auto_map
    m = auto_map(Mapping(), REAL_HEADERS, _real_rows())
    next_week = REAL_HEADERS[:4] + ["Lemon Salmon", "Beef Tacos", "Banana Bread", "Cooler Bag"] + REAL_HEADERS[7:]
    assert m.item_headers(next_week) == ["Lemon Salmon", "Beef Tacos", "Banana Bread", "Cooler Bag"]
    assert m.missing_columns(next_week) == []


def test_missing_anchor_column_is_reported():
    from packslip.mapping import auto_map
    m = auto_map(Mapping(), REAL_HEADERS, _real_rows())
    renamed = [h if h != "Delivery Fee" else "Delivery Charge" for h in REAL_HEADERS]
    assert ("End of menu items", "Delivery Fee") in m.missing_columns(renamed)


def test_mapping_v2_roundtrip():
    from packslip.mapping import auto_map
    m = auto_map(Mapping(), REAL_HEADERS, _real_rows())
    save_mapping(m, "Standard")
    m2 = load_mapping("Standard")
    assert (m2.items_mode, m2.items_after, m2.items_before) == ("columns", "Address", "Delivery Fee")


def test_total_items_placeholder():
    m = Mapping()
    el = T.make_element("text", 0, 0, 10, 10, text="Total items: {Total Items}")
    assert T.element_text(el, {"item_count": "7"}, m) == "Total items: 7"


def test_settings_migrate_from_old_app_name(tmp_path, monkeypatch):
    import sys
    from pathlib import Path
    from packslip import storage
    monkeypatch.delenv("PACKSLIP_DATA_DIR", raising=False)
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    old = tmp_path / "Library" / "Application Support" / "Pack Slip Maker"
    (old / "templates").mkdir(parents=True)
    (old / "mapping.json").write_text("{}")
    new = storage.data_dir()
    assert new.name == "Packs Be Slippin'"
    assert (new / "mapping.json").exists() and not old.exists()


def test_old_navy_gold_layouts_switch_to_black_and_white():
    t = T.Template.from_json({"name": "x", "brand": {"primary": "#1F3A5F", "accent": "#C8A24A"}})
    assert t.brand == T.DEFAULT_BRAND == {"primary": "#000000", "accent": "#555555"}
    custom = T.Template.from_json({"name": "y", "brand": {"primary": "#FF0000", "accent": "#C8A24A"}})
    assert custom.brand["primary"] == "#FF0000"  # colours someone chose are kept


def test_each_layout_has_its_own_column_matches():
    from packslip import mapping as M
    a, b = Mapping(), Mapping()
    a.columns = {"customer_name": "Customer Name"}
    b.columns = {"customer_name": "Client", "address": "Ship To"}
    M.save_mapping(a, "Meal Prep")
    M.save_mapping(b, "Other Biz")
    assert M.load_mapping("Meal Prep").columns == a.columns
    assert M.load_mapping("Other Biz").columns == b.columns
    M.copy_mapping("Other Biz", "Other Biz copy")
    M.rename_mapping("Other Biz copy", "Renamed")
    assert M.load_mapping("Renamed").columns == b.columns and M.load_mapping("Other Biz copy") is None
    M.delete_mapping("Renamed")
    assert M.load_mapping("Renamed") is None


def test_legacy_app_wide_mapping_migrates_to_every_layout():
    from packslip import mapping as M, storage
    old = Mapping()
    old.columns = {"customer_name": "Customer Name"}
    storage.write_json(storage.data_dir() / "mapping.json", old.to_json())
    M.migrate_legacy_mapping(["Standard", "Driver copy"])
    assert M.load_mapping("Standard").columns == old.columns
    assert M.load_mapping("Driver copy").columns == old.columns
    assert not (storage.data_dir() / "mapping.json").exists()


def test_fit_score_picks_the_right_business():
    from packslip.mapping import auto_map
    meal = auto_map(Mapping(), REAL_HEADERS, _real_rows())
    other_headers = ["Client", "Ship To", "SKU", "Qty Ordered"]
    other = Mapping()
    other.columns = {"customer_name": "Client", "address": "Ship To", "items": "SKU", "quantity": "Qty Ordered"}
    assert meal.fit_score(REAL_HEADERS) > 0 and other.fit_score(REAL_HEADERS) == -1
    assert other.fit_score(other_headers) > 0 and meal.fit_score(other_headers) == -1
    assert Mapping().fit_score(REAL_HEADERS) == -1  # never matched
