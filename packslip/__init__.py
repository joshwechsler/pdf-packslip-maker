"""Packs Be Slippin': turn a weekly order spreadsheet into one print-ready PDF."""

APP_NAME = "Packs Be Slippin'"
LEGACY_APP_NAME = "Pack Slip Maker"  # earlier name; its saved settings are migrated
# Version = MAJOR.FEATURES.FIXES (e.g. 2.4.1), worked out by tools/version.py from the labels on saved
# changes and written by CI to _build.py with BUILD (the updater compares BUILD, which goes up every update).
try:
    from ._build import BUILD
except ImportError:  # running from source
    BUILD = 0
try:
    from ._build import VERSION
except ImportError:  # running from source, or a build from before automatic versions
    VERSION = ""
__version__ = VERSION or "0.0.0"
