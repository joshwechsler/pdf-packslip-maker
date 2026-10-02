"""Field-mapping screen (FR-2, FR-3): match spreadsheet columns to pack-slip fields."""

from __future__ import annotations

import copy
import tkinter as tk
from tkinter import messagebox, ttk

from .mapping import DEFAULT_FIELDS, ITEM_KEYS, Mapping, auto_map, guess_columns
from .spreadsheet import Sheet
from .ui_common import ScrollFrame, center_on

NOT_USED_LABEL = "(not used)"
START_LABEL = "(first column)"
END_LABEL = "(last column)"
BUILT_IN_KEYS = {f["key"] for f in DEFAULT_FIELDS}
NONE_LABEL = "(none)"


class MappingDialog(tk.Toplevel):
    """Modal. After wait_window(), `.result` holds the saved Mapping or None."""

    def __init__(self, master, mapping: Mapping | None, sheet: Sheet):
        super().__init__(master)
        self.title("Match Spreadsheet Columns")
        self.transient(master)
        self.minsize(800, 640)
        self.sheet = sheet
        self.result: Mapping | None = None
        first_time = mapping is None or mapping.is_empty()
        self.mapping = copy.deepcopy(mapping) if mapping else Mapping()
        if first_time:
            auto_map(self.mapping, sheet.headers, sheet.rows)
        self.vars: dict[str, tk.StringVar] = {}

        outer = ttk.Frame(self, padding=16)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="Match your spreadsheet's columns to the pack slip",
                  font=("Helvetica", 15, "bold")).pack(anchor="w")
        intro = ("We've guessed the matches below. Check them, fix any that are wrong, and choose "
                 "“(not used)” for anything you don't need. This is saved and reused every week "
                 "until you click “Remap Fields” again.")
        ttk.Label(outer, text=intro, wraplength=760, foreground="#555555").pack(anchor="w", pady=(4, 10))

        self.scroll = ScrollFrame(outer, height=440)
        self.scroll.pack(fill="both", expand=True)
        self.body = self.scroll.inner
        self._build()

        add = ttk.Frame(outer)
        add.pack(fill="x", pady=(8, 4))
        ttk.Label(add, text="Need another field on the slip?").pack(side="left")
        self.new_field = tk.StringVar()
        entry = ttk.Entry(add, textvariable=self.new_field, width=22)
        entry.pack(side="left", padx=6)
        entry.bind("<Return>", lambda e: self._add_field())
        ttk.Button(add, text="Add Field", command=self._add_field).pack(side="left")

        btns = ttk.Frame(outer)
        btns.pack(fill="x", pady=(8, 0))
        ttk.Button(btns, text="Guess Again", command=self._auto).pack(side="left")
        ttk.Button(btns, text="Save Matches", command=self._save, default="active").pack(side="right")
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(side="right", padx=8)

        self.bind("<Escape>", lambda e: self.destroy())
        center_on(self, master)
        self.grab_set()
        self.focus_set()

    # ---------------------------------------------------------------------
    def _example(self, header: str) -> str:
        if not header or header == NOT_USED_LABEL or not self.sheet.rows:
            return ""
        val = self.sheet.rows[0].get(header, "")
        val = " / ".join(p.strip() for p in val.splitlines() if p.strip())
        return val if len(val) <= 38 else val[:37] + "…"

    def _section(self, text, row):
        ttk.Label(self.body, text=text, font=("Helvetica", 13, "bold")).grid(
            row=row, column=0, columnspan=4, sticky="w", pady=(10, 4))

    def _field_row(self, f, r, options):
        key = f["key"]
        current = self.mapping.columns.get(key, "")
        var = self.vars.setdefault(key, tk.StringVar())
        var.set(current if current in self.sheet.headers else NOT_USED_LABEL)
        ttk.Label(self.body, text=f["label"], width=20).grid(row=r, column=0, sticky="w", padx=4, pady=3)
        combo = ttk.Combobox(self.body, textvariable=var, values=options, state="readonly", width=26)
        combo.grid(row=r, column=1, sticky="w", padx=4, pady=3)
        example = ttk.Label(self.body, text=self._example(var.get()), width=32, foreground="#666666")
        example.grid(row=r, column=2, sticky="w", padx=4)
        combo.bind("<<ComboboxSelected>>", lambda e: (example.configure(text=self._example(var.get())),
                                                      self._update_items_preview()))
        if key not in BUILT_IN_KEYS:
            ttk.Button(self.body, text="Remove", width=7,
                       command=lambda k=key: self._remove_field(k)).grid(row=r, column=3, padx=4)

    def _build(self):
        for child in self.body.winfo_children():
            child.destroy()
        options = [NOT_USED_LABEL] + self.sheet.headers
        r = 0
        self._section("Customer details", r)
        r += 1
        for f in self.mapping.fields:
            if f["key"] in ITEM_KEYS:
                continue
            self._field_row(f, r, options)
            r += 1

        self._section("What they ordered", r)
        r += 1
        self.mode = tk.StringVar(value=self.mapping.items_mode)
        ttk.Radiobutton(self.body, text="Each menu item has its own column (quantity in each cell)",
                        value="columns", variable=self.mode, command=self._update_items_preview).grid(
            row=r, column=0, columnspan=4, sticky="w")
        r += 1
        span = ttk.Frame(self.body)
        span.grid(row=r, column=0, columnspan=4, sticky="w", padx=(24, 0), pady=2)
        ttk.Label(span, text="Menu items are the columns after").pack(side="left")
        self.after_var = tk.StringVar(value=self.mapping.items_after or START_LABEL)
        self.before_var = tk.StringVar(value=self.mapping.items_before or END_LABEL)
        a = ttk.Combobox(span, textvariable=self.after_var, values=[START_LABEL] + self.sheet.headers,
                         state="readonly", width=18)
        a.pack(side="left", padx=4)
        ttk.Label(span, text="and before").pack(side="left")
        b = ttk.Combobox(span, textvariable=self.before_var, values=self.sheet.headers + [END_LABEL],
                         state="readonly", width=18)
        b.pack(side="left", padx=4)
        for c in (a, b):
            c.bind("<<ComboboxSelected>>", lambda e: (self.mode.set("columns"), self._update_items_preview()))
        r += 1
        self.items_preview = ttk.Label(self.body, text="", foreground="#1E7B34", wraplength=720)
        self.items_preview.grid(row=r, column=0, columnspan=4, sticky="w", padx=(24, 0), pady=(0, 6))
        r += 1

        ttk.Radiobutton(self.body, text="Each row is one item (an order takes up several rows)", value="rows",
                        variable=self.mode, command=self._update_items_preview).grid(
            row=r, column=0, columnspan=4, sticky="w")
        r += 1
        self.group_var = tk.StringVar(value=self.mapping.group_by or (self.sheet.headers[0] if self.sheet.headers else ""))
        self.variant_var = tk.StringVar(value=self.mapping.variant_col or NONE_LABEL)
        self.detail_var = tk.StringVar(value=self.mapping.detail_col or NONE_LABEL)
        for label, var, values in (
                ("Rows with the same", self.group_var, self.sheet.headers),
                ("Item size / variant", self.variant_var, [NONE_LABEL] + self.sheet.headers),
                ("Item details (e.g. custom-meal parts)", self.detail_var, [NONE_LABEL] + self.sheet.headers)):
            line = ttk.Frame(self.body)
            line.grid(row=r, column=0, columnspan=4, sticky="w", padx=(24, 0), pady=2)
            ttk.Label(line, text=label, width=32).pack(side="left")
            c = ttk.Combobox(line, textvariable=var, values=values, state="readonly", width=24)
            c.pack(side="left", padx=4)
            if var is self.group_var:
                ttk.Label(line, text="are one order").pack(side="left")
            c.bind("<<ComboboxSelected>>", lambda e: (self.mode.set("rows"), self._update_items_preview()))
            r += 1
        self.rows_preview = ttk.Label(self.body, text="", foreground="#1E7B34", wraplength=720)
        self.rows_preview.grid(row=r, column=0, columnspan=4, sticky="w", padx=(24, 0), pady=(0, 6))
        r += 1

        ttk.Radiobutton(self.body, text="All items are listed in one column", value="single",
                        variable=self.mode, command=self._update_items_preview).grid(
            row=r, column=0, columnspan=4, sticky="w")
        r += 1
        ttk.Label(self.body, text="Item name and quantity columns (for the two options above):",
                  foreground="#555555").grid(row=r, column=0, columnspan=4, sticky="w", padx=(24, 0), pady=(4, 0))
        r += 1
        for f in self.mapping.fields:
            if f["key"] in ITEM_KEYS:
                self._field_row(f, r, options)
                r += 1
        self._update_items_preview()

    def _collect(self):
        for key, var in self.vars.items():
            v = var.get()
            self.mapping.columns[key] = "" if v == NOT_USED_LABEL else v
        self.mapping.items_mode = self.mode.get()
        after, before = self.after_var.get(), self.before_var.get()
        self.mapping.items_after = "" if after == START_LABEL else after
        self.mapping.items_before = "" if before == END_LABEL else before
        self.mapping.group_by = self.group_var.get() if self.mapping.items_mode == "rows" else ""
        variant, detail = self.variant_var.get(), self.detail_var.get()
        self.mapping.variant_col = "" if variant == NONE_LABEL else variant
        self.mapping.detail_col = "" if detail == NONE_LABEL else detail
        if self.mapping.items_mode == "columns":
            for k in ITEM_KEYS:
                self.mapping.columns.pop(k, None)

    def _update_items_preview(self):
        self._collect()
        self.rows_preview.configure(text="")
        if self.mapping.items_mode == "rows":
            self.items_preview.configure(text="")
            orders = self.mapping.records(self.sheet.rows)
            if not self.mapping.columns.get("items"):
                self.rows_preview.configure(text="Choose the item name column below.", foreground="#B00020")
                return
            first = self.mapping.item_rows(orders[0]) if orders else []
            sample = ", ".join(f"{q} × {n}" for n, q, _ in first[:3]) + (" …" if len(first) > 3 else "")
            self.rows_preview.configure(
                text=f"✓ {len(self.sheet.rows)} rows → {len(orders)} orders (one pack slip each). "
                     f"First order: {sample}", foreground="#1E7B34")
            return
        if self.mapping.items_mode != "columns":
            self.items_preview.configure(text="")
            return
        names = self.mapping.item_headers(self.sheet.headers)
        if not names:
            self.items_preview.configure(text="No columns in that range — pick different start/end columns.",
                                         foreground="#B00020")
            return
        shown = ", ".join(names[:8]) + (f", and {len(names) - 8} more" if len(names) > 8 else "")
        self.items_preview.configure(text=f"✓ Found {len(names)} menu items: {shown}", foreground="#1E7B34")

    def _auto(self):
        auto_map(self.mapping, self.sheet.headers, self.sheet.rows)
        self.vars.clear()
        self._build()

    def _add_field(self):
        label = " ".join(self.new_field.get().split())
        if not label:
            return
        if any(f["label"].lower() == label.lower() for f in self.mapping.all_fields()):
            messagebox.showinfo("Already there", f"There's already a field called “{label}”.", parent=self)
            return
        self._collect()
        key = self.mapping.add_field(label)
        self.mapping.columns[key] = guess_columns([self.mapping.fields[-1]], self.sheet.headers).get(key, "")
        self.new_field.set("")
        self._build()

    def _remove_field(self, key):
        self._collect()
        self.mapping.remove_field(key)
        self.vars.pop(key, None)
        self._build()

    def _save(self):
        self._collect()
        m = self.mapping
        if m.is_empty():
            messagebox.showwarning("Nothing matched",
                                   "Match at least one field to a spreadsheet column before saving.", parent=self)
            return
        if m.items_mode == "rows" and not (m.group_by and m.columns.get("items")):
            messagebox.showwarning("Missing item columns",
                                   "Choose which column groups rows into an order, and which column has the "
                                   "item name.", parent=self)
            return
        if m.items_mode == "columns" and not m.item_headers(self.sheet.headers):
            messagebox.showwarning("No menu items",
                                   "No menu-item columns were found between the columns you picked. "
                                   "Choose different start/end columns.", parent=self)
            return
        if not m.columns.get("customer_name"):
            if not messagebox.askyesno(
                    "No customer name?",
                    "“Customer Name” isn't matched to a column, so slips won't show who they're for.\n\n"
                    "Save anyway?", parent=self):
                return
        self.result = m
        self.destroy()
