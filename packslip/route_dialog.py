"""Match a route file's columns and preview how many orders it covers."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from .drivers import is_pickup
from .routes import RouteColumns, join_routes
from .spreadsheet import Sheet
from .ui_common import center_on, dropdown, make_modal

NONE = "(none)"


class RouteDialog(tk.Toplevel):
    """Modal. After wait_window(), `.result` is the chosen RouteColumns (or None if cancelled)."""

    def __init__(self, master, route_sheet: Sheet, cols: RouteColumns, all_values: list[dict]):
        super().__init__(master)
        self.title("Route File")
        self.transient(master)
        self.minsize(640, 360)
        self.sheet, self.values = route_sheet, all_values
        self.result: RouteColumns | None = None

        f = ttk.Frame(self, padding=16)
        f.pack(fill="both", expand=True)
        ttk.Label(f, text=f"Combine “{route_sheet.path.name}” with this week's orders",
                  font=("Helvetica", 15, "bold")).pack(anchor="w")
        ttk.Label(f, text="Orders are matched by order number. Orders without a number in both files are "
                          "matched by customer name. Check the columns below.",
                  wraplength=600, foreground="#555555").pack(anchor="w", pady=(4, 12))
        grid = ttk.Frame(f)
        grid.pack(anchor="w")
        options = [NONE] + route_sheet.headers
        self.vars = {}
        for r, (key, label) in enumerate((("order", "Order number"), ("customer", "Customer name"),
                                          ("driver", "Driver / Route"), ("stop", "Stop # (optional)"))):
            var = tk.StringVar(value=getattr(cols, key) or NONE)
            self.vars[key] = var
            ttk.Label(grid, text=label, width=18).grid(row=r, column=0, sticky="w", pady=4)
            dropdown(grid, var, options, command=self._preview, width=26).grid(row=r, column=1, sticky="w")
        self.preview = ttk.Label(f, text="", wraplength=600)
        self.preview.pack(anchor="w", pady=(14, 0))
        btns = ttk.Frame(f)
        btns.pack(side="bottom", fill="x", pady=(16, 0))
        self.ok = ttk.Button(btns, text="Use Route File", command=self._save, default="active")
        self.ok.pack(side="right")
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(side="right", padx=8)
        self.bind("<Escape>", lambda e: self.destroy())
        self._preview()
        center_on(self, master)
        make_modal(self)

    def _cols(self) -> RouteColumns:
        return RouteColumns(**{k: ("" if v.get() == NONE else v.get()) for k, v in self.vars.items()})

    def _preview(self):
        cols = self._cols()
        if not cols.usable():
            self.preview.configure(text="Choose the Driver / Route column, and an Order number or Customer "
                                        "name column.", foreground="#B00020")
            self.ok.state(["disabled"])
            return
        self.ok.state(["!disabled"])
        res = join_routes(self.sheet, cols, self.values)
        deliveries = [i for i, v in enumerate(self.values) if not is_pickup(v)]
        missing = [i for i in res.unmatched if i in set(deliveries)]
        routes = len(set(res.assignment.values()))
        text = (f"✓ {len(res.assignment)} of {len(self.values)} orders matched to {routes} "
                f"driver{'s' if routes != 1 else ''}/route{'s' if routes != 1 else ''}")
        if res.by_name:
            text += f" ({res.by_name} by customer name)"
        text += "."
        if cols.stop:
            text += f"  {len(res.stops)} have a stop number."
        if missing:
            names = ", ".join(self.values[i].get("customer_name", "?") for i in missing[:8])
            more = f" and {len(missing) - 8} more" if len(missing) > 8 else ""
            text += (f"\n\n{len(missing)} deliver{'ies' if len(missing) != 1 else 'y'} not in the route file: "
                     f"{names}{more}. They stay with any driver you assigned before, or can be assigned "
                     "with “Assign Drivers…”.")
        self.preview.configure(text=text, foreground="#1E7B34" if not missing else "#8A5A00")

    def _save(self):
        self.result = self._cols()
        self.destroy()
