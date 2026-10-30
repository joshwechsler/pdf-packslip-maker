"""Meal labels: reading the Label Data export into label fields (deterministic, column by column)."""

from packslip.meal_labels import (MealColumns, filter_records, guess_meal_columns, read_records, sort_records,
                                  split_custom)
from packslip.spreadsheet import load

HEAD = "Customer,Product,Variant,Modifiers,Price,Calories,Protein,Carbs,Fat,How to Prepare\n"
ROWS = [
    'Zoe Adams,Bacon Jam Turkey Burger,Regular,,$13.99 ,720,40,48,27,"Remove lid.\nMicrowave 2 min."\n',
    'Ann Lee,Custom Beef,Default,Ground beef 5oz (1x); Mashed Sweet Potato 1/2 cup (1x); ,$15.00 ,0,0,0,0,\n',
    'Bo Ray,Custom Thin Slice Chicken,Default,Roasted Sweet Potato 1 cup (1x); Broccoli 1 cups (1x); '
    'Thin Chicken Breast 3oz (1x); ,$15.00 ,0,0,0,0,\n',
    'Cy Putt,Custom Ground Beef TFLC,Custom,Ground Beef 3.4 oz (1x); Whole Wheat Pasta 1.8 Cup (1x); '
    'Spinach 1 Cup (1x); Day 1 (1x); Meal 3 (1x); ,$15.00 ,0,0,0,0,\n',
    'Dee Kim,$10 delivery,Default,,$10.00 ,0,0,0,0,\n',
    'Ann Lee,Bacon Jam Turkey Burger,Small,,$11.99 ,390,22,26,15,\n',
]


def _sheet(tmp_path):
    p = tmp_path / "labels.csv"
    p.write_text(HEAD + "".join(ROWS))
    return load(p)


def test_columns_are_matched_by_heading():
    cols = guess_meal_columns(["Customer", "Product", "Variant", "Modifiers", "Price", "Calories", "Protein",
                               "Carbs", "Fat", "How to Prepare"])
    assert (cols.customer, cols.product, cols.size, cols.modifiers, cols.calories, cols.protein_g,
            cols.carbs_g, cols.fat_g, cols.prepare) == ("Customer", "Product", "Variant", "Modifiers", "Calories",
                                                        "Protein", "Carbs", "Fat", "How to Prepare")


def test_custom_split_in_order_day_and_meal_apart():
    s = split_custom("Ground Beef 3.4 oz (1x); Whole Wheat Pasta 1.8 Cup (1x); Spinach 1 Cup (1x); "
                     "Day 1 (1x); Meal 3 (1x); ")
    assert s["item_1"] == "Ground Beef 3.4 oz" and s["item_2"] == "Whole Wheat Pasta 1.8 Cup"
    assert s["item_3"] == "Spinach 1 Cup" and s["item_4"] == "" and (s["day"], s["meal"]) == ("Day 1", "Meal 3")
    assert s["ingredients"] == "Ground Beef 3.4 oz\nWhole Wheat Pasta 1.8 Cup\nSpinach 1 Cup"
    assert split_custom("Peppers, Onions 1 cup (1x); Rice (2x); ")["item_1"] == "Peppers, Onions 1 cup"   # commas kept
    assert split_custom("Rice (2x); ")["item_1"] == "Rice (2x)"                                         # only (1x) removed


def test_custom_by_type():
    s = split_custom("Roasted Sweet Potato 1 cup (1x); Broccoli 1 cups (1x); Thin Chicken Breast 3oz (1x); "
                     "Lemon Tahini Sauce (1x); ")
    assert s["item_1"] == "Roasted Sweet Potato 1 cup"                                  # in order, as listed
    assert (s["protein_item"], s["carb"], s["veg"], s["sauce"]) == (
        "Thin Chicken Breast 3oz", "Roasted Sweet Potato 1 cup", "Broccoli 1 cups", "Lemon Tahini Sauce")


