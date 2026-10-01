"""Command-line entry points (for the Owner/CI, not the Operator).

    "Packs Be Slippin'" [file.xlsx]                 open the app (optionally with a file)
    "Packs Be Slippin'" --generate in.xlsx [--delivery-date YYYY-MM-DD] [--out out.pdf] [--template NAME]
    "Packs Be Slippin'" --selftest [--out out.pdf]  build a PDF from generated data; exit 0 if OK
    "Packs Be Slippin'" --selftest-gui              open and close every window; exit 0 if OK
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

    tmp = Path(tempfile.mkdtemp(prefix="packslip-selftest-"))
    os.environ["PACKSLIP_DATA_DIR"] = str(tmp / "data")

    from . import storage
    from . import template as T
    from .mapping import Mapping, auto_map
    from .pdfgen import generate_pdf
    from .spreadsheet import load

    wb = Workbook()
    ws = wb.active
    menu = ["Backyard Italian Pasta", "Orange Chicken", "Texas Turkey Chili", "Protein Overnight Oats"]
    ws.append(["Order Received", "Customer Name", "Phone Number", "Address", *menu,
               "Delivery Fee", "Total Cost", "Paid", "Delivery Instructions"])
    rows = 300
    for i in range(rows):
        ws.append([dt.datetime(2026, 9, 8, 19, 29), f"Customer {i} Ünïcode", 2035550100, "1 Main St, Town, CT",
                   1, i % 3, 2, None, 0, "$89.50", False, "Leave at door" if i % 3 else None])
    ws.append([None, "TOTALS", None, None, 300, 300, 600, 0, 0, None])
    xlsx = tmp / "orders.xlsx"
    wb.save(xlsx)

    sheet = load(xlsx)
    m = auto_map(Mapping(), sheet.headers, sheet.rows)
    tpl = T.default_template()
    logo_ok = any(el["type"] == "logo" and el.get("image") and (storage.assets_dir() / el["image"]).exists()
                  for el in tpl.elements)
    out_path = Path(out) if out else tmp / "selftest.pdf"
    t0 = time.perf_counter()
    pages = generate_pdf(out_path, tpl, m, sheet)
    secs = time.perf_counter() - t0
    size = out_path.stat().st_size
    items = m.item_headers(sheet.headers)
    ok = (logo_ok and pages == rows and size > 10_000 and secs < 30 and m.items_mode == "columns" and items == menu
          and m.columns.get("customer_name") == "Customer Name")
    print(f"selftest: pages={pages} size={size} seconds={secs:.2f} items={items} mapped={m.columns} "
          f"logo={logo_ok} -> {'OK' if ok else 'FAIL'}")
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


def _generate(src: str, out: str | None, template_name: str | None, delivery: str | None = None) -> int:
    import datetime as dt
    from . import template as T
    from .mapping import Mapping, auto_map, load_mapping
    from .pdfgen import GenerateError, default_output_path, format_delivery_date, generate_pdf
    from .spreadsheet import SpreadsheetError, load

    try:
        sheet = load(src)
    except SpreadsheetError as e:
        print(e, file=sys.stderr)
        return 2
    m = load_mapping()
    if m is None or m.is_empty():
        m = auto_map(Mapping(), sheet.headers, sheet.rows)
    names = T.ensure_default_template()
    tpl = T.load_template(template_name or names[0]) or T.default_template()
    day = dt.date.fromisoformat(delivery) if delivery else None
    extra = {"delivery_date": format_delivery_date(day)} if day else {}
    out_path = Path(out) if out else default_output_path(sheet.path, day)
    try:
        n = generate_pdf(out_path, tpl, m, sheet, extra=extra)
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
    p.add_argument("--delivery-date", metavar="YYYY-MM-DD")
    p.add_argument("--selftest", action="store_true")
    p.add_argument("--selftest-gui", action="store_true")
    args = p.parse_args(argv)

    if args.selftest:
        return _selftest(args.out)
    if args.selftest_gui:
        return _selftest_gui()
    if args.generate:
        return _generate(args.generate, args.out, args.template, args.delivery_date)

    from .app import run_gui
    run_gui(args.file)
    return 0
