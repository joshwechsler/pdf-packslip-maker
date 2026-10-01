"""Pack-slip fields and how they map to spreadsheet columns (FR-2, FR-3)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import storage

# Initial field list. Placeholder until the Owner supplies the real one (SRS §8).
# "sample" values are only used to preview a layout before a spreadsheet is loaded.
DEFAULT_FIELDS = [
    {"key": "customer_name", "label": "Customer Name", "sample": "Jane Smith",
     "aliases": ["customer", "name", "customer name", "client", "full name", "client name"]},
    {"key": "order_number", "label": "Order #", "sample": "1042",
     "aliases": ["order", "order #", "order number", "order no", "order id", "invoice", "invoice #"]},
    {"key": "delivery_date", "label": "Delivery Date", "sample": "Oct 2, 2026",
     "aliases": ["date", "delivery date", "ship date", "pickup date", "delivery day", "day"]},
    {"key": "address", "label": "Address", "sample": "123 Main St\nSpringfield, IL 62701",
     "aliases": ["address", "delivery address", "shipping address", "ship to", "street"]},
    {"key": "phone", "label": "Phone", "sample": "(555) 123-4567",
     "aliases": ["phone", "phone number", "mobile", "cell", "tel", "telephone"]},
    {"key": "items", "label": "Items", "sample": "Chicken Bowl\nGreek Salad\nBanana Bread",
     "aliases": ["items", "item", "products", "product", "order items", "meals", "description"]},
    {"key": "quantity", "label": "Quantity", "sample": "2\n1\n3",
     "aliases": ["qty", "quantity", "count", "quantities", "#"]},
    {"key": "notes", "label": "Notes", "sample": "Leave at the side door. No nuts please.",
     "aliases": ["notes", "note", "special instructions", "instructions", "comments", "comment", "allergies"]},
]

NOT_USED = ""


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9#]+", " ", s.lower()).strip()


def slugify(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_") or "field"


@dataclass
class Mapping:
    fields: list[dict] = field(default_factory=lambda: [dict(f) for f in DEFAULT_FIELDS])
    columns: dict[str, str] = field(default_factory=dict)  # field key -> header ("" = not used)

    # -- fields ------------------------------------------------------------
    def field_label(self, key: str) -> str:
        for f in self.fields:
            if f["key"] == key:
                return f["label"]
        return key

    def field_keys(self) -> list[str]:
        return [f["key"] for f in self.fields]

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

    # -- values ------------------------------------------------------------
    def values_for_row(self, row: dict[str, str]) -> dict[str, str]:
        return {f["key"]: row.get(self.columns.get(f["key"], ""), "") if self.columns.get(f["key"]) else ""
                for f in self.fields}

    def sample_values(self) -> dict[str, str]:
        return {f["key"]: f.get("sample", f["label"]) for f in self.fields}

    def missing_columns(self, headers: list[str], used_keys: set[str] | None = None) -> list[tuple[str, str]]:
        """(field label, expected header) for mapped columns absent from `headers`."""
        present = set(headers)
        out = []
        for f in self.fields:
            if used_keys is not None and f["key"] not in used_keys:
                continue
            col = self.columns.get(f["key"], NOT_USED)
            if col and col not in present:
                out.append((f["label"], col))
        return out

    def is_empty(self) -> bool:
        return not any(self.columns.values())

    # -- persistence -------------------------------------------------------
    def to_json(self) -> dict:
        return {"version": 1, "fields": self.fields, "columns": self.columns}

    @classmethod
    def from_json(cls, data: dict) -> "Mapping":
        fields = data.get("fields") or [dict(f) for f in DEFAULT_FIELDS]
        return cls(fields=fields, columns=dict(data.get("columns") or {}))


def guess_columns(fields: list[dict], headers: list[str]) -> dict[str, str]:
    """Best-effort automatic match of fields to headers, each header used once."""
    normed = {h: _norm(h) for h in headers}
    taken: set[str] = set()
    result: dict[str, str] = {}

    def candidates(f):
        return [_norm(f["label"])] + [_norm(a) for a in f.get("aliases", [])]

    # Pass 1: exact matches (in alias priority order). Pass 2: header contains alias.
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
                    hit = nh == cand if exact else (len(cand) > 2 and re.search(rf"\b{re.escape(cand)}\b", nh))
                    if hit:
                        result[f["key"]] = h
                        taken.add(h)
                        break
                if f["key"] in result:
                    break
    return result


def mapping_path():
    return storage.data_dir() / "mapping.json"


def load_mapping() -> Mapping | None:
    data = storage.read_json(mapping_path())
    return Mapping.from_json(data) if data else None


def save_mapping(m: Mapping) -> None:
    storage.write_json(mapping_path(), m.to_json())
