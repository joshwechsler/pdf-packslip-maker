"""Create sample/sample_orders.xlsx: fake data in the same shape as the real weekly order sheet.

One row per customer, one column per menu item (quantity in the cell), a TOTALS row at the end.
Usage:  python tools/make_sample.py [rows] [out.xlsx]
"""

import datetime as dt
import random
import sys
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font

FIRST = ["Jane", "Marcus", "Priya", "Tom", "Aisha", "Luis", "Chen", "Hannah", "Omar", "Grace", "Diego", "Maya"]
LAST = ["Smith", "Johnson", "Patel", "Nguyen", "Garcia", "Okafor", "Kim", "Rossi", "Cohen", "Brown"]
STREETS = ["Maple Ave", "Oak St", "Elm Dr", "Cedar Ln", "Lakeview Rd", "Hillcrest Blvd"]
TOWNS = ["Derby, CT 06418", "Shelton, CT 06484", "Ansonia, CT 06401", "Seymour, CT 06483"]
MENU = ["Backyard Italian Pasta", "Orange Chicken", "Texas Turkey Chili", "French Onion Beef",
        "Chipotle breakfast", "Protein Overnight Oats", "100% Organic Juice", "S'mores Protein Muffin",
        "Oreo Cheesecake Protein Truffles", "Insulated Cooler Bag"]
NOTES = ["", "", "Leave at side door", "Call on arrival", "Gate code 4412", "", "Ring bell twice"]


def make(rows: int, out: Path, seed: int = 7) -> Path:
    rnd = random.Random(seed)
    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.append(["Order Received", "Customer Name", "Phone Number", "Address", *MENU,
               "Delivery Fee", "Total Cost", "Paid", "Delivery Instructions"])
    for c in ws[1]:
        c.font = Font(bold=True)
    totals = [0] * len(MENU)
    for i in range(rows):
        qtys = [rnd.choice([0, 0, 0, 1, 1, 2, 3]) for _ in MENU]
        for j, q in enumerate(qtys):
            totals[j] += q
        cost = sum(qtys) * 8.95
        ws.append([
            dt.datetime(2026, 9, 7, 8, 0) + dt.timedelta(minutes=rnd.randint(0, 6000)),
            f"{rnd.choice(FIRST)} {rnd.choice(LAST)}",
            int(f"203{rnd.randint(2000000, 9999999)}"),
            f"{rnd.randint(10, 999)} {rnd.choice(STREETS)}, {rnd.choice(TOWNS)}",
            *[q or None for q in qtys],
            rnd.choice([0, 0, 5]),
            f"${cost:.2f}",
            rnd.choice([True, False]),
            rnd.choice(NOTES) or None,
        ])
    ws.append([None, "TOTALS", None, None, *totals, None, None])
    ws.column_dimensions["A"].width = 18
    ws.column_dimensions["B"].width = 18
    ws.column_dimensions["D"].width = 40
    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out)
    return out


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 12
    path = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(__file__).resolve().parent.parent / "sample" / "sample_orders.xlsx"
    print(make(n, path))
