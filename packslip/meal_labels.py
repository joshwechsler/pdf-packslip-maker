"""Meal labels: read the store's Label Data export (one row per container) into label fields.

Everything is deterministic and column-by-column; no row is skipped or guessed at.

Custom meals (Product starts with "Custom") list their ingredients in the Modifiers cell:
    "Ground Beef 3.4 oz (1x); Whole Wheat Pasta 1.8 Cup (1x); Spinach 1 Cup (1x); Day 1 (1x); Meal 3 (1x); "
That cell is split at semicolons and "(1x)" is removed. Ingredients become Item 1-6 in the order listed
(as the Operator's spreadsheet does) and, separately, Protein / Carb / Veg / Sauce by fixed word lists.
"Day N" and "Meal N" always go to their own Day and Meal fields.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, fields

from .mapping import guess_columns, split_name
from .spreadsheet import Sheet

MAX_ITEMS = 6

# (key, label shown in the editor, heading aliases). Keys are the MealColumns attributes.
MEAL_COLUMN_FIELDS = [
    ("customer", "Customer", ["customer", "customer name", "name"]),
    ("product", "Product", ["product", "product name", "item"]),
    ("size", "Size", ["variant", "size"]),
    ("modifiers", "Modifiers", ["modifiers", "options"]),
    ("price", "Price", ["price"]),
    ("calories", "Calories", ["calories", "cals", "kcal"]),
    ("protein_g", "Protein (g)", ["=protein", "protein (g)", "protein g"]),
    ("carbs_g", "Carbs (g)", ["carbs", "carbohydrates", "carbs (g)"]),
    ("fat_g", "Fat (g)", ["fat", "fat (g)"]),
    ("prepare", "How to Prepare", ["how to prepare", "instructions", "heating instructions", "preparation"]),
]

# Label fields the editor offers for meal labels: (key, label, sample).
MEAL_LABEL_FIELDS = [
    ("customer_name", "Customer", "Jane Smith"),
    ("first_name", "First Name", "Jane"),
    ("last_name", "Last Name", "Smith"),
    ("last_first", "Last, First Name", "Smith, Jane"),
    ("product", "Product", "Bacon Jam Turkey Burger"),
    ("size", "Size", "Regular"),
    ("price", "Price", "$13.99"),
    ("calories", "Calories", "720"),
    ("protein_g", "Protein (g)", "40"),
    ("carbs_g", "Carbs (g)", "48"),
    ("fat_g", "Fat (g)", "27"),
    ("prepare", "How to Prepare", "Microwave 2-3 minutes."),
    ("modifiers", "Modifiers (as in the file)", "Ground beef 5oz (1x); Brown Rice 1 cup (1x);"),
    *[(f"item_{n}", f"Custom Item {n}", ["Ground beef 5oz", "Mashed Sweet Potato 1/2 cup", "Green Beans 1 cup",
                                         "Tzatziki Sauce", "", ""][n - 1]) for n in range(1, MAX_ITEMS + 1)],
    ("ingredients", "Custom Items (all, one per line)", "Ground beef 5oz\nMashed Sweet Potato 1/2 cup"),
    ("protein_item", "Custom Protein", "Ground beef 5oz"),
    ("carb", "Custom Carb", "Mashed Sweet Potato 1/2 cup"),
    ("veg", "Custom Veg", "Green Beans 1 cup"),
    ("sauce", "Custom Sauce", "Tzatziki Sauce"),
    ("day", "Day", "Day 1"),
    ("meal", "Meal", "Meal 2"),
    ("delivery_date", "Delivery Date", "Sun, Oct 25, 2026"),
    ("delivery_date_short", "Delivery Date (10/25/26)", "10/25/26"),
]

# Fixed word lists for sorting custom-meal ingredients by type (first match wins; checked in this order).
_DAY_MEAL = re.compile(r"^(day|meal)\s*\d+\b", re.I)
_TYPES = [
    ("sauce", re.compile(r"sauce|oil\b|tahini|tzatziki|dressing|salsa|aioli|pesto|glaze|chimichurri|gravy", re.I)),
    ("protein_item", re.compile(r"chicken|beef|steak|salmon|shrimp|turkey|cod|pork|tofu|tuna|egg|tilapia|"
                                r"halibut|bison|lamb|sausage|tempeh", re.I)),
    ("carb", re.compile(r"rice|potato|couscous|pasta|quinoa|noodle|carb|bread|tortilla|oats|farro|orzo|wrap|"
                        r"bun|bagel|plantain|yam", re.I)),
    ("veg", re.compile(r"broccoli|bean|sprout|asparagus|medley|pepper|onion|cauliflower|spinach|peas?\b|"
                       r"zucchini|carrot|kale|salad|green|corn|squash|mushroom|tomato|cabbage|vegetable|veg", re.I)),
]
_ONE_X = re.compile(r"\s*\(1x\)\s*$", re.I)


@dataclass
class MealColumns:
    """Which heading each label field comes from ("" = not in this file)."""
    customer: str = ""
    product: str = ""
    size: str = ""
    modifiers: str = ""
    price: str = ""
    calories: str = ""
    protein_g: str = ""
    carbs_g: str = ""
    fat_g: str = ""
    prepare: str = ""

    def to_json(self) -> dict:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    @classmethod
    def from_json(cls, data: dict | None) -> "MealColumns":
        data = data or {}
        return cls(**{f.name: str(data.get(f.name) or "") for f in fields(cls)})

    def fits(self, headers: list[str]) -> bool:
        used = [v for v in self.to_json().values() if v]
        return bool(self.product) and all(h in headers for h in used)


def guess_meal_columns(headers: list[str]) -> MealColumns:
    spec = [{"key": k, "label": label, "aliases": aliases} for k, label, aliases in MEAL_COLUMN_FIELDS]
    return MealColumns(**guess_columns(spec, headers))


def looks_like_meal_file(sheet: Sheet) -> bool:
    """The Label Data export: product + nutrition/heating columns, and no delivery address."""
    heads = {h.strip().lower() for h in sheet.headers}
    return "product" in heads and bool(heads & {"calories", "how to prepare"}) and not any(
        "address" in h for h in heads)


def is_custom(product: str) -> bool:
    return product.strip().lower().startswith("custom")


def split_custom(modifiers: str) -> dict:
    """Ingredient fields from a custom meal's Modifiers cell (see the module notes)."""
    parts = [_ONE_X.sub("", p).strip() for p in (modifiers or "").split(";")]
    parts = [p for p in parts if p]
    out = {f"item_{n}": "" for n in range(1, MAX_ITEMS + 1)}
    out.update(day="", meal="", protein_item="", carb="", veg="", sauce="")
    items = []
    for p in parts:
        m = _DAY_MEAL.match(p)
        if m:
            out[m.group(1).lower()] = p
        else:
            items.append(p)
    for n, p in enumerate(items[:MAX_ITEMS], 1):
        out[f"item_{n}"] = p
    for p in items:
        for key, pattern in _TYPES:
            if pattern.search(p):
                if not out[key]:
                    out[key] = p
                break
    out["ingredients"] = "\n".join(items)
    return out


