"""Pack-slip fields and how they map to spreadsheet columns (FR-2, FR-3).

Three ways a spreadsheet can list what a customer ordered:

  "columns" – one column per menu item, quantity in each cell (the real weekly
              sheet). Item columns are found *between two anchor columns*
              (e.g. after "Address", before "Delivery Fee"), so the mapping keeps
              working when the menu changes from week to week.
  "single"  – one cell holds the item list (and optionally a parallel quantity cell).
  "rows"    – one row per item (an online-store export). Rows sharing the same
              order number (the `group_by` column) become one pack slip; customer
              details are taken from the order's first row.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import storage

# "sample" values are only used to preview a layout before a spreadsheet is loaded.
DEFAULT_FIELDS = [
    {"key": "customer_name", "label": "Customer Name", "sample": "Jane Smith",
     "aliases": ["customer name", "customer", "name", "client", "full name", "client name"]},
    {"key": "phone", "label": "Phone", "sample": "(555) 123-4567",
     "aliases": ["phone number", "phone", "mobile", "cell", "tel", "telephone", "contact #", "contact number",
                 "contact"]},
    {"key": "address", "label": "Address", "sample": "123 Main St, Unit 4, Springfield, CT 06401",
     "aliases": ["full address", "address", "delivery address", "shipping address", "ship to", "street"]},
    {"key": "order_date", "label": "Order Date", "sample": "Sep 8, 2026 7:29 PM",
     "aliases": ["order received", "order date", "date ordered", "created date", "timestamp", "received", "date"]},
    {"key": "order_number", "label": "Order #", "sample": "1042",
     "aliases": ["order #", "order number", "order no", "order id", "=order", "invoice #", "invoice number"]},
    {"key": "notes", "label": "Delivery Instructions", "sample": "Leave at the side door.",
     "aliases": ["delivery instructions", "driver instructions", "special instructions", "instructions", "notes",
                 "note", "comments", "comment"]},
    {"key": "fulfillment", "label": "Delivery / Pickup", "sample": "Scheduled Delivery",
     "aliases": ["fulfillment type", "fulfillment method", "delivery method", "shipping method", "order type"]},
    {"key": "pickup_location", "label": "Pickup Location", "sample": "",
     "aliases": ["pickup location", "=location", "store", "pickup at"]},
    {"key": "time_window", "label": "Delivery Window", "sample": "12PM to 5PM",
     "aliases": ["delivery window", "time window", "fulfillment time", "time slot", "window"]},
    {"key": "pickup_time", "label": "Pickup Time", "sample": "4:30 PM",
     "aliases": ["pickup time", "=fulfillment time"]},
    {"key": "access_code", "label": "Gate / Access Code", "sample": "",
     "aliases": ["building address code", "gate code", "access code", "door code", "address accessibility"]},
    {"key": "zone", "label": "Route / Zone", "sample": "Sunday 2",
     "aliases": ["delivery zone", "route", "zone"]},
    {"key": "company", "label": "Business Name", "sample": "",
     "aliases": ["business name", "company", "company name"]},
    {"key": "total", "label": "Order Total", "sample": "$89.50",
     "aliases": ["total cost", "order total", "=total", "grand total"]},
    {"key": "paid", "label": "Paid", "sample": "No", "aliases": ["paid", "payment status", "payment"]},
    {"key": "items", "label": "Items", "sample": "Orange Chicken\nTexas Turkey Chili\nProtein Overnight Oats",
     "aliases": ["items", "item", "products", "product", "order items", "item name", "product name", "sku",
                 "meals", "description"]},
    {"key": "quantity", "label": "Quantity", "sample": "2\n1\n3",
     "aliases": ["qty", "quantity", "quantities", "qty ordered", "quantity ordered", "count"]},
]

# Always available on layouts; never matched to a column.
#   item_count    – sum of the customer's item quantities
#   delivery_date – the date the Operator picks in the app before generating
COMPUTED_FIELDS = [
    {"key": "item_count", "label": "Total Items", "sample": "6"},
    {"key": "delivery_date", "label": "Delivery Date", "sample": "Thu, Oct 2, 2026"},
]
COMPUTED_KEYS = {f["key"] for f in COMPUTED_FIELDS}

ITEM_KEYS = {"items", "quantity"}
NOT_USED = ""
ITEMS_KEY = "__items__"  # values dict entry holding [(name, qty, detail), ...]
LINES_KEY = "__lines__"  # rows mode: an order record's item rows
DEFAULT_HIDDEN_VARIANTS = ["Default", "Regular", "Standard"]

# Guesses for the extra per-item columns in rows mode.
_VARIANT_NAMES = ["variant", "size", "portion", "option"]
_DETAIL_NAMES = ["modifiers", "modifier", "customizations", "customization", "add ons", "item notes", "options"]
_GROUP_NAMES = ["order", "order #", "order number", "order id", "order no"]

# Headers that are never menu items even if their cells hold numbers.
_NOT_ITEM_WORDS = re.compile(
    r"\b(fee|fees|total|totals|subtotal|cost|price|paid|tip|tax|discount|amount|balance|due|"
    r"instructions?|notes?|phone)\b", re.I)


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9#]+", " ", s.lower()).strip()


def slugify(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_") or "field"


def format_phone(value: str) -> str:
    digits = re.sub(r"\D", "", value)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) == 10 and re.fullmatch(r"[\d\s().+-]+", value):
        return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
    return value


def _is_quantity(value: str) -> bool:
    return bool(re.fullmatch(r"\d+(\.\d+)?", value.strip()))


def _qty_number(value: str) -> float | None:
    try:
        return float(value)
    except ValueError:
        return None


# One item inside an item-list cell: "Teriyaki Steak Tips (3x Regular)" or a modifier "Asparagus 1 cup (1x)".
_ITEM_RE = re.compile(r"^(?P<name>.+?)\s*\((?P<qty>\d+(?:\.\d+)?)\s*x(?:\s+(?P<variant>[^()]*?))?\)\s*$", re.I)


def _qty_text(q: str) -> str:
    return q[:-2] if q.endswith(".0") else q


def with_variant(name: str, variant: str, hidden: list[str]) -> str:
    """Add "(Small)" etc. after an item name, unless hidden (Regular/Default) or already in the name."""
    variant = (variant or "").strip()
    if variant and variant.lower() not in {h.lower() for h in hidden} and variant.lower() not in name.lower():
        return f"{name} ({variant})"
    return name


def parse_item_list(text: str, hidden_variants: list[str]) -> list[tuple[str, str, str]] | None:
    """Parse a whole order written in one cell, e.g.

        Custom Chicken (2x Default); Modifiers: Grilled Chicken Breast 4oz (1x); Broccoli 1 cup (1x);
        Teriyaki Steak Tips (1x Regular); $10 delivery (1x Default);

    -> [("Custom Chicken", "2", "Grilled Chicken Breast 4oz, Broccoli 1 cup"),
        ("Teriyaki Steak Tips", "1", "")]

    Items carry "(Nx Size)"; the parts after "Modifiers:" carry "(Nx)" and belong to the item
    before them. Fee lines starting with "$" are skipped. Returns None if the cell isn't in
    this format (so plain lists still work)."""
    segments = [seg.strip() for seg in re.split(r"[;\n]", text or "") if seg.strip()]
    if not segments or not any(_ITEM_RE.match(re.sub(r"(?i)^modifiers:\s*", "", seg)) for seg in segments):
        return None
    items: list[list] = []
    in_modifiers = False
    for seg in segments:
        is_mod_start = bool(re.match(r"(?i)^modifiers:", seg))
        if is_mod_start:
            seg = re.sub(r"(?i)^modifiers:\s*", "", seg)
            in_modifiers = True
        m = _ITEM_RE.match(seg)
        new_item = m is not None and not is_mod_start and (bool(m.group("variant")) or not in_modifiers)
        if new_item:
            in_modifiers = False
            name = m.group("name").strip()
            if name.startswith("$"):  # a fee, not something to pack
                items.append(None)
                continue
            items.append([with_variant(name, m.group("variant") or "", hidden_variants),
                          _qty_text(m.group("qty")), []])
        elif items and items[-1] is not None:
            items[-1][2].append(seg)
        elif not items:
            items.append([seg, "", []])
    return [(n, q, clean_detail("; ".join(d))) for n, q, d in (i for i in items if i is not None)]


def clean_detail(text: str) -> str:
    """'Grilled Salmon 4oz (1x); Asparagus 1 cup (2x); ' -> 'Grilled Salmon 4oz, Asparagus 1 cup (2x)'."""
    text = re.sub(r"<[^>]+>", " ", text or "")
    parts = [re.sub(r"\s*\(1x\)$", "", p.strip()) for p in re.split(r"[;\n]", text)]
    return ", ".join(" ".join(p.split()) for p in parts if p.strip())


def split_camel(value: str) -> str:
    """'InStorePickup' -> 'In Store Pickup' (only for single CamelCase words)."""
    if " " in value or not re.fullmatch(r"[A-Za-z]+", value):
        return value
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", value)


@dataclass
class Mapping:
    fields: list[dict] = field(default_factory=lambda: [dict(f) for f in DEFAULT_FIELDS])
    columns: dict[str, str] = field(default_factory=dict)  # field key -> header ("" = not used)
    items_mode: str = "single"   # "columns" or "single"
    items_after: str = ""        # columns mode: item columns start after this header ("" = first column)
    items_before: str = ""       # ...and stop before this header ("" = last column)
    group_by: str = ""           # rows mode: rows with the same value here are one order
    variant_col: str = ""        # rows mode: optional size/variant column, shown after the item name
    detail_col: str = ""         # rows mode: optional per-item details (e.g. custom-meal components)
    hidden_variants: list[str] = field(default_factory=lambda: list(DEFAULT_HIDDEN_VARIANTS))

    # -- fields ------------------------------------------------------------
    def all_fields(self) -> list[dict]:
        return self.fields + COMPUTED_FIELDS

    def field_label(self, key: str) -> str:
        for f in self.all_fields():
            if f["key"] == key:
                return f["label"]
        return key

    def field_keys(self) -> list[str]:
        return [f["key"] for f in self.all_fields()]

    def column_fields(self) -> list[dict]:
        """Fields matched one-to-one with a column (item columns are handled separately in columns mode)."""
        if self.items_mode == "columns":
            return [f for f in self.fields if f["key"] not in ITEM_KEYS]
        return list(self.fields)

    def add_field(self, label: str) -> str:
        label = label.strip()
        base = slugify(label)
        key, n = base, 2
        while key in self.field_keys():
            key, n = f"{base}_{n}", n + 1
        self.fields.append({"key": key, "label": label, "sample": label, "aliases": [label.lower()]})
        return key

    def remove_field(self, key: str) -> None:
        self.fields = [f for f in self.fields if f["key"] != key]
        self.columns.pop(key, None)

    # -- orders --------------------------------------------------------------
    def records(self, rows: list[dict[str, str]]) -> list[dict]:
        """One record per pack slip. In rows mode, the item rows of each order are grouped
        (orders keep the order they first appear in); otherwise each row is a slip."""
        if self.items_mode != "rows" or not self.group_by:
            return rows
        orders: dict[str, dict] = {}
        for i, row in enumerate(rows):
            key = (row.get(self.group_by) or "").strip() or f"__row{i}"
            rec = orders.get(key)
            if rec is None:
                rec = orders[key] = dict(row)
                rec[LINES_KEY] = []
            rec[LINES_KEY].append(row)
        return list(orders.values())

    def extra_columns(self) -> list[tuple[str, str]]:
        """(purpose, header) for the rows-mode columns that aren't ordinary fields."""
        if self.items_mode != "rows":
            return []
        return [(label, col) for label, col in (("Order grouping", self.group_by), ("Item size / variant",
                self.variant_col), ("Item details", self.detail_col)) if col]

    # -- menu items ----------------------------------------------------------
    def item_headers(self, headers: list[str]) -> list[str]:
        if self.items_mode != "columns":
            return []
        start = headers.index(self.items_after) + 1 if self.items_after in headers else 0
        end = headers.index(self.items_before) if self.items_before in headers else len(headers)
        taken = {v for k, v in self.columns.items() if v and k not in ITEM_KEYS}
        return [h for h in headers[start:end] if h not in taken]

    def item_rows(self, row: dict) -> list[tuple[str, str, str]]:
        """[(item name, quantity, detail)] for one customer, skipping items they didn't order."""
        if self.items_mode == "columns":
            out = []
            for h in self.item_headers([k for k in row.keys() if k != LINES_KEY]):
                v = (row.get(h) or "").strip()
                if not v or v in ("0", "No") or (_qty_number(v) is not None and _qty_number(v) <= 0):
                    continue
                out.append((h, v, ""))
            return out
        if self.items_mode == "rows":
            name_col, qty_col = self.columns.get("items"), self.columns.get("quantity")
            out = []
            for line in row.get(LINES_KEY, [row]):
                name = (line.get(name_col, "") if name_col else "").strip()
                qty = (line.get(qty_col, "") if qty_col else "").strip()
                if not name or (_qty_number(qty) is not None and _qty_number(qty) <= 0):
                    continue
                name = with_variant(name, line.get(self.variant_col, "") if self.variant_col else "",
                                    self.hidden_variants)
                detail = clean_detail(line.get(self.detail_col, "")) if self.detail_col else ""
                out.append((name, qty, detail))
            return out
        names_col, qty_col = self.columns.get("items"), self.columns.get("quantity")
        parsed = parse_item_list(row.get(names_col, "") if names_col else "", self.hidden_variants)
        if parsed is not None:  # "Name (2x Regular); Name (1x Small); Modifiers: ..." in one cell
            return parsed
        names = [n.strip() for n in (row.get(names_col, "") if names_col else "").split("\n") if n.strip()]
        qtys = [q.strip() for q in (row.get(qty_col, "") if qty_col else "").split("\n")]
        if len(names) == 1 and ("," in names[0] or ";" in names[0]) and not qty_col:
            names = [n.strip() for n in re.split(r"[;,]", names[0]) if n.strip()]
        return [(n, qtys[i] if i < len(qtys) else "", "") for i, n in enumerate(names)]

    # -- values ------------------------------------------------------------
    def values_for_row(self, row: dict[str, str]) -> dict:
        vals: dict = {}
        for f in self.fields:
            col = self.columns.get(f["key"])
            vals[f["key"]] = row.get(col, "") if col else ""
        if vals.get("phone"):
            vals["phone"] = format_phone(vals["phone"])
        if vals.get("fulfillment"):
            vals["fulfillment"] = split_camel(vals["fulfillment"])
            # A store "location" on a delivery order is where it ships from, not a pickup spot.
            if re.search(r"deliver|ship", vals["fulfillment"], re.I):
                vals["pickup_location"] = vals["pickup_time"] = ""
        items = self.item_rows(row)
        vals[ITEMS_KEY] = items
        if self.items_mode in ("columns", "rows"):
            vals["items"] = "\n".join(n for n, _, _ in items)
            vals["quantity"] = "\n".join(q for _, q, _ in items)
        nums = [_qty_number(q) for _, q, _ in items]
        if items and all(n is not None for n in nums):
            total = sum(nums)
            vals["item_count"] = str(int(total)) if float(total).is_integer() else f"{total:g}"
        else:
            vals["item_count"] = str(len(items)) if items else ""
        return vals

    def sample_values(self) -> dict:
        vals = {f["key"]: f.get("sample", f["label"]) for f in self.all_fields()}
        names = DEFAULT_FIELDS[-2]["sample"].split("\n")
        qtys = DEFAULT_FIELDS[-1]["sample"].split("\n")
        vals[ITEMS_KEY] = [(n, q, "") for n, q in zip(names, qtys)]
        return vals

    # -- validation -----------------------------------------------------------
    def missing_columns(self, headers: list[str], used_keys: set[str] | None = None) -> list[tuple[str, str]]:
        """(what it's for, expected header) for mapped columns absent from `headers`."""
        present = set(headers)
        out = []
        for f in self.column_fields():
            if used_keys is not None and f["key"] not in used_keys:
                continue
            col = self.columns.get(f["key"], NOT_USED)
            if col and col not in present:
                out.append((f["label"], col))
        uses_items = used_keys is None or bool(used_keys & (ITEM_KEYS | {"item_count", ITEMS_KEY}))
        if self.items_mode == "columns" and uses_items:
            for label, col in (("Start of menu items", self.items_after), ("End of menu items", self.items_before)):
                if col and col not in present:
                    out.append((label, col))
        if self.items_mode == "rows":
            if self.group_by and self.group_by not in present:  # needed even if items aren't shown
                out.append(("Order grouping", self.group_by))
            if uses_items:
                for f in self.fields:  # items/quantity are skipped above when not in used_keys
                    col = self.columns.get(f["key"])
                    if f["key"] in ITEM_KEYS and col and col not in present and (f["label"], col) not in out:
                        out.append((f["label"], col))
                out += [(lab, col) for lab, col in self.extra_columns()[1:] if col not in present]
        return out

    def fit_score(self, headers: list[str], used_keys: set[str] | None = None) -> int:
        """How well this mapping fits a spreadsheet: -1 if columns it needs are missing,
        else the number of its columns found (0 = nothing matched)."""
        if self.is_empty() or self.missing_columns(headers, used_keys):
            return -1
        present = set(headers)
        score = sum(1 for k, v in self.columns.items() if v and v in present and k not in ITEM_KEYS)
        if self.items_mode == "columns":
            score += 1 if self.item_headers(headers) else 0
        elif self.items_mode == "rows":
            score += sum(1 for _, col in self.extra_columns() if col in present)
            score += sum(1 for k in ITEM_KEYS if self.columns.get(k) in present)
        else:
            score += sum(1 for k in ITEM_KEYS if self.columns.get(k) in present)
        return score

    def fill_new_fields(self, headers: list[str]) -> bool:
        """Guess columns for fields that were never matched (e.g. added in an app update).
        Fields the user set to "(not used)" are left alone. Returns True if anything changed."""
        new = [f for f in self.fields if f["key"] not in self.columns and f["key"] not in ITEM_KEYS]
        if not new:
            return False
        taken = {v for v in self.columns.values() if v} | {self.group_by, self.variant_col, self.detail_col}
        guesses = guess_columns(new, [h for h in headers if h not in taken])
        for f in new:
            self.columns[f["key"]] = guesses.get(f["key"], "")
        return True

    def is_empty(self) -> bool:
        return self.items_mode != "columns" and not any(self.columns.values())

    # -- persistence -------------------------------------------------------
    def to_json(self) -> dict:
        return {"version": 3, "fields": self.fields, "columns": self.columns, "items_mode": self.items_mode,
                "items_after": self.items_after, "items_before": self.items_before, "group_by": self.group_by,
                "variant_col": self.variant_col, "detail_col": self.detail_col,
                "hidden_variants": self.hidden_variants}

    @classmethod
    def from_json(cls, data: dict) -> "Mapping":
        fields = [f for f in (data.get("fields") or [dict(f) for f in DEFAULT_FIELDS])
                  if f.get("key") not in COMPUTED_KEYS]
        known = {f.get("key") for f in fields}
        fields += [dict(f) for f in DEFAULT_FIELDS if f["key"] not in known]  # fields added in later versions
        mode = data.get("items_mode") if data.get("items_mode") in ("columns", "single", "rows") else "single"
        hidden = data.get("hidden_variants")
        return cls(fields=fields, columns=dict(data.get("columns") or {}), items_mode=mode,
                   items_after=data.get("items_after") or "", items_before=data.get("items_before") or "",
                   group_by=data.get("group_by") or "", variant_col=data.get("variant_col") or "",
                   detail_col=data.get("detail_col") or "",
                   hidden_variants=list(hidden) if isinstance(hidden, list) else list(DEFAULT_HIDDEN_VARIANTS))


