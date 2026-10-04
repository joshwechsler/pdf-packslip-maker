"""Orders written in one cell: 'Name (2x Regular); Custom X (1x Default); Modifiers: a (1x); b (1x);'"""

from pathlib import Path

from packslip.mapping import DEFAULT_HIDDEN_VARIANTS, Mapping, auto_map, parse_item_list

CELLS = (Path(__file__).parent / "data" / "item_cells.txt").read_text().splitlines()
H = DEFAULT_HIDDEN_VARIANTS


def test_simple_and_side_items():
    assert parse_item_list(CELLS[0], H) == [("Grilled Chicken Breast - Side", "3", "")]


def test_custom_meal_gets_its_modifiers_and_next_item_starts_fresh():
    assert parse_item_list(CELLS[2], H) == [
        ("Custom Chicken", "1", "Grilled Chicken Breast 6oz"),
        ("Creamy Coconut Chicken Thighs", "1", ""),
        ("Teriyaki Glazed Salmon", "1", ""),
    ]
    items = parse_item_list(CELLS[3], H)
    assert [i[0] for i in items] == ["Teriyaki Steak Tips", "Hot Honey Chicken Bowl", "Custom Chicken",
                                     "Custom Steak", "Creamy Coconut Chicken Thighs",
                                     "Downright Breads - Chocolate Chip Banana Bread", "Bang Bang Shrimp Bowl"]
    assert items[2] == ("Custom Chicken", "3", "Grilled Chicken Breast 8oz, Peppers and Onions 1 cup, "
                                               "Baked Russet Potato 1 cup")


def test_sizes_shown_only_when_they_matter():
    names = [i[0] for i in parse_item_list(CELLS[5], H)]
    assert "Hot Honey Chicken Bowl (Small)" in names and "Teriyaki Glazed Salmon" in names
    names = [i[0] for i in parse_item_list(CELLS[6], H)]
    assert names[0] == "Bang Bang Shrimp Bowl (Small)"          # not "(Small) (Small)"
    assert "Bang Bang Shrimp Bowl" in names


def test_custom_tflc_meals_and_delivery_fee_is_skipped():
    items = parse_item_list(CELLS[8], H)
    assert [i[0] for i in items] == ["Custom Chicken TFLC", "Custom Ground Beef TFLC", "Custom Cod TFLC"]
    assert items[2][2] == "Baked Cod 5.4 oz, Brown Rice - 0.5 Cup, Peppers and Onions 1 cup, Olive Oil - 7 g, Day 2, Meal 4"


def test_two_identical_custom_meals_keep_their_own_modifiers():
    a, b = parse_item_list(CELLS[10], H)
    assert a[2].endswith("Broccoli 1 cups") and b[2].endswith("Green Beans 1 cup")


def test_every_pasted_order_parses_and_quantities_add_up():
    import re
    for cell in CELLS:
        items = parse_item_list(cell, H)
        assert items, cell
        expected = sum(int(q) for name, q in re.findall(r"(?:^|; )([^;]*?) \((\d+)x [^)]*\)", cell)
                       if not name.startswith("$") and not name.startswith("Modifiers:"))
        assert sum(int(q) for _, q, _ in items) == expected, cell


def test_end_to_end_one_row_per_customer(tmp_path):
    import csv
    from packslip.spreadsheet import load
    p = tmp_path / "orders.csv"
    with open(p, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Order", "Customer", "Total Items", "Items", "Full Address", "Customer Phone"])
        for i, cell in enumerate(CELLS[:4]):
            w.writerow([1000 + i, f"Person {i}", "", cell, "1 Main St", "(203) 555-0100"])
    sheet = load(p)
    m = auto_map(Mapping(), sheet.headers, sheet.rows)
    assert m.items_mode == "single" and m.columns["items"] == "Items"
    v = m.values_for_row(m.records(sheet.rows)[1])
    assert v["item_count"] == "10"
    assert ("Custom Steak", "5", "Grilled Flank Steak 4oz, Asparagus 2 cups") in v["__items__"]


def test_plain_lists_still_work():
    m = Mapping()
    m.columns = {"items": "Items"}
    assert m.item_rows({"Items": "Bowl\nSalad"}) == [("Bowl", "", ""), ("Salad", "", "")]
