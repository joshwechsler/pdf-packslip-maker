"""Main window: load spreadsheet → check layout → Generate (FR-1, FR-7, FR-8, FR-9)."""

from __future__ import annotations

import datetime as dt
import os
import queue
import sys
import threading
import tkinter as tk
import traceback
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import APP_NAME, __version__, diagnostics, storage, updater
from . import template as T
from .designer import Designer
from .drivers import DriverBook, customer_key
from . import meal_window
from .delivery_report import build_report, fold_into_drops, load_locations, write_report
from .delivery_window import PickupLocationsDialog, ReportCheckDialog
from .meal_labels import filter_records, looks_like_meal_file, read_records
from .route_dialog import RouteDialog
from .routes import RouteColumns, guess_route_columns, join_routes, looks_like_route_file
from .mapping import Mapping, load_mapping, migrate_legacy_mapping, save_mapping
from .mapping_dialog import MappingDialog
from .datepicker import DatePicker, default_delivery_date, sheet_delivery_date
from .pdfgen import (GenerateError, blank_line_warnings, check_ready, default_output_path, format_delivery_date,
                     generate_labels, generate_meal_labels, generate_pdf)
from .spreadsheet import Sheet, SpreadsheetError, load as load_sheet
from .ui_common import (IS_MAC, ask_choice, ask_name, center_on, disable_combobox_wheel, make_modal, open_path,
                        reveal_path)

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
except Exception:  # pragma: no cover - drag and drop is a nicety; Browse always works
    TkinterDnD = None
    DND_FILES = None

ACCENT = "#111111"
DROP_BG = "#F4F6F9"
DROP_HOVER = "#E3ECF7"


def make_root() -> tuple[tk.Tk, bool]:
    if TkinterDnD is not None:
        try:
            return TkinterDnD.Tk(), True
        except Exception:
            pass
    return tk.Tk(), False


def _wrapping_label(parent) -> ttk.Label:
    """A status label that fills the space left in its row and wraps to fit it."""
    label = ttk.Label(parent, text="", style="Muted.TLabel", justify="left")
    label.pack(side="left", fill="x", expand=True, padx=(0, 8))
    label.bind("<Configure>", lambda e: label.configure(wraplength=max(e.width, 50)))
    return label


class _DropBox(tk.Frame):
    """A file box: title, hint, Browse…, and a status line once a file is loaded. Files can be dropped on it."""

    def __init__(self, parent, title: str, hint: str, browse, dnd: bool):
        super().__init__(parent, background=DROP_BG, highlightthickness=2, highlightbackground="#B7C3D3")
        self.hint = hint
        self.body = tk.Frame(self, background=DROP_BG)
        self.body.pack(fill="both", expand=True, padx=10, pady=10)
        tk.Label(self.body, text=title, background=DROP_BG, foreground="#22313F",
                 font=("Helvetica", 13, "bold")).pack()
        tk.Label(self.body, text=f"for {hint}", background=DROP_BG, foreground="#7F8C8D",
                 font=("Helvetica", 10)).pack()
        if dnd:
            tk.Label(self.body, text="drag the file here, or", background=DROP_BG, foreground="#7F8C8D",
                     font=("Helvetica", 10)).pack(pady=(4, 0))
        ttk.Button(self.body, text="Browse…", command=browse).pack(pady=(6, 0))
        self.status = tk.Label(self.body, text="", background=DROP_BG, foreground="#7F8C8D",
                               font=("Helvetica", 10), justify="center", wraplength=160)
        self.status.pack(pady=(6, 0))
        self.bind("<Configure>", lambda e: self.status.configure(wraplength=max(e.width - 30, 80)))

    def set_status(self, text: str, ok: bool = False):
        self.status.configure(text=text, foreground="#1E7B34" if ok else "#7F8C8D")

    def register_drop(self, on_file):
        def dropped(event):
            self._hover(False)
            paths = self.tk.splitlist(event.data)
            if paths:  # after the drag finishes: opening a dialog inside the drop can lock macOS up
                self.after(100, lambda p=paths[0]: on_file(p))
            return getattr(event, "action", "copy")

        for w in self._all():
            w.drop_target_register(DND_FILES)
            w.dnd_bind("<<Drop>>", dropped)
            w.dnd_bind("<<DropEnter>>", lambda e: self._hover(True))
            w.dnd_bind("<<DropLeave>>", lambda e: self._hover(False))

    def _all(self):
        out, todo = [], [self]
        while todo:
            w = todo.pop()
            if isinstance(w, (tk.Frame, tk.Label)):
                out.append(w)
            todo.extend(w.winfo_children())
        return out

    def _hover(self, on: bool):
        bg = DROP_HOVER if on else DROP_BG
        self.configure(highlightbackground=ACCENT if on else "#B7C3D3")
        for w in self._all():
            w.configure(background=bg)
        return getattr(tk, "COPY", "copy")


