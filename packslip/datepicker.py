"""Delivery-date picker: a dropdown of upcoming days plus a small month calendar."""

from __future__ import annotations

import calendar
import datetime as dt
import tkinter as tk
from tkinter import ttk

from .pdfgen import format_delivery_date

UPCOMING_DAYS = 28


def default_delivery_date(weekday: int | None, today: dt.date | None = None) -> dt.date:
    """Next occurrence (from tomorrow) of the usual delivery weekday, else tomorrow."""
    tomorrow = (today or dt.date.today()) + dt.timedelta(days=1)
    if weekday is None:
        return tomorrow
    return tomorrow + dt.timedelta(days=(weekday - tomorrow.weekday()) % 7)


class DatePicker(ttk.Frame):
    def __init__(self, master, initial: dt.date, command=None):
        super().__init__(master)
        self.command = command
        self.value = initial
        self.var = tk.StringVar()
        self.combo = ttk.Combobox(self, textvariable=self.var, state="readonly", width=22)
        self.combo.pack(side="left")
        self.combo.bind("<<ComboboxSelected>>", self._picked)
        ttk.Button(self, text="Calendar…", command=self._open_calendar).pack(side="left", padx=6)
        self.set(initial)

    def _upcoming_days(self):
        start = dt.date.today()
        days = [start + dt.timedelta(days=i) for i in range(UPCOMING_DAYS)]
        if self.value not in days:
            days.append(self.value)
            days.sort()
        return days

    def set(self, d: dt.date):
        self.value = d
        self._days = self._upcoming_days()
        labels = []
        for day in self._days:
            label = format_delivery_date(day)
            if day == dt.date.today():
                label += "  (today)"
            elif day == dt.date.today() + dt.timedelta(days=1):
                label += "  (tomorrow)"
            labels.append(label)
        self.combo.configure(values=labels)
        self.var.set(labels[self._days.index(d)])
        if self.command:
            self.command(d)

    def _picked(self, _e=None):
        idx = self.combo.current()
        if idx >= 0:
            self.set(self._days[idx])

    def _open_calendar(self):
        CalendarPopup(self, self.value, self.set)


class CalendarPopup(tk.Toplevel):
    def __init__(self, master, current: dt.date, on_pick):
        super().__init__(master)
        self.title("Pick delivery date")
        self.transient(master.winfo_toplevel())
        self.resizable(False, False)
        self.on_pick = on_pick
        self.current = current
        self.year, self.month = current.year, current.month
        head = ttk.Frame(self, padding=(10, 10, 10, 4))
        head.pack(fill="x")
        ttk.Button(head, text="◀", width=3, command=lambda: self._shift(-1)).pack(side="left")
        self.title_label = ttk.Label(head, font=("Helvetica", 13, "bold"), anchor="center")
        self.title_label.pack(side="left", expand=True, fill="x")
        ttk.Button(head, text="▶", width=3, command=lambda: self._shift(1)).pack(side="right")
        self.grid_frame = ttk.Frame(self, padding=(10, 0, 10, 10))
        self.grid_frame.pack()
        self._draw()
        self.bind("<Escape>", lambda e: self.destroy())
        self.update_idletasks()
        x = master.winfo_rootx()
        y = master.winfo_rooty() + master.winfo_height() + 4
        self.geometry(f"+{x}+{y}")
        self.grab_set()

    def _shift(self, delta):
        m = self.month - 1 + delta
        self.year, self.month = self.year + m // 12, m % 12 + 1
        self._draw()

    def _draw(self):
        for w in self.grid_frame.winfo_children():
            w.destroy()
        self.title_label.configure(text=f"{calendar.month_name[self.month]} {self.year}")
        for col, name in enumerate(["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]):
            ttk.Label(self.grid_frame, text=name, foreground="#666666", anchor="center", width=4).grid(
                row=0, column=col, pady=(0, 2))
        today = dt.date.today()
        for r, week in enumerate(calendar.Calendar().monthdatescalendar(self.year, self.month), start=1):
            for c, day in enumerate(week):
                if day.month != self.month:
                    continue
                text = str(day.day)
                if day == self.current:
                    text = f"[{text}]"
                elif day == today:
                    text = f"•{text}"
                ttk.Button(self.grid_frame, text=text, width=4,
                           command=lambda d=day: self._pick(d)).grid(row=r, column=c, padx=1, pady=1)

    def _pick(self, d):
        self.destroy()
        self.on_pick(d)
