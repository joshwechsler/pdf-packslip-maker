"""Render docs/OPERATOR_GUIDE.md (simple Markdown subset) into a one-page PDF.

Usage: python tools/make_guide_pdf.py docs/OPERATOR_GUIDE.md out.pdf
"""

import re
import sys

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import ListFlowable, ListItem, Paragraph, SimpleDocTemplate, Spacer

NAVY = HexColor("#1F3A5F")
H1 = ParagraphStyle("h1", fontName="Helvetica-Bold", fontSize=22, leading=26, textColor=NAVY, spaceAfter=6)
H2 = ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=14, leading=18, textColor=NAVY,
                    spaceBefore=12, spaceAfter=4)
BODY = ParagraphStyle("body", fontName="Helvetica", fontSize=11, leading=15)


def inline(text):
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = text.replace("⌘", "Cmd ").replace("→", "&gt;").replace("–", "-")
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)


def build(md_path, out_path):
    story, items, kind = [], [], None

    def flush():
        nonlocal items, kind
        if items:
            story.append(ListFlowable(
                [ListItem(Paragraph(inline(t), BODY), leftIndent=18) for t in items],
                bulletType="1" if kind == "ol" else "bullet", start="1" if kind == "ol" else None,
                bulletFontName="Helvetica-Bold", leftIndent=18, spaceAfter=2))
            story.append(Spacer(1, 2))
        items, kind = [], None

    for raw in open(md_path, encoding="utf-8"):
        line = raw.rstrip()
        m_ol, m_ul = re.match(r"^\d+\.\s+(.*)", line), re.match(r"^[-*]\s+(.*)", line)
        if m_ol or m_ul:
            new_kind = "ol" if m_ol else "ul"
            if kind and kind != new_kind:
                flush()
            kind = new_kind
            items.append((m_ol or m_ul).group(1))
            continue
        flush()
        if line.startswith("# "):
            story.append(Paragraph(inline(line[2:]), H1))
        elif line.startswith("## "):
            story.append(Paragraph(inline(line[3:]), H2))
        elif line:
            story.append(Paragraph(inline(line), BODY))
            story.append(Spacer(1, 4))
    flush()
    doc = SimpleDocTemplate(out_path, pagesize=letter, leftMargin=54, rightMargin=54, topMargin=48,
                            bottomMargin=48, title="How to use Packs Be Slippin'")
    doc.build(story)


if __name__ == "__main__":
    build(sys.argv[1], sys.argv[2])
    from pypdf import PdfReader  # noqa: E402  (dev dependency; confirms the one-page promise)
    n = len(PdfReader(sys.argv[2]).pages)
    print(f"{sys.argv[2]}: {n} page(s)")
    if n != 1:
        sys.exit("Operator guide must fit on one page")
