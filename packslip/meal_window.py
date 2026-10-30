"""Meal label sort & filter settings (the "Sort & filter" link on the main window)."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from . import storage
from .meal_labels import SORT_KEYS
from .ui_common import center_on, dropdown, make_modal

NO_SORT = "(none)"
ORDERS = ["A → Z", "Z → A"]
DEFAULTS = {"sort": [["Product", "A → Z"], ["Size", "A → Z"], ["Customer last name", "A → Z"]],
            "custom": True, "regular": True, "skip": "", "customers": "", "products": ""}


def _split_list(text: str) -> list[str]:
    return [x.strip() for x in text.split(",") if x.strip()]


def meal_options(settings: dict) -> dict:
    """The saved meal-label sort & filter choices (with defaults)."""
    return dict(DEFAULTS, **(settings.get("meal_labels") or {}))


def sort_keys(settings: dict) -> list[tuple[str, bool]]:
    return [(SORT_KEYS[k], o == ORDERS[1]) for k, o in meal_options(settings)["sort"] if k in SORT_KEYS]


def filters(settings: dict) -> dict:
    o = meal_options(settings)
    kinds = {k for k in ("custom", "regular") if o[k]}
    return {"kinds": kinds or {"none"}, "skip_words": _split_list(o["skip"]),
            "customers": _split_list(o["customers"]), "products": _split_list(o["products"])}


def describe(settings: dict) -> str:
    """Short summary for the main window, e.g. 'Product, Size, Customer last name · skips: $'."""
    o = meal_options(settings)
    text = ", ".join(k + (" (Z→A)" if order == ORDERS[1] else "") for k, order in o["sort"] if k in SORT_KEYS) \
        or "as in file"
    if not (o["custom"] and o["regular"]):
        text += " · custom only" if o["custom"] else " · regular only" if o["regular"] else " · nothing selected"
    for key, word in (("skip", "skips"), ("customers", "customers"), ("products", "products")):
        if o[key].strip():
            text += f" · {word}: {o[key].strip()}"
    return "Sorted by " + text


class SortFilterDialog(tk.Toplevel):
    """Modal. Saves the choices into app settings on OK."""

    def __init__(self, master, settings: dict):
        super().__init__(master)
        self.title("Meal labels: sort & filter")
        self.transient(master)
        self.resizable(False, False)
        self.settings = settings
        saved = meal_options(settings)

        f = ttk.Frame(self, padding=18)
        f.pack(fill="both", expand=True)
        r = 0
        ttk.Label(f, text="Sort", font=("Helvetica", 13, "bold")).grid(row=r, column=0, sticky="w", pady=(0, 4))
        self.sort_vars = []
        for n, (key, order) in enumerate((saved["sort"] + [[NO_SORT, ORDERS[0]]] * 3)[:3]):
            r += 1
            ttk.Label(f, text=("Sort by", "then by", "then by")[n]).grid(row=r, column=0, sticky="w", pady=2)
            kv, ov = tk.StringVar(value=key), tk.StringVar(value=order)
            dropdown(f, kv, [NO_SORT, *SORT_KEYS], width=20).grid(row=r, column=1, sticky="w", padx=6)
            dropdown(f, ov, ORDERS, width=7).grid(row=r, column=2, sticky="w")
            self.sort_vars.append((kv, ov))

        r += 1
        ttk.Label(f, text="Filters", font=("Helvetica", 13, "bold")).grid(row=r, column=0, sticky="w", pady=(14, 4))
        r += 1
        kinds = ttk.Frame(f)
        kinds.grid(row=r, column=0, columnspan=3, sticky="w")
        self.custom_var, self.regular_var = tk.BooleanVar(value=saved["custom"]), tk.BooleanVar(value=saved["regular"])
        ttk.Checkbutton(kinds, text="Custom meals", variable=self.custom_var).pack(side="left")
        ttk.Checkbutton(kinds, text="Regular meals", variable=self.regular_var).pack(side="left", padx=12)
        self.text_vars = {}
        for key, label in (("skip", "Skip products containing"), ("customers", "Only these customers"),
                           ("products", "Only these products")):
            r += 1
            ttk.Label(f, text=label).grid(row=r, column=0, sticky="w", pady=2)
            var = tk.StringVar(value=saved[key])
            ttk.Entry(f, textvariable=var, width=34).grid(row=r, column=1, columnspan=2, sticky="we", padx=6)
            self.text_vars[key] = var
        r += 1
        ttk.Label(f, text="Separate several with commas, e.g.  $, Downright   (blank = no filter)",
                  foreground="#666666").grid(row=r, column=0, columnspan=3, sticky="w")
        r += 1
        btns = ttk.Frame(f)
        btns.grid(row=r, column=0, columnspan=3, sticky="e", pady=(14, 0))
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(btns, text="OK", command=self._save, default="active").pack(side="right", padx=8)
        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<Return>", lambda e: self._save())
        center_on(self, master)
        make_modal(self)

    def _save(self):
        self.settings["meal_labels"] = {
            **(self.settings.get("meal_labels") or {}),
            "sort": [[k.get(), o.get()] for k, o in self.sort_vars],
            "custom": self.custom_var.get(), "regular": self.regular_var.get(),
            **{k: v.get() for k, v in self.text_vars.items()},
        }
        storage.save_settings(self.settings)
        self.destroy()
