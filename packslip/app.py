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
from .drivers import DriverBook, customer_key, is_pickup
from .drivers_dialog import DriversDialog
from .mapping import Mapping, load_mapping, migrate_legacy_mapping, save_mapping
from .mapping_dialog import MappingDialog
from .datepicker import DatePicker, default_delivery_date, sheet_delivery_date
from .pdfgen import GenerateError, check_ready, default_output_path, format_delivery_date, generate_pdf
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


class App:
    def __init__(self, root: tk.Tk, dnd: bool):
        self.root = root
        self.dnd = dnd
        self.sheet: Sheet | None = None
        self.mapping: Mapping | None = None  # column matches for the selected layout
        self.settings = storage.load_settings()
        migrate_legacy_mapping(T.ensure_default_template())
        T.install_default_logo()  # refresh the built-in logo after an app update

        root.title(APP_NAME)
        root.minsize(560, 520)
        root.report_callback_exception = self._unexpected_error
        disable_combobox_wheel(root)
        self._build()
        self._refresh_templates()
        self._refresh_mapping_status()
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
        style.configure("Big.TButton", font=("Helvetica", 16, "bold"), padding=(20, 12))
        style.configure("Step.TLabel", font=("Helvetica", 14, "bold"))
        style.configure("Muted.TLabel", foreground="#666666")
        style.configure("Ok.TLabel", foreground="#1E7B34")

        outer = ttk.Frame(self.root, padding=22)
        outer.pack(fill="both", expand=True)

        ttk.Label(outer, text=APP_NAME, font=("Helvetica", 22, "bold"), foreground=ACCENT).pack(anchor="w")
        ttk.Label(outer, text="Turn this week's order spreadsheet into printable pack slips.",
                  style="Muted.TLabel").pack(anchor="w", pady=(0, 14))

        # Step 1 — spreadsheet
        ttk.Label(outer, text="1.  Load this week's spreadsheet", style="Step.TLabel").pack(anchor="w")
        self.drop = tk.Frame(outer, background=DROP_BG, highlightthickness=2,
                             highlightbackground="#B7C3D3", height=110)
        self.drop.pack(fill="x", pady=(6, 4))
        self.drop.pack_propagate(False)
        inner = tk.Frame(self.drop, background=DROP_BG)
        inner.place(relx=0.5, rely=0.5, anchor="center")
        drop_text = ("Drag your spreadsheet (.xlsx or .csv) here" if self.dnd
                     else "Choose your spreadsheet (.xlsx or .csv)")
        self.drop_label = tk.Label(inner, text=drop_text, background=DROP_BG, foreground="#34495E",
                                   font=("Helvetica", 14))
        self.drop_label.pack()
        tk.Label(inner, text="or", background=DROP_BG, foreground="#7F8C8D").pack(pady=2)
        ttk.Button(inner, text="Browse…", command=self.browse).pack()
        self._drop_inner = inner

        sheet_row = ttk.Frame(outer)
        sheet_row.pack(fill="x")
        self.file_status = ttk.Label(sheet_row, text="No spreadsheet loaded yet.", style="Muted.TLabel")
        self.file_status.pack(side="left")
        self.sheet_var = tk.StringVar()
        self.sheet_combo = ttk.Combobox(sheet_row, textvariable=self.sheet_var, state="readonly", width=18)
        self.sheet_combo.bind("<<ComboboxSelected>>", lambda e: self._change_sheet())

        # Step 2 — layout & fields
        ttk.Label(outer, text="2.  Check the layout", style="Step.TLabel").pack(anchor="w", pady=(18, 4))
        row = ttk.Frame(outer)
        row.pack(fill="x")
        ttk.Label(row, text="Layout:").pack(side="left")
        self.tpl_var = tk.StringVar()
        self.tpl_combo = ttk.Combobox(row, textvariable=self.tpl_var, state="readonly", width=24)
        self.tpl_combo.pack(side="left", padx=6)
        self.tpl_combo.bind("<<ComboboxSelected>>", lambda e: self._template_chosen())
        ttk.Button(row, text="Edit Layout…", command=self.edit_layout).pack(side="left")
        ttk.Button(row, text="New Layout…", command=self.new_business_layout).pack(side="left", padx=6)

        row2 = ttk.Frame(outer)
        row2.pack(fill="x", pady=(6, 0))
        self.map_status = ttk.Label(row2, text="", style="Muted.TLabel")
        self.map_status.pack(side="left")
        ttk.Button(row2, text="Remap Fields…", command=self.remap).pack(side="right")
        row3 = ttk.Frame(outer)
        row3.pack(fill="x", pady=(6, 0))
        self.driver_status = ttk.Label(row3, text="", style="Muted.TLabel")
        self.driver_status.pack(side="left")
        ttk.Button(row3, text="Assign Drivers…", command=self.assign_drivers).pack(side="right")

        # Step 3 — generate
        ttk.Label(outer, text="3.  Pick the delivery date and make the PDF", style="Step.TLabel").pack(
            anchor="w", pady=(18, 6))
        date_row = ttk.Frame(outer)
        date_row.pack(fill="x", pady=(0, 8))
        ttk.Label(date_row, text="Delivery date:").pack(side="left")
        self.gen_btn = ttk.Button(outer, text="Generate Pack Slips", style="Big.TButton", command=self.generate)
        self.date_picker = DatePicker(date_row, default_delivery_date(self._usual_weekday(self.settings.get("template", ""))),
                                      command=self._delivery_chosen)
        self.date_picker.pack(side="left", padx=6)
        self.gen_btn.pack(fill="x")
        self.progress = ttk.Progressbar(outer, mode="determinate")
        self.status = ttk.Label(outer, text="", style="Muted.TLabel")
        self.status.pack(anchor="w", pady=(8, 0))

        footer = ttk.Frame(outer)
        footer.pack(side="bottom", fill="x")
        ttk.Label(footer, text=f"Version {__version__} ({updater.describe_current()})", style="Muted.TLabel",
                  font=("Helvetica", 10)).pack(side="right")
        ttk.Button(footer, text="Check for Updates", command=lambda: self.check_updates(quiet=False)).pack(
            side="right", padx=8)
        ttk.Button(footer, text="Show Diagnostics", command=lambda: reveal_path(diagnostics.path())).pack(
            side="left")

        if self.dnd:
            for w in (self.root, self.drop, inner, self.drop_label):
                w.drop_target_register(DND_FILES)
                w.dnd_bind("<<Drop>>", self._on_drop)
                w.dnd_bind("<<DropEnter>>", lambda e: self._drop_hover(True))
                w.dnd_bind("<<DropLeave>>", lambda e: self._drop_hover(False))

    def _drop_hover(self, on: bool):
        bg = DROP_HOVER if on else DROP_BG
        self.drop.configure(background=bg, highlightbackground=ACCENT if on else "#B7C3D3")
        for w in [self._drop_inner, *self._drop_inner.winfo_children()]:
            if isinstance(w, (tk.Frame, tk.Label)):
                w.configure(background=bg)
        return getattr(tk, "COPY", "copy")

    # ------------------------------------------------------- spreadsheets
    def _on_drop(self, event):
        self._drop_hover(False)
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

    def browse(self):
        initial = self.settings.get("last_dir") or str(Path.home())
        path = filedialog.askopenfilename(
            parent=self.root, title="Choose this week's spreadsheet", initialdir=initial,
            filetypes=[("Spreadsheets", "*.xlsx *.xlsm *.csv"), ("All files", "*.*")])
        if path:
            self.load_file(path)

    def load_file(self, path, sheet_name=None):
        path = Path(path)
        diagnostics.note(f"load spreadsheet ({path.suffix})")
        try:
            sheet = load_sheet(path, sheet_name)
        except SpreadsheetError as e:
            messagebox.showerror("Can't read that spreadsheet", str(e), parent=self.root)
            return
        self.sheet = sheet
        self.settings["last_dir"] = str(path.parent)
        storage.save_settings(self.settings)
        self._refresh_file_status()
        if len(sheet.sheet_names) > 1:
            self.sheet_combo.configure(values=sheet.sheet_names)
            self.sheet_var.set(sheet.sheet_name)
            self.sheet_combo.pack(side="right")
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
        text = f"✓  {self.sheet.path.name}  —  {n} {'order' if self.mapping and self.mapping.items_mode == 'rows' else 'customer'}{'s' if n != 1 else ''}"
        if self.mapping and self.mapping.items_mode == "rows":
            text += f" ({len(self.sheet.rows)} item rows)"
        self.file_status.configure(text=text, style="Ok.TLabel")

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
        scores = {n: self._fit(n, sheet) for n in T.list_templates() if n != current}
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
        values = self._all_values()
        book = DriverBook.load(self.tpl_var.get())
        self.driver_by_key = {customer_key(values[i]): d for i, d in book.suggest(values).items()}
        self._refresh_driver_status()

    def _refresh_driver_status(self):
        if not hasattr(self, "driver_status"):
            return
        values = self._all_values()
        deliveries = sum(1 for v in values if not is_pickup(v))
        if not deliveries:
            self.driver_status.configure(text="Drivers: none yet (optional)")
            return
        n = len(self._driver_assignment())
        if n:
            drivers = len(set(self._driver_assignment().values()))
            self.driver_status.configure(text=f"Drivers: {n} of {deliveries} deliveries assigned "
                                              f"({drivers} driver{'s' if drivers != 1 else ''})")
        else:
            self.driver_status.configure(text=f"Drivers: none assigned yet (optional)")

    def assign_drivers(self):
        values = self._all_values()
        if not values:
            messagebox.showinfo("Load a spreadsheet first",
                                "Load this week's spreadsheet (and match its columns) first.", parent=self.root)
            return
        book = DriverBook.load(self.tpl_var.get())
        diagnostics.note("drivers: opening")
        dlg = DriversDialog(self.root, book, values, self._driver_assignment())
        if dlg.winfo_exists():
            self.root.wait_window(dlg)
        diagnostics.note(f"drivers: closed ({'saved' if dlg.result is not None else 'cancelled'})")
        if dlg.result is None:
            return
        book.remember(values, dlg.result)
        book.save()
        self.driver_by_key = {customer_key(values[i]): d for i, d in dlg.result.items() if d}
        self._refresh_driver_status()

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
        names = T.ensure_default_template()
        self.tpl_combo.configure(values=names)
        want = select or self.settings.get("template")
        self.tpl_var.set(want if want in names else names[0])
        self._template_chosen()

    def _delivery_chosen(self, d):
        self.gen_btn.configure(text=f"Generate Pack Slips for {d:%a}, {d:%b} {d.day}")
        layout = self.tpl_var.get()
        if layout:  # each layout (business) remembers its own delivery day
            self.settings.setdefault("delivery_weekday_by_layout", {})[layout] = d.weekday()
            storage.save_settings(self.settings)

    def _usual_weekday(self, layout: str):
        return self.settings.get("delivery_weekday_by_layout", {}).get(layout, self.settings.get("delivery_weekday"))

    def delivery_values(self) -> dict:
        return {"delivery_date": format_delivery_date(self.date_picker.value)}

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

    def edit_layout(self):
        if getattr(self, "_designer", None) is not None and self._designer.winfo_exists():
            self._designer.lift()
            return
        mapping = load_mapping(self.tpl_var.get()) or Mapping()
        self._designer = Designer(self.root, self.tpl_var.get(), mapping, self.sheet,
                                  extra_values=self.delivery_values,
                                  on_close=lambda name: self._refresh_templates(name))

    def _refresh_generate_state(self):
        if self.sheet is None:
            self.status.configure(text=self.status.cget("text") or "Load a spreadsheet to get started.")

    # ------------------------------------------------------------ generate
    def _output_path(self) -> Path:
        out = default_output_path(self.sheet.path, self.date_picker.value)
        if os.access(out.parent, os.W_OK):
            return out
        fallback = Path.home() / "Documents" / "Pack Slips"
        fallback.mkdir(parents=True, exist_ok=True)
        return default_output_path(fallback / self.sheet.path.name, self.date_picker.value)

    def generate(self):
        if self.sheet is None:
            messagebox.showinfo("No spreadsheet yet", "First load this week's spreadsheet (step 1).", parent=self.root)
            return
        # Re-read the file so last-minute edits in Excel are included.
        try:
            self.sheet = load_sheet(self.sheet.path, self.sheet.sheet_name)
        except SpreadsheetError as e:
            messagebox.showerror("Can't read that spreadsheet", str(e), parent=self.root)
            return
        if self.mapping is None or self.mapping.is_empty():
            self.remap(first_time=True)
            if self.mapping is None or self.mapping.is_empty():
                return
        tpl = self._current_template()
        try:
            check_ready(tpl, self.mapping, self.sheet)
        except GenerateError as e:
            if messagebox.askyesno("Can't make the pack slips yet", f"{e}\n\nOpen “Remap Fields” now?",
                                   parent=self.root, icon="warning"):
                self.remap()
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
                                 driver_order=DriverBook.load(self.tpl_var.get()).names)
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

    def _show_success(self, out: Path, pages: int):
        win = tk.Toplevel(self.root)
        win.title("Pack slips ready")
        win.transient(self.root)
        win.resizable(False, False)
        f = ttk.Frame(win, padding=22)
        f.pack(fill="both", expand=True)
        ttk.Label(f, text="✓  Your pack slips are ready", font=("Helvetica", 17, "bold"),
                  foreground="#1E7B34").pack(anchor="w")
        ttk.Label(f, text=f"{pages} page{'s' if pages != 1 else ''} — one per customer.").pack(anchor="w", pady=(6, 10))
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
            f"A new version of {APP_NAME} is ready (build {info.build}; you have {updater.describe_current()}).\n\n"
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
