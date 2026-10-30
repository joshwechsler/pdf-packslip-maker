"""Match a driver list's columns and preview how many orders it covers."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from .drivers import is_pickup
from .routes import RouteColumns, driver_label, drop_off_drivers, join_routes
from .spreadsheet import Sheet
from .ui_common import ScrollFrame, center_on, dropdown, make_modal

NONE = "(none)"


class RouteDialog(tk.Toplevel):
    """Modal. After wait_window(), `.result` is the chosen RouteColumns (or None if cancelled) and
    `.manual` the drivers picked by hand for deliveries the file didn't cover: {order index: driver or ""}."""

    def __init__(self, master, route_sheet: Sheet, cols: RouteColumns, all_values: list[dict], locations=()):
        super().__init__(master)
        self.title("Driver List")
        self.transient(master)
        self.minsize(680, 420)
        self.sheet, self.values, self.locations = route_sheet, all_values, list(locations)
        self.result: RouteColumns | None = None
        self.manual: dict[int, str] = {}
        self._pick_vars: dict[int, tk.StringVar] = {}   # kept while the columns are changed

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
                                          ("driver", "Driver name"), ("stop", "Stop # (optional)"))):
            var = tk.StringVar(value=getattr(cols, key) or NONE)
            self.vars[key] = var
            ttk.Label(grid, text=label, width=18).grid(row=r, column=0, sticky="w", pady=4)
            dropdown(grid, var, options, command=self._preview, width=26).grid(row=r, column=1, sticky="w")
        self.preview = ttk.Label(f, text="", wraplength=640)
        self.preview.pack(anchor="w", pady=(14, 0))
        # Deliveries the file didn't cover: pick a driver by hand (this week's slips only).
        self.picks = ScrollFrame(f, height=200)
        self._shown: list[int] = []
        btns = ttk.Frame(f)
        btns.pack(side="bottom", fill="x", pady=(16, 0))
        self.ok = ttk.Button(btns, text="Use Driver List", command=self._save, default="active")
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
            self.preview.configure(text="Choose the Driver name column, and an Order number or Customer "
                                        "name column.", foreground="#B00020")
            self.ok.state(["disabled"])
            return
        self.ok.state(["!disabled"])
        res = join_routes(self.sheet, cols, self.values)
        drops = drop_off_drivers(self.sheet, cols, self.values, self.locations, skip=set(res.assignment))
        deliveries = [i for i, v in enumerate(self.values) if not is_pickup(v)]
        missing = [i for i in res.unmatched if i in set(deliveries) and i not in drops]
        routes = len(set(res.assignment.values()))
        text = (f"✓ {len(res.assignment)} of {len(self.values)} orders matched to {routes} "
                f"driver{'s' if routes != 1 else ''}")
        if res.by_name:
            text += f" ({res.by_name} by customer name)"
        text += "."
        names = sorted(set(res.assignment.values()), key=str.lower)
        if names:  # so a wrong column (e.g. instructions) is obvious at a glance
            shown = ", ".join(n if len(n) <= 30 else n[:29] + "…" for n in names[:4])
            text += f"\nDrivers: {shown}" + (f" and {len(names) - 4} more" if len(names) > 4 else "")
        if cols.stop:
            text += f"  {len(res.stops)} have a stop number."
        if drops:
            text += (f"\n{len(drops)} home deliver{'ies' if len(drops) != 1 else 'y'} going to a drop-off stop "
                     f"took that stop's driver ({', '.join(sorted(set(drops.values())))}).")
        if missing:
            text += (f"\n\n{len(missing)} deliver{'ies' if len(missing) != 1 else 'y'} not in the driver list. "
                     "Pick a driver for each below, or leave “(none)”:")
        elif drops:
            text += "\n\nYou can change the drop-off ones below."
        self.preview.configure(text=text, foreground="#1E7B34" if not missing else "#8A5A00")
        file_drivers = sorted({driver_label(r.get(cols.driver, "")) for r in self.sheet.rows} - {""}, key=str.lower)
        self._show_picks(missing + sorted(drops), drops, file_drivers)

    def _show_picks(self, indexes: list[int], presets: dict[int, str], drivers: list[str]):
        """One row per delivery to pick for: name, address, and a driver menu."""
        for w in self.picks.inner.winfo_children():
            w.destroy()
        self._shown = indexes
        if not indexes:
            self.picks.pack_forget()
            return
        self.picks.pack(fill="both", expand=True, pady=(8, 0))
        for r, i in enumerate(indexes):
            v = self.values[i]
            var = self._pick_vars.setdefault(i, tk.StringVar(value=presets.get(i, NONE)))
            label = f"{v.get('customer_name', '?')}  ·  {v.get('address', '')}"
            tk.Label(self.picks.inner, text=label if len(label) < 70 else label[:69] + "…", anchor="w").grid(
                row=r, column=0, sticky="w", padx=(4, 10), pady=2)
            dropdown(self.picks.inner, var, [NONE, *drivers], width=14).grid(row=r, column=1, sticky="w", pady=2)

    def _save(self):
        self.result = self._cols()
        self.manual = {i: ("" if self._pick_vars[i].get() == NONE else self._pick_vars[i].get())
                       for i in self._shown}
        self.destroy()
