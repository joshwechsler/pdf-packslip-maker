"""Text fitting shared by the PDF renderer and the designer preview.

Both use reportlab's font metrics so the on-screen preview wraps lines at the
same places as the printed PDF.
"""

from __future__ import annotations

from dataclasses import dataclass

from reportlab.pdfbase.pdfmetrics import getFont, stringWidth

LEADING = 1.2
MIN_SIZE = 6.0
PAD = 4.0  # inner padding (points) used when an element has a fill or border

_PDF_FONTS = {
    ("Helvetica", False, False): "Helvetica",
    ("Helvetica", True, False): "Helvetica-Bold",
    ("Helvetica", False, True): "Helvetica-Oblique",
    ("Helvetica", True, True): "Helvetica-BoldOblique",
    ("Times", False, False): "Times-Roman",
    ("Times", True, False): "Times-Bold",
    ("Times", False, True): "Times-Italic",
    ("Times", True, True): "Times-BoldItalic",
    ("Courier", False, False): "Courier",
    ("Courier", True, False): "Courier-Bold",
    ("Courier", False, True): "Courier-Oblique",
    ("Courier", True, True): "Courier-BoldOblique",
}


def pdf_font(family: str, bold: bool, italic: bool) -> str:
    return _PDF_FONTS.get((family, bool(bold), bool(italic)), "Helvetica")


def ascent(font_name: str, size: float) -> float:
    return getFont(font_name).face.ascent / 1000.0 * size


def sanitize(text: str) -> str:
    """Replace characters the built-in PDF fonts can't draw (they'd print as boxes)."""
    replacements = {"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-",
                    "—": "-", "…": "...", " ": " ", "\t": "    "}
    out = []
    for ch in text:
        ch = replacements.get(ch, ch)
        try:
            ch.encode("cp1252")
            out.append(ch)
        except UnicodeEncodeError:
            out.append("?")
    return "".join(out)


def _wrap_paragraph(para: str, font: str, size: float, width: float) -> list[str]:
    if not para:
        return [""]
    lines: list[str] = []
    cur = ""
    for word in para.split(" "):
        trial = f"{cur} {word}" if cur else word
        if stringWidth(trial, font, size) <= width:
            cur = trial
            continue
        if cur:
            lines.append(cur)
        # Break words that are wider than the box on their own.
        while stringWidth(word, font, size) > width and len(word) > 1:
            cut = len(word)
            while cut > 1 and stringWidth(word[:cut], font, size) > width:
                cut -= 1
            lines.append(word[:cut])
            word = word[cut:]
        cur = word
    lines.append(cur)
    return lines


def wrap(text: str, font: str, size: float, width: float) -> list[str]:
    lines: list[str] = []
    for para in text.split("\n"):
        lines.extend(_wrap_paragraph(para, font, size, width))
    return lines


@dataclass
class TextLayout:
    lines: list[str]
    font: str
    size: float

    @property
    def leading(self) -> float:
        return self.size * LEADING