def test_records_every_row_with_fields(tmp_path):
    recs = read_records(_sheet(tmp_path))
    assert len(recs) == 6                                                               # nothing skipped
    burger = recs[0]
    assert burger["kind"] == "regular" and burger["product"] == "Bacon Jam Turkey Burger"
    assert (burger["size"], burger["calories"], burger["protein_g"], burger["carbs_g"], burger["fat_g"]) == (
        "Regular", "720", "40", "48", "27")
    assert burger["prepare"] == "Remove lid.\nMicrowave 2 min." and burger["last_first"] == "Adams, Zoe"
    beef = recs[1]
    assert beef["kind"] == "custom" and beef["item_1"] == "Ground beef 5oz" and beef["day"] == ""
    assert recs[4]["product"] == "$10 delivery" and recs[4]["kind"] == "regular"


def test_sort_and_filter(tmp_path):
    recs = read_records(_sheet(tmp_path))
    by = sort_records(recs, [("product", False), ("size", False), ("last_name", False)])
    assert [r["product"] for r in by][:3] == ["$10 delivery", "Bacon Jam Turkey Burger", "Bacon Jam Turkey Burger"]
    assert [r["size"] for r in by[1:3]] == ["Regular", "Small"]
    assert [r["customer_name"] for r in sort_records(recs, [("last_name", True)])][0] == "Bo Ray"   # Z->A
    assert sort_records(recs, []) == recs                                                            # as in file
    assert all(r["kind"] == "custom" for r in filter_records(recs, kinds={"custom"}))
    kept = filter_records(recs, skip_words=["$", "downright"])
    assert len(kept) == 5 and not any(r["product"].startswith("$") for r in kept)
    assert {r["customer_name"] for r in filter_records(recs, customers=["ann lee"])} == {"Ann Lee"}
    assert [r["product"] for r in filter_records(recs, products=["custom beef"])] == ["Custom Beef"]


def test_meal_layouts_kind_size_and_round_trip():
    from packslip import template as T
    T.ensure_default_template()
    assert T.list_templates(T.MEAL) == ["Custom Meal Label", "Regular Meal Label"]
    assert "Custom Meal Label" not in T.list_templates(T.SLIP) + T.list_templates(T.LABEL)
    c = T.load_template("Custom Meal Label")
    assert c.kind == T.MEAL and c.meal_for == "custom" and c.page_size == (216.0, 360.0)   # 3 x 5 in
    assert T.load_template("Regular Meal Label").meal_for == "regular"
    c.meal_for = "all"
    T.save_template(c)
    assert T.load_template("Custom Meal Label").meal_for == "all"


def test_meal_layouts_render_like_the_photos(tmp_path):
    from pypdf import PdfReader
    from packslip import template as T
    from packslip.meal_labels import MealFields, guess_meal_columns
    from packslip.pdfgen import render_preview_pdf
    sheet = _sheet(tmp_path)
    fields = MealFields(guess_meal_columns(sheet.headers))
    extra = {"delivery_date_short": "10/25/26"}
    out = tmp_path / "c.pdf"
    render_preview_pdf(out, T.custom_meal_template(), fields, {**fields.values_for_row(sheet.rows[3]), **extra})
    text = PdfReader(out).pages[0].extract_text()
    for s in ("Date: 10/25/26", "Cy Putt", "Custom Ground Beef TFLC", "Ground Beef 3.4 oz", "Whole Wheat Pasta 1.8 Cup",
              "Spinach 1 Cup", "Day 1", "Meal 3"):
        assert s in text, s
    out = tmp_path / "r.pdf"
    render_preview_pdf(out, T.regular_meal_template(), fields, {**fields.values_for_row(sheet.rows[0]), **extra})
    text = PdfReader(out).pages[0].extract_text()
    for s in ("Date: 10/25/26", "Zoe Adams", "Bacon Jam Turkey Burger", "Size: Regular", "Cals: 720", "P: 40",
              "C: 48", "F: 27"):
        assert s in text, s