def guess_columns(fields: list[dict], headers: list[str]) -> dict[str, str]:
    """Best-effort automatic match of fields to headers, each header used once."""
    normed = {h: _norm(h) for h in headers}
    taken: set[str] = set()
    result: dict[str, str] = {}

    def candidates(f):
        # An alias starting with "=" only matches a heading exactly (e.g. "=order" must not
        # match "Order Received" or "Corporate Order").
        out = [(_norm(f["label"]), False)]
        for a in f.get("aliases", []):
            out.append((_norm(a[1:]), True) if a.startswith("=") else (_norm(a), False))
        return out

    # Pass 1: exact matches (in alias priority order). Pass 2: header contains alias as a word.
    for exact in (True, False):
        for f in fields:
            if f["key"] in result:
                continue
            for cand, exact_only in candidates(f):
                if not cand or (exact_only and not exact):
                    continue
                for h, nh in normed.items():
                    if h in taken:
                        continue
                    hit = nh == cand if exact else (len(cand) >= 3 and re.search(rf"\b{re.escape(cand)}\b", nh))
                    if hit:
                        result[f["key"]] = h
                        taken.add(h)
                        break
                if f["key"] in result:
                    break
    return result


def guess_item_columns(headers: list[str], rows: list[dict[str, str]], taken: set[str]) -> tuple[str, str] | None:
    """Find the longest run of adjacent 'quantity' columns. Returns (after, before) anchors."""
    def is_item_col(h):
        if h in taken or _NOT_ITEM_WORDS.search(h):
            return False
        vals = [r.get(h, "").strip() for r in rows]
        filled = [v for v in vals if v]
        return all(_is_quantity(v) for v in filled)

    best, cur = (0, 0), None
    for i, h in enumerate(headers):
        if is_item_col(h):
            cur = (cur[0], i + 1) if cur else (i, i + 1)
            if cur[1] - cur[0] > best[1] - best[0]:
                best = cur
        else:
            cur = None
    start, end = best
    if end - start < 2:
        return None
    return (headers[start - 1] if start > 0 else "", headers[end] if end < len(headers) else "")


