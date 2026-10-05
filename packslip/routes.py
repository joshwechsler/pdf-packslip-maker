"""Combine a separate route file (order/customer -> driver/route, optional stop #) with the orders.

Rows are matched by order number first (most reliable), then by customer name when the
order has no number or isn't in the route file under its number.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .mapping import guess_columns
from .spreadsheet import Sheet

ROUTE_FIELDS = [
    {"key": "order", "label": "Order number",
     "aliases": ["order #", "order number", "order no", "order id", "=order", "invoice #", "order"]},
    {"key": "customer", "label": "Customer name",
     "aliases": ["customer name", "customer", "name", "client", "full name", "recipient"]},
    {"key": "driver", "label": "Driver / Route",
     "aliases": ["driver", "driver name", "route", "route name", "assigned driver", "assigned to", "van",
                 "vehicle", "run"]},
    {"key": "stop", "label": "Stop # (optional)",
     "aliases": ["stop #", "stop number", "stop", "sequence", "seq", "stop order", "position"]},
]


def norm_order(v: str) -> str:
    """'#05704919' / ' 5704919 ' / '5704919.0' -> '5704919'."""
    v = (v or "").strip().lower()
    v = re.sub(r"\.0+$", "", v)
    v = re.sub(r"[^0-9a-z]", "", v)
    return v.lstrip("0") or v


def norm_name(v: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", (v or "").lower()).split())


def _stop_number(v: str) -> int | None:
    m = re.search(r"\d+", v or "")
    return int(m.group()) if m else None


@dataclass
class RouteColumns:
    order: str = ""
    customer: str = ""
    driver: str = ""
    stop: str = ""

    def to_json(self) -> dict:
        return {"order": self.order, "customer": self.customer, "driver": self.driver, "stop": self.stop}

    @classmethod
    def from_json(cls, d: dict | None) -> "RouteColumns":
        d = d or {}
        return cls(**{k: d.get(k, "") or "" for k in ("order", "customer", "driver", "stop")})

    def usable(self) -> bool:
        return bool(self.driver and (self.order or self.customer))

    def fits(self, headers: list[str]) -> bool:
        return self.usable() and all(c in headers for c in (self.order, self.customer, self.driver, self.stop) if c)


def guess_route_columns(headers: list[str]) -> RouteColumns:
    g = guess_columns(ROUTE_FIELDS, headers)
    return RouteColumns(order=g.get("order", ""), customer=g.get("customer", ""), driver=g.get("driver", ""),
                        stop=g.get("stop", ""))


def looks_like_route_file(sheet: Sheet) -> bool:
    """A sheet with a driver/route column and no obvious item columns."""
    cols = guess_route_columns(sheet.headers)
    itemish = any(re.search(r"\b(items?|product|qty|quantity|sku|modifiers)\b", h, re.I) for h in sheet.headers)
    return cols.usable() and not itemish


@dataclass
class RouteResult:
    assignment: dict[int, str] = field(default_factory=dict)   # record index -> driver/route
    stops: dict[int, int] = field(default_factory=dict)        # record index -> stop number
    unmatched: list[int] = field(default_factory=list)         # orders not found in the route file
    by_name: int = 0                                           # how many matched by name (not number)


def join_routes(route_sheet: Sheet, cols: RouteColumns, all_values: list[dict]) -> RouteResult:
    by_order: dict[str, dict] = {}
    by_name: dict[str, list[dict]] = {}
    for row in route_sheet.rows:
        if not (row.get(cols.driver) or "").strip():
            continue
        if cols.order and norm_order(row.get(cols.order, "")):
            # A row with an order number belongs to that order only, never to another order
            # by the same customer.
            by_order.setdefault(norm_order(row[cols.order]), row)
        elif cols.customer and norm_name(row.get(cols.customer, "")):
            by_name.setdefault(norm_name(row[cols.customer]), []).append(row)

    res = RouteResult()
    for i, v in enumerate(all_values):
        row = by_order.get(norm_order(v.get("order_number", ""))) if v.get("order_number") else None
        if row is None:
            candidates = by_name.get(norm_name(v.get("customer_name", "")), [])
            if len(candidates) == 1:  # only trust a name that appears once (among rows without a number)
                row = candidates[0]
                res.by_name += 1
        if row is None:
            res.unmatched.append(i)
            continue
        res.assignment[i] = " ".join(row[cols.driver].split())
        if cols.stop:
            n = _stop_number(row.get(cols.stop, ""))
            if n is not None:
                res.stops[i] = n
    return res
