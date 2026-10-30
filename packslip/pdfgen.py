"""Render the combined multi-page PDF: one page per customer row (FR-7)."""

from __future__ import annotations

import datetime as dt
from contextlib import contextmanager
from pathlib import Path
from typing import Callable

from reportlab.lib.colors import HexColor
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas as rl_canvas

from . import APP_NAME, storage
from . import template as T
from .layout import ascent, fit_text, inner_box, items_primitives, line_width, pdf_font
from .delivery_list import draw_delivery_list
from .drivers import is_pickup, make_plan
from .mapping import ITEMS_KEY, Mapping
from .spreadsheet import Sheet
from .template import Template, element_text, resolve_color


class GenerateError(Exception):
    """A problem generating the PDF, worded for a non-technical reader."""


def _color(value: str):
    try:
        return HexColor(value)
    except (ValueError, TypeError):
        return HexColor("#000000")


class _ImageCache:
    def __init__(self, assets: Path):
        self.assets = assets
        self._cache: dict[str, ImageReader | None] = {}

    def get(self, name: str):
        if not name:
            return None
        if name not in self._cache:
            path = self.assets / name
            try:
                self._cache[name] = ImageReader(str(path)) if path.exists() else None
            except Exception:
                self._cache[name] = None
        return self._cache[name]


def draw_page(c, template: Template, values: dict[str, str], mapping: Mapping, images: _ImageCache,
              extra_bag: bool = False) -> None:
    """`extra_bag`: a second/third… bag's slip, which leaves out elements marked "first bag only"."""
    _, page_h = template.page_size
    brand = template.brand

    def flip(y, h):  # top-left coordinates -> reportlab bottom-left
        return page_h - y - h

    for el in template.elements:
        if extra_bag and el.get("first_bag_only"):
            continue
        x, y, w, h = el["x"], el["y"], el["w"], el["h"]
        etype = el["type"]

        fill = resolve_color(el.get("fill", ""), brand)
        border = resolve_color(el.get("border", ""), brand)
        if etype in ("box", "field", "text") and (fill or border):
            c.saveState()
            if fill:
                c.setFillColor(_color(fill))
            if border:
                c.setStrokeColor(_color(border))
                c.setLineWidth(float(el.get("border_width", 1.0) or 1.0))
            radius = float(el.get("radius", 0) or 0)
            if radius > 0:
                c.roundRect(x, flip(y, h), w, h, radius, stroke=1 if border else 0, fill=1 if fill else 0)
            else:
                c.rect(x, flip(y, h), w, h, stroke=1 if border else 0, fill=1 if fill else 0)
            c.restoreState()

        if etype == "logo":
            img = images.get(el.get("image", ""))
            if img is not None:
                c.drawImage(img, x, flip(y, h), w, h, preserveAspectRatio=True, anchor="c", mask="auto")
            continue

        if etype == "items":
            color = resolve_color(el.get("color", "#222222"), brand) or "#222222"
            line_color = resolve_color(el.get("line_color", ""), brand)
            for prim in items_primitives(el, values.get(ITEMS_KEY, []), color, line_color):
                _draw_primitive(c, prim, page_h)
            continue

        if etype not in ("field", "text"):
            continue
        text = element_text(el, values, mapping)
        if not text.strip():
            continue
        ix, iy, iw, ih = inner_box(el)
        lay = fit_text(text, el["font"], el["bold"], el["italic"], el["size"], iw, ih, el.get("shrink", True))
        c.setFillColor(_color(resolve_color(el.get("color", "#000000"), brand) or "#000000"))
        c.setFont(lay.font, lay.size)
        base = iy + ascent(lay.font, lay.size)
        for i, line in enumerate(lay.lines):
            ly = page_h - (base + i * lay.leading)
            if el["align"] == "center":
                c.drawString(ix + (iw - line_width(line, lay)) / 2, ly, line)
            elif el["align"] == "right":
                c.drawRightString(ix + iw, ly, line)
            else:
                c.drawString(ix, ly, line)


def _draw_primitive(c, prim, page_h: float) -> None:
    kind = prim[0]
    if kind == "text":
        _, x, base, text, family, bold, italic, size, color, align = prim
        c.setFillColor(_color(color))
        c.setFont(pdf_font(family, bold, italic), size)
        if align == "right":
            c.drawRightString(x, page_h - base, text)
        else:
            c.drawString(x, page_h - base, text)
    elif kind == "rect":
        _, x, y, w, h, color = prim
        c.saveState()
        c.setStrokeColor(_color(color))
        c.setLineWidth(0.9)
        c.rect(x, page_h - y - h, w, h, stroke=1, fill=0)
        c.restoreState()
    elif kind == "line":
        _, x1, y1, x2, y2, color = prim
        c.saveState()
        c.setStrokeColor(_color(color))
        c.setLineWidth(0.5)
        c.line(x1, page_h - y1, x2, page_h - y2)
        c.restoreState()


