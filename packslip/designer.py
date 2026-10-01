"""Layout designer (FR-4, FR-5, FR-6, FR-10).

A canvas showing the slip at scale with real (or sample) customer data. Items
can be dragged, resized from their corners, nudged with the arrow keys, and
styled from the panel on the right. Templates are saved as named JSON files.
"""

from __future__ import annotations

import hashlib
import shutil
import tempfile
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

from . import storage
from . import template as T
from .layout import ascent, fit_text, inner_box
from .mapping import Mapping
from .pdfgen import render_preview_pdf
from .spreadsheet import Sheet
from .ui_common import ColorSwatch, ask_name, open_path

MARGIN = 24          # px around the page on the canvas
HANDLE = 7           # px, resize handle size
SELECT = "#2F80ED"
GUIDE = "#9DB7D5"
PT_PER_IN = 72.0


class Designer(tk.Toplevel):
    def __init__(self, master, template_name: str, mapping: Mapping, sheet: Sheet | None, on_close=None):
        super().__init__(master)
        self.title("Edit Layout")
        self.geometry("1180x820")
        self.minsize(960, 640)
        self.mapping = mapping
        self.sheet = sheet
        self.on_close = on_close
        self.preview_index = 0
        self.selected: str | None = None
        self.dirty = False
        self._drag = None
        self._syncing = False
        self._fonts: dict = {}
        self._images: dict = {}
        self._tk_images: list = []
        self.scale = 1.0
        self.ox = self.oy = MARGIN

        self.tpl = T.load_template(template_name) or T.default_template(template_name)

        self._build_toolbar()
        body = ttk.Frame(self)
        body.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(body, background="#E6E8EB", highlightthickness=0)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.panel = ttk.Frame(body, padding=(12, 8), width=320)
        self.panel.pack(side="right", fill="y")
        self.panel.pack_propagate(False)
        self._build_panel()

        self.canvas.bind("<Configure>", lambda e: self.redraw())
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<Motion>", self._on_motion)
        for key, dx, dy in (("Left", -1, 0), ("Right", 1, 0), ("Up", 0, -1), ("Down", 0, 1)):
            self.canvas.bind(f"<{key}>", lambda e, dx=dx, dy=dy: self._nudge(dx, dy, 1))
            self.canvas.bind(f"<Shift-{key}>", lambda e, dx=dx, dy=dy: self._nudge(dx, dy, 10))
        self.canvas.bind("<Delete>", lambda e: self._delete_selected())
        self.canvas.bind("<BackSpace>", lambda e: self._delete_selected())
        self.bind("<Command-s>" if self._tk_ws() == "aqua" else "<Control-s>", lambda e: self._save())
        self.protocol("WM_DELETE_WINDOW", self._close)
        self._refresh_template_list()
        self._show_props()

    def _tk_ws(self):
        try:
            return self.tk.call("tk", "windowingsystem")
        except tk.TclError:
            return "x11"

    # ------------------------------------------------------------------ UI
    def _build_toolbar(self):
        bar = ttk.Frame(self, padding=(10, 8))
        bar.pack(fill="x")
        ttk.Label(bar, text="Layout:").pack(side="left")
        self.tpl_var = tk.StringVar(value=self.tpl.name)
        self.tpl_combo = ttk.Combobox(bar, textvariable=self.tpl_var, state="readonly", width=22)
        self.tpl_combo.pack(side="left", padx=(4, 6))
        self.tpl_combo.bind("<<ComboboxSelected>>", lambda e: self._switch_template(self.tpl_var.get()))
        for text, cmd in (("New", self._new_template), ("Duplicate", self._duplicate_template),
                          ("Rename", self._rename_template), ("Delete", self._delete_template)):
            ttk.Button(bar, text=text, command=cmd).pack(side="left", padx=2)

        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=10)
        ttk.Label(bar, text="Page:").pack(side="left")
        self.page_var = tk.StringVar(value=self.tpl.page)
        page = ttk.Combobox(bar, textvariable=self.page_var, values=list(T.PAGE_SIZES), state="readonly", width=22)
        page.pack(side="left", padx=4)
        page.bind("<<ComboboxSelected>>", lambda e: self._set_page(self.page_var.get()))

        ttk.Button(bar, text="Save", command=self._save).pack(side="right")
        ttk.Button(bar, text="Preview PDF", command=self._preview_pdf).pack(side="right", padx=6)

        bar2 = ttk.Frame(self, padding=(10, 0, 10, 8))
        bar2.pack(fill="x")
        ttk.Label(bar2, text="Add:").pack(side="left")
        self.field_menu_btn = ttk.Menubutton(bar2, text="Field ▾")
        self.field_menu = tk.Menu(self.field_menu_btn, tearoff=0)
        self.field_menu_btn["menu"] = self.field_menu
        self.field_menu_btn.pack(side="left", padx=4)
        self._rebuild_field_menu()
        ttk.Button(bar2, text="Text", command=self._add_text).pack(side="left", padx=2)
        ttk.Button(bar2, text="Logo…", command=self._add_logo).pack(side="left", padx=2)
        ttk.Button(bar2, text="Box / Line", command=self._add_box).pack(side="left", padx=2)

        nav = ttk.Frame(bar2)
        nav.pack(side="right")
        ttk.Button(nav, text="◀", width=3, command=lambda: self._step_preview(-1)).pack(side="left")
        self.preview_label = ttk.Label(nav, text="", width=40, anchor="center")
        self.preview_label.pack(side="left", padx=4)
        ttk.Button(nav, text="▶", width=3, command=lambda: self._step_preview(1)).pack(side="left")

    def _rebuild_field_menu(self):
        self.field_menu.delete(0, "end")
        for f in self.mapping.fields:
            mapped = self.mapping.columns.get(f["key"])
            label = f["label"] if mapped else f"{f['label']}  (not matched to a column)"
            self.field_menu.add_command(label=label, command=lambda k=f["key"]: self._add_field(k))

    def _build_panel(self):
        p = self.panel
        ttk.Label(p, text="Brand", font=("Helvetica", 13, "bold")).pack(anchor="w")
        brand = ttk.Frame(p)
        brand.pack(fill="x", pady=(4, 2))
        self.brand_swatches = {}
        for i, (key, label) in enumerate((("primary", "Primary color"), ("accent", "Accent color"))):
            ttk.Label(brand, text=label).grid(row=i, column=0, sticky="w", pady=2)
            sw = ColorSwatch(brand, lambda: self.tpl.brand, value=self.tpl.brand[key], allow_none=False,
                             brand_choices=False, command=lambda v, k=key: self._set_brand(k, v))
            sw.grid(row=i, column=1, sticky="w", padx=8)
            self.brand_swatches[key] = sw
        ttk.Label(p, text="Items set to a brand color update when you change it here.",
                  foreground="#666666", wraplength=290).pack(anchor="w", pady=(0, 6))
        ttk.Separator(p).pack(fill="x", pady=8)
        self.props = ttk.Frame(p)
        self.props.pack(fill="both", expand=True)

        help_text = ("Drag items to move them. Drag a corner to resize. Arrow keys nudge "
                     "(hold Shift for bigger steps). Delete removes the selected item.")
        ttk.Label(p, text=help_text, foreground="#666666", wraplength=290).pack(side="bottom", anchor="w", pady=(8, 0))

    # ------------------------------------------------------- preview values
    def _values(self) -> dict:
        if self.sheet and self.sheet.rows:
            self.preview_index %= len(self.sheet.rows)
            return self.mapping.values_for_row(self.sheet.rows[self.preview_index])
        return self.mapping.sample_values()

    def _step_preview(self, d):
        if self.sheet and self.sheet.rows:
            self.preview_index = (self.preview_index + d) % len(self.sheet.rows)
        self.redraw()

    def _update_preview_label(self):
        if self.sheet and self.sheet.rows:
            name = self._values().get("customer_name") or "customer"
            self.preview_label.configure(
                text=f"Previewing: {name[:22]}  ({self.preview_index + 1} of {len(self.sheet.rows)})")
        else:
            self.preview_label.configure(text="Previewing sample data")

    # -------------------------------------------------------------- drawing
    def _font(self, family, px, bold, italic):
        key = (family, px, bold, italic)
        if key not in self._fonts:
            self._fonts[key] = tkfont.Font(family=family, size=-max(px, 1),
                                           weight="bold" if bold else "normal",
                                           slant="italic" if italic else "roman")
        return self._fonts[key]

    def _logo_image(self, name, w, h):
        if not name:
            return None
        key = (name, w, h)
        if key in self._images:
            return self._images[key]
        img = None
        try:
            with Image.open(storage.assets_dir() / name) as src:
                src.load()
                im = src.convert("RGBA")
            im.thumbnail((max(w, 1), max(h, 1)), Image.LANCZOS)
            img = ImageTk.PhotoImage(im, master=self.canvas)
        except Exception:
            img = None
        if len(self._images) > 40:
            self._images.clear()
        self._images[key] = img
        return img

    def _c(self, x, y):
        return self.ox + x * self.scale, self.oy + y * self.scale

    def _p(self, cx, cy):
        return (cx - self.ox) / self.scale, (cy - self.oy) / self.scale

    def redraw(self):
        cv = self.canvas
        cv.delete("all")
        pw, ph = self.tpl.page_size
        cw, ch = max(cv.winfo_width(), 100), max(cv.winfo_height(), 100)
        self.scale = min((cw - 2 * MARGIN) / pw, (ch - 2 * MARGIN) / ph)
        self.scale = max(self.scale, 0.2)
        self.ox = (cw - pw * self.scale) / 2
        self.oy = MARGIN
        x0, y0 = self._c(0, 0)
        x1, y1 = self._c(pw, ph)
        cv.create_rectangle(x0 + 3, y0 + 3, x1 + 3, y1 + 3, fill="#C5C9CF", outline="")
        cv.create_rectangle(x0, y0, x1, y1, fill="#FFFFFF", outline="#B0B4BA")

        values = self._values()
        brand = self.tpl.brand
        s = self.scale
        for el in self.tpl.elements:
            ex0, ey0 = self._c(el["x"], el["y"])
            ex1, ey1 = self._c(el["x"] + el["w"], el["y"] + el["h"])
            t = el["type"]
            fill = T.resolve_color(el.get("fill", ""), brand)
            border = T.resolve_color(el.get("border", ""), brand)
            if t in ("box", "field", "text") and (fill or border):
                cv.create_rectangle(ex0, ey0, ex1, ey1, fill=fill or "", outline=border or "",
                                    width=max(1, float(el.get("border_width", 1) or 1) * s) if border else 0)
            if t == "logo":
                img = self._logo_image(el.get("image", ""), int(ex1 - ex0), int(ey1 - ey0))
                if img:
                    self._tk_images.append(img)
                    cv.create_image((ex0 + ex1) / 2, (ey0 + ey1) / 2, image=img)
                else:
                    cv.create_rectangle(ex0, ey0, ex1, ey1, outline=GUIDE, dash=(4, 3))
                    cv.create_text((ex0 + ex1) / 2, (ey0 + ey1) / 2, text="Your logo\n(select, then “Choose Image…”)",
                                   fill="#7C8A9C", justify="center", font=self._font("Helvetica", 11, False, False))
                continue
            if t not in ("field", "text"):
                continue
            # Designer-only outline so empty or white-on-white items are still findable.
            cv.create_rectangle(ex0, ey0, ex1, ey1, outline="#D6DEE8", dash=(2, 3))
            text = T.element_text(el, values, self.mapping)
            if not text.strip():
                if t == "field":
                    cv.create_text(ex0 + 3, ey0 + 2, anchor="nw", fill="#9AA5B1",
                                   text=f"[{self.mapping.field_label(el.get('field', ''))} – empty]",
                                   font=self._font("Helvetica", max(int(9 * s), 8), False, True))
                continue
            ix, iy, iw, ih = inner_box(el)
            lay = fit_text(text, el["font"], el["bold"], el["italic"], el["size"], iw, ih, el.get("shrink", True))
            f = self._font(el["font"], int(round(lay.size * s)), el["bold"], el["italic"])
            asc_pdf = ascent(lay.font, lay.size)
            tk_asc = f.metrics("ascent")
            color = T.resolve_color(el.get("color", "#000000"), brand) or "#000000"
            for i, line in enumerate(lay.lines):
                base_y = self.oy + (iy + asc_pdf + i * lay.leading) * s
                y = base_y - tk_asc
                if el["align"] == "right":
                    cv.create_text(self.ox + (ix + iw) * s, y, text=line, anchor="ne", font=f, fill=color)
                elif el["align"] == "center":
                    cv.create_text(self.ox + (ix + iw / 2) * s, y, text=line, anchor="n", font=f, fill=color)
                else:
                    cv.create_text(self.ox + ix * s, y, text=line, anchor="nw", font=f, fill=color)

        sel = self.tpl.find(self.selected) if self.selected else None
        if sel:
            sx0, sy0 = self._c(sel["x"], sel["y"])
            sx1, sy1 = self._c(sel["x"] + sel["w"], sel["y"] + sel["h"])
            cv.create_rectangle(sx0 - 1, sy0 - 1, sx1 + 1, sy1 + 1, outline=SELECT, width=2)
            for hx, hy in self._handles(sel).values():
                cv.create_rectangle(hx - HANDLE / 2, hy - HANDLE / 2, hx + HANDLE / 2, hy + HANDLE / 2,
                                    fill="#FFFFFF", outline=SELECT, width=1.5)
        self._tk_images = self._tk_images[-60:]
        self._update_preview_label()

    def _handles(self, el):
        x0, y0 = self._c(el["x"], el["y"])
        x1, y1 = self._c(el["x"] + el["w"], el["y"] + el["h"])
        return {"nw": (x0, y0), "ne": (x1, y0), "sw": (x0, y1), "se": (x1, y1)}

    # ---------------------------------------------------------- mouse/keys
    def _hit(self, cx, cy):
        px, py = self._p(cx, cy)
        tol = 3 / self.scale
        for el in reversed(self.tpl.elements):
            if el["x"] - tol <= px <= el["x"] + el["w"] + tol and el["y"] - tol <= py <= el["y"] + el["h"] + tol:
                return el
        return None

    def _handle_at(self, cx, cy):
        sel = self.tpl.find(self.selected) if self.selected else None
        if not sel:
            return None
        for name, (hx, hy) in self._handles(sel).items():
            if abs(cx - hx) <= HANDLE and abs(cy - hy) <= HANDLE:
                return name
        return None

    def _on_motion(self, e):
        h = self._handle_at(e.x, e.y)
        cursor = ""
        if h:
            cursor = "sizing"
        elif self._hit(e.x, e.y):
            cursor = "fleur"
        try:
            self.canvas.configure(cursor=cursor)
        except tk.TclError:
            pass

    def _on_press(self, e):
        self.canvas.focus_set()
        handle = self._handle_at(e.x, e.y)
        if handle:
            el = self.tpl.find(self.selected)
            self._drag = ("resize", handle, dict(el), e.x, e.y)
            return
        el = self._hit(e.x, e.y)
        if el is None:
            self._select(None)
            self._drag = None
            return
        if el["id"] != self.selected:
            self._select(el["id"])
        self._drag = ("move", None, dict(el), e.x, e.y)

    def _on_drag(self, e):
        if not self._drag:
            return
        mode, handle, orig, sx, sy = self._drag
        el = self.tpl.find(self.selected)
        if not el:
            return
        dx = round((e.x - sx) / self.scale)
        dy = round((e.y - sy) / self.scale)
        pw, ph = self.tpl.page_size
        if mode == "move":
            el["x"] = float(min(max(orig["x"] + dx, -orig["w"] + 8), pw - 8))
            el["y"] = float(min(max(orig["y"] + dy, -orig["h"] + 8), ph - 8))
        else:
            x0, y0 = orig["x"], orig["y"]
            x1, y1 = orig["x"] + orig["w"], orig["y"] + orig["h"]
            if "w" in handle:
                x0 = min(x0 + dx, x1 - 4)
            if "e" in handle:
                x1 = max(x1 + dx, x0 + 4)
            if "n" in handle:
                y0 = min(y0 + dy, y1 - 1)
            if "s" in handle:
                y1 = max(y1 + dy, y0 + 1)
            el["x"], el["y"], el["w"], el["h"] = float(x0), float(y0), float(x1 - x0), float(y1 - y0)
        self._mark_dirty()
        self._sync_geometry_vars()
        self.redraw()

    def _on_release(self, e):
        self._drag = None

    def _nudge(self, dx, dy, step):
        el = self.tpl.find(self.selected) if self.selected else None
        if not el:
            return "break"
        el["x"] += dx * step
        el["y"] += dy * step
        self._mark_dirty()
        self._sync_geometry_vars()
        self.redraw()
        return "break"

    # ------------------------------------------------------------- editing
    def _mark_dirty(self):
        if not self.dirty:
            self.dirty = True
            self.title("Edit Layout — unsaved changes")

    def _select(self, element_id):
        self.selected = element_id
        self._show_props()
        self.redraw()

    def _place(self, w, h):
        """A free-ish spot near the middle of the visible page for a new item."""
        pw, ph = self.tpl.page_size
        n = sum(1 for _ in self.tpl.elements) % 8
        return min(pw / 2 - w / 2 + n * 8, pw - w), min(ph / 3 + n * 8, ph - h)

    def _append(self, el):
        self.tpl.elements.append(el)
        self._mark_dirty()
        self._select(el["id"])

    def _add_field(self, key):
        w, h = 220, 18
        x, y = self._place(w, h)
        self._append(T.make_element("field", x, y, w, h, field=key))

    def _add_text(self):
        w, h = 200, 18
        x, y = self._place(w, h)
        self._append(T.make_element("text", x, y, w, h, text="New text"))
        self.after(50, self._focus_text_box)

    def _add_box(self):
        w, h = 200, 4
        x, y = self._place(w, h)
        self._append(T.make_element("box", x, y, w, h, fill="brand:accent"))

    def _add_logo(self):
        name = self._choose_image()
        if not name:
            return
        w, h = 160, 60
        x, y = 36, 36
        self._append(T.make_element("logo", x, y, w, h, image=name))

    def _choose_image(self) -> str | None:
        path = filedialog.askopenfilename(
            parent=self, title="Choose your logo",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.gif *.bmp *.tif *.tiff"), ("All files", "*.*")])
        if not path:
            return None
        src = Path(path)
        try:
            with Image.open(src) as im:
                im.verify()
        except Exception:
            messagebox.showerror("Can't use that image",
                                 f"“{src.name}” isn't an image this app can read.\n\n"
                                 "Please choose a PNG or JPEG file.", parent=self)
            return None
        digest = hashlib.sha1(src.read_bytes()).hexdigest()[:8]
        dest_name = f"{src.stem}-{digest}{src.suffix.lower()}"
        dest = storage.assets_dir() / dest_name
        if not dest.exists():
            shutil.copy2(src, dest)
        return dest_name

    def _delete_selected(self):
        if not self.selected:
            return "break"
        self.tpl.elements = [e for e in self.tpl.elements if e["id"] != self.selected]
        self._mark_dirty()
        self._select(None)
        return "break"

    def _duplicate_selected(self):
        el = self.tpl.find(self.selected) if self.selected else None
        if not el:
            return
        dup = T.normalize_element(dict(el, id=T.new_id(), x=el["x"] + 12, y=el["y"] + 12))
        self._append(dup)

    def _reorder(self, to_front: bool):
        el = self.tpl.find(self.selected) if self.selected else None
        if not el:
            return
        self.tpl.elements.remove(el)
        if to_front:
            self.tpl.elements.append(el)
        else:
            self.tpl.elements.insert(0, el)
        self._mark_dirty()
        self.redraw()

    def _set_brand(self, key, value):
        self.tpl.brand[key] = value
        self._mark_dirty()
        self._show_props()
        self.redraw()

    def _set_page(self, page):
        if page == self.tpl.page:
            return
        self.tpl.page = page
        pw, ph = self.tpl.page_size
        off = [e for e in self.tpl.elements if e["x"] + 8 > pw or e["y"] + 8 > ph]
        self._mark_dirty()
        self.redraw()
        if off:
            messagebox.showinfo("Some items are off the page",
                                f"{len(off)} item(s) are now outside the smaller page. "
                                "Drag them back on, or delete them.", parent=self)

    # ---------------------------------------------------------- properties
    def _show_props(self):
        for w in self.props.winfo_children():
            w.destroy()
        el = self.tpl.find(self.selected) if self.selected else None
        p = self.props
        if not el:
            ttk.Label(p, text="Nothing selected", font=("Helvetica", 13, "bold")).pack(anchor="w")
            ttk.Label(p, text="Click an item on the slip to change it, or use the Add buttons above.",
                      wraplength=290, foreground="#666666").pack(anchor="w", pady=4)
            return
        titles = {"field": "Spreadsheet field", "text": "Text", "logo": "Logo", "box": "Box / Line"}
        ttk.Label(p, text=titles[el["type"]], font=("Helvetica", 13, "bold")).pack(anchor="w")
        grid = ttk.Frame(p)
        grid.pack(fill="x", pady=6)
        grid.columnconfigure(1, weight=1)
        row = [0]

        def add_row(label, widget):
            ttk.Label(grid, text=label).grid(row=row[0], column=0, sticky="w", pady=3, padx=(0, 8))
            widget.grid(row=row[0], column=1, sticky="w", pady=3)
            row[0] += 1

        def bind_var(var, key, conv=lambda v: v):
            def changed(*_):
                if self._syncing:
                    return
                try:
                    el[key] = conv(var.get())
                except (tk.TclError, ValueError):
                    return
                self._mark_dirty()
                self.redraw()
            var.trace_add("write", changed)

        def swatch(key, allow_none=True):
            return ColorSwatch(grid, lambda: self.tpl.brand, value=el.get(key, ""), allow_none=allow_none,
                               command=lambda v: (el.__setitem__(key, v), self._mark_dirty(), self.redraw()))

        t = el["type"]
        if t == "field":
            labels = [f["label"] for f in self.mapping.fields]
            fvar = tk.StringVar(value=self.mapping.field_label(el.get("field", "")))
            combo = ttk.Combobox(grid, textvariable=fvar, values=labels, state="readonly", width=20)
            add_row("Shows", combo)

            def field_changed(*_):
                for f in self.mapping.fields:
                    if f["label"] == fvar.get():
                        el["field"] = f["key"]
                self._mark_dirty()
                self.redraw()
            combo.bind("<<ComboboxSelected>>", field_changed)
            lvar = tk.StringVar(value=el.get("label", ""))
            add_row("Label before it", ttk.Entry(grid, textvariable=lvar, width=22))
            bind_var(lvar, "label")
        elif t == "text":
            txt = tk.Text(grid, width=26, height=3, wrap="word", font=("Helvetica", 12),
                          highlightthickness=1, highlightbackground="#B0B4BA")
            txt.insert("1.0", el.get("text", ""))
            add_row("Text", txt)
            self._text_widget = txt

            def text_changed(_e=None):
                el["text"] = txt.get("1.0", "end-1c")
                self._mark_dirty()
                self.redraw()
            txt.bind("<KeyRelease>", text_changed)
            hint = ("Tip: type a field name in curly brackets, e.g. {Customer Name}, "
                    "to drop in that customer's value.")
            ttk.Label(grid, text=hint, foreground="#666666", wraplength=280).grid(
                row=row[0], column=0, columnspan=2, sticky="w")
            row[0] += 1

        if t in ("field", "text"):
            font_var = tk.StringVar(value=el["font"])
            add_row("Font", ttk.Combobox(grid, textvariable=font_var, values=T.FONTS, state="readonly", width=12))
            bind_var(font_var, "font")
            size_var = tk.DoubleVar(value=el["size"])
            add_row("Size", ttk.Spinbox(grid, from_=5, to=96, increment=1, textvariable=size_var, width=6))
            bind_var(size_var, "size", lambda v: max(4.0, min(float(v), 200.0)))
            style = ttk.Frame(grid)
            bvar, ivar = tk.BooleanVar(value=el["bold"]), tk.BooleanVar(value=el["italic"])
            ttk.Checkbutton(style, text="Bold", variable=bvar).pack(side="left")
            ttk.Checkbutton(style, text="Italic", variable=ivar).pack(side="left", padx=8)
            bind_var(bvar, "bold")
            bind_var(ivar, "italic")
            add_row("Style", style)
            align = ttk.Frame(grid)
            avar = tk.StringVar(value=el["align"])
            for a in ("left", "center", "right"):
                ttk.Radiobutton(align, text=a.title(), value=a, variable=avar).pack(side="left")
            bind_var(avar, "align")
            add_row("Align", align)
            add_row("Text color", swatch("color", allow_none=False))
            add_row("Background", swatch("fill"))
            add_row("Border", swatch("border"))
            shrink = tk.BooleanVar(value=el.get("shrink", True))
            cb = ttk.Checkbutton(grid, text="Shrink text to fit the box", variable=shrink)
            cb.grid(row=row[0], column=0, columnspan=2, sticky="w")
            row[0] += 1
            bind_var(shrink, "shrink")
        if t == "field":
            split = tk.BooleanVar(value=el.get("split_lines", False))
            bullets = tk.BooleanVar(value=el.get("bullets", False))
            ttk.Checkbutton(grid, text="One item per line (splits at , and ;)",
                            variable=split).grid(row=row[0], column=0, columnspan=2, sticky="w")
            row[0] += 1
            ttk.Checkbutton(grid, text="Add bullet points", variable=bullets).grid(
                row=row[0], column=0, columnspan=2, sticky="w")
            row[0] += 1
            bind_var(split, "split_lines")
            bind_var(bullets, "bullets")
        if t == "logo":
            ttk.Button(grid, text="Choose Image…", command=lambda: self._replace_logo(el)).grid(
                row=row[0], column=0, columnspan=2, sticky="w")
            row[0] += 1
            ttk.Label(grid, text="The logo keeps its shape and fits inside the box.",
                      foreground="#666666", wraplength=280).grid(row=row[0], column=0, columnspan=2, sticky="w")
            row[0] += 1
        if t == "box":
            add_row("Fill", swatch("fill"))
            add_row("Border", swatch("border"))
            rvar = tk.DoubleVar(value=el.get("radius", 0))
            add_row("Rounded corners", ttk.Spinbox(grid, from_=0, to=40, increment=1, textvariable=rvar, width=6))
            bind_var(rvar, "radius", lambda v: max(0.0, float(v)))

        # Position & size in inches (more natural than points for most people).
        ttk.Separator(p).pack(fill="x", pady=6)
        geo = ttk.Frame(p)
        geo.pack(fill="x")
        ttk.Label(geo, text="Position & size (inches)").grid(row=0, column=0, columnspan=4, sticky="w")
        self._geo_vars = {}
        for i, (key, label) in enumerate((("x", "Left"), ("y", "Top"), ("w", "Width"), ("h", "Height"))):
            var = tk.StringVar(value=f"{el[key] / PT_PER_IN:.2f}")
            ttk.Label(geo, text=label).grid(row=1 + i // 2, column=(i % 2) * 2, sticky="w", pady=2)
            ttk.Spinbox(geo, from_=-5, to=30, increment=0.05, textvariable=var, width=6, format="%.2f").grid(
                row=1 + i // 2, column=(i % 2) * 2 + 1, sticky="w", padx=(4, 12), pady=2)
            minimum = 1.0 if key in ("w", "h") else -1e9
            bind_var(var, key, lambda v, m=minimum: max(m, round(float(v) * PT_PER_IN, 1)))
            self._geo_vars[key] = var

        actions = ttk.Frame(p)
        actions.pack(fill="x", pady=(10, 0))
        ttk.Button(actions, text="Duplicate", command=self._duplicate_selected).grid(row=0, column=0, sticky="ew", padx=2, pady=2)
        ttk.Button(actions, text="Delete", command=self._delete_selected).grid(row=0, column=1, sticky="ew", padx=2, pady=2)
        ttk.Button(actions, text="Bring to Front", command=lambda: self._reorder(True)).grid(row=1, column=0, sticky="ew", padx=2, pady=2)
        ttk.Button(actions, text="Send to Back", command=lambda: self._reorder(False)).grid(row=1, column=1, sticky="ew", padx=2, pady=2)

    def _sync_geometry_vars(self):
        el = self.tpl.find(self.selected) if self.selected else None
        if not el or not getattr(self, "_geo_vars", None):
            return
        self._syncing = True
        try:
            for key, var in self._geo_vars.items():
                var.set(f"{el[key] / PT_PER_IN:.2f}")
        finally:
            self._syncing = False

    def _focus_text_box(self):
        w = getattr(self, "_text_widget", None)
        if w is not None and w.winfo_exists():
            w.focus_set()
            w.tag_add("sel", "1.0", "end-1c")

    def _replace_logo(self, el):
        name = self._choose_image()
        if name:
            el["image"] = name
            self._mark_dirty()
            self.redraw()

    # ------------------------------------------------------- templates I/O
    def _refresh_template_list(self):
        names = T.list_templates()
        if self.tpl.name not in names:
            names.append(self.tpl.name)
        self.tpl_combo.configure(values=sorted(names, key=str.lower))
        self.tpl_var.set(self.tpl.name)
        self.page_var.set(self.tpl.page)
        for key, sw in self.brand_swatches.items():
            sw.set(self.tpl.brand[key])

    def _confirm_discard(self) -> bool:
        """True if it's OK to leave the current template (saved, discarded, or unchanged)."""
        if not self.dirty:
            return True
        ans = messagebox.askyesnocancel("Save changes?",
                                        f"Save your changes to the “{self.tpl.name}” layout first?", parent=self)
        if ans is None:
            return False
        if ans:
            self._save()
        return True

    def _load(self, tpl: T.Template):
        self.tpl = tpl
        self.selected = None
        self.dirty = False
        self.title("Edit Layout")
        self._refresh_template_list()
        self._show_props()
        self.redraw()

    def _switch_template(self, name):
        if name == self.tpl.name:
            return
        if not self._confirm_discard():
            self.tpl_var.set(self.tpl.name)
            return
        self._load(T.load_template(name) or T.default_template(name))

    def _unique_name_ok(self, name, current=None) -> bool:
        existing = {n.lower() for n in T.list_templates()}
        if current:
            existing.discard(current.lower())
        if name.lower() in existing:
            messagebox.showwarning("Name taken", f"There's already a layout called “{name}”.", parent=self)
            return False
        return True

    def _new_template(self):
        if not self._confirm_discard():
            return
        name = ask_name(self, "New Layout", "Name for the new layout:")
        if not name or not self._unique_name_ok(name):
            return
        tpl = T.default_template(name)
        tpl.brand = dict(self.tpl.brand)
        for el in tpl.elements:  # carry over the current logo so it isn't lost
            if el["type"] == "logo":
                logos = [e for e in self.tpl.elements if e["type"] == "logo" and e.get("image")]
                if logos:
                    el["image"] = logos[0]["image"]
        T.save_template(tpl)
        self._load(tpl)

    def _duplicate_template(self):
        name = ask_name(self, "Duplicate Layout", "Name for the copy:", f"{self.tpl.name} copy")
        if not name or not self._unique_name_ok(name):
            return
        tpl = self.tpl.copy(name)
        T.save_template(tpl)
        self.dirty = False
        self._load(tpl)

    def _rename_template(self):
        old = self.tpl.name
        name = ask_name(self, "Rename Layout", "New name:", old)
        if not name or name == old or not self._unique_name_ok(name, current=old):
            return
        self.tpl.name = name
        T.save_template(self.tpl)
        T.delete_template(old)
        settings = storage.load_settings()
        if settings.get("template") == old:
            settings["template"] = name
            storage.save_settings(settings)
        self.dirty = False
        self.title("Edit Layout")
        self._refresh_template_list()

    def _delete_template(self):
        names = T.list_templates()
        if len(names) <= 1 and self.tpl.name in names:
            messagebox.showinfo("Can't delete", "You need at least one layout. Create another one first.", parent=self)
            return
        if not messagebox.askyesno("Delete layout?", f"Delete the “{self.tpl.name}” layout? This can't be undone.",
                                   parent=self):
            return
        T.delete_template(self.tpl.name)
        remaining = T.list_templates() or T.ensure_default_template()
        self.dirty = False
        self._load(T.load_template(remaining[0]) or T.default_template())

    def _save(self):
        T.save_template(self.tpl)
        self.dirty = False
        self.title("Edit Layout — saved")
        self.after(1500, lambda: self.winfo_exists() and not self.dirty and self.title("Edit Layout"))
        self._refresh_template_list()

    def _preview_pdf(self):
        out = Path(tempfile.gettempdir()) / f"Pack Slip Preview - {T._safe_filename(self.tpl.name)}.pdf"
        try:
            render_preview_pdf(out, self.tpl, self.mapping, self._values())
        except OSError as e:
            messagebox.showerror("Preview failed", f"The preview couldn't be created: {e}", parent=self)
            return
        open_path(out)

    def _close(self):
        if not self._confirm_discard():
            return
        name = self.tpl.name if T.template_path(self.tpl.name).exists() else None
        self.destroy()
        if self.on_close:
            self.on_close(name)