def record_from_row(row: dict, cols: MealColumns, index: int = 0) -> dict:
    """All label fields for one row of the export."""
    def get(key):
        col = getattr(cols, key)
        return (row.get(col, "") if col else "").strip()

    rec = {key: get(key) for key, _, _ in MEAL_COLUMN_FIELDS}
    rec["customer_name"] = rec.pop("customer")
    first, last = split_name(rec["customer_name"])
    rec.update(first_name=first, last_name=last, last_first=", ".join(x for x in (last, first) if x),
               kind="custom" if is_custom(rec["product"]) else "regular", row_index=index)
    rec.update(split_custom(rec["modifiers"]) if rec["kind"] == "custom" else split_custom(""))
    return rec


def read_records(sheet: Sheet, cols: MealColumns | None = None) -> list[dict]:
    """One record (dict of label fields) per row, in file order. Nothing is skipped."""
    cols = cols or guess_meal_columns(sheet.headers)
    return [record_from_row(row, cols, i) for i, row in enumerate(sheet.rows)]


class MealFields:
    """The meal-label field list, shaped like a pack-slip Mapping so the layout editor and the
    PDF renderer can use it unchanged (field menu, labels, placeholders, preview rows)."""
    items_mode = "single"

    def __init__(self, cols: MealColumns | None = None):
        self.cols = cols or MealColumns()
        self.fields = [{"key": k, "label": label, "sample": sample} for k, label, sample in MEAL_LABEL_FIELDS]
        self.columns = {k: k for k, _, _ in MEAL_LABEL_FIELDS}  # every field is always available

    def all_fields(self) -> list[dict]:
        return self.fields

    def field_label(self, key: str) -> str:
        return next((f["label"] for f in self.fields if f["key"] == key), key)

    def records(self, rows: list[dict]) -> list[dict]:
        return list(rows)

    def values_for_row(self, row: dict) -> dict:
        return record_from_row(row, self.cols)

    def sample_values(self) -> dict:
        return {f["key"]: f["sample"] for f in self.fields}

    def is_empty(self) -> bool:
        return False


# Sort keys the Operator can choose (label shown in the app -> record key).
SORT_KEYS = {"Product": "product", "Size": "size", "Customer last name": "last_name",
             "Customer first name": "first_name"}


def sort_records(records: list[dict], keys: list[tuple[str, bool]]) -> list[dict]:
    """keys: [(record key, descending?)], most important first. No keys = as in the file."""
    out = list(records)
    for key, descending in reversed(keys):  # stable sorts, least important first
        out.sort(key=lambda r: (r.get(key) or "").lower(), reverse=descending)
    return out


def filter_records(records: list[dict], kinds: set[str] | None = None, skip_words: list[str] | None = None,
                   customers: list[str] | None = None, products: list[str] | None = None) -> list[dict]:
    """kinds: {"custom", "regular"}; skip_words: drop products containing any of them;
    customers / products: keep only these (exact names, any case). Empty/None = no filter."""
    skip = [w.strip().lower() for w in (skip_words or []) if w.strip()]
    want_c = {c.strip().lower() for c in (customers or []) if c.strip()}
    want_p = {p.strip().lower() for p in (products or []) if p.strip()}
    out = []
    for r in records:
        product = r.get("product", "").lower()
        if kinds and r.get("kind") not in kinds:
            continue
        if any(w in product for w in skip):
            continue
        if want_c and r.get("customer_name", "").lower() not in want_c:
            continue
        if want_p and product not in want_p:
            continue
        out.append(r)
    return out