def check_ready(template: Template, mapping: Mapping, sheet: Sheet) -> None:
    """Raise GenerateError (FR-9) if mapped columns used by the layout are missing."""
    used = template.used_field_keys(mapping)
    missing = mapping.missing_columns(sheet.headers, used)
    if missing:
        lines = "\n".join(f"  • {label}  (expected a column called “{col}”)" for label, col in missing)
        raise GenerateError(
            "This spreadsheet is missing columns the pack slip needs:\n\n"
            f"{lines}\n\n"
            "The column headings may have been renamed. Click “Remap Fields” to match "
            "them up again, then generate."
        )
    if mapping.items_mode != "columns" and not any(mapping.columns.get(k) for k in used):
        raise GenerateError(
            "None of the fields on this layout are matched to a spreadsheet column yet.\n\n"
            "Click “Remap Fields” to match the pack-slip fields to your spreadsheet's columns."
        )


def blank_line_warnings(template: Template, mapping: Mapping, drivers_matched: int) -> list[str]:
    """Lines on the layout that will print empty on every slip because a setting is missing."""
    used = template.used_field_keys(mapping)
    out = []
    if "bag" in used and template.bag_size <= 0:
        out.append("This layout has a Bag line, but Max items per bag is 0 (off), so bag numbers will be "
                   "blank. Set it in Edit Layout (e.g. 10).")
    if used & {"driver", "driver_stop"} and drivers_matched <= 0:
        out.append("This layout has a Driver line, but no driver list is loaded (or none of its orders "
                   "matched), so driver names will be blank. Load the orders first, then click Driver List.")
    if used & {"ship_to", "ship_to_heading"} and not mapping.columns.get("fulfillment"):
        out.append("This layout has an Address / Pickup Location line, but the Delivery / Pickup field isn't "
                   "matched to a column, so pickup orders will look like deliveries. Click Remap Fields and "
                   "match it (e.g. “Fulfillment Type”).")
    return out


def format_delivery_date(d: dt.date) -> str:
    return f"{d:%a}, {d:%b} {d.day}, {d.year}"


def default_output_path(sheet_path: Path, delivery: dt.date | None = None, prefix: str = "Pack Slips") -> Path:
    folder = sheet_path.parent
    if delivery:
        stem = f"{prefix} - {sheet_path.stem} - delivery {delivery:%Y-%m-%d}"
    else:
        stem = f"{prefix} - {sheet_path.stem} - {dt.date.today():%Y-%m-%d}"
    out = folder / f"{stem}.pdf"
    n = 2
    while out.exists():
        out = folder / f"{stem} ({n}).pdf"
        n += 1
    return out