def _find_header(headers: list[str], names: list[str], taken: set[str]) -> str:
    normed = {h: _norm(h) for h in headers if h not in taken}
    for name in names:  # exact first, then whole-word contains
        for h, nh in normed.items():
            if nh == _norm(name):
                return h
    for name in names:
        for h, nh in normed.items():
            if re.search(rf"\b{re.escape(_norm(name))}\b", nh):
                return h
    return ""


def guess_line_items(headers: list[str], rows: list[dict[str, str]], cols: dict[str, str]) -> dict | None:
    """Detect a one-row-per-item export: an order (or customer) column whose values repeat
    on neighbouring rows, plus an item-name column. Returns rows-mode settings or None."""
    if len(rows) < 2:
        return None
    item_fields = [f for f in DEFAULT_FIELDS if f["key"] in ITEM_KEYS]
    taken = {v for v in cols.values() if v}
    item_cols = guess_columns(item_fields, [h for h in headers if h not in taken])
    if not item_cols.get("items"):
        return None
    candidates = [c for c in (cols.get("order_number"), _find_header(headers, _GROUP_NAMES, set()),
                              cols.get("customer_name")) if c]
    for col in candidates:
        vals = [(r.get(col) or "").strip() for r in rows]
        repeats = sum(1 for a, b in zip(vals, vals[1:]) if a and a == b)
        if repeats >= max(1, len(rows) // 10):
            used = taken | set(item_cols.values()) | {col}
            variant = _find_header(headers, _VARIANT_NAMES, used)
            detail = _find_header(headers, _DETAIL_NAMES, used | {variant})
            return {"group_by": col, "items": item_cols["items"], "quantity": item_cols.get("quantity", ""),
                    "variant_col": variant, "detail_col": detail}
    return None


def auto_map(mapping: Mapping, headers: list[str], rows: list[dict[str, str]]) -> Mapping:
    """Fill in a mapping's columns and item settings from a spreadsheet."""
    mapping.group_by = mapping.variant_col = mapping.detail_col = ""
    base = guess_columns([f for f in mapping.fields if f["key"] not in ITEM_KEYS], headers)
    lines = guess_line_items(headers, rows, base)
    if lines:
        mapping.items_mode = "rows"
        mapping.items_after = mapping.items_before = ""
        mapping.columns = dict(base, items=lines["items"], quantity=lines["quantity"])
        mapping.group_by, mapping.variant_col, mapping.detail_col = (
            lines["group_by"], lines["variant_col"], lines["detail_col"])
        return mapping
    anchors = guess_item_columns(
        headers, rows, set(guess_columns([f for f in mapping.fields if f["key"] not in ITEM_KEYS], headers).values()))
    if anchors:
        mapping.items_mode = "columns"
        mapping.items_after, mapping.items_before = anchors
        mapping.columns = guess_columns([f for f in mapping.fields if f["key"] not in ITEM_KEYS], headers)
    else:
        mapping.items_mode = "single"
        mapping.items_after = mapping.items_before = ""
        mapping.columns = guess_columns(mapping.fields, headers)
    return mapping


# -- persistence: one set of column matches per layout ---------------------------
#
# Each layout (template) has its own matches, so two businesses with different
# spreadsheets can each have a layout that reads their own columns.

def _legacy_path():
    return storage.data_dir() / "mapping.json"  # before matches were per layout


def mapping_path(layout: str):
    d = storage.data_dir() / "mappings"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{storage.safe_filename(layout)}.json"


def load_mapping(layout: str) -> Mapping | None:
    data = storage.read_json(mapping_path(layout))
    return Mapping.from_json(data) if data else None


def save_mapping(m: Mapping, layout: str) -> None:
    storage.write_json(mapping_path(layout), m.to_json())


def delete_mapping(layout: str) -> None:
    mapping_path(layout).unlink(missing_ok=True)


def rename_mapping(old: str, new: str) -> None:
    src = mapping_path(old)
    if src.exists():
        src.replace(mapping_path(new))


def copy_mapping(src: str, dst: str) -> None:
    m = load_mapping(src)
    if m is not None:
        save_mapping(m, dst)


def migrate_legacy_mapping(layouts: list[str]) -> None:
    """Give every existing layout a copy of the old app-wide matches (one time)."""
    legacy = _legacy_path()
    data = storage.read_json(legacy)
    if not data:
        return
    for name in layouts:
        if not mapping_path(name).exists():
            storage.write_json(mapping_path(name), data)
    legacy.replace(legacy.with_name("mapping.json.migrated"))
