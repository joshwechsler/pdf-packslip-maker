"""Assign Drivers window: pick a driver for each delivery order."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from .drivers import DriverBook, is_pickup, town
from .ui_common import center_on, make_modal

NONE = "—"


class DriversDialog(tk.Toplevel):
    """Modal. After wait_window(), `.result` is {record index: driver} (or None if cancelled)."""

    def __init__(self, master, book: DriverBook, all_values: list[dict], assignment: dict[int, str]):
        super().__init__(master)
        self.title("Assign Drivers")
        self.transient(master)
        self.minsize(1000, 580)
        self.book = book
        self.values = all_values
        self.assignment = {i: d for i, d in assignment.items() if d}
        self.names = list(book.names)
        self.result: dict[int, str] | None = None
        self.deliveries = [i for i, v in enumerate(all_values) if not is_pickup(v)]
        pickups = len(all_values) - len(self.deliveries)

        outer = ttk.Frame(self, padding=14)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="Assign a driver to each delivery", font=("Helvetica", 15, "bold")).pack(anchor="w")
        hint = ("Click an order (hold ⌘ or Shift to pick several), choose a driver on the right, then click "
                "Assign. Click a column title to sort, e.g. by Town. Returning customers are pre-filled "
                "with last time's driver.")
        if pickups:
            hint += f"  ({pickups} pickup order{'s' if pickups != 1 else ''} need no driver.)"
        ttk.Label(outer, text=hint, wraplength=960, foreground="#555555").pack(anchor="w", pady=(2, 8))

        body = ttk.Frame(outer)
        body.pack(fill="both", expand=True)
        cols = ("customer", "town", "window", "items", "driver")
        self.tree = ttk.Treeview(body, columns=cols, show="headings", selectmode="extended", height=18)
        for col, title, width in (("customer", "Customer", 190), ("town", "Town", 130), ("window", "Window / Zone", 230),
                                  ("items", "Items", 50), ("driver", "Driver", 120)):
            self.tree.heading(col, text=title, command=lambda c=col: self._sort(c))
            self.tree.column(col, width=width, anchor="w")
        vsb = ttk.Scrollbar(body, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="left", fill="y")
        self._sort_state = ("town", False)

        side = ttk.Frame(body, padding=(14, 0, 0, 0))
        side.pack(side="left", fill="y")
        ttk.Label(side, text="Drivers", font=("Helvetica", 13, "bold")).pack(anchor="w")
        self.names_box = tk.Listbox(side, height=8, exportselection=False)
        self.names_box.pack(fill="x", pady=(4, 4))
        add = ttk.Frame(side)
        add.pack(fill="x")
        self.new_name = tk.StringVar()
        entry = ttk.Entry(add, textvariable=self.new_name, width=14)
        entry.pack(side="left")
        entry.bind("<Return>", lambda e: self._add_driver())
        ttk.Button(add, text="Add", command=self._add_driver).pack(side="left", padx=4)
        ttk.Button(side, text="Remove Driver", command=self._remove_driver).pack(anchor="w", pady=(4, 14))

        ttk.Label(side, text="Selected orders", font=("Helvetica", 13, "bold")).pack(anchor="w")
        ttk.Button(side, text="Assign to Selected Driver", command=self._assign).pack(fill="x", pady=(4, 2))
        ttk.Button(side, text="Remove Driver from Order", command=self._unassign).pack(fill="x", pady=2)
        ttk.Button(side, text="Select All", command=lambda: self.tree.selection_set(self.tree.get_children())).pack(
            fill="x", pady=(10, 2))

        bottom = ttk.Frame(outer)
        bottom.pack(fill="x", pady=(10, 0))
        self.summary = ttk.Label(bottom, text="")
        self.summary.pack(side="left")
        ttk.Button(bottom, text="Save Drivers", command=self._save, default="active").pack(side="right")
        ttk.Button(bottom, text="Cancel", command=self.destroy).pack(side="right", padx=8)
        self.bind("<Escape>", lambda e: self.destroy())

        self._refresh_names()
        self._fill()
        center_on(self, master)
        make_modal(self)

    # ------------------------------------------------------------------
    def _row(self, i):
        v = self.values[i]
        window = " · ".join(x for x in (v.get("time_window", ""), v.get("zone", "")) if x)
        return (v.get("customer_name", ""), town(v.get("address", "")), window, v.get("item_count", ""),
                self.assignment.get(i, NONE))

    def _fill(self):
        keep = set(self.tree.selection())
        self.tree.delete(*self.tree.get_children())
        col, reverse = self._sort_state
        idx = {"customer": 0, "town": 1, "window": 2, "items": 3, "driver": 4}[col]
        rows = sorted(self.deliveries, key=lambda i: (str(self._row(i)[idx]).lower(), self._row(i)[0].lower()),
                      reverse=reverse)
        for i in rows:
            self.tree.insert("", "end", iid=str(i), values=self._row(i))
        self.tree.selection_set([k for k in keep if self.tree.exists(k)])
        done = sum(1 for i in self.deliveries if self.assignment.get(i))
        self.summary.configure(text=f"{done} of {len(self.deliveries)} deliveries have a driver")

    def _sort(self, col):
        last, reverse = self._sort_state
        self._sort_state = (col, not reverse if last == col else False)
        self._fill()

    def _refresh_names(self):
        self.names_box.delete(0, "end")
        for n in self.names:
            self.names_box.insert("end", n)
        if self.names and not self.names_box.curselection():
            self.names_box.selection_set(0)

    def _add_driver(self):
        name = " ".join(self.new_name.get().split())
        if not name:
            return
        if name.lower() not in {n.lower() for n in self.names}:
            self.names.append(name)
        self.new_name.set("")
        self._refresh_names()
        pos = [n.lower() for n in self.names].index(name.lower())
        self.names_box.selection_clear(0, "end")
        self.names_box.selection_set(pos)

    def _remove_driver(self):
        sel = self.names_box.curselection()
        if not sel:
            return
        name = self.names[sel[0]]
        used = sum(1 for d in self.assignment.values() if d == name)
        if used and not messagebox.askyesno("Remove driver?", f"{name} has {used} order(s) this week. "
                                            "Remove them from those orders too?", parent=self):
            return
        self.names.pop(sel[0])
        self.assignment = {i: d for i, d in self.assignment.items() if d != name}
        self._refresh_names()
        self._fill()

    def _assign(self):
        sel = self.names_box.curselection()
        if not sel:
            messagebox.showinfo("Pick a driver", "Add a driver on the right (type a name, click Add), "
                                "click their name, then click Assign.", parent=self)
            return
        rows = self.tree.selection()
        if not rows:
            messagebox.showinfo("Pick orders", "Click one or more orders in the list first.", parent=self)
            return
        for r in rows:
            self.assignment[int(r)] = self.names[sel[0]]
        self._fill()

    def _unassign(self):
        for r in self.tree.selection():
            self.assignment.pop(int(r), None)
        self._fill()

    def _save(self):
        self.book.names = self.names
        self.result = dict(self.assignment)
        self.destroy()
