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
