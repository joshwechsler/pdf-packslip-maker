"""Layout templates (FR-4, FR-5, FR-10): named JSON files, separate from the mapping.

Coordinates are PDF points (1/72 inch) measured from the page's TOP-LEFT corner.

Element types:
    field  – shows one spreadsheet value (optionally prefixed by a label)
    text   – fixed text; may contain {Field Name} placeholders
    logo   – an image file from the assets folder
    box    – a filled/outlined rectangle (brand bars, dividers, panels)
    items  – the customer's order as a table: tick box, quantity, item name
"""

from __future__ import annotations

import copy
import re
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from . import storage

PAGE_SIZES = {
    "Letter (8.5 × 11 in)": (612.0, 792.0),
    "Half Letter (5.5 × 8.5 in)": (396.0, 612.0),
    "A4": (595.28, 841.89),
    "Label (4 × 6 in)": (288.0, 432.0),
}
DEFAULT_PAGE = "Letter (8.5 × 11 in)"

FONTS = ["Helvetica", "Times", "Courier"]

# Placeholder brand colours until the Owner supplies real ones (SRS §8).
DEFAULT_BRAND = {"primary": "#1F3A5F", "accent": "#C8A24A"}

ELEMENT_DEFAULTS = {
    "field": {"field": "", "label": "", "font": "Helvetica", "size": 11, "bold": False, "italic": False,
              "align": "left", "color": "#222222", "fill": "", "border": "", "shrink": True,
              "split_lines": False, "bullets": False},
    "text": {"text": "Text", "font": "Helvetica", "size": 11, "bold": False, "italic": False,
             "align": "left", "color": "#222222", "fill": "", "border": "", "shrink": True},
    "logo": {"image": ""},
    "box": {"fill": "#1F3A5F", "border": "", "border_width": 1.0, "radius": 0.0},
    "items": {"font": "Helvetica", "size": 13, "color": "#222222", "show_boxes": True,
              "row_lines": True, "line_color": "#DDDDDD", "shrink": True},
}


def new_id() -> str:
    return uuid.uuid4().hex[:8]


def make_element(etype: str, x: float, y: float, w: float, h: float, **props) -> dict:
    el = {"id": new_id(), "type": etype, "x": float(x), "y": float(y), "w": float(w), "h": float(h)}
    el.update(copy.deepcopy(ELEMENT_DEFAULTS[etype]))
    el.update(props)
    return el


def normalize_element(el: dict) -> dict:
    etype = el.get("type", "text")
    if etype not in ELEMENT_DEFAULTS:
        etype = "text"
    out = {"id": el.get("id") or new_id(), "type": etype}
    out.update(copy.deepcopy(ELEMENT_DEFAULTS[etype]))
    for k, v in el.items():
        out[k] = v
    for k in ("x", "y", "w", "h"):
        out[k] = float(out.get(k, 0) or 0)
    out["w"] = max(out["w"], 1.0)
    out["h"] = max(out["h"], 1.0)
    if etype in ("field", "text", "items"):
        out["size"] = float(out.get("size") or 11)
        if out.get("font") not in FONTS:
            out["font"] = "Helvetica"
        if out.get("align") not in ("left", "center", "right"):
            out["align"] = "left"
    return out


@dataclass
class Template:
    name: str = "Standard"
    page: str = DEFAULT_PAGE
    brand: dict = field(default_factory=lambda: dict(DEFAULT_BRAND))
    elements: list[dict] = field(default_factory=list)

    @property
    def page_size(self) -> tuple[float, float]:
        return PAGE_SIZES.get(self.page, PAGE_SIZES[DEFAULT_PAGE])

    def find(self, element_id: str) -> dict | None:
        for el in self.elements:
            if el["id"] == element_id:
                return el
        return None

    def used_field_keys(self, mapping=None) -> set[str]:
        keys = {el["field"] for el in self.elements if el["type"] == "field" and el.get("field")}
        if any(el["type"] == "items" for el in self.elements):
            keys |= {"items", "quantity", "item_count"}
        if mapping is not None:
            for el in self.elements:
                if el["type"] == "text":
                    keys |= placeholder_keys(el.get("text", ""), mapping)
        return keys

    def to_json(self) -> dict:
        return {"version": 1, "name": self.name, "page": self.page, "brand": self.brand,
                "elements": self.elements}

    @classmethod
    def from_json(cls, data: dict) -> "Template":
        brand = dict(DEFAULT_BRAND)
        brand.update(data.get("brand") or {})
        page = data.get("page") if data.get("page") in PAGE_SIZES else DEFAULT_PAGE
        return cls(name=data.get("name") or "Untitled", page=page, brand=brand,
                   elements=[normalize_element(e) for e in data.get("elements") or []])

    def copy(self, name: str | None = None) -> "Template":
        t = Template.from_json(copy.deepcopy(self.to_json()))
        if name:
            t.name = name
        return t


