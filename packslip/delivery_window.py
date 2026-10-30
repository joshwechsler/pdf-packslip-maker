"""Delivery report screens: the check summary before saving, and the pickup-location editor."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from .delivery_report import MODES, PickupLocation, Report, load_locations, save_locations
from .ui_common import center_on, dropdown, make_modal


class ReportCheckDialog(tk.Toplevel):
    """Modal. Shows the counts and anything flagged; `.save` is True if the Operator chose to save."""

    def __init__(self, master, report: Report, file_name: str):
        super().__init__(master)
        self.title("Delivery report check")
        self.transient(master)
        self.resizable(False, False)
        self.save = False
        a = report.audit
        f = ttk.Frame(self, padding=18)
        f.pack(fill="both", expand=True)
        ttk.Label(f, text="Delivery report check", font=("Helvetica", 15, "bold")).pack(anchor="w")
        lines = [f"{a['orders']} orders read",
                 f"{a['rows']} stops on the delivery report:",
                 f"     {a['home']} home deliveries",
                 f"     {a['pickups_listed']} pickup-location order{'s' if a['pickups_listed'] != 1 else ''}"]
        if a["drops"]:
            lines.append(f"     {a['drops']} combined drop-off{'s' if a['drops'] != 1 else ''} "
                         f"({a['combined']} order{'s' if a['combined'] != 1 else ''})")
        if a["left_off"]:
            lines.append(f"{a['left_off']} pickup order{'s' if a['left_off'] != 1 else ''} left off (not on the list)")
        ttk.Label(f, text="\n".join(lines), justify="left").pack(anchor="w", pady=(8, 10))
        if report.warnings:
            ttk.Label(f, text=f"Check these ({len(report.warnings)}):", foreground="#8A5A00",
                      font=("Helvetica", 12, "bold")).pack(anchor="w")
            box = tk.Text(f, width=72, height=min(12, len(report.warnings) + 1), wrap="word",
                          font=("Helvetica", 11), relief="solid", borderwidth=1)
            box.insert("1.0", "\n".join("• " + w for w in report.warnings))
            box.configure(state="disabled")
            box.pack(fill="x", pady=(4, 10))
        else:
            ttk.Label(f, text="✓ Nothing to check: every order has its name, address, email and phone.",
                      foreground="#1E7B34").pack(anchor="w", pady=(0, 10))
        ttk.Label(f, text=f"Saves as: {file_name}", foreground="#666666").pack(anchor="w")
        btns = ttk.Frame(f)
        btns.pack(fill="x", pady=(12, 0))
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(btns, text="Save Delivery Report", command=self._save, default="active").pack(side="right", padx=8)
        self.bind("<Escape>", lambda e: self.destroy())
        center_on(self, master)
        make_modal(self)

    def _save(self):
        self.save = True
        self.destroy()


class PickupLocationsDialog(tk.Toplevel):
    """Modal editor for the pickup-location list used by the delivery report."""

    def __init__(self, master):
        super().__init__(master)
        self.title("Pickup locations")
        self.transient(master)
        self.minsize(760, 480)
        self.locations = load_locations()
        self.current: int | None = None

        f = ttk.Frame(self, padding=14)
        f.pack(fill="both", expand=True)
        ttk.Label(f, text="Pickup locations", font=("Helvetica", 15, "bold")).pack(anchor="w")
        ttk.Label(f, text="Pickup orders go to their location's address on the delivery report. Matching ignores "
                          "capitals and spaces, and a “(Town)” the store adds to the name.",
                  foreground="#555555", wraplength=720).pack(anchor="w", pady=(2, 8))
        body = ttk.Frame(f)
        body.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(body, columns=("name", "list", "address"), show="headings", height=12,
                                 selectmode="browse")
        for col, title, width in (("name", "Location", 220), ("list", "On the delivery list", 200),
                                  ("address", "Address", 320)):
            self.tree.heading(col, text=title)
            self.tree.column(col, width=width, anchor="w")
        scroll = ttk.Scrollbar(body, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._pick())

        form = ttk.Frame(f)
        form.pack(fill="x", pady=(10, 0))
        form.columnconfigure(1, weight=1)
        self.vars = {k: tk.StringVar() for k in ("name", "address", "address_format", "aliases", "drop_name", "mode")}
        rows = (("name", "Name (as the store spells it)"), ("address", "Address"),
                ("address_format", "Address on the report (optional)"),
                ("aliases", "Other spellings (commas)"), ("drop_name", "Stop name (one drop-off only)"))
        for r, (key, label) in enumerate(rows):
            ttk.Label(form, text=label).grid(row=r, column=0, sticky="w", pady=2, padx=(0, 8))
            ttk.Entry(form, textvariable=self.vars[key]).grid(row=r, column=1, sticky="we", pady=2)
        ttk.Label(form, text="On the delivery list").grid(row=len(rows), column=0, sticky="w", pady=2)
        dropdown(form, self.vars["mode"], list(MODES.values()), width=30).grid(row=len(rows), column=1, sticky="w")

        btns = ttk.Frame(f)
        btns.pack(fill="x", pady=(12, 0))
        ttk.Button(btns, text="Add Location", command=self._add).pack(side="left")
        ttk.Button(btns, text="Delete", command=self._delete).pack(side="left", padx=6)
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(btns, text="Save", command=self._save, default="active").pack(side="right", padx=8)
        self.bind("<Escape>", lambda e: self.destroy())
        self._fill()
        center_on(self, master)
        make_modal(self)

    def _fill(self, select: int | None = None):
        self.tree.delete(*self.tree.get_children())
        for i, loc in enumerate(self.locations):
            self.tree.insert("", "end", iid=str(i), values=(loc.name, MODES[loc.mode], loc.address))
        if self.locations:
            self.tree.selection_set(str(select if select is not None else 0))

    def _store(self):
        """Copy the form back into the selected location."""
        if self.current is None or self.current >= len(self.locations):
            return
        v = {k: var.get().strip() for k, var in self.vars.items()}
        loc = self.locations[self.current]
        loc.name, loc.address, loc.address_format = v["name"] or loc.name, v["address"], v["address_format"]
        loc.aliases = [a.strip() for a in v["aliases"].split(",") if a.strip()]
        loc.drop_name = v["drop_name"]
        loc.mode = next((k for k, label in MODES.items() if label == v["mode"]), "each")
        self.tree.item(str(self.current), values=(loc.name, MODES[loc.mode], loc.address))

    def _pick(self):
        self._store()
        sel = self.tree.selection()
        if not sel:
            return
        self.current = int(sel[0])
        loc = self.locations[self.current]
        for key, value in (("name", loc.name), ("address", loc.address), ("address_format", loc.address_format),
                           ("aliases", ", ".join(loc.aliases)), ("drop_name", loc.drop_name),
                           ("mode", MODES[loc.mode])):
            self.vars[key].set(value)

    def _add(self):
        self._store()
        self.locations.append(PickupLocation(name="New location", address=""))
        self.current = None
        self._fill(select=len(self.locations) - 1)

    def _delete(self):
        if self.current is None:
            return
        name = self.locations[self.current].name
        if not messagebox.askyesno("Delete location?", f"Delete “{name}” from the pickup locations?", parent=self):
            return
        del self.locations[self.current]
        self.current = None
        self._fill()

    def _save(self):
        self._store()
        save_locations(self.locations)
        self.destroy()
