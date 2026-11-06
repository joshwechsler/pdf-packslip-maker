"""The Operator's own instructions behind the "?" icons on the main window (edited in Settings).

Saved in settings.json under "help_text" (this Mac only). A spot never edited shows its starter
text; a spot saved blank shows no "?" at all."""

from __future__ import annotations

# (key, label in Settings, where the ? sits)
SPOTS = [
    ("orders", "Orders CSV box", "under Browse…"),
    ("drivers", "Driver list box", "under Browse…"),
    ("meals", "Meal label CSV box", "under Browse…"),
    ("date", "Delivery date", "next to Calendar…"),
    ("report", "Delivery report", "next to its name"),
    ("slips", "Pack slips", "next to its name"),
    ("bags", "Bag labels", "next to its name"),
    ("meal_labels", "Meal labels", "next to its name"),
]

DEFAULTS = {
    "orders": "The store's fulfillment export (Fulfillment to Fulfill → CSV).\n"
              "Used for pack slips, bag labels and the delivery report.",
    "drivers": "The file you get back from the delivery software after assigning routes.\n"
               "Optional: it adds each order's driver to the pack slips.",
    "meals": "The Label Data export, one row per meal container.\nUsed only for meal labels.",
    "date": "The day these orders go out. It prints on the slips and labels and names the files.",
    "report": "1. Generate and upload the CSV to the delivery software.\n"
              "2. Assign the routes there.\n3. Download it and drop it on the Driver list box.",
    "slips": "One page per customer, A–Z by last name. Big orders get one slip per bag.",
    "bags": "One Zebra label per bag for pickup orders. Print at Actual size (100%).",
    "meal_labels": "One 3×5 label per meal container. Print at Actual size (100%).",
}


def get(settings: dict, key: str) -> str:
    saved = settings.get("help_text") or {}
    return saved[key] if key in saved else DEFAULTS.get(key, "")


def set_all(settings: dict, texts: dict[str, str]) -> None:
    saved = dict(settings.get("help_text") or {})
    for key, text in texts.items():
        saved[key] = "\n".join(line.rstrip() for line in (text or "").strip().splitlines()).strip()
    settings["help_text"] = saved
