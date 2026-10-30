"""Packs Be Slippin': turn a weekly order spreadsheet into one print-ready PDF."""

APP_NAME = "Packs Be Slippin'"
LEGACY_APP_NAME = "Pack Slip Maker"  # earlier name; its saved settings are migrated
# Version = MAJOR.BUILD, e.g. 1.39. BUILD goes up with every update (CI writes it to _build.py).
# Change MAJOR only for a big milestone (e.g. a redesign, or saved layouts needing conversion).
MAJOR = 1
try:
    from ._build import BUILD
except ImportError:  # running from source
    BUILD = 0
__version__ = f"{MAJOR}.{BUILD}"


def version_for(build: int) -> str:
    return f"{MAJOR}.{build}"
