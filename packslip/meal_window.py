"""Meal Labels window: load the Label Data export, pick the layouts, sort and filter, make the PDF."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import storage
from . import template as T
from .meal_labels import SORT_KEYS, filter_records, looks_like_meal_file, read_records
from .pdfgen import GenerateError, generate_meal_labels
from .spreadsheet import Sheet, SpreadsheetError, load as load_sheet
from .ui_common import center_on, dropdown

NO_SORT = "(none)"
ORDERS = ["A → Z", "Z → A"]
DEFAULTS = {"sort": [["Product", "A → Z"], ["Size", "A → Z"], ["Customer last name", "A → Z"]],
            "custom": True, "regular": True, "skip": "", "customers": "", "products": ""}


def _split_list(text: str) -> list[str]:
    return [x.strip() for x in text.split(",") if x.strip()]


class MealLabelsWindow(tk.Toplevel):
    """Not modal, so the layout editor can stay open next to it. `app` is the main window (App)."""

    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        self.title("Meal Labels")
        self.transient(master)
        self.resizable(False, False)
        saved = dict(DEFAULTS, **(app.settings.get("meal_labels") or {}))

        f = ttk.Frame(self, padding=18)
        f.pack(fill="both", expand=True)
        ttk.Label(f, text="Meal labels", font=("Helvetica", 16, "bold")).grid(row=0, column=0, columnspan=4, sticky="w")
        ttk.Label(f, text="One label per container, from the Label Data export (.csv).",
                  foreground="#555555").grid(row=1, column=0, columnspan=4, sticky="w", pady=(2, 10))

        r = 2
        self.file_label = ttk.Label(f, text="No file yet", foreground="#666666", width=46)
        self.file_label.grid(row=r, column=0, columnspan=3, sticky="w")
        ttk.Button(f, text="Choose File…", command=self.choose_file).grid(row=r, column=3, sticky="e")

        r += 1
        ttk.Label(f, text="Layouts", font=("Helvetica", 13, "bold")).grid(row=r, column=0, sticky="w", pady=(14, 4))
        self.layout_vars, self.layout_buttons = {}, {}
        for kind, label in (("custom", "Custom meals"), ("regular", "Regular meals")):
            r += 1
            ttk.Label(f, text=label).grid(row=r, column=0, sticky="w", pady=2)
            var = tk.StringVar()
            self.layout_vars[kind] = var
            mb = dropdown(f, var, [], command=self._remember, width=24)
            mb.grid(row=r, column=1, columnspan=2, sticky="w", padx=6)
            self.layout_buttons[kind] = mb
            ttk.Button(f, text="Edit…", command=lambda k=kind: self._edit(k)).grid(row=r, column=3, sticky="e")
        self.refresh_layouts()

        r += 1
        ttk.Label(f, text="Sort", font=("Helvetica", 13, "bold")).grid(row=r, column=0, sticky="w", pady=(14, 4))
        self.sort_vars = []
        for n, (key, order) in enumerate((saved["sort"] + [[NO_SORT, ORDERS[0]]] * 3)[:3]):
            r += 1
            ttk.Label(f, text=("Sort by", "then by", "then by")[n]).grid(row=r, column=0, sticky="w", pady=2)
            kv, ov = tk.StringVar(value=key), tk.StringVar(value=order)
            dropdown(f, kv, [NO_SORT, *SORT_KEYS], command=self._changed, width=20).grid(
                row=r, column=1, sticky="w", padx=6)
            dropdown(f, ov, ORDERS, command=self._changed, width=7).grid(row=r, column=2, sticky="w")
            self.sort_vars.append((kv, ov))

        r += 1
        ttk.Label(f, text="Filters", font=("Helvetica", 13, "bold")).grid(row=r, column=0, sticky="w", pady=(14, 4))
        r += 1
        kinds = ttk.Frame(f)
        kinds.grid(row=r, column=0, columnspan=4, sticky="w")
        self.custom_var, self.regular_var = tk.BooleanVar(value=saved["custom"]), tk.BooleanVar(value=saved["regular"])
        ttk.Checkbutton(kinds, text="Custom meals", variable=self.custom_var, command=self._changed).pack(side="left")
        ttk.Checkbutton(kinds, text="Regular meals", variable=self.regular_var, command=self._changed).pack(
            side="left", padx=12)
        self.text_vars = {}
        for key, label in (("skip", "Skip products containing"), ("customers", "Only these customers"),
                           ("products", "Only these products")):
            r += 1
            ttk.Label(f, text=label).grid(row=r, column=0, sticky="w", pady=2)
            var = tk.StringVar(value=saved[key])
            var.trace_add("write", lambda *_: self._changed())
            ttk.Entry(f, textvariable=var, width=34).grid(row=r, column=1, columnspan=3, sticky="we", padx=6)
            self.text_vars[key] = var
        r += 1
        ttk.Label(f, text="Separate several with commas, e.g.  $, Downright   (leave blank for no filter)",
                  foreground="#666666").grid(row=r, column=0, columnspan=4, sticky="w")

        r += 1
        self.count_label = ttk.Label(f, text="", foreground="#1E7B34")
        self.count_label.grid(row=r, column=0, columnspan=4, sticky="w", pady=(14, 6))
        r += 1
        self.gen_btn = ttk.Button(f, text="Generate Meal Labels", command=self.generate, default="active")
        self.gen_btn.grid(row=r, column=0, columnspan=4, sticky="we")

        self.bind("<Escape>", lambda e: self.destroy())
        self._changed()
        center_on(self, master)

    # ------------------------------------------------------------------ state
    def refresh_layouts(self):
        """Fill the layout menus (call again after layouts are added or renamed in the editor)."""
        names = T.list_templates(T.MEAL)
        saved = self.app.settings.get("meal_labels") or {}
        for kind, var in self.layout_vars.items():
            menu = self.nametowidget(self.layout_buttons[kind]["menu"])
            menu.delete(0, "end")
            for n in names:
                menu.add_radiobutton(label=n, value=n, variable=var, command=self._remember)
            want = var.get() or saved.get(f"{kind}_layout")
            if want not in names:  # first time: the layout that says it's for this kind of meal
                want = next((n for n in names if (T.load_template(n) or T.Template()).meal_for == kind),
                            names[0] if names else "")
            var.set(want)

    def _sort(self) -> list[tuple[str, bool]]:
        return [(SORT_KEYS[k.get()], o.get() == ORDERS[1]) for k, o in self.sort_vars if k.get() in SORT_KEYS]

    def _filters(self) -> dict:
        kinds = {k for k, v in (("custom", self.custom_var), ("regular", self.regular_var)) if v.get()}
        return {"kinds": kinds or {"none"}, "skip_words": _split_list(self.text_vars["skip"].get()),
                "customers": _split_list(self.text_vars["customers"].get()),
                "products": _split_list(self.text_vars["products"].get())}

    def _remember(self):
        self.app.settings["meal_labels"] = {
            "sort": [[k.get(), o.get()] for k, o in self.sort_vars],
            "custom": self.custom_var.get(), "regular": self.regular_var.get(),
            **{k: v.get() for k, v in self.text_vars.items()},
            **{f"{k}_layout": v.get() for k, v in self.layout_vars.items()},
        }
        storage.save_settings(self.app.settings)

    def _changed(self):
        if not hasattr(self, "count_label"):
            return
        self._remember()
        sheet = self.app.meal_sheet
        if sheet is None:
            self.count_label.configure(text="Choose the Label Data file (or drop it on the main window).",
                                       foreground="#666666")
            return
        self.file_label.configure(text=f"✓  {sheet.path.name}  —  {len(sheet.rows)} rows", foreground="#1E7B34")
        recs = filter_records(read_records(sheet), **self._filters())
        custom = sum(1 for x in recs if x["kind"] == "custom")
        self.count_label.configure(
            text=f"{len(recs)} label{'s' if len(recs) != 1 else ''} ({custom} custom, {len(recs) - custom} regular)"
                 f"  ·  Date: {self.app.delivery_values()['delivery_date_short']}",
            foreground="#1E7B34" if recs else "#B00020")

    # ---------------------------------------------------------------- actions
    def choose_file(self):
        path = filedialog.askopenfilename(
            parent=self, title="Choose the Label Data file",
            initialdir=self.app.settings.get("last_dir") or str(Path.home()),
            filetypes=[("Spreadsheets", "*.csv *.xlsx"), ("All files", "*.*")])
        if path:
            try:
                sheet = load_sheet(Path(path))
            except SpreadsheetError as e:
                messagebox.showerror("Can't read that file", str(e), parent=self)
                return
            self.use_sheet(sheet)

    def use_sheet(self, sheet: Sheet):
        if not looks_like_meal_file(sheet) and not messagebox.askyesno(
                "Meal label file?", f"“{sheet.path.name}” doesn't look like the Label Data export (no Product / "
                "Calories / How to Prepare columns). Use it anyway?", parent=self):
            return
        self.app.meal_sheet = sheet
        self._changed()

    def _edit(self, kind: str):
        name = self.layout_vars[kind].get()
        if name:
            self.app.edit_layout(name)

    def generate(self):
        sheet = self.app.meal_sheet
        if sheet is None:
            messagebox.showinfo("No file yet", "Choose the Label Data file first.", parent=self)
            return
        try:  # re-read so last-minute edits are included
            sheet = self.app.meal_sheet = load_sheet(sheet.path, sheet.sheet_name)
        except SpreadsheetError as e:
            messagebox.showerror("Can't read that file", str(e), parent=self)
            return
        layouts = {k: T.load_template(v.get()) if v.get() else None for k, v in self.layout_vars.items()}
        if not all(layouts.values()):
            messagebox.showinfo("Pick the layouts", "Choose a layout for custom meals and for regular meals.",
                                parent=self)
            return
        out = self.app._output_path("Meal Labels", sheet)
        try:
            n = generate_meal_labels(out, sheet, layouts["custom"], layouts["regular"], sort=self._sort(),
                                     filters=self._filters(), extra=self.app.delivery_values())
        except GenerateError as e:
            messagebox.showerror("Couldn't make the meal labels", str(e), parent=self)
            return
        self.app._show_success(out, n, title="Meal labels ready",
                               detail=f"{n} label{'s' if n != 1 else ''}, one per container.\n"
                                      "Print at Actual size (100%), not “Fit to page”.")
