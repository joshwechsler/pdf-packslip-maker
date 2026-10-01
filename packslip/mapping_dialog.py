"""Field-mapping screen (FR-2, FR-3): match spreadsheet columns to pack-slip fields."""

from __future__ import annotations

import copy
import tkinter as tk
from tkinter import messagebox, ttk

from .mapping import Mapping, guess_columns
from .spreadsheet import Sheet
from .ui_common import ScrollFrame, center_on

NOT_USED_LABEL = "(not used)"


class MappingDialog(tk.Toplevel):
    """Modal. After wait_window(), `.result` holds the saved Mapping or None."""

    def __init__(self, master, mapping: Mapping | None, sheet: Sheet):
        super().__init__(master)
        self.title("Match Spreadsheet Columns")
        self.transient(master)
        self.resizable(True, True)
        self.sheet = sheet
        self.result: Mapping | None = None
        first_time = mapping is None or mapping.is_empty()
        self.mapping = copy.deepcopy(mapping) if mapping else Mapping()
        if first_time:
            self.mapping.columns = guess_columns(self.mapping.fields, sheet.headers)
        self.vars: dict[str, tk.StringVar] = {}

        outer = ttk.Frame(self, padding=16)
        outer.pack(fill="both", expand=True)

        ttk.Label(outer, text="Match each pack-slip field to a column in your spreadsheet",
                  font=("Helvetica", 15, "bold")).pack(anchor="w")
        intro = ("We've guessed the matches below. Check each one, change any that are wrong, "
                 "and choose “(not used)” for fields you don't need.  This is saved and reused "
                 "every week until you click “Remap Fields” again.")
        ttk.Label(outer, text=intro, wraplength=640, foreground="#555555").pack(anchor="w", pady=(4, 12))

        head = ttk.Frame(outer)
        head.pack(fill="x")
        for col, (txt, w) in enumerate((("Pack-slip field", 18), ("Spreadsheet column", 26),
                                        (f"Example (first customer)", 30))):
            ttk.Label(head, text=txt, width=w, font=("Helvetica", 12, "bold")).grid(row=0, column=col, sticky="w", padx=4)

        self.scroll = ScrollFrame(outer, height=330)
        self.scroll.pack(fill="both", expand=True, pady=(4, 8))
        self.rows_frame = self.scroll.inner
        self._build_rows()

        add = ttk.Frame(outer)
        add.pack(fill="x", pady=(4, 8))
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
        if not header or not self.sheet.rows:
            return ""
        val = self.sheet.rows[0].get(header, "")
        val = " / ".join(p.strip() for p in val.splitlines() if p.strip())
        return val if len(val) <= 40 else val[:39] + "…"

    def _build_rows(self):
        for child in self.rows_frame.winfo_children():
            child.destroy()
        options = [NOT_USED_LABEL] + self.sheet.headers
        default_keys = {"customer_name", "order_number", "delivery_date", "address",
                        "phone", "items", "quantity", "notes"}
        for r, f in enumerate(self.mapping.fields):
            key = f["key"]
            current = self.mapping.columns.get(key, "")
            if key not in self.vars:
                self.vars[key] = tk.StringVar()
            var = self.vars[key]
            var.set(current if current in self.sheet.headers else NOT_USED_LABEL)

            ttk.Label(self.rows_frame, text=f["label"], width=18).grid(row=r, column=0, sticky="w", padx=4, pady=3)
            combo = ttk.Combobox(self.rows_frame, textvariable=var, values=options, state="readonly", width=26)
            combo.grid(row=r, column=1, sticky="w", padx=4, pady=3)
            example = ttk.Label(self.rows_frame, text=self._example(current), width=30, foreground="#666666")
            example.grid(row=r, column=2, sticky="w", padx=4)
            combo.bind("<<ComboboxSelected>>",
                       lambda e, v=var, lab=example: lab.configure(
                           text=self._example("" if v.get() == NOT_USED_LABEL else v.get())))
            if key not in default_keys:
                ttk.Button(self.rows_frame, text="Remove", width=7,
                           command=lambda k=key: self._remove_field(k)).grid(row=r, column=3, padx=4)
            if current and current not in self.sheet.headers:
                ttk.Label(self.rows_frame, text=f"“{current}” not found", foreground="#B00020").grid(
                    row=r, column=4, sticky="w")

    def _collect(self):
        for key, var in self.vars.items():
            v = var.get()
            self.mapping.columns[key] = "" if v == NOT_USED_LABEL else v

    def _auto(self):
        self.mapping.columns = guess_columns(self.mapping.fields, self.sheet.headers)
        self._build_rows()

    def _add_field(self):
        label = " ".join(self.new_field.get().split())
        if not label:
            return
        if any(f["label"].lower() == label.lower() for f in self.mapping.fields):
            messagebox.showinfo("Already there", f"There's already a field called “{label}”.", parent=self)
            return
        self._collect()
        key = self.mapping.add_field(label)
        self.mapping.columns[key] = guess_columns([self.mapping.fields[-1]], self.sheet.headers).get(key, "")
        self.new_field.set("")
        self._build_rows()
        self.scroll.canvas.after(50, lambda: self.scroll.canvas.yview_moveto(1.0))

    def _remove_field(self, key):
        self._collect()
        self.mapping.remove_field(key)
        self.vars.pop(key, None)
        self._build_rows()

    def _save(self):
        self._collect()
        if self.mapping.is_empty():
            messagebox.showwarning("Nothing matched",
                                   "Match at least one field to a spreadsheet column before saving.",
                                   parent=self)
            return
        if not self.mapping.columns.get("customer_name") and any(
                f["key"] == "customer_name" for f in self.mapping.fields):
            if not messagebox.askyesno(
                    "No customer name?",
                    "“Customer Name” isn't matched to a column, so slips won't show who they're for.\n\n"
                    "Save anyway?", parent=self):
                return
        self.result = self.mapping
        self.destroy()
