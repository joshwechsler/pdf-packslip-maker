from packslip import template as T
from packslip.mapping import Mapping, guess_columns, load_mapping, save_mapping


def test_guess_columns_matches_common_headers():
    m = Mapping()
    headers = ["Order No", "Client Name", "Ship Date", "Shipping Address", "Mobile", "Order Items",
               "QTY", "Special Instructions", "Unrelated"]
    cols = guess_columns(m.fields, headers)
    assert cols == {"order_number": "Order No", "customer_name": "Client Name", "delivery_date": "Ship Date",
                    "address": "Shipping Address", "phone": "Mobile", "items": "Order Items",
                    "quantity": "QTY", "notes": "Special Instructions"}


def test_mapping_roundtrip_and_custom_field():
    m = Mapping()
    key = m.add_field("Route")
    m.columns = {"customer_name": "Customer", key: "Route #"}
    save_mapping(m)
    loaded = load_mapping()
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