class App:
    def __init__(self, root: tk.Tk, dnd: bool):
        self.root = root
        self.dnd = dnd
        self.sheet: Sheet | None = None
        self.mapping: Mapping | None = None  # column matches for the selected layout
        self.meal_sheet: Sheet | None = None  # the Label Data export, for meal labels
        names = T.ensure_default_template()  # may record new built-in layouts in the settings
        self.settings = storage.load_settings()
        migrate_legacy_mapping(names)
        T.install_default_logo()  # refresh the built-in logo after an app update

        root.title(APP_NAME)
        root.minsize(720, 600)
        root.report_callback_exception = self._unexpected_error
        disable_combobox_wheel(root)
        self._build()
        self._refresh_templates()
        self._refresh_mapping_status()
        self._refresh_meal_status()
        self._refresh_generate_state()

        if updater.can_self_update():
            root.after(2500, lambda: self.check_updates(quiet=True))

        if IS_MAC:
            # Files dropped on the Dock icon or opened via Finder's "Open With".
            root.createcommand("::tk::mac::OpenDocument", self._open_documents)
            root.createcommand("::tk::mac::ShowPreferences", lambda: None)

    # ------------------------------------------------------------------ UI
    def _build(self):
        style = ttk.Style(self.root)
        style.configure("Muted.TLabel", foreground="#666666")
        style.configure("Ok.TLabel", foreground="#1E7B34")

        style.configure("Job.TLabel", font=("Helvetica", 13, "bold"))
        style.configure("Link.TLabel", foreground="#1F5FAD", font=("Helvetica", 12, "underline"))

        outer = ttk.Frame(self.root, padding=20)
        outer.pack(fill="both", expand=True)

        head = ttk.Frame(outer)
        head.pack(fill="x")
        ttk.Button(head, text="Templates", command=self.open_templates).pack(side="right")
        ttk.Label(head, text=APP_NAME, font=("Helvetica", 22, "bold"), foreground=ACCENT).pack(side="left")
        ttk.Label(outer, text="Load this week's files, check the date, then generate.",
                  style="Muted.TLabel").pack(anchor="w", pady=(0, 12))

        # Files: one box each; drop a file on a box, or anywhere on the window to have it sorted.
        files = ttk.Frame(outer)
        files.pack(fill="x")
        self.boxes: dict[str, _DropBox] = {}
        for col, (slot, title, hint) in enumerate((("orders", "Orders CSV", "pack slips + bag labels"),
                                                   ("drivers", "Driver list", "drivers (optional)"),
                                                   ("meals", "Meal label CSV", "meal labels"))):
            files.columnconfigure(col, weight=1, uniform="files")
            box = _DropBox(files, title, hint, browse=lambda s=slot: self.browse(s), dnd=self.dnd)
            box.grid(row=0, column=col, sticky="nsew", padx=(0 if col == 0 else 8, 0))
            self.boxes[slot] = box
            if self.dnd:
                box.register_drop(lambda path, s=slot: self.load_file(path, slot=s))
        self.sheet_var = tk.StringVar()  # workbooks with several sheets: which one
        self.sheet_combo = ttk.Combobox(self.boxes["orders"].body, textvariable=self.sheet_var, state="readonly",
                                        width=14)
        self.sheet_combo.bind("<<ComboboxSelected>>", lambda e: self._change_sheet())

        date_row = ttk.Frame(outer)
        date_row.pack(fill="x", pady=(14, 4))
        ttk.Label(date_row, text="Delivery date", style="Job.TLabel").pack(side="left")
        self.date_picker = DatePicker(date_row, default_delivery_date(self._usual_weekday(self.settings.get("template", ""))),
                                      command=self._delivery_chosen)
        self.date_picker.pack(side="left", padx=10)

        # One row per job: what it is, which template, a setting link, and its Generate button.
        jobs = ttk.Frame(outer)
        jobs.pack(fill="x", pady=(10, 0))
        jobs.columnconfigure(1, weight=1)

        def job(row, title):
            ttk.Label(jobs, text=title, style="Job.TLabel").grid(row=row, column=0, sticky="w", pady=(8, 0),
                                                                 padx=(0, 12))

        def link(parent, text, command):
            lbl = ttk.Label(parent, text=text, style="Link.TLabel", cursor="hand2")
            lbl.bind("<Button-1>", lambda e: command())
            return lbl

        def combo(parent, var, on_pick, width=22):
            c = ttk.Combobox(parent, textvariable=var, state="readonly", width=width)
            c.bind("<<ComboboxSelected>>", lambda e: on_pick())
            return c

        job(0, "Delivery report")
        link(jobs, "Pickup locations", self.pickup_locations).grid(row=0, column=2, sticky="e", padx=10, pady=(8, 0))
        self.report_btn = ttk.Button(jobs, text="Generate Delivery Report", command=self.generate_delivery_report,
                                     width=22)
        self.report_btn.grid(row=0, column=3, sticky="ew", pady=(8, 0))
        ttk.Label(jobs, text="For the delivery software: upload it, add drivers, then drop it back in as the "
                             "driver list.", style="Muted.TLabel").grid(row=1, column=1, columnspan=3, sticky="w")

        job(2, "Pack slips")
        self.tpl_var = tk.StringVar()
        self.tpl_combo = combo(jobs, self.tpl_var, self._template_chosen)
        self.tpl_combo.grid(row=2, column=1, sticky="w", pady=(8, 0))
        link(jobs, "Remap Fields", self.remap).grid(row=2, column=2, sticky="e", padx=10, pady=(8, 0))
        self.gen_btn = ttk.Button(jobs, text="Generate Pack Slips", command=self.generate, width=22)
        self.gen_btn.grid(row=2, column=3, sticky="ew", pady=(8, 0))
        self.map_status = ttk.Label(jobs, text="", style="Muted.TLabel")
        self.map_status.grid(row=3, column=1, columnspan=3, sticky="w")

        job(4, "Bag labels")
        self.label_var = tk.StringVar()
        self.label_combo = combo(jobs, self.label_var, self._label_chosen)
        self.label_combo.grid(row=4, column=1, sticky="w", pady=(8, 0))
        self.label_btn = ttk.Button(jobs, text="Generate Bag Labels", command=self.generate_labels, width=22)
        self.label_btn.grid(row=4, column=3, sticky="ew", pady=(8, 0))

        job(5, "Meal labels")
        meal_tpls = ttk.Frame(jobs)  # custom and regular meals each have their own template
        meal_tpls.grid(row=5, column=1, sticky="w", pady=(8, 0))
        self.meal_custom_var, self.meal_regular_var = tk.StringVar(), tk.StringVar()
        self.meal_custom_combo = combo(meal_tpls, self.meal_custom_var, self._meal_layout_chosen, width=18)
        self.meal_regular_combo = combo(meal_tpls, self.meal_regular_var, self._meal_layout_chosen, width=18)
        for r, (text, c) in enumerate((("Custom", self.meal_custom_combo), ("Regular", self.meal_regular_combo))):
            ttk.Label(meal_tpls, text=text, style="Muted.TLabel").grid(row=r, column=0, sticky="w", padx=(0, 6))
            c.grid(row=r, column=1, sticky="w", pady=(0 if r == 0 else 3, 0))
        link(jobs, "Sort & filter", self.meal_sort_filter).grid(row=5, column=2, sticky="e", padx=10, pady=(8, 0))
        self.meal_btn = ttk.Button(jobs, text="Generate Meal Labels", command=self.generate_meal_labels, width=22)
        self.meal_btn.grid(row=5, column=3, sticky="ew", pady=(8, 0))
        self.meal_summary = ttk.Label(jobs, text="", style="Muted.TLabel")
        self.meal_summary.grid(row=6, column=1, columnspan=3, sticky="w", pady=(2, 0))

        self.progress = ttk.Progressbar(outer, mode="determinate")
        self.status = ttk.Label(outer, text="", style="Muted.TLabel")
        self.status.pack(anchor="w", pady=(12, 0))

        footer = ttk.Frame(outer)
        footer.pack(side="bottom", fill="x")
        ttk.Label(footer, text=updater.describe_current().capitalize(), style="Muted.TLabel",
                  font=("Helvetica", 10)).pack(side="right")
        ttk.Button(footer, text="Check for Updates", command=lambda: self.check_updates(quiet=False)).pack(
            side="right", padx=8)
        ttk.Button(footer, text="Show Diagnostics", command=lambda: reveal_path(diagnostics.path())).pack(
            side="left")

        if self.dnd:  # dropped anywhere else on the window: sort it into the right box
            self.root.drop_target_register(DND_FILES)
            self.root.dnd_bind("<<Drop>>", self._on_drop)

    # ------------------------------------------------------- spreadsheets
    def _on_drop(self, event):
        paths = self.root.tk.splitlist(event.data)
        if paths:
            # Let macOS finish the drag before opening any windows: showing a dialog from
            # inside the drop callback can lock the app up.
            diagnostics.note(f"file dropped ({Path(paths[0]).suffix})")
            self.root.after(100, lambda p=paths[0]: self.load_file(p))
        return getattr(event, "action", "copy")

    def _open_documents(self, *paths):
        if paths:
            self.root.after(10, lambda: self.load_file(paths[0]))

    def browse(self, slot: str = "orders"):
        titles = {"orders": "Choose this week's orders file", "drivers": "Choose the driver list",
                  "meals": "Choose the meal label file (Label Data)"}
        path = filedialog.askopenfilename(
            parent=self.root, title=titles[slot], initialdir=self.settings.get("last_dir") or str(Path.home()),
            filetypes=[("Spreadsheets", "*.xlsx *.xlsm *.csv"), ("All files", "*.*")])
        if path:
            self.load_file(path, slot=slot)

    def load_file(self, path, sheet_name=None, slot: str | None = None):
        """Load a file into a box: "orders", "drivers" or "meals". With no slot (dropped elsewhere on
        the window, or opened from the Dock), the file goes to whichever box it looks like it belongs in."""
        path = Path(path)
        diagnostics.note(f"load spreadsheet ({path.suffix}) into {slot or 'auto'}")
        try:
            sheet = load_sheet(path, sheet_name)
        except SpreadsheetError as e:
            messagebox.showerror("Can't read that spreadsheet", str(e), parent=self.root)
            return
        if slot == "meals" or (slot is None and looks_like_meal_file(sheet)):
            self._use_meal_sheet(sheet)
            return
        if slot == "drivers":
            if not self._all_values():
                messagebox.showinfo("Load the orders first",
                                    "Load this week's orders file first, then the driver list.", parent=self.root)
                return
            self.load_route_file(path, sheet)
            return
        if slot == "orders" and looks_like_meal_file(sheet):
            if ask_choice(self.root, "Meal label file?", f"“{path.name}” looks like the meal label file "
                          "(Label Data), not an orders file.",
                          ["Use it for meal labels", "Load it as orders anyway"]) == 0:
                self._use_meal_sheet(sheet)
                return
        if slot is None and self.sheet is not None and self.mapping is not None and looks_like_route_file(sheet) and \
                self._fit(self.tpl_var.get(), sheet) <= 0:
            choice = ask_choice(self.root, "Driver list?",
                                f"“{path.name}” looks like a driver list (it has a driver column but no "
                                "items). Use it to put the driver on each pack slip?",
                                ["Yes, it's the driver list", "No, load it as this week's orders"])
            if choice is None:
                return
            if choice == 0:
                self.load_route_file(path, sheet)
                return
        self.sheet = sheet
        self.route_sheet = None  # a new orders file needs its driver list loaded again
        self.settings["last_dir"] = str(path.parent)
        storage.save_settings(self.settings)
        self._refresh_file_status()
        if len(sheet.sheet_names) > 1:
            self.sheet_combo.configure(values=sheet.sheet_names)
            self.sheet_var.set(sheet.sheet_name)
            self.sheet_combo.pack(pady=(4, 0))
        else:
            self.sheet_combo.pack_forget()
        self.status.configure(text="")
        self._choose_layout_for(sheet)
        if self.mapping is not None and self.mapping.fill_new_fields(sheet.headers):
            save_mapping(self.mapping, self.tpl_var.get())  # match fields added in an app update
        self._load_remembered_drivers()
        day = sheet_delivery_date(sheet)
        if day is not None:  # the file says when these go out: pre-select it
            self.date_picker.set(day)
        self._refresh_file_status()
        self._refresh_mapping_status()
        self._refresh_generate_state()

    def slip_count(self) -> int:
        if self.sheet is None:
            return 0
        return len(self.mapping.records(self.sheet.rows)) if self.mapping else len(self.sheet.rows)

    def _refresh_file_status(self):
        if self.sheet is None:
            return
        n = self.slip_count()
        what = "order" if self.mapping and self.mapping.items_mode == "rows" else "customer"
        self.boxes["orders"].set_status(f"✓ {self.sheet.path.name}\n{n} {what}{'s' if n != 1 else ''}", ok=True)

    def _fit(self, name: str, sheet: Sheet) -> int:
        m = load_mapping(name)
        tpl = T.load_template(name)
        if m is None or tpl is None:
            return -1
        return m.fit_score(sheet.headers, tpl.used_field_keys(m))

    def _choose_layout_for(self, sheet: Sheet):
        """Use the layout whose column matches fit this spreadsheet (one layout per business)."""
        current = self.tpl_var.get()
        if self._fit(current, sheet) > 0:
            return
        if self.mapping is None or self.mapping.is_empty():
            # The selected layout has never been matched (e.g. just created): set it up for this
            # spreadsheet rather than switching to another layout.
            self.remap(first_time=True)
            return
        scores = {n: self._fit(n, sheet) for n in T.list_templates(T.SLIP) if n != current}
        best = max(scores, key=scores.get, default=None)
        if best is not None and scores[best] > 0:
            self._refresh_templates(best)
            self.status.configure(text=f"Switched to the “{best}” layout, which matches this spreadsheet.",
                                  style="Ok.TLabel")
            return
        if self.mapping is None or self.mapping.is_empty():
            # The selected layout has never been matched: set it up for this spreadsheet.
            self.remap(first_time=True)
            return
        missing = self.mapping.missing_columns(sheet.headers, self._current_template().used_field_keys(self.mapping))
        cols = "\n".join(f"  • {label}  (expected “{col}”)" for label, col in missing[:6])
        choice = ask_choice(
            self.root, "This spreadsheet doesn't match",
            f"This spreadsheet doesn't have the columns the “{current}” layout uses:\n\n{cols}\n\n"
            "Is it for a different business, or did the column headings change?",
            ["It's a different business: make a new layout for it",
             f"Headings changed: re-match the “{current}” layout",
             "Cancel"])
        if choice == 0:
            self.new_business_layout()
        elif choice == 1:
            self.remap(fresh_guess=True)  # the old matches don't fit: start from new guesses

    def new_business_layout(self):
        """A new layout = its own slip design + its own column matches (e.g. one per spreadsheet type)."""
        name = ask_name(self.root, "New layout",
                        "Each layout has its own slip design and remembers its own spreadsheet columns.\n"
                        "Make one for each kind of spreadsheet (or business).\n\nName for the new layout:")
        if not name:
            return
        if name.lower() in {n.lower() for n in T.list_templates()}:
            messagebox.showwarning("Name taken", f"There's already a layout called “{name}”.", parent=self.root)
            return
        current = self._current_template()
        logo = next((e.get("image") for e in current.elements if e["type"] == "logo" and e.get("image")), "")
        keep_logo = False
        if logo:
            choice = ask_choice(self.root, "Logo", f"Which logo should the “{name}” layout use?",
                                [f"The same logo as “{current.name}”", "No logo yet (I'll add one in Edit Layout)"])
            if choice is None:
                return
            keep_logo = choice == 0
        tpl = T.default_template(name)
        tpl.brand = dict(current.brand)
        for el in tpl.elements:
            if el["type"] == "logo":
                el["image"] = logo if keep_logo else ""
        T.save_template(tpl)
        self._refresh_templates(name)
        if self.sheet is None:
            self.status.configure(text=f"Layout “{name}” created. Load its spreadsheet to match the columns.",
                                  style="Ok.TLabel")
            return
        self.remap(first_time=True)
        if self.mapping is not None and not self.mapping.is_empty():
            self.status.configure(text=f"Layout “{name}” is ready and remembers this spreadsheet's columns.",
                                  style="Ok.TLabel")

    def _change_sheet(self):
        if self.sheet and self.sheet_var.get() != self.sheet.sheet_name:
            self.load_file(self.sheet.path, self.sheet_var.get())

    # ------------------------------------------------------ mapping/layout
    def remap(self, first_time=False, fresh_guess=False):
        if self.sheet is None:
            messagebox.showinfo("Load a spreadsheet first",
                                "Load this week's spreadsheet first, so the app can show you its columns.",
                                parent=self.root)
            return
        diagnostics.note(f"matching screen: opening (layout has matches: {bool(self.mapping)})")
        dlg = MappingDialog(self.root, self.mapping, self.sheet, fresh_guess=fresh_guess)
        if dlg.winfo_exists():
            self.root.wait_window(dlg)
        diagnostics.note(f"matching screen: closed ({'saved' if dlg.result is not None else 'cancelled'})")
        if dlg.result is not None:
            self.mapping = dlg.result
            save_mapping(self.mapping, self.tpl_var.get())
        elif first_time and (self.mapping is None or self.mapping.is_empty()):
            self.status.configure(text="Fields aren't matched yet — click “Remap Fields…” when you're ready.")
        self._refresh_mapping_status()
        self._refresh_generate_state()

    # ------------------------------------------------------------- drivers
    def _all_values(self) -> list[dict]:
        if self.sheet is None or self.mapping is None or self.mapping.is_empty():
            return []
        return [self.mapping.values_for_row(r) for r in self.mapping.records(self.sheet.rows)]

    def _driver_assignment(self) -> dict[int, str]:
        """Record index -> driver for the loaded sheet (stored by customer, so re-reading the file is safe)."""
        by_key = getattr(self, "driver_by_key", {})
        return {i: by_key[k] for i, v in enumerate(self._all_values()) if (k := customer_key(v)) in by_key}

    def _load_remembered_drivers(self):
        """Drivers come only from this week's driver list (re-applied if the orders are re-matched)."""
        self.driver_by_key, self.stop_by_key = {}, {}
        if getattr(self, "route_sheet", None) is not None:
            self._apply_routes()
        self._refresh_driver_status()

    def _stop_assignment(self) -> dict[int, int]:
        by_key = getattr(self, "stop_by_key", {})
        return {i: by_key[k] for i, v in enumerate(self._all_values()) if (k := customer_key(v)) in by_key}

    def choose_route_file(self):
        if not self._all_values():
            messagebox.showinfo("Load the orders first",
                                "Load this week's orders spreadsheet first, then the driver list.", parent=self.root)
            return
        path = filedialog.askopenfilename(
            parent=self.root, title="Choose the driver list", initialdir=self.settings.get("last_dir") or str(Path.home()),
            filetypes=[("Spreadsheets", "*.xlsx *.xlsm *.csv"), ("All files", "*.*")])
        if path:
            try:
                sheet = load_sheet(Path(path))
            except SpreadsheetError as e:
                messagebox.showerror("Can't read that file", str(e), parent=self.root)
                return
            self.load_route_file(Path(path), sheet)

    def load_route_file(self, path: Path, sheet: Sheet):
        """Match the route file's columns (pre-filled), then give each order its driver/route and stop."""
        diagnostics.note(f"driver list: {path.suffix}")
        values = self._all_values()
        book = DriverBook.load(self.tpl_var.get())
        cols = RouteColumns.from_json(book.route_columns)
        if not cols.fits(sheet.headers):
            cols = guess_route_columns(sheet.headers)
        dlg = RouteDialog(self.root, sheet, cols, values)
        if dlg.winfo_exists():
            self.root.wait_window(dlg)
        if dlg.result is None:
            return
        book.route_columns = dlg.result.to_json()
        book.save()
        self.route_sheet, self.route_cols, self.route_name = sheet, dlg.result, path.name
        self._apply_routes()
        self._refresh_driver_status()

    def _apply_routes(self):
        values = self._all_values()
        res = join_routes(self.route_sheet, self.route_cols, values)
        for i, d in res.assignment.items():
            self.driver_by_key[customer_key(values[i])] = d
        self.stop_by_key = {customer_key(values[i]): n for i, n in res.stops.items()}

    def _refresh_driver_status(self):
        if not hasattr(self, "boxes"):
            return
        values = self._all_values()
        if not values or getattr(self, "route_sheet", None) is None:
            self.boxes["drivers"].set_status("")
            return
        n = len(self._driver_assignment())
        drivers = len(set(self._driver_assignment().values()))
        self.boxes["drivers"].set_status(f"✓ {self.route_name}\n{n} of {len(values)} orders matched, "
                                         f"{drivers} driver{'s' if drivers != 1 else ''}", ok=True)

    def _refresh_mapping_status(self):
        self._refresh_file_status()  # the slip count depends on the matches (grouped orders)
        if self.mapping is None or self.mapping.is_empty():
            self.map_status.configure(text=f"Columns for “{self.tpl_var.get()}”: not matched yet")
            return
        n = sum(1 for v in self.mapping.columns.values() if v)
        text = f"Columns for “{self.tpl_var.get()}”: {n} matched"
        if self.mapping.items_mode == "rows":
            text += f", grouped by “{self.mapping.group_by}”"
        if self.mapping.items_mode == "columns":
            if self.sheet is not None:
                text += f" + {len(self.mapping.item_headers(self.sheet.headers))} menu items"
            else:
                text += " + menu-item columns"
        self.map_status.configure(text=text)
        self._refresh_driver_status()

    def _refresh_templates(self, select: str | None = None):
        """Reload both layout lists. `select` (e.g. the layout the editor closed on) is chosen in
        whichever list it belongs to; the other list keeps its choice."""
        names = T.ensure_default_template()
        labels = T.list_templates(T.LABEL)
        self.tpl_combo.configure(values=names)
        want = select if select in names else self.settings.get("template")
        self.tpl_var.set(want if want in names else names[0])
        self._template_chosen()
        self.label_combo.configure(values=labels)
        want = select if select in labels else self.settings.get("label_layout")
        self.label_var.set(want if want in labels else (labels[0] if labels else ""))
        if self.label_var.get() != self.settings.get("label_layout"):
            self._label_chosen()
        meals = T.list_templates(T.MEAL)
        saved = self.settings.get("meal_labels") or {}
        for kind, var, box in (("custom", self.meal_custom_var, self.meal_custom_combo),
                               ("regular", self.meal_regular_var, self.meal_regular_combo)):
            box.configure(values=meals)
            want = select if select in meals and (T.load_template(select) or T.Template()).meal_for in (kind, "all") \
                else saved.get(f"{kind}_layout")
            if want not in meals:  # the template that says it's for this kind of meal
                want = next((n for n in meals if (T.load_template(n) or T.Template()).meal_for == kind),
                            meals[0] if meals else "")
            var.set(want)
        self._meal_layout_chosen()

    def _label_chosen(self):
        self.settings["label_layout"] = self.label_var.get()
        storage.save_settings(self.settings)

    def _delivery_chosen(self, d):
        if not hasattr(self, "tpl_var"):  # the date picker reports its first date while the window is built
            return
        layout = self.tpl_var.get()
        if layout:  # each layout (business) remembers its own delivery day
            self.settings.setdefault("delivery_weekday_by_layout", {})[layout] = d.weekday()
            storage.save_settings(self.settings)

    def _usual_weekday(self, layout: str):
        return self.settings.get("delivery_weekday_by_layout", {}).get(layout, self.settings.get("delivery_weekday"))

    def delivery_values(self) -> dict:
        d = self.date_picker.value
        return {"delivery_date": format_delivery_date(d), "delivery_date_short": f"{d:%m/%d/%y}"}

    def _template_chosen(self):
        name = self.tpl_var.get()
        changed = name != getattr(self, "_shown_layout", None)
        self._shown_layout = name
        self.settings["template"] = name
        storage.save_settings(self.settings)
        self.mapping = load_mapping(name)
        self._refresh_mapping_status()
        if changed:
            self.date_picker.set(default_delivery_date(self._usual_weekday(name)))
            self._load_remembered_drivers()

    def _current_template(self) -> T.Template:
        return T.load_template(self.tpl_var.get()) or T.default_template(self.tpl_var.get() or "Standard")

    def edit_layout(self, name: str | None = None):
        """Open the layout editor on `name` (default: the selected pack-slip layout)."""
        name = name or self.tpl_var.get()
        if getattr(self, "_designer", None) is not None and self._designer.winfo_exists():
            self._designer._meal_sheet = self.meal_sheet
            self._designer._switch_template(name)
            self._designer.lift()
            return
        mapping = load_mapping(name) or Mapping()
        self._designer = Designer(self.root, name, mapping, self.sheet,
                                  extra_values=self.delivery_values,
                                  on_close=lambda closed: self._refresh_templates(closed),
                                  meal_sheet=self.meal_sheet)

    def open_templates(self):
        """The template builder, opened on the selected pack slip template; pick another kind inside."""
        self.edit_layout()

    def _refresh_generate_state(self):
        """Each Generate button works only once the file it needs is loaded."""
        orders, meals = self.sheet is not None, self.meal_sheet is not None
        for btn, ready in ((self.report_btn, orders), (self.gen_btn, orders), (self.label_btn, orders),
                           (self.meal_btn, meals)):
            btn.state(["!disabled"] if ready else ["disabled"])
        if not orders and not meals:
            self.status.configure(text=self.status.cget("text") or "Load this week's files to get started.")

    # ------------------------------------------------------------ generate
    def _output_path(self, prefix: str = "Pack Slips", sheet: Sheet | None = None) -> Path:
        """Next to the spreadsheet (default: the orders), or in Documents/Pack Slips if that's read-only."""
        src = (sheet or self.sheet).path
        out = default_output_path(src, self.date_picker.value, prefix)
        if os.access(out.parent, os.W_OK):
            return out
        fallback = Path.home() / "Documents" / "Pack Slips"
        fallback.mkdir(parents=True, exist_ok=True)
        return default_output_path(fallback / src.name, self.date_picker.value, prefix)

    # ------------------------------------------------------ delivery report
    def pickup_locations(self):
        dlg = PickupLocationsDialog(self.root)
        if dlg.winfo_exists():
            self.root.wait_window(dlg)

    def generate_delivery_report(self):
        if self.sheet is None:
            messagebox.showinfo("No orders file yet", "Load this week's orders file first.", parent=self.root)
            return
        try:  # re-read so last-minute edits are included
            self.sheet = load_sheet(self.sheet.path, self.sheet.sheet_name)
        except SpreadsheetError as e:
            messagebox.showerror("Can't read that spreadsheet", str(e), parent=self.root)
            return
        report = build_report(self.sheet, load_locations())
        if report.errors:
            messagebox.showerror("Can't make the delivery report", "\n\n".join(report.errors), parent=self.root)
            return
        out = self._report_path()
        dlg = ReportCheckDialog(self.root, report, out.name)
        if dlg.winfo_exists():
            self.root.wait_window(dlg)
        if not dlg.save:
            return
        fold_into_drops(report, dlg.fold)
        try:
            write_report(out, report.rows)
        except OSError as e:
            messagebox.showerror("Couldn't save the delivery report", f"The file couldn't be saved: {e.strerror or e}.",
                                 parent=self.root)
            return
        diagnostics.note(f"delivery report: {len(report.rows)} rows")
        self.status.configure(text=f"✓  Last run: delivery report with {len(report.rows)} stops saved to {out.name}",
                              style="Ok.TLabel")
        self._show_success(out, len(report.rows), title="Delivery report ready",
                           detail=f"{len(report.rows)} stops. Upload it to the delivery software, add the drivers, "
                                  "then drop the file back on the Driver list box.")

    def _report_path(self) -> Path:
        """Honeyplate_Delivery_Report_<date>.csv next to the orders file (never overwrites)."""
        folder = self.sheet.path.parent if os.access(self.sheet.path.parent, os.W_OK) else \
            Path.home() / "Documents" / "Pack Slips"
        folder.mkdir(parents=True, exist_ok=True)
        stem = f"Honeyplate_Delivery_Report_{self.date_picker.value:%Y-%m-%d}"
        out, n = folder / f"{stem}.csv", 2
        while out.exists():
            out, n = folder / f"{stem} ({n}).csv", n + 1
        return out

    # --------------------------------------------------------- meal labels
    def _use_meal_sheet(self, sheet: Sheet):
        if not looks_like_meal_file(sheet) and ask_choice(
                self.root, "Meal label file?", f"“{sheet.path.name}” doesn't look like the meal label file "
                "(no Product / Calories / How to Prepare columns).", ["Use it anyway", "Cancel"]) != 0:
            return
        self.meal_sheet = sheet
        self.settings["last_dir"] = str(sheet.path.parent)
        storage.save_settings(self.settings)
        self._refresh_meal_status()
        self._refresh_generate_state()

    def _refresh_meal_status(self):
        self.meal_summary.configure(text=meal_window.describe(self.settings))
        if self.meal_sheet is None:
            return
        recs = filter_records(read_records(self.meal_sheet), **meal_window.filters(self.settings))
        custom = sum(1 for r in recs if r["kind"] == "custom")
        self.boxes["meals"].set_status(f"✓ {self.meal_sheet.path.name}\n{len(recs)} labels "
                                       f"({custom} custom, {len(recs) - custom} regular)", ok=bool(recs))

    def _meal_layout_chosen(self):
        self.settings["meal_labels"] = {**(self.settings.get("meal_labels") or {}),
                                        "custom_layout": self.meal_custom_var.get(),
                                        "regular_layout": self.meal_regular_var.get()}
        storage.save_settings(self.settings)

    def meal_sort_filter(self):
        dlg = meal_window.SortFilterDialog(self.root, self.settings)
        if dlg.winfo_exists():
            self.root.wait_window(dlg)
        self._refresh_meal_status()

    def generate_meal_labels(self):
        sheet = self.meal_sheet
        if sheet is None:
            messagebox.showinfo("No meal label file yet", "Load the meal label file (Label Data) first.",
                                parent=self.root)
            return
        try:  # re-read so last-minute edits are included
            sheet = self.meal_sheet = load_sheet(sheet.path, sheet.sheet_name)
        except SpreadsheetError as e:
            messagebox.showerror("Can't read that file", str(e), parent=self.root)
            return
        custom = T.load_template(self.meal_custom_var.get()) if self.meal_custom_var.get() else None
        regular = T.load_template(self.meal_regular_var.get()) if self.meal_regular_var.get() else None
        if custom is None or regular is None:
            messagebox.showinfo("Pick the templates", "Choose a meal label template for custom and for regular "
                                "meals (or make one in Templates).", parent=self.root)
            return
        out = self._output_path("Meal Labels", sheet)
        diagnostics.note("generate meal labels")
        try:
            n = generate_meal_labels(out, sheet, custom, regular, sort=meal_window.sort_keys(self.settings),
                                     filters=meal_window.filters(self.settings), extra=self.delivery_values())
        except GenerateError as e:
            messagebox.showerror("Couldn't make the meal labels", str(e), parent=self.root)
            return
        self.status.configure(text=f"✓  Last run: {n} meal label{'s' if n != 1 else ''} saved to {out.name}",
                              style="Ok.TLabel")
        self._show_success(out, n, title="Meal labels ready",
                           detail=f"{n} label{'s' if n != 1 else ''}, one per container.\n"
                                  "Print at Actual size (100%), not “Fit to page”.")

    def _ready_to_generate(self) -> bool:
        """A spreadsheet is loaded (re-read for last-minute edits) and its columns are matched."""
        if self.sheet is None:
            messagebox.showinfo("No spreadsheet yet", "First load this week's spreadsheet (step 1).", parent=self.root)
            return False
        try:
            self.sheet = load_sheet(self.sheet.path, self.sheet.sheet_name)
        except SpreadsheetError as e:
            messagebox.showerror("Can't read that spreadsheet", str(e), parent=self.root)
            return False
        if self.mapping is None or self.mapping.is_empty():
            self.remap(first_time=True)
        return self.mapping is not None and not self.mapping.is_empty()

    def generate_labels(self):
        """Bag labels for the loaded orders, using the selected pack-slip layout's column matches."""
        name = self.label_var.get()
        tpl = T.load_template(name) if name else None
        if tpl is None:
            messagebox.showinfo("No bag label layout", "There's no bag label layout yet. Make one in "
                                "Edit Layout (Duplicate “Pickup Bag Label”).", parent=self.root)
            return
        if not self._ready_to_generate():
            return
        out = self._output_path("Bag Labels")
        diagnostics.note("generate bag labels")
        try:
            labels = generate_labels(out, tpl, self.mapping, self.sheet, extra=self.delivery_values())
        except GenerateError as e:
            messagebox.showerror("Couldn't make the bag labels", str(e), parent=self.root)
            return
        self.status.configure(text=f"✓  Last run: {labels} bag label{'s' if labels != 1 else ''} saved to {out.name}",
                              style="Ok.TLabel")
        self._show_success(out, labels, title="Bag labels ready",
                           detail=f"{labels} label{'s' if labels != 1 else ''}: one per bag, A–Z by last name.\n"
                                  "On the Zebra, print at Actual size (100%), not “Fit to page”.")

    def generate(self):
        if not self._ready_to_generate():
            return
        tpl = self._current_template()
        try:
            check_ready(tpl, self.mapping, self.sheet)
        except GenerateError as e:
            if messagebox.askyesno("Can't make the pack slips yet", f"{e}\n\nOpen “Remap Fields” now?",
                                   parent=self.root, icon="warning"):
                self.remap()
            return
        warnings = blank_line_warnings(tpl, self.mapping, len(self._driver_assignment()))
        if warnings and ask_choice(self.root, "Some lines will be blank", "\n\n".join(warnings),
                                   ["Generate Anyway", "Cancel"]) != 0:
            return

        out = self._output_path()
        self.gen_btn.state(["disabled"])
        self.progress.configure(maximum=max(self.slip_count(), 1), value=0)
        self.progress.pack(fill="x", pady=(8, 0), before=self.status)
        self.status.configure(text="Making pack slips…", style="Muted.TLabel")
        self.root.configure(cursor="watch")
        self.root.update()

        def progress(i, total):
            self.progress.configure(value=i)
            if i % 10 == 0 or i == total:
                self.status.configure(text=f"Making pack slips… {i} of {total}")
                self.root.update_idletasks()

        try:
            pages = generate_pdf(out, tpl, self.mapping, self.sheet, progress=progress,
                                 extra=self.delivery_values(), drivers=self._driver_assignment(),
                                 stops=self._stop_assignment())
        except GenerateError as e:
            messagebox.showerror("Couldn't make the PDF", str(e), parent=self.root)
            self.status.configure(text="")
            return
        finally:
            self.gen_btn.state(["!disabled"])
            self.progress.pack_forget()
            self.root.configure(cursor="")
        self.status.configure(text=f"✓  Last run: {pages} pack slip{'s' if pages != 1 else ''} saved to {out.name}", style="Ok.TLabel")
        self._show_success(out, pages)

    def _show_success(self, out: Path, pages: int, title: str = "Pack slips ready", detail: str = ""):
        win = tk.Toplevel(self.root)
        win.title(title)
        win.transient(self.root)
        win.resizable(False, False)
        f = ttk.Frame(win, padding=22)
        f.pack(fill="both", expand=True)
        ttk.Label(f, text=f"✓  Your {title.replace(' ready', '').lower()} are ready", font=("Helvetica", 17, "bold"),
                  foreground="#1E7B34").pack(anchor="w")
        ttk.Label(f, text=detail or f"{pages} page{'s' if pages != 1 else ''} — one per customer.",
                  justify="left").pack(anchor="w", pady=(6, 10))
        ttk.Label(f, text="Saved as:", style="Muted.TLabel").pack(anchor="w")
        win.path_var = tk.StringVar(master=win, value=str(out))  # keep a reference or Tk shows it blank
        entry = ttk.Entry(f, textvariable=win.path_var, width=60, state="readonly")
        entry.pack(fill="x", pady=(2, 16))
        btns = ttk.Frame(f)
        btns.pack(fill="x")
        ttk.Button(btns, text="Done", command=win.destroy).pack(side="right")
        ttk.Button(btns, text="Show in Finder" if IS_MAC else "Show Folder",
                   command=lambda: (reveal_path(out), win.destroy())).pack(side="right", padx=8)
        open_btn = ttk.Button(btns, text="Open PDF to Print", command=lambda: (open_path(out), win.destroy()),
                              default="active")
        open_btn.pack(side="right")
        win.bind("<Return>", lambda e: (open_path(out), win.destroy()))
        win.bind("<Escape>", lambda e: win.destroy())
        center_on(win, self.root)
        make_modal(win)
        open_btn.focus_set()

    # ------------------------------------------------------------- updates
    def _in_background(self, work, done):
        """Run work() on a thread; call done(result, error) back on the Tk thread."""
        q: queue.Queue = queue.Queue()

        def run():
            try:
                q.put((work(), None))
            except Exception as e:  # noqa: BLE001 - reported to the user below
                q.put((None, e))

        def poll():
            try:
                result, error = q.get_nowait()
            except queue.Empty:
                self.root.after(150, poll)
                return
            done(result, error)

        threading.Thread(target=run, daemon=True).start()
        self.root.after(150, poll)

    def _busy_elsewhere(self) -> bool:
        return any(isinstance(w, tk.Toplevel) and w.winfo_exists() for w in self.root.winfo_children())

    def check_updates(self, quiet: bool):
        if not updater.can_self_update():
            if not quiet:
                messagebox.showinfo("Updates", "Updates can only be installed in the Mac app.", parent=self.root)
            return
        if quiet and self._busy_elsewhere():  # don't interrupt another window; ask again shortly
            self.root.after(30_000, lambda: self.check_updates(quiet=True))
            return

        def done(info, error):
            if error is not None:
                if not quiet:
                    msg = str(error) if isinstance(error, updater.UpdateError) else f"Couldn't check for updates: {error}"
                    messagebox.showerror("Couldn't check for updates", msg, parent=self.root)
                return
            if info is not None and quiet and self._busy_elsewhere():
                self.root.after(30_000, lambda: self.check_updates(quiet=True))
                return
            if info is None:
                if not quiet:
                    messagebox.showinfo("Up to date", f"You have the latest version ({updater.describe_current()}).",
                                        parent=self.root)
                return
            self._offer_update(info)

        self._in_background(lambda: updater.check_for_update(raise_errors=not quiet), done)

    def _offer_update(self, info):
        designer = getattr(self, "_designer", None)
        if designer is not None and designer.winfo_exists():
            messagebox.showinfo("Update available",
                                "A new version is ready. Close the Edit Layout window, then click "
                                "“Check for Updates” to install it.", parent=self.root)
            return
        choice = ask_choice(
            self.root, "Update available",
            f"A new version of {APP_NAME} is ready ({info.describe()}; you have {updater.describe_current()}).\n\n"
            "Updating takes about a minute. The app closes and reopens by itself. Your layouts, column "
            "matches and logos are kept.",
            ["Update Now", "Later"])
        if choice == 0:
            self._install_update(info)

    def _install_update(self, info):
        win = tk.Toplevel(self.root)
        win.title("Updating")
        win.transient(self.root)
        win.resizable(False, False)
        f = ttk.Frame(win, padding=20)
        f.pack(fill="both", expand=True)
        ttk.Label(f, text=f"Downloading the new version of {APP_NAME}…").pack(anchor="w")
        bar = ttk.Progressbar(f, mode="indeterminate", length=320)
        bar.pack(fill="x", pady=(10, 0))
        bar.start(12)
        win.protocol("WM_DELETE_WINDOW", lambda: None)  # can't cancel mid-download
        center_on(win, self.root)
        make_modal(win)

        def done(result, error):
            bar.stop()
            win.destroy()
            if error is not None:
                msg = str(error) if isinstance(error, updater.UpdateError) else \
                    "Something went wrong while downloading the update."
                messagebox.showerror("Couldn't update", f"{msg}\n\nYou can keep using this version.",
                                     parent=self.root)
                return
            new_app, bundle, work = result
            updater.start_swap(new_app, bundle, work)
            self.root.destroy()  # the swap script waits for us to quit, then reopens the new version

        self._in_background(lambda: updater.prepare_update(info), done)

    # -------------------------------------------------------------- errors
    def _unexpected_error(self, exc, val, tb):
        log = storage.data_dir() / "error-log.txt"
        try:
            with open(log, "a", encoding="utf-8") as f:
                f.write(f"\n--- {dt.datetime.now():%Y-%m-%d %H:%M:%S} (v{__version__})\n")
                f.write("".join(traceback.format_exception(exc, val, tb)))
        except OSError:
            pass
        try:
            self.root.configure(cursor="")
            self.gen_btn.state(["!disabled"])
            self.progress.pack_forget()
        except tk.TclError:
            pass
        messagebox.showerror(
            "Something went wrong",
            "Sorry — something unexpected happened, and that last step didn't finish.\n\n"
            "Please try again. If it keeps happening, send this file to whoever set up the app:\n\n"
            f"{log}", parent=self.root)


def run_gui(initial_file: str | None = None) -> None:
    root, dnd = make_root()
    app = App(root, dnd)
    root.update_idletasks()
    w, h = 640, 700
    x = max((root.winfo_screenwidth() - w) // 2, 0)
    y = max((root.winfo_screenheight() - h) // 3, 0)
    root.geometry(f"{w}x{h}+{x}+{y}")
    if initial_file:
        root.after(200, lambda: app.load_file(initial_file))
    root.lift()
    diagnostics.start_watchdog(root)
    root.lift()
    root.focus_force()
    root.mainloop()