_PLACEHOLDER = re.compile(r"\{([^{}]+)\}")


def _lookup_key(token: str, mapping) -> str | None:
    t = token.strip().lower()
    for f in mapping.all_fields():
        if t in (f["key"].lower(), f["label"].lower()):
            return f["key"]
    return None


def placeholder_keys(text: str, mapping) -> set[str]:
    return {k for k in (_lookup_key(m, mapping) for m in _PLACEHOLDER.findall(text)) if k}


def fill_placeholders(text: str, values: dict[str, str], mapping) -> str:
    def sub(m):
        key = _lookup_key(m.group(1), mapping)
        return values.get(key, "") if key else m.group(0)
    return _PLACEHOLDER.sub(sub, text)


def element_text(el: dict, values: dict[str, str], mapping) -> str:
    """The string an element shows for one customer (empty for non-text types)."""
    if el["type"] == "text":
        return fill_placeholders(el.get("text", ""), values, mapping)
    if el["type"] != "field":
        return ""
    value = values.get(el.get("field", ""), "")
    if el.get("split_lines") and value:
        parts = re.split(r"\s*(?:\n|;|,)\s*", value)
        parts = [p for p in parts if p]
        prefix = "• " if el.get("bullets") else ""
        value = "\n".join(prefix + p for p in parts)
    label = (el.get("label") or "").strip()
    if label and value:
        return f"{label} {value}"
    return value


def resolve_color(value: str, brand: dict) -> str:
    """Colours may be literal '#rrggbb' or 'brand:primary' / 'brand:accent'."""
    if not value:
        return ""
    if value.startswith("brand:"):
        return brand.get(value[6:], "#000000")
    return value


DEFAULT_LOGO = "meal_prep_logo.png"
BUNDLED_ASSETS = Path(__file__).resolve().parent / "assets"


def install_default_logo() -> str:
    """Copy the bundled logo into the user's assets folder (once). Returns its asset name."""
    dest = storage.assets_dir() / DEFAULT_LOGO
    src = BUNDLED_ASSETS / DEFAULT_LOGO
    if not dest.exists() and src.exists():
        shutil.copyfile(src, dest)
    return DEFAULT_LOGO if dest.exists() else ""


def default_template(name: str = "Standard") -> Template:
    """Starting layout, built around the weekly order sheet's columns."""
    E = make_element
    P, A = "brand:primary", "brand:accent"
    els = [
        E("box", 0, 0, 612, 12, fill=P),
        E("logo", 36, 40, 250, 30, image=install_default_logo()),
        E("text", 316, 36, 260, 30, text="PACKING SLIP", size=24, bold=True, align="right", color=P),
        E("field", 316, 72, 260, 16, field="order_date", label="Ordered:", size=11, align="right"),
        E("box", 36, 116, 540, 2, fill=A),
        E("text", 36, 132, 300, 14, text="DELIVER TO", size=9, bold=True, color=A),
        E("field", 36, 147, 360, 24, field="customer_name", size=18, bold=True),
        E("field", 36, 174, 360, 32, field="address", size=11),
        E("field", 36, 208, 360, 16, field="phone", size=11, color="#555555"),
        E("box", 36, 244, 540, 26, fill=P),
        E("text", 46, 252, 300, 14, text="ITEMS", size=10, bold=True, color="#FFFFFF"),
        E("text", 306, 252, 260, 14, text="Total items: {Total Items}", size=10, bold=True,
          align="right", color="#FFFFFF"),
        E("items", 46, 280, 520, 360),
        E("text", 36, 658, 300, 14, text="DELIVERY INSTRUCTIONS", size=9, bold=True, color=A),
        E("field", 36, 673, 540, 56, field="notes", size=11, border="#CCCCCC"),
        E("text", 36, 748, 540, 16, text="Thank you for your order!", size=10, italic=True,
          align="center", color="#777777"),
    ]
    return Template(name=name, elements=els)


# -- persistence -------------------------------------------------------------

def _safe_filename(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "_", name).strip(" .") or "Untitled"


def template_path(name: str) -> Path:
    return storage.templates_dir() / f"{_safe_filename(name)}.json"


def list_templates() -> list[str]:
    names = []
    for p in sorted(storage.templates_dir().glob("*.json")):
        data = storage.read_json(p)
        if isinstance(data, dict):
            names.append(data.get("name") or p.stem)
    return sorted(set(names), key=str.lower)


def load_template(name: str) -> Template | None:
    data = storage.read_json(template_path(name))
    if isinstance(data, dict):
        t = Template.from_json(data)
        t.name = name
        return t
    return None


def save_template(t: Template) -> None:
    storage.write_json(template_path(t.name), t.to_json())


def delete_template(name: str) -> None:
    try:
        template_path(name).unlink()
    except FileNotFoundError:
        pass


def ensure_default_template() -> list[str]:
    names = list_templates()
    if not names:
        save_template(default_template())
        names = list_templates()
    return names