def bag_count(items: int, bag_size: int) -> int:
    """1-10 items -> 1 bag, 11-20 -> 2, ... (bag_size 0 = bags off)."""
    if bag_size <= 0 or items <= bag_size:
        return 1
    return -(-items // bag_size)


def item_total(values: dict) -> int:
    try:
        return int(float(values.get("item_count") or 0))
    except ValueError:
        return 0


def _name_key(values: dict) -> tuple:
    last = (values.get("last_name") or "").strip().lower()
    first = (values.get("first_name") or "").strip().lower()
    return (not (last or first), last, first)


@contextmanager
def _saving(out_path: Path):
    """Write to a temporary file, then move it into place; friendly errors if saving fails."""
    tmp = out_path.with_name(out_path.name + ".partial")
    try:
        yield tmp
        tmp.replace(out_path)
    except PermissionError:
        tmp.unlink(missing_ok=True)
        raise GenerateError(
            f"The PDF couldn't be saved in “{out_path.parent}”. You may not have permission "
            "to save files there, or a PDF with the same name is open."
        ) from None
    except OSError as e:
        tmp.unlink(missing_ok=True)
        raise GenerateError(f"The PDF couldn't be saved: {e.strerror or e}.") from None


def _all_values(mapping: Mapping, sheet: Sheet, extra: dict | None) -> list[dict]:
    """One values dict per order (orders grouped in rows mode), with `extra` added to each."""
    out = []
    for row in mapping.records(sheet.rows):
        values = mapping.values_for_row(row)
        values.update(extra or {})
        out.append(values)
    return out


def generate_pdf(out_path: str | Path, template: Template, mapping: Mapping, sheet: Sheet,
                 progress: Callable[[int, int], None] | None = None, extra: dict | None = None,
                 drivers: dict[int, str] | None = None, driver_order: list[str] | None = None,
                 stops: dict[int, int] | None = None) -> int:
    """`extra` values (e.g. the chosen delivery date) are added to every page.

    `drivers` maps record index -> driver name (from the driver list file). If any are set, the PDF
    starts with a delivery list (in route order); each slip shows its driver."""
    check_ready(template, mapping, sheet)
    out_path = Path(out_path)
    w, h = template.page_size
    images = _ImageCache(storage.assets_dir())
    all_values = _all_values(mapping, sheet, extra)
    total = len(all_values)
    with _saving(out_path) as tmp:
        c = rl_canvas.Canvas(str(tmp), pagesize=(w, h), pageCompression=1)
        c.setTitle(f"Pack Slips – {sheet.path.stem}")
        c.setCreator(APP_NAME)
        order = list(range(total))
        if drivers and any(drivers.values()):
            plan = make_plan(all_values, drivers, driver_order or [], stops)
            draw_delivery_list(c, plan, all_values, (extra or {}).get("delivery_date", ""))
            for i, (driver, stop) in plan.stop_of().items():
                all_values[i]["driver"] = driver
                # "Mike · Stop 5" when the driver list has stop numbers, otherwise just "Mike"
                all_values[i]["driver_stop"] = f"{driver} · Stop {stop}" if i in plan.given_stops else driver
        # Slips print A-Z by last name (then first name) so they're easy to find; orders with no name go last.
        order.sort(key=lambda i: _name_key(all_values[i]))
        for n, i in enumerate(order, 1):
            values = all_values[i]
            # Big delivery orders get one slip per bag; pickups always get one.
            bags = 1 if is_pickup(values) else bag_count(item_total(values), template.bag_size)
            for bag in range(1, bags + 1):
                values["bag"] = f"{bag}/{bags}" if template.bag_size > 0 else ""
                c.setPageSize((w, h))
                draw_page(c, template, values, mapping, images, extra_bag=bag > 1)
                c.showPage()
            if progress:
                progress(n, total)
        c.save()
    return total


def _wanted_for_labels(values: dict, which: str) -> bool:
    if which == "pickup":
        return is_pickup(values)
    if which == "delivery":
        return not is_pickup(values)
    return True


def generate_labels(out_path: str | Path, template: Template, mapping: Mapping, sheet: Sheet,
                    extra: dict | None = None) -> int:
    """Bag labels: one page (label) per bag, for the orders the label layout is for
    (e.g. pickups only), A-Z by last name. Returns the number of labels."""
    out_path = Path(out_path)
    if template.label_orders != "all" and not mapping.columns.get("fulfillment"):
        raise GenerateError(
            "The app can't tell pickup orders from deliveries yet: the “Delivery / Pickup” field isn't "
            "matched to a column.\n\nClick “Remap Fields” and match it (e.g. “Fulfillment Type”).")
    all_values = [v for v in _all_values(mapping, sheet, extra) if _wanted_for_labels(v, template.label_orders)]
    if not all_values:
        kind = T.LABEL_ORDERS.get(template.label_orders, "orders").lower()
        raise GenerateError(f"There are no {kind} in this spreadsheet, so there are no bag labels to make.\n\n"
                            "(Bag labels for pickup orders look for “pickup” in the Delivery / Pickup column.)")
    all_values.sort(key=_name_key)
    w, h = template.page_size
    images = _ImageCache(storage.assets_dir())
    labels = 0
    with _saving(out_path) as tmp:
        c = rl_canvas.Canvas(str(tmp), pagesize=(w, h), pageCompression=1)
        c.setTitle(f"Bag Labels – {sheet.path.stem}")
        c.setCreator(APP_NAME)
        for values in all_values:
            bags = bag_count(item_total(values), template.bag_size)
            for bag in range(1, bags + 1):
                values["bag"] = f"{bag}/{bags}"
                draw_page(c, template, values, mapping, images)
                c.showPage()
                labels += 1
        c.save()
    return labels


def generate_meal_labels(out_path: str | Path, sheet: Sheet, custom_template: Template, regular_template: Template,
                         sort: list[tuple[str, bool]] | None = None, filters: dict | None = None,
                         extra: dict | None = None) -> int:
    """Meal labels from the Label Data export: one page per row (after filters), in the chosen sort
    order; custom meals use custom_template, the rest regular_template. Returns the number of labels."""
    from .meal_labels import MealFields, filter_records, guess_meal_columns, read_records, sort_records
    out_path = Path(out_path)
    cols = guess_meal_columns(sheet.headers)
    if not cols.product:
        raise GenerateError("This file has no Product column, so it doesn't look like the meal label export.")
    records = sort_records(filter_records(read_records(sheet, cols), **(filters or {})), sort or [])
    if not records:
        raise GenerateError("No labels to make: the filters leave nothing from this file.\n\n"
                            "Check “Custom meals” / “Regular meals” and the other filters.")
    fields = MealFields(cols)
    images = _ImageCache(storage.assets_dir())
    with _saving(out_path) as tmp:
        c = rl_canvas.Canvas(str(tmp), pagesize=regular_template.page_size, pageCompression=1)
        c.setTitle(f"Meal Labels – {sheet.path.stem}")
        c.setCreator(APP_NAME)
        for rec in records:
            tpl = custom_template if rec["kind"] == "custom" else regular_template
            c.setPageSize(tpl.page_size)
            draw_page(c, tpl, {**rec, **(extra or {})}, fields, images)
            c.showPage()
        c.save()
    return len(records)


def render_preview_pdf(out_path: str | Path, template: Template, mapping: Mapping,
                       values: dict[str, str]) -> None:
    w, h = template.page_size
    c = rl_canvas.Canvas(str(out_path), pagesize=(w, h))
    draw_page(c, template, values, mapping, _ImageCache(storage.assets_dir()))
    c.showPage()
    c.save()
