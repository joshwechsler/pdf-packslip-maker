"""Main window: load spreadsheet → check layout → Generate (FR-1, FR-7, FR-8, FR-9)."""

from __future__ import annotations

import datetime as dt
import os
import sys
import tkinter as tk
import traceback
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import APP_NAME, __version__, storage
from . import template as T
from .designer import Designer
from .mapping import Mapping, load_mapping, save_mapping
from .mapping_dialog import MappingDialog
from .pdfgen import GenerateError, check_ready, default_output_path, generate_pdf
from .spreadsheet import Sheet, SpreadsheetError, load as load_sheet
from .ui_common import IS_MAC, center_on, open_path, reveal_path

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
except Exception:  # pragma: no cover - drag and drop is a nicety; Browse always works
    TkinterDnD = None
    DND_FILES = None

ACCENT = "#1F3A5F"
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
        self.mapping: Mapping | None = load_mapping()
        self.settings = storage.load_settings()
        T.ensure_default_template()

        root.title(APP_NAME)
        root.minsize(560, 520)
        root.report_callback_exception = self._unexpected_error
        self._build()
        self._refresh_templates()
        self._refresh_mapping_status()
        self._refresh_generate_state()

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
        drop_text = "Drag your spreadsheet (.xlsx) here" if self.dnd else "Choose your spreadsheet (.xlsx)"
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

        row2 = ttk.Frame(outer)
        row2.pack(fill="x", pady=(6, 0))
        self.map_status = ttk.Label(row2, text="", style="Muted.TLabel")
        self.map_status.pack(side="left")
        ttk.Button(row2, text="Remap Fields…", command=self.remap).pack(side="right")

        # Step 3 — generate
        ttk.Label(outer, text="3.  Make the PDF", style="Step.TLabel").pack(anchor="w", pady=(18, 6))
        self.gen_btn = ttk.Button(outer, text="Generate Pack Slips", style="Big.TButton", command=self.generate)
        self.gen_btn.pack(fill="x")
        self.progress = ttk.Progressbar(outer, mode="determinate")
        self.status = ttk.Label(outer, text="", style="Muted.TLabel")
        self.status.pack(anchor="w", pady=(8, 0))

        ttk.Label(outer, text=f"Version {__version__}", style="Muted.TLabel",
                  font=("Helvetica", 10)).pack(side="bottom", anchor="e")

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
            self.load_file(paths[0])
        return getattr(event, "action", "copy")

    def _open_documents(self, *paths):
        if paths:
            self.root.after(10, lambda: self.load_file(paths[0]))

    def browse(self):
        initial = self.settings.get("last_dir") or str(Path.home())
        path = filedialog.askopenfilename(
            parent=self.root, title="Choose this week's spreadsheet", initialdir=initial,
            filetypes=[("Excel spreadsheets", "*.xlsx *.xlsm"), ("All files", "*.*")])
        if path:
            self.load_file(path)

    def load_file(self, path, sheet_name=None):
        path = Path(path)
        try:
            sheet = load_sheet(path, sheet_name)
        except SpreadsheetError as e:
            messagebox.showerror("Can't read that spreadsheet", str(e), parent=self.root)
            return
        self.sheet = sheet
        self.settings["last_dir"] = str(path.parent)
        storage.save_settings(self.settings)
        n = sheet.customer_count
        self.file_status.configure(
            text=f"✓  {path.name}  —  {n} customer{'s' if n != 1 else ''} found", style="Ok.TLabel")
        if len(sheet.sheet_names) > 1:
            self.sheet_combo.configure(values=sheet.sheet_names)
            self.sheet_var.set(sheet.sheet_name)
            self.sheet_combo.pack(side="right")
        else:
            self.sheet_combo.pack_forget()
        self.status.configure(text="")

        if self.mapping is None or self.mapping.is_empty():
            self.remap(first_time=True)
        else:
            missing = self.mapping.missing_columns(sheet.headers, self._current_template().used_field_keys(self.mapping))
            if missing:
                cols = "\n".join(f"  • {label}  (expected “{col}”)" for label, col in missing)
                if messagebox.askyesno(
                        "Some columns have changed",
                        "This spreadsheet doesn't have some of the columns the pack slip uses:\n\n"
                        f"{cols}\n\nWould you like to match the fields up again now?", parent=self.root):
                    self.remap()
        self._refresh_mapping_status()
        self._refresh_generate_state()

    def _change_sheet(self):
        if self.sheet and self.sheet_var.get() != self.sheet.sheet_name:
            self.load_file(self.sheet.path, self.sheet_var.get())

    # ------------------------------------------------------ mapping/layout
    def remap(self, first_time=False):
        if self.sheet is None:
            messagebox.showinfo("Load a spreadsheet first",
                                "Load this week's spreadsheet first, so the app can show you its columns.",
                                parent=self.root)
            return
        dlg = MappingDialog(self.root, self.mapping, self.sheet)
        if dlg.winfo_exists():
            self.root.wait_window(dlg)
        if dlg.result is not None:
            self.mapping = dlg.result
            save_mapping(self.mapping)
        elif first_time and (self.mapping is None or self.mapping.is_empty()):
            self.status.configure(text="Fields aren't matched yet — click “Remap Fields…” when you're ready.")
        self._refresh_mapping_status()
        self._refresh_generate_state()

    def _refresh_mapping_status(self):
        if self.mapping is None or self.mapping.is_empty():
            self.map_status.configure(text="Fields: not matched to spreadsheet columns yet")
            return
        n = sum(1 for v in self.mapping.columns.values() if v)
        self.map_status.configure(text=f"Fields: using your saved matches ({n} columns)")

    def _refresh_templates(self, select: str | None = None):
        names = T.ensure_default_template()
        self.tpl_combo.configure(values=names)
        want = select or self.settings.get("template")
        self.tpl_var.set(want if want in names else names[0])
        self._template_chosen()

    def _template_chosen(self):
        self.settings["template"] = self.tpl_var.get()
        storage.save_settings(self.settings)

    def _current_template(self) -> T.Template:
        return T.load_template(self.tpl_var.get()) or T.default_template(self.tpl_var.get() or "Standard")

    def edit_layout(self):
        if getattr(self, "_designer", None) is not None and self._designer.winfo_exists():
            self._designer.lift()
            return
        mapping = self.mapping or Mapping()
        self._designer = Designer(self.root, self.tpl_var.get(), mapping, self.sheet,
                                  on_close=lambda name: self._refresh_templates(name))

    def _refresh_generate_state(self):
        if self.sheet is None:
            self.status.configure(text=self.status.cget("text") or "Load a spreadsheet to get started.")

    # ------------------------------------------------------------ generate
    def _output_path(self) -> Path:
        out = default_output_path(self.sheet.path)
        if os.access(out.parent, os.W_OK):
            return out
        fallback = Path.home() / "Documents" / "Pack Slips"
        fallback.mkdir(parents=True, exist_ok=True)
        return default_output_path(fallback / self.sheet.path.name)

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
        self.progress.configure(maximum=max(self.sheet.customer_count, 1), value=0)
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
            pages = generate_pdf(out, tpl, self.mapping, self.sheet, progress=progress)
        except GenerateError as e:
            messagebox.showerror("Couldn't make the PDF", str(e), parent=self.root)
            self.status.configure(text="")
            return
        finally:
            self.gen_btn.state(["!disabled"])
            self.progress.pack_forget()
            self.root.configure(cursor="")
        self.status.configure(text=f"✓  Last run: {pages} pack slips saved to {out.name}", style="Ok.TLabel")
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
        path_var = tk.StringVar(value=str(out))
        entry = ttk.Entry(f, textvariable=path_var, width=60, state="readonly")
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
        win.grab_set()
        open_btn.focus_set()

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
    w, h = 640, 600
    x = max((root.winfo_screenwidth() - w) // 2, 0)
    y = max((root.winfo_screenheight() - h) // 3, 0)
    root.geometry(f"{w}x{h}+{x}+{y}")
    if initial_file:
        root.after(200, lambda: app.load_file(initial_file))
    root.lift()
    root.after(300, lambda: root.attributes("-topmost", False))
    root.attributes("-topmost", True)
    root.mainloop()
