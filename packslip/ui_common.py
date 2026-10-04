"""Small Tk helpers shared by the main window, mapping screen and designer."""

from __future__ import annotations

import os
import subprocess
import sys
import tkinter as tk
from tkinter import colorchooser, simpledialog

IS_MAC = sys.platform == "darwin"

COLOR_CHOICES = [
    ("Brand primary", "brand:primary"),
    ("Brand accent", "brand:accent"),
    ("Black", "#000000"),
    ("Dark gray", "#222222"),
    ("Gray", "#777777"),
    ("Light gray", "#CCCCCC"),
    ("White", "#FFFFFF"),
]


def open_path(path) -> None:
    """Open a file (or folder) with the system's default app."""
    path = str(path)
    if IS_MAC:
        subprocess.Popen(["open", path])
    elif os.name == "nt":
        os.startfile(path)  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["xdg-open", path])


def reveal_path(path) -> None:
    """Show a file selected in Finder."""
    path = str(path)
    if IS_MAC:
        subprocess.Popen(["open", "-R", path])
    else:
        open_path(os.path.dirname(path))


def center_on(win: tk.Toplevel, parent: tk.Misc) -> None:
    win.update_idletasks()
    pw, ph = parent.winfo_width(), parent.winfo_height()
    px, py = parent.winfo_rootx(), parent.winfo_rooty()
    w, h = win.winfo_reqwidth(), win.winfo_reqheight()
    x = max(px + (pw - w) // 2, 0)
    y = max(py + (ph - h) // 3, 0)
    win.geometry(f"+{x}+{y}")


def ask_name(parent, title: str, prompt: str, initial: str = "") -> str | None:
    value = simpledialog.askstring(title, prompt, initialvalue=initial, parent=parent)
    if value is None:
        return None
    value = " ".join(value.split())
    return value or None


class ColorSwatch(tk.Canvas):
    """A clickable colour chip. Value is '' (none), '#rrggbb' or 'brand:<name>'."""

    def __init__(self, master, get_brand, value: str = "", allow_none: bool = True,
                 command=None, brand_choices: bool = True, **kw):
        super().__init__(master, width=44, height=20, highlightthickness=1,
                         highlightbackground="#999999", cursor="hand2", **kw)
        self.get_brand = get_brand
        self.allow_none = allow_none
        self.brand_choices = brand_choices
        self.command = command
        self.value = value
        self.bind("<Button-1>", self._popup)
        self._draw()

    def resolved(self) -> str:
        if self.value.startswith("brand:"):
            return self.get_brand().get(self.value[6:], "#000000")
        return self.value

    def set(self, value: str) -> None:
        self.value = value or ""
        self._draw()

    def _draw(self):
        self.delete("all")
        color = self.resolved()
        if color:
            self.create_rectangle(0, 0, 46, 22, fill=color, outline="")
        else:
            self.create_rectangle(0, 0, 46, 22, fill="#FFFFFF", outline="")
            self.create_line(2, 18, 42, 2, fill="#CC3333", width=2)

    def _choose(self, value):
        self.set(value)
        if self.command:
            self.command(value)

    def _custom(self):
        initial = self.resolved() or "#000000"
        _, hexval = colorchooser.askcolor(color=initial, parent=self.winfo_toplevel())
        if hexval:
            self._choose(hexval.upper())

    def _popup(self, event):
        menu = tk.Menu(self, tearoff=0)
        if self.allow_none:
            menu.add_command(label="None", command=lambda: self._choose(""))
        for label, val in COLOR_CHOICES:
            if val.startswith("brand:") and not self.brand_choices:
                continue
            menu.add_command(label=label, command=lambda v=val: self._choose(v))
        menu.add_separator()
        menu.add_command(label="Custom…", command=self._custom)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()


def dropdown(parent, var: tk.StringVar, values: list[str], command=None, width: int = 24):
    """A pick-one button that opens a menu of `values`.

    Used instead of ttk.Combobox in dialogs: on macOS a combobox's list can stop taking
    clicks inside a modal window (the screen looks frozen), and scrolling over a combobox
    silently changes its value. This uses a native menu, which has neither problem."""
    from tkinter import ttk
    mb = ttk.Menubutton(parent, textvariable=var, width=width, direction="below")
    menu = tk.Menu(mb, tearoff=0)
    for v in values:
        menu.add_radiobutton(label=v, value=v, variable=var, command=command)
    mb["menu"] = menu
    return mb


def disable_combobox_wheel(root) -> None:
    """Stop the scroll wheel from changing combobox values by accident (app-wide)."""
    for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>", "<Shift-MouseWheel>"):
        root.bind_class("TCombobox", seq, lambda e: "break")


class ScrollFrame(tk.Frame):
    """A vertically scrolling frame; put children in `.inner`."""

    def __init__(self, master, height=360, **kw):
        super().__init__(master, **kw)
        self.canvas = tk.Canvas(self, height=height, highlightthickness=0, bd=0)
        self.vsb = tk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = tk.Frame(self.canvas)
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self._win, width=e.width))
        self.canvas.configure(yscrollcommand=self.vsb.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.vsb.pack(side="right", fill="y")
        # Scroll with the wheel/trackpad only while the pointer is over this frame. (A global
        # binding that is never removed would pile up each time a dialog opens.)
        self.bind("<Enter>", lambda e: self._wheel(True))
        self.bind("<Leave>", lambda e: self._wheel(False))
        self.bind("<Destroy>", lambda e: e.widget is self and self._wheel(False))

    def _wheel(self, on: bool):
        for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            try:
                if on:
                    self.bind_all(seq, self._on_wheel)
                else:
                    self.unbind_all(seq)
            except tk.TclError:
                pass

    def _on_wheel(self, event):
        if not self.winfo_exists():
            return
        if getattr(event, "num", None) == 4:
            delta = -1
        elif getattr(event, "num", None) == 5:
            delta = 1
        else:
            delta = -1 if event.delta > 0 else 1
        self.canvas.yview_scroll(delta, "units")


def ask_choice(parent, title: str, message: str, choices: list[str]) -> int | None:
    """Modal question with one button per choice. Returns the chosen index, or None if closed."""
    from tkinter import ttk
    win = tk.Toplevel(parent)
    win.title(title)
    win.transient(parent)
    win.resizable(False, False)
    result: list[int | None] = [None]
    f = ttk.Frame(win, padding=20)
    f.pack(fill="both", expand=True)
    ttk.Label(f, text=message, wraplength=440, justify="left").pack(anchor="w", pady=(0, 16))
    for i, text in enumerate(choices):
        ttk.Button(f, text=text, command=lambda i=i: (result.__setitem__(0, i), win.destroy())).pack(
            fill="x", pady=3)
    win.bind("<Escape>", lambda e: win.destroy())
    center_on(win, parent)
    win.grab_set()
    parent.wait_window(win)
    return result[0]
