"""Snap-to-align for the layout editor: while a box is dragged or resized, its edges and centre
click into line with other boxes' edges and centres and with the page's margins and centre.

All values are page points (1/72 inch). `tol` is how close (in points) counts as "lined up".
"""

from __future__ import annotations

PAGE_MARGIN = 36.0  # 0.5 inch


def targets(elements: list[dict], exclude_id: str | None, page_w: float, page_h: float,
            margin: float = PAGE_MARGIN) -> tuple[list[float], list[float]]:
    """Lines a box can snap to: (x positions, y positions)."""
    xs = [margin, page_w - margin, page_w / 2]
    ys = [margin, page_h - margin, page_h / 2]
    for el in elements:
        if el.get("id") == exclude_id:
            continue
        xs += [el["x"], el["x"] + el["w"], el["x"] + el["w"] / 2]
        ys += [el["y"], el["y"] + el["h"], el["y"] + el["h"] / 2]
    return xs, ys


def _nearest(points: list[float], lines: list[float], tol: float) -> tuple[float, float | None]:
    """Smallest shift that puts one of `points` on one of `lines` (within tol): (shift, line)."""
    best_shift, best_line = 0.0, None
    for p in points:
        for line in lines:
            d = line - p
            if abs(d) <= tol and (best_line is None or abs(d) < abs(best_shift)):
                best_shift, best_line = d, line
    return best_shift, best_line


def snap_move(x: float, y: float, w: float, h: float, xs: list[float], ys: list[float],
              tol: float) -> tuple[float, float, float | None, float | None]:
    """A box moved to (x, y): snap its left/centre/right and top/middle/bottom.
    Returns (x, y, vertical guide x or None, horizontal guide y or None)."""
    dx, gx = _nearest([x, x + w / 2, x + w], xs, tol)
    dy, gy = _nearest([y, y + h / 2, y + h], ys, tol)
    return x + dx, y + dy, gx, gy


def snap_edge(value: float, lines: list[float], tol: float) -> tuple[float, float | None]:
    """One edge being resized: (snapped value, guide or None)."""
    d, line = _nearest([value], lines, tol)
    return value + d, line
