"""Draw the delivery list pages (landscape Letter) at the front of the pack-slip PDF."""

from __future__ import annotations

from reportlab.lib.colors import HexColor

from .drivers import UNASSIGNED, Plan, town
from .layout import ascent, sanitize, wrap

PAGE_W, PAGE_H = 792.0, 612.0
MARGIN = 36.0
SIZE, LEAD = 8.5, 10.5
HEAD_FONT, BODY_FONT, BOLD_FONT = "Helvetica-Bold", "Helvetica", "Helvetica-Bold"

# (title, width, value function)
DELIVERY_COLUMNS = [
    ("", 18, lambda v, n: ""),                       # tick box
    ("Stop", 28, lambda v, n: str(n)),
    ("Customer", 110, lambda v, n: v.get("customer_name", "")),
    ("Address", 190, lambda v, n: "\n".join(x for x in (v.get("address", ""), ("Access: " + v["access_code"])
                                                          if v.get("access_code") else "") if x)),
    ("Phone", 80, lambda v, n: v.get("phone", "")),
    ("Window", 74, lambda v, n: "\n".join(x for x in (v.get("time_window", ""), v.get("zone", "")) if x)),
    ("Items", 32, lambda v, n: v.get("item_count", "")),
    ("Instructions", 0, lambda v, n: v.get("notes", "")),   # 0 = the rest of the width
]
PICKUP_COLUMNS = [
    ("", 18, lambda v, n: ""),
    ("#", 28, lambda v, n: str(n)),
    ("Customer", 160, lambda v, n: v.get("customer_name", "")),
    ("Phone", 100, lambda v, n: v.get("phone", "")),
    ("Pickup time", 90, lambda v, n: v.get("pickup_time", "")),
    ("Items", 40, lambda v, n: v.get("item_count", "")),
    ("Notes", 0, lambda v, n: v.get("notes", "")),
]


def _widths(columns):
    fixed = sum(w for _, w, _ in columns)
    rest = PAGE_W - 2 * MARGIN - fixed
    return [w or rest for _, w, _ in columns]


class _Table:
    def __init__(self, c, title: str, subtitle: str, columns):
        self.c, self.title, self.subtitle, self.columns = c, title, subtitle, columns
        self.widths = _widths(columns)
        self.y = None
        self.page_no = 0

    def _new_page(self):
        c = self.c
        if self.page_no:
            c.showPage()
        c.setPageSize((PAGE_W, PAGE_H))
        self.page_no += 1
        top = PAGE_H - MARGIN
        c.setFillColor(HexColor("#000000"))
        c.setFont(HEAD_FONT, 16)
        c.drawString(MARGIN, top - 14, sanitize(self.title + ("  (continued)" if self.page_no > 1 else "")))
        c.setFont(BODY_FONT, 10)
        c.drawRightString(PAGE_W - MARGIN, top - 12, sanitize(self.subtitle))
        y = top - 30
        c.setFillColor(HexColor("#000000"))
        c.rect(MARGIN, y - 16, PAGE_W - 2 * MARGIN, 16, stroke=0, fill=1)
        c.setFillColor(HexColor("#FFFFFF"))
        c.setFont(HEAD_FONT, SIZE)
        x = MARGIN
        for (title, _, _), w in zip(self.columns, self.widths):
            c.drawString(x + 3, y - 11.5, title)
            x += w
        self.y = y - 16

    def row(self, values: dict, n: int):
        c = self.c
        cells = []
        for (_, _, fn), w in zip(self.columns, self.widths):
            text = sanitize(str(fn(values, n) or ""))
            cells.append(wrap(text, BODY_FONT, SIZE, max(w - 6, 10)) if text else [])
        lines = max([len(x) for x in cells] + [1])
        h = lines * LEAD + 6
        if self.y is None or self.y - h < MARGIN:
            self._new_page()
        top = self.y
        c.setFillColor(HexColor("#000000"))
        x = MARGIN
        for i, (cell, w) in enumerate(zip(cells, self.widths)):
            if i == 0:  # tick box
                c.setLineWidth(0.8)
                c.rect(x + 4, top - 4 - SIZE, SIZE, SIZE, stroke=1, fill=0)
            font = BOLD_FONT if i in (1, 2) else BODY_FONT
            c.setFont(font, SIZE)
            for k, line in enumerate(cell):
                c.drawString(x + 3, top - 3 - ascent(font, SIZE) - k * LEAD, line)
            x += w
        c.setStrokeColor(HexColor("#CCCCCC"))
        c.setLineWidth(0.5)
        c.line(MARGIN, top - h, PAGE_W - MARGIN, top - h)
        c.setStrokeColor(HexColor("#000000"))
        self.y = top - h

    def finish(self):
        if self.page_no:
            self.c.showPage()


def draw_delivery_list(c, plan: Plan, all_values: list[dict], date_text: str) -> int:
    """Draw the list; returns the number of pages drawn. Leaves the canvas on a fresh page."""
    pages = 0
    for driver, idx in plan.routes:
        title = f"Driver: {driver}" if driver != UNASSIGNED else "Deliveries without a driver"
        towns = sorted({town(all_values[i].get("address", "")) for i in idx} - {""})
        items = sum(int(all_values[i].get("item_count") or 0) for i in idx
                    if str(all_values[i].get("item_count") or "").isdigit())
        sub = f"{date_text}  ·  {len(idx)} stop{'s' if len(idx) != 1 else ''}  ·  {items} items"
        if towns:
            sub += "  ·  " + ", ".join(towns[:4]) + ("…" if len(towns) > 4 else "")
        t = _Table(c, title, sub, DELIVERY_COLUMNS)
        stop_of = plan.stop_of()
        for n, i in enumerate(idx, 1):
            t.row(all_values[i], stop_of.get(i, (driver, n))[1])
        t.finish()
        pages += t.page_no
    for location, idx in plan.pickups:
        t = _Table(c, f"Pickups: {location}", f"{date_text}  ·  {len(idx)} order{'s' if len(idx) != 1 else ''}",
                   PICKUP_COLUMNS)
        for n, i in enumerate(idx, 1):
            t.row(all_values[i], n)
        t.finish()
        pages += t.page_no
    return pages
