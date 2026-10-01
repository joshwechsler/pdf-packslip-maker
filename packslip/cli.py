"""Command-line entry points (for the Owner/CI, not the Operator).

    "Pack Slip Maker" [file.xlsx]                 open the app (optionally with a file)
    "Pack Slip Maker" --generate in.xlsx [--out out.pdf] [--template NAME]
    "Pack Slip Maker" --selftest [--out out.pdf]  build a PDF from generated data; exit 0 if OK
    "Pack Slip Maker" --selftest-gui              open and close every window; exit 0 if OK
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import time
from pathlib import Path


def _selftest(out: str | None) -> int:
    import datetime as dt

    from openpyxl import Workbook
    from PIL import Image, ImageDraw

    tmp = Path(tempfile.mkdtemp(prefix="packslip-selftest-"))
    os.environ["PACKSLIP_DATA_DIR"] = str(tmp / "data")

    from . import storage
    from . import template as T
    from .mapping import Mapping, guess_columns
    from .pdfgen import generate_pdf
    from .spreadsheet import load

    wb = Workbook()
    ws = wb.active
    ws.append(["Order No", "Customer", "Delivery Date", "Address", "Phone", "Items", "Qty", "Notes"])
    rows = 300
    for i in range(rows):
        ws.append([1000 + i, f"Customer {i} Ünïcode", dt.datetime(2026, 10, 1), "1 Main St\nTown",
                   "555-0100", "Bowl\nSalad\nBread", "1\n2\n3", "Leave at door" if i % 3 else None])
    xlsx = tmp / "orders.xlsx"
    wb.save(xlsx)

    logo = storage.assets_dir() / "logo.png"
    im = Image.new("RGBA", (300, 100), (31, 58, 95, 255))
    ImageDraw.Draw(im).rectangle((20, 20, 280, 80), fill=(200, 162, 74, 255))
    im.save(logo)

    sheet = load(xlsx)
    m = Mapping()
    m.columns = guess_columns(m.fields, sheet.headers)
    tpl = T.default_template()
    for el in tpl.elements:
        if el["type"] == "logo":
            el["image"] = "logo.png"
    out_path = Path(out) if out else tmp / "selftest.pdf"
    t0 = time.perf_counter()
    pages = generate_pdf(out_path, tpl, m, sheet)
    secs = time.perf_counter() - t0
    size = out_path.stat().st_size
    ok = pages == rows and size > 10_000 and secs < 30 and len([v for v in m.columns.values() if v]) == 8
    print(f"selftest: pages={pages} size={size} seconds={secs:.2f} mapped={m.columns} -> {'OK' if ok else 'FAIL'}")
    return 0 if ok else 1


def _selftest_gui() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="packslip-guitest-"))
    os.environ["PACKSLIP_DATA_DIR"] = str(tmp / "data")
    from .app import App, make_root
    from .designer import Designer
    from .mapping import Mapping

    root, dnd = make_root()
    app = App(root, dnd)
    root.update()
    d = Designer(root, app.tpl_var.get(), app.mapping or Mapping(), None)
    d.update()
    d._select(d.tpl.elements[3]["id"])
    d.update()
    d.dirty = False
    d.destroy()
    root.destroy()
    print(f"selftest-gui: OK (drag-and-drop {'available' if dnd else 'unavailable'})")
    return 0


def _generate(src: str, out: str | None, template_name: str | None) -> int:
    from . import template as T
    from .mapping import Mapping, guess_columns, load_mapping
    from .pdfgen import GenerateError, default_output_path, generate_pdf
    from .spreadsheet import SpreadsheetError, load

    try:
        sheet = load(src)
    except SpreadsheetError as e:
        print(e, file=sys.stderr)
        return 2
    m = load_mapping()
    if m is None or m.is_empty():
        m = Mapping()
        m.columns = guess_columns(m.fields, sheet.headers)
    names = T.ensure_default_template()
    tpl = T.load_template(template_name or names[0]) or T.default_template()
    out_path = Path(out) if out else default_output_path(sheet.path)
    try:
        n = generate_pdf(out_path, tpl, m, sheet)
    except GenerateError as e:
        print(e, file=sys.stderr)
        return 3
    print(f"{n} pages -> {out_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    # macOS may pass a "-psn_0_12345" process serial number on older systems.
    argv = [a for a in argv if not a.startswith("-psn_")]
    p = argparse.ArgumentParser(prog="packslip", add_help=True)
    p.add_argument("file", nargs="?")
    p.add_argument("--generate", metavar="XLSX")
    p.add_argument("--out")
    p.add_argument("--template")
    p.add_argument("--selftest", action="store_true")
    p.add_argument("--selftest-gui", action="store_true")
    args = p.parse_args(argv)

    if args.selftest:
        return _selftest(args.out)
    if args.selftest_gui:
        return _selftest_gui()
    if args.generate:
        return _generate(args.generate, args.out, args.template)

    from .app import run_gui
    run_gui(args.file)
    return 0