def fit_text(text: str, family: str, bold: bool, italic: bool, size: float,
             width: float, height: float, shrink: bool = True) -> TextLayout:
    """Wrap text into width; shrink the font (if allowed) until it fits height.

    If it still doesn't fit at the minimum size, extra lines are cut and the
    last visible line ends with '...'.
    """
    font = pdf_font(family, bold, italic)
    text = sanitize(text)
    width = max(width, 1.0)
    size = max(float(size), 1.0)

    def fits(lines, s):
        return len(lines) * s * LEADING <= height + 0.01

    lines = wrap(text, font, size, width)
    if shrink:
        while not fits(lines, size) and size > MIN_SIZE:
            size = max(MIN_SIZE, size - 0.5)
            lines = wrap(text, font, size, width)

    max_lines = max(1, int((height + 0.01) // (size * LEADING)))
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1].rstrip()
        while last and stringWidth(last + "...", font, size) > width:
            last = last[:-1]
        lines[-1] = last + "..."
    return TextLayout(lines=lines, font=font, size=size)


def line_width(line: str, layout: TextLayout) -> float:
    return stringWidth(line, layout.font, layout.size)


def inner_box(el: dict) -> tuple[float, float, float, float]:
    """Content area of a text/field element (x, y, w, h), inset if it has a fill or border."""
    pad = PAD if (el.get("fill") or el.get("border")) else 0.0
    return el["x"] + pad, el["y"] + pad, max(el["w"] - 2 * pad, 1.0), max(el["h"] - 2 * pad, 1.0)


# -- items table ---------------------------------------------------------------
#
# Produces drawing primitives (page coordinates, top-left origin) so the PDF
# renderer and the designer preview draw exactly the same thing:
#   ("text", x, baseline_y, text, family, bold, italic, size, color, align)  align: left|right
#   ("rect", x, y, w, h, stroke_color)
#   ("line", x1, y1, x2, y2, color)

ROW_PAD = 0.5       # extra space per row, as a fraction of font size
DETAIL_SCALE = 0.8  # item details (e.g. custom-meal components) print smaller, under the name
DETAIL_COLOR = "#555555"


def _items_rows(items, family, size, name_w_total, show_boxes):
    regular, bold = pdf_font(family, False, False), pdf_font(family, True, False)
    italic = pdf_font(family, False, True)
    gap = size * 0.6
    box = size * 0.85 if show_boxes else 0.0
    qtys = [sanitize(it[1]) for it in items]
    qty_w = max([stringWidth(q, bold, size) for q in qtys] + [stringWidth("0", bold, size)])
    name_x = (box + gap if box else 0.0) + qty_w + gap
    name_w = max(name_w_total - name_x, 10.0)
    lead, dsize = size * LEADING, size * DETAIL_SCALE
    rows, y = [], 0.0
    for it, q in zip(items, qtys):
        lines = wrap(sanitize(it[0]), regular, size, name_w)
        detail = it[2] if len(it) > 2 else ""
        dlines = wrap(sanitize(detail), italic, dsize, name_w) if detail else []
        h = len(lines) * lead + len(dlines) * dsize * LEADING + size * ROW_PAD
        rows.append((q, lines, dlines, y, h))
        y += h
    return rows, y, box, gap, qty_w, name_x


def items_primitives(el: dict, items: list[tuple], color: str, line_color: str,
                     detail_color: str = DETAIL_COLOR) -> list[tuple]:
    """items: [(name, quantity, detail)] (detail optional)."""
    x, y0, w, h = el["x"], el["y"], el["w"], el["h"]
    family = el.get("font", "Helvetica")
    size = float(el.get("size", 12))
    show_boxes = el.get("show_boxes", True)
    if not items:
        return []

    rows, total, box, gap, qty_w, name_x = _items_rows(items, family, size, w, show_boxes)
    if el.get("shrink", True):
        while total > h + 0.01 and size > MIN_SIZE:
            size = max(MIN_SIZE, size - 0.5)
            rows, total, box, gap, qty_w, name_x = _items_rows(items, family, size, w, show_boxes)

    lead, dsize = size * LEADING, size * DETAIL_SCALE
    regular = pdf_font(family, False, False)
    asc = ascent(regular, size)
    out: list[tuple] = []
    overflow = 0
    if total > h + 0.01:  # still too long: keep what fits, then a "+ N more" line
        kept, used = [], 0.0
        for r in rows:
            if used + r[4] + lead > h + 0.01:
                break
            kept.append(r)
            used += r[4]
        overflow = len(rows) - len(kept)
        rows = kept

    for q, lines, dlines, ry, rh in rows:
        top = y0 + ry + size * ROW_PAD / 2
        base = top + asc
        if box:
            out.append(("rect", x, base - box * 0.85, box, box, color))
        out.append(("text", x + (box + gap if box else 0) + qty_w, base, q, family, True, False, size, color, "right"))
        for i, line in enumerate(lines):
            out.append(("text", x + name_x, base + i * lead, line, family, False, False, size, color, "left"))
        dbase = base + (len(lines) - 1) * lead + dsize * LEADING
        for i, line in enumerate(dlines):
            out.append(("text", x + name_x, dbase + i * dsize * LEADING, line, family, False, True, dsize,
                        detail_color, "left"))
        if el.get("row_lines", True) and line_color:
            out.append(("line", x, y0 + ry + rh, x + w, y0 + ry + rh, line_color))
    if overflow:
        end = rows[-1][3] + rows[-1][4] if rows else 0.0
        out.append(("text", x + name_x, y0 + end + size * ROW_PAD / 2 + asc,
                    f"+ {overflow} more item{'s' if overflow != 1 else ''} (not enough room - make this box bigger)",
                    family, False, True, size, color, "left"))
    return out
