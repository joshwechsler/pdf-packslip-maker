"""Pack-slip fields and how they map to spreadsheet columns (FR-2, FR-3).

Two ways a spreadsheet can list what a customer ordered:

  "columns" – one column per menu item, quantity in each cell (the real weekly
              sheet). Item columns are found *between two anchor columns*
              (e.g. after "Address", before "Delivery Fee"), so the mapping keeps
              working when the menu changes from week to week.
  "single"  – one cell holds the item list (and optionally a parallel quantity cell).
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
     "aliases": ["phone number", "phone", "mobile", "cell", "tel", "telephone"]},
    {"key": "address", "label": "Address", "sample": "123 Main St, Unit 4, Springfield, CT 06401",
     "aliases": ["address", "delivery address", "shipping address", "ship to", "street"]},
    {"key": "order_date", "label": "Order Date", "sample": "Sep 8, 2026 7:29 PM",
     "aliases": ["order received", "order date", "ordered", "date ordered", "timestamp", "received", "date"]},
    {"key": "delivery_date", "label": "Delivery Date", "sample": "Oct 2, 2026",
     "aliases": ["delivery date", "ship date", "pickup date", "delivery day"]},
    {"key": "order_number", "label": "Order #", "sample": "1042",
     "aliases": ["order #", "order number", "order no", "order id", "invoice #", "invoice number"]},
    {"key": "notes", "label": "Delivery Instructions", "sample": "Leave at the side door.",
     "aliases": ["delivery instructions", "special instructions", "instructions", "notes", "note",
                 "comments", "comment"]},
    {"key": "total", "label": "Total", "sample": "$89.50",
     "aliases": ["total cost", "order total", "total", "amount", "grand total"]},
    {"key": "paid", "label": "Paid", "sample": "No", "aliases": ["paid", "payment status", "payment"]},
    {"key": "items", "label": "Items", "sample": "Orange Chicken\nTexas Turkey Chili\nProtein Overnight Oats",
     "aliases": ["items", "item", "products", "order items", "meals", "description"]},
    {"key": "quantity", "label": "Quantity", "sample": "2\n1\n3",
     "aliases": ["qty", "quantity", "quantities"]},
]

# Always available on layouts; calculated, never matched to a column.
COMPUTED_FIELDS = [
    {"key": "item_count", "label": "Total Items", "sample": "6"},
]

ITEM_KEYS = {"items", "quantity"}
NOT_USED = ""
ITEMS_KEY = "__items__"  # values dict entry holding [(name, qty), ...]

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


@dataclass
class Mapping:
    fields: list[dict] = field(default_factory=lambda: [dict(f) for f in DEFAULT_FIELDS])
    columns: dict[str, str] = field(default_factory=dict)  # field key -> header ("" = not used)
    items_mode: str = "single"   # "columns" or "single"
    items_after: str = ""        # columns mode: item columns start after this header ("" = first column)
    items_before: str = ""       # ...and stop before this header ("" = last column)

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
        """Fields matched one-to-one with a column (items handled separately in columns mode)."""
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

    # -- menu items ----------------------------------------------------------
    def item_headers(self, headers: list[str]) -> list[str]:
        if self.items_mode != "columns":
            return []
        start = headers.index(self.items_after) + 1 if self.items_after in headers else 0
        end = headers.index(self.items_before) if self.items_before in headers else len(headers)
        taken = {v for k, v in self.columns.items() if v and k not in ITEM_KEYS}
        return [h for h in headers[start:end] if h not in taken]

    def item_rows(self, row: dict[str, str]) -> list[tuple[str, str]]:
        """[(item name, quantity)] for one customer, skipping items they didn't order."""
        if self.items_mode == "columns":
            out = []
            for h in self.item_headers(list(row.keys())):
                v = (row.get(h) or "").strip()
                if not v or v in ("0", "No") or (_qty_number(v) is not None and _qty_number(v) <= 0):
                    continue
                out.append((h, v))
            return out
        names_col, qty_col = self.columns.get("items"), self.columns.get("quantity")
        names = [n.strip() for n in (row.get(names_col, "") if names_col else "").split("\n") if n.strip()]
        qtys = [q.strip() for q in (row.get(qty_col, "") if qty_col else "").split("\n")]
        if len(names) == 1 and ("," in names[0] or ";" in names[0]) and not qty_col:
            names = [n.strip() for n in re.split(r"[;,]", names[0]) if n.strip()]
        return [(n, qtys[i] if i < len(qtys) else "") for i, n in enumerate(names)]

    # -- values ------------------------------------------------------------
    def values_for_row(self, row: dict[str, str]) -> dict:
        vals: dict = {}
        for f in self.fields:
            col = self.columns.get(f["key"])
            vals[f["key"]] = row.get(col, "") if col else ""
        if vals.get("phone"):
            vals["phone"] = format_phone(vals["phone"])
        items = self.item_rows(row)
        vals[ITEMS_KEY] = items
        if self.items_mode == "columns":
            vals["items"] = "\n".join(n for n, _ in items)
            vals["quantity"] = "\n".join(q for _, q in items)
        nums = [_qty_number(q) for _, q in items]
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
        vals[ITEMS_KEY] = list(zip(names, qtys))
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
        if self.items_mode == "columns" and (used_keys is None or used_keys & (ITEM_KEYS | {"item_count", ITEMS_KEY})):
            for label, col in (("Start of menu items", self.items_after), ("End of menu items", self.items_before)):
                if col and col not in present:
                    out.append((label, col))
        return out

    def is_empty(self) -> bool:
        return self.items_mode != "columns" and not any(self.columns.values())

    # -- persistence -------------------------------------------------------
    def to_json(self) -> dict:
        return {"version": 2, "fields": self.fields, "columns": self.columns, "items_mode": self.items_mode,
                "items_after": self.items_after, "items_before": self.items_before}

    @classmethod
    def from_json(cls, data: dict) -> "Mapping":
        fields = data.get("fields") or [dict(f) for f in DEFAULT_FIELDS]
        mode = data.get("items_mode") if data.get("items_mode") in ("columns", "single") else "single"
        return cls(fields=fields, columns=dict(data.get("columns") or {}), items_mode=mode,
                   items_after=data.get("items_after") or "", items_before=data.get("items_before") or "")


def guess_columns(fields: list[dict], headers: list[str]) -> dict[str, str]:
    """Best-effort automatic match of fields to headers, each header used once."""
    normed = {h: _norm(h) for h in headers}
    taken: set[str] = set()
    result: dict[str, str] = {}

    def candidates(f):
        return [_norm(f["label"])] + [_norm(a) for a in f.get("aliases", [])]

    # Pass 1: exact matches (in alias priority order). Pass 2: header contains alias as a word.
    for exact in (True, False):
        for f in fields:
            if f["key"] in result:
                continue
            for cand in candidates(f):
                if not cand:
                    continue
                for h, nh in normed.items():
                    if h in taken:
                        continue
                    hit = nh == cand if exact else (len(cand) > 3 and re.search(rf"\b{re.escape(cand)}\b", nh))
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


def auto_map(mapping: Mapping, headers: list[str], rows: list[dict[str, str]]) -> Mapping:
    """Fill in a mapping's columns and item settings from a spreadsheet."""
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


def mapping_path():
    return storage.data_dir() / "mapping.json"


def load_mapping() -> Mapping | None:
    data = storage.read_json(mapping_path())
    return Mapping.from_json(data) if data else None


def save_mapping(m: Mapping) -> None:
    storage.write_json(mapping_path(), m.to_json())
