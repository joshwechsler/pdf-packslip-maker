"""Settings (the button at the top right): the "?" help text, Google Drive folders and the password."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from . import help_text, password, storage
from .drive import drive_roots
from .ui_common import center_on, make_modal

DRIVE_KINDS = [("pack slips", "Pack slips"), ("bag labels", "Bag labels"), ("meal labels", "Meal labels")]


def unlock(parent, settings: dict) -> bool:
    """Ask for the Settings password (if one is set). True when Settings may open."""
    if not password.is_set(settings):
        return True
    prompt = "Enter the Settings password:"
    while True:
        pw = simpledialog.askstring("Settings password", prompt, show="•", parent=parent)
        if pw is None:
            return False
        if password.check(settings, pw):
            return True
        prompt = "That password isn't right. Try again:"


class SettingsDialog(tk.Toplevel):
    """Modal. Saves everything on Save, then calls on_saved()."""

    def __init__(self, master, settings: dict, on_saved=lambda: None):
        super().__init__(master)
        self.title("Settings")
        self.transient(master)
        self.resizable(False, False)
        self.settings, self.on_saved = settings, on_saved
        self.drive = dict(settings.get("drive_folders") or {})

        f = ttk.Frame(self, padding=16)
        f.pack(fill="both", expand=True)
        ttk.Label(f, text="Settings", font=("Helvetica", 17, "bold")).pack(anchor="w")
        ttk.Label(f, text="Saved on this Mac only.", foreground="#666666").pack(anchor="w", pady=(0, 8))
        tabs = ttk.Notebook(f)
        tabs.pack(fill="both", expand=True)
        tabs.add(self._help_tab(tabs), text="Help text (?)")
        tabs.add(self._drive_tab(tabs), text="Google Drive")
        tabs.add(self._password_tab(tabs), text="Password")

        btns = ttk.Frame(f)
        btns.pack(fill="x", pady=(12, 0))
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(btns, text="Save", command=self._save, default="active").pack(side="right", padx=8)
        self.bind("<Escape>", lambda e: self.destroy())
        center_on(self, master)
        make_modal(self)

    # ---------------------------------------------------------- help text
    def _help_tab(self, parent):
        tab = ttk.Frame(parent, padding=12)
        ttk.Label(tab, text="What each ⓘ on the main window shows. Leave one blank to hide its ⓘ.",
                  foreground="#555555").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))
        self.texts: dict[str, tk.Text] = {}
        for i, (key, label, where) in enumerate(help_text.SPOTS):
            r, c = 1 + (i // 2) * 2, i % 2
            head = ttk.Frame(tab)
            head.grid(row=r, column=c, sticky="we", padx=(0 if c == 0 else 12, 0), pady=(6, 0))
            ttk.Label(head, text=label, font=("Helvetica", 12, "bold")).pack(side="left")
            ttk.Label(head, text=f"  {where}", foreground="#777777").pack(side="left")
            starter = ttk.Label(head, text="Starter text", foreground="#1F5FAD", cursor="hand2")
            starter.pack(side="right")
            box = tk.Text(tab, width=44, height=4, wrap="word", font=("Helvetica", 12),
                          highlightthickness=1, highlightbackground="#B0B4BA", relief="flat")
            box.insert("1.0", help_text.get(self.settings, key))
            box.grid(row=r + 1, column=c, sticky="we", padx=(0 if c == 0 else 12, 0))
            starter.bind("<Button-1>", lambda e, b=box, k=key: (b.delete("1.0", "end"),
                                                                b.insert("1.0", help_text.DEFAULTS[k])))
            self.texts[key] = box
        return tab

    # -------------------------------------------------------- Google Drive
    def _drive_tab(self, parent):
        tab = ttk.Frame(parent, padding=12)
        ttk.Label(tab, text="Where “Save to Google Drive” puts each kind of file. Blank: it asks the first time.",
                  foreground="#555555", wraplength=640).grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 8))
        self.drive_labels: dict[str, ttk.Label] = {}
        for r, (kind, label) in enumerate(DRIVE_KINDS, start=1):
            ttk.Label(tab, text=label, font=("Helvetica", 12, "bold"), width=12).grid(row=r, column=0, sticky="w",
                                                                                     pady=4)
            shown = ttk.Label(tab, text="", width=48)
            shown.grid(row=r, column=1, sticky="w")
            self.drive_labels[kind] = shown
            ttk.Button(tab, text="Change…", command=lambda k=kind: self._pick_drive(k)).grid(row=r, column=2, padx=6)
            ttk.Button(tab, text="Clear", command=lambda k=kind: self._set_drive(k, None)).grid(row=r, column=3)
            self._set_drive(kind, self.drive.get(kind))
        return tab

    def _set_drive(self, kind: str, folder: str | None):
        if folder:
            self.drive[kind] = folder
        else:
            self.drive.pop(kind, None)
        p = Path(folder) if folder else None
        text = "(not chosen)" if p is None else (p.name if p.is_dir() else f"{p.name} (folder not found)")
        self.drive_labels[kind].configure(text=text, foreground="#B00020" if p and not p.is_dir() else "")

    def _pick_drive(self, kind: str):
        current = self.drive.get(kind)
        roots = drive_roots()
        start = current if current and Path(current).is_dir() else str(roots[0] if roots else Path.home())
        chosen = filedialog.askdirectory(parent=self, title=f"Google Drive folder for {kind}", initialdir=start,
                                         mustexist=True)
        if chosen:
            self._set_drive(kind, chosen)

    # ------------------------------------------------------------ password
    def _password_tab(self, parent):
        tab = ttk.Frame(parent, padding=12)
        locked = password.is_set(self.settings)
        ttk.Label(tab, text="Settings is locked with a password." if locked else
                  "No password yet: anyone can open Settings. Set one below.",
                  font=("Helvetica", 12, "bold")).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
        self.pw1, self.pw2 = tk.StringVar(), tk.StringVar()
        for r, (label, var) in enumerate((("New password", self.pw1), ("Type it again", self.pw2)), start=1):
            ttk.Label(tab, text=label).grid(row=r, column=0, sticky="w", pady=3, padx=(0, 8))
            ttk.Entry(tab, textvariable=var, show="•", width=28).grid(row=r, column=1, sticky="w")
        self.remove_pw = tk.BooleanVar(value=False)
        if locked:
            ttk.Checkbutton(tab, text="Remove the password", variable=self.remove_pw).grid(
                row=3, column=0, columnspan=2, sticky="w", pady=(8, 0))
        ttk.Label(tab, text="Leave both boxes empty to keep the current password. The password only guards "
                            "Settings; it's not a security lock for the app or your files.",
                  foreground="#666666", wraplength=560, justify="left").grid(row=4, column=0, columnspan=2,
                                                                             sticky="w", pady=(10, 0))
        return tab

    # ---------------------------------------------------------------- save
    def _save(self):
        new, again = self.pw1.get(), self.pw2.get()
        if (new or again) and new != again:
            messagebox.showerror("Passwords don't match", "The two passwords are different. Type them again.",
                                 parent=self)
            return
        help_text.set_all(self.settings, {k: box.get("1.0", "end-1c") for k, box in self.texts.items()})
        self.settings["drive_folders"] = self.drive
        if self.remove_pw.get():
            password.set_password(self.settings, "")
        elif new:
            password.set_password(self.settings, new)
        storage.save_settings(self.settings)
        self.on_saved()
        self.destroy()
