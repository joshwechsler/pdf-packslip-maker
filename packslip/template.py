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
ORIENTATIONS = ["Portrait", "Landscape"]

FONTS = ["Helvetica", "Times", "Courier"]

# Black and white, to match the logo and print cleanly on any printer.
DEFAULT_BRAND = {"primary": "#000000", "accent": "#555555"}
# Earlier placeholder colours; layouts still using them are switched to black and white on load.
_OLD_PLACEHOLDER_BRAND = {"primary": "#1F3A5F", "accent": "#C8A24A"}

ELEMENT_DEFAULTS = {
    "field": {"field": "", "label": "", "font": "Helvetica", "size": 11, "bold": False, "italic": False,
              "align": "left", "color": "#222222", "fill": "", "border": "", "shrink": True,
              "split_lines": False, "bullets": False},
    "text": {"text": "Text", "font": "Helvetica", "size": 11, "bold": False, "italic": False,
             "align": "left", "color": "#222222", "fill": "", "border": "", "shrink": True},
    "logo": {"image": ""},
    "box": {"fill": "brand:primary", "border": "", "border_width": 1.0, "radius": 0.0},
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
    upgrades: list[str] = field(default_factory=list)  # one-time layout upgrades already applied
    landscape: bool = False
    bag_size: int = 0   # max items per bag; bigger orders get extra slips (0 = off)

    @property
    def page_size(self) -> tuple[float, float]:
        w, h = PAGE_SIZES.get(self.page, PAGE_SIZES[DEFAULT_PAGE])
        return (h, w) if self.landscape else (w, h)

    @property
    def orientation(self) -> str:
        return "Landscape" if self.landscape else "Portrait"

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
        return {"version": 1, "name": self.name, "page": self.page, "orientation": self.orientation,
                "bag_size": self.bag_size, "brand": self.brand, "elements": self.elements, "upgrades": self.upgrades}

    @classmethod
    def from_json(cls, data: dict) -> "Template":
        brand = dict(DEFAULT_BRAND)
        saved = data.get("brand") or {}
        if {k: str(v).upper() for k, v in saved.items()} != _OLD_PLACEHOLDER_BRAND:
            brand.update(saved)
        page = data.get("page") if data.get("page") in PAGE_SIZES else DEFAULT_PAGE
        t = cls(name=data.get("name") or "Untitled", page=page, brand=brand,
                elements=[normalize_element(e) for e in data.get("elements") or []],
                upgrades=list(data.get("upgrades") or []),
                landscape=str(data.get("orientation", "")).lower() == "landscape",
                bag_size=_int(data.get("bag_size")))
        _upgrade_pickup_and_access(t)
        _upgrade_driver(t)
        return t

    def copy(self, name: str | None = None) -> "Template":
        t = Template.from_json(copy.deepcopy(self.to_json()))
        if name:
            t.name = name
        return t


def _int(v) -> int:
    try:
        return max(0, int(v or 0))
    except (TypeError, ValueError):
        return 0


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
    """Copy the bundled logo into the user's assets folder, refreshing it if a new
    app version ships a changed logo. (Logos the user picks are stored under other names.)"""
    dest = storage.assets_dir() / DEFAULT_LOGO
    src = BUNDLED_ASSETS / DEFAULT_LOGO
    if src.exists() and (not dest.exists() or dest.read_bytes() != src.read_bytes()):
        shutil.copyfile(src, dest)
    return DEFAULT_LOGO if dest.exists() else ""


def _upgrade_pickup_and_access(t: "Template") -> None:
    """Layouts made for delivery/pickup orders (they show the Delivery / Pickup field) get the
    pickup-time and gate/access-code lines added once. Deleting them later is respected."""
    if "pickup_access" in t.upgrades:
        return
    t.upgrades.append("pickup_access")
    keys = {e.get("field") for e in t.elements if e["type"] == "field"}
    if "fulfillment" not in keys:
        return
    if "pickup_time" not in keys:
        t.elements.append(make_element("field", 400, 184, 176, 16, field="pickup_time", label="Pickup time:",
                                       size=11, align="right"))
    if "access_code" not in keys:
        t.elements.append(make_element("field", 36, 226, 360, 16, field="access_code", label="Access:",
                                       size=10, color="#555555"))


def _upgrade_driver(t: "Template") -> None:
    """Add the "Driver: Mike · Stop 3" line once (prints only when drivers are assigned)."""
    if "driver" in t.upgrades:
        return
    t.upgrades.append("driver")
    if not any(e.get("field") in ("driver", "driver_stop") for e in t.elements if e["type"] == "field"):
        t.elements.append(make_element("field", 316, 92, 260, 16, field="driver_stop", label="Driver:",
                                       size=12, bold=True, align="right"))


def default_template(name: str = "Standard") -> Template:
    """Starting layout, built around the weekly order sheet's columns."""
    E = make_element
    P, A = "brand:primary", "brand:accent"
    els = [
        E("box", 0, 0, 612, 12, fill=P),
        E("logo", 36, 40, 250, 30, image=install_default_logo()),
        E("text", 316, 36, 260, 30, text="PACKING SLIP", size=24, bold=True, align="right", color=P),
        E("field", 316, 72, 260, 18, field="delivery_date", label="Delivery Date:", size=13, bold=True,
          align="right"),
        E("field", 316, 92, 260, 16, field="driver_stop", label="Driver:", size=12, bold=True, align="right"),
        E("box", 36, 116, 540, 2, fill=A),
        E("text", 36, 132, 300, 14, text="CUSTOMER", size=9, bold=True, color=A),
        E("field", 36, 147, 360, 24, field="customer_name", size=18, bold=True),
        E("field", 36, 174, 360, 32, field="address", size=11),
        E("field", 36, 208, 360, 16, field="phone", size=11, color="#555555"),
        # How the order gets to the customer. Each line only prints when the spreadsheet has it.
        E("field", 400, 147, 176, 18, field="fulfillment", size=12, bold=True, align="right"),
        E("field", 400, 167, 176, 16, field="pickup_location", label="Pickup at:", size=11, align="right"),
        E("field", 400, 184, 176, 16, field="time_window", label="Window:", size=11, align="right"),
        # Pickup time and delivery window never both apply, so they share a line.
        E("field", 400, 184, 176, 16, field="pickup_time", label="Pickup time:", size=11, align="right"),
        E("field", 400, 201, 176, 16, field="zone", label="Zone:", size=11, align="right", color="#555555"),
        E("field", 36, 226, 360, 16, field="access_code", label="Access:", size=10, color="#555555"),
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
    return Template(name=name, elements=els, upgrades=["pickup_access", "driver"])


LANDSCAPE_NAME = "Landscape"


def landscape_template(name: str = LANDSCAPE_NAME) -> Template:
    """Landscape Letter: the order on the left; address, instructions and a name/date/driver
    panel on the right (drawn from the Operator's sketch)."""
    E = make_element
    A = "brand:accent"
    els = [
        # Left: order details
        E("box", 36, 36, 372, 540, fill="", border="#000000", border_width=1.5, first_bag_only=True),
        E("text", 50, 48, 344, 18, text="ORDER DETAILS", size=13, bold=True, color="#000000",
          first_bag_only=True),
        E("box", 50, 70, 344, 1, fill="#000000", first_bag_only=True),
        E("items", 50, 78, 344, 486, size=12, first_bag_only=True),
        # Right: where it goes
        E("text", 432, 40, 324, 14, text="DELIVERY ADDRESS", size=9, bold=True, color=A),
        E("field", 432, 55, 324, 52, field="address", size=15, bold=True),
        E("field", 432, 109, 324, 16, field="access_code", label="Access:", size=11),
        E("field", 432, 127, 324, 16, field="pickup_location", label="Pickup at:", size=11),
        E("field", 432, 127, 324, 16, field="time_window", label="Window:", size=11, color="#555555"),
        E("text", 432, 152, 324, 14, text="DELIVERY INSTRUCTIONS", size=9, bold=True, color=A),
        E("field", 432, 167, 324, 150, field="notes", size=13),
        # Right, bottom: item count and the label panel
        E("box", 432, 400, 160, 32, fill="", border="#000000", border_width=1.5),
        E("text", 442, 408, 140, 18, text="TOTAL ITEMS", size=14, bold=True, color="#000000"),
        E("box", 604, 400, 64, 32, fill="", border="#000000", border_width=1.5),
        E("field", 606, 406, 60, 22, field="item_count", size=18, bold=True, align="center", color="#000000"),
        E("box", 432, 442, 324, 134, fill="", border="#000000", border_width=1.5),
        E("field", 446, 450, 296, 28, field="last_name", size=24, bold=True, color="#000000"),
        E("field", 446, 479, 296, 20, field="first_name", size=17, color="#000000"),
        E("field", 446, 503, 296, 17, field="delivery_date", label="Delivery:", size=13, color="#000000"),
        E("field", 446, 523, 296, 18, field="bag", label="Bag:", size=14, bold=True, color="#000000"),
        E("field", 446, 546, 296, 22, field="driver_stop", label="Driver:", size=15, bold=True, color="#000000"),
    ]
    return Template(name=name, elements=els, upgrades=["pickup_access", "driver"], landscape=True, bag_size=10)


# -- persistence -------------------------------------------------------------

def template_path(name: str) -> Path:
    return storage.templates_dir() / f"{storage.safe_filename(name)}.json"


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
    install_builtin_layouts()
    return list_templates()


def install_builtin_layouts() -> list[str]:
    """Add layouts shipped in an app update, once each (deleting one later is respected).
    A new layout gets a copy of the current layout's column matches so it works straight away."""
    from .mapping import copy_mapping  # local import: mapping doesn't depend on templates

    settings = storage.load_settings()
    done = settings.setdefault("builtin_layouts", [])
    added = []
    if LANDSCAPE_NAME not in done:
        done.append(LANDSCAPE_NAME)
        if not template_path(LANDSCAPE_NAME).exists():
            save_template(landscape_template())
            src = settings.get("template") or "Standard"
            copy_mapping(src if template_path(src).exists() else "Standard", LANDSCAPE_NAME)
            added.append(LANDSCAPE_NAME)
        storage.save_settings(settings)
    return added
