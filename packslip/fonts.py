"""Fonts for layouts: the three built into every PDF, the bundled starter fonts, and fonts added
from the Mac ("Add Font…").

Bundled fonts live in packslip/assets/fonts/<Family>/ (built by tools/make_fonts.py); added ones are
copied into <data dir>/fonts/ so they keep working if the original file moves. Each .ttf is
registered with reportlab (for the PDF) and, on a Mac, with the app's own process (so the
designer preview draws it too). A layout that names a font this Mac doesn't have prints in Helvetica.
"""

from __future__ import annotations

import shutil
import struct
import sys
from pathlib import Path

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import FF_FORCEBOLD, FF_ITALIC, TTFont, TTFontFile

from . import storage

BUILTIN = ["Helvetica", "Times", "Courier"]
_BUILTIN_FACES = {
    "Helvetica": ("Helvetica", "Helvetica-Bold", "Helvetica-Oblique", "Helvetica-BoldOblique"),
    "Times": ("Times-Roman", "Times-Bold", "Times-Italic", "Times-BoldItalic"),
    "Courier": ("Courier", "Courier-Bold", "Courier-Oblique", "Courier-BoldOblique"),
}
_STYLES = ((False, False), (True, False), (False, True), (True, True))

# family -> {(bold, italic): reportlab font name}
_faces: dict[str, dict[tuple[bool, bool], str]] = {}
_loaded = False


class FontError(Exception):
    """A font file that can't be used, with a reason the Operator can act on."""


def bundled_dir() -> Path:
    return Path(__file__).parent / "assets" / "fonts"


def user_dir() -> Path:
    return storage.data_dir() / "fonts"


def reset() -> None:
    """Forget what was loaded (the next call reads the folders again)."""
    global _loaded
    _faces.clear()
    _loaded = False


def _check_file(path: Path) -> None:
    """Refuse the kinds of font files reportlab can't put in a PDF, before it tries."""
    try:
        with open(path, "rb") as f:
            head = f.read(12)
            if len(head) < 12:
                raise FontError(f"“{path.name}” isn't a font file.")
            if head[:4] == b"ttcf":
                raise FontError(f"“{path.name}” is a font collection (.ttc), which can't go in a PDF. "
                                "Use the .ttf files for that font instead.")
            if head[:4] == b"OTTO":
                raise FontError(f"“{path.name}” is a PostScript-style .otf font, which can't go in a PDF. "
                                "Look for a .ttf version of the same font.")
            if head[:4] not in (b"\0\1\0\0", b"true"):
                raise FontError(f"“{path.name}” isn't a font file this app can read (use .ttf).")
            tables = struct.unpack(">H", head[4:6])[0]
            tags = {f.read(16)[:4] for _ in range(tables)}
    except OSError as e:
        raise FontError(f"Couldn't read “{path.name}”: {e}") from e
    if b"fvar" in tags:
        raise FontError(f"“{path.name}” is a variable font (one file with every weight), which can't go in a "
                        "PDF. Google Fonts downloads have a “static” folder: add the files from there, "
                        "e.g. …-Regular.ttf and …-Bold.ttf.")


def _read(path: Path) -> tuple[str, bool, bool]:
    """(family, bold, italic) from the font file itself."""
    try:
        info = TTFontFile(str(path), charInfo=0)
    except Exception as e:  # noqa: BLE001 - reportlab raises several kinds for bad files
        raise FontError(f"“{path.name}” can't be used in a PDF ({e}).") from e
    family = info.familyName.decode("utf-8", "replace") if isinstance(info.familyName, bytes) else str(info.familyName)
    return family.strip(), bool(info.flags & FF_FORCEBOLD), bool(info.flags & FF_ITALIC)


def _register(path: Path) -> str | None:
    """Register one .ttf; returns its family (None if the file is unusable)."""
    try:
        _check_file(path)
        family, bold, italic = _read(path)
        name = f"PBS-{path.stem}"
        if name not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(name, str(path)))
    except Exception:  # noqa: BLE001 - one bad file must not stop the app
        return None
    if family in BUILTIN:
        return None
    _faces.setdefault(family, {}).setdefault((bold, italic), name)
    _register_on_mac(path)
    return family


def _register_on_mac(path: Path) -> None:
    """Let Tk (the designer preview) draw the font, for this app only. Best effort."""
    if sys.platform != "darwin":
        return
    try:
        import ctypes
        cf = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
        ct = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/CoreText.framework/CoreText")
        cf.CFURLCreateFromFileSystemRepresentation.restype = ctypes.c_void_p
        cf.CFURLCreateFromFileSystemRepresentation.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_long,
                                                               ctypes.c_bool]
        cf.CFRelease.argtypes = [ctypes.c_void_p]
        ct.CTFontManagerRegisterFontsForURL.restype = ctypes.c_bool
        ct.CTFontManagerRegisterFontsForURL.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p]
        raw = str(path).encode("utf-8")
        url = cf.CFURLCreateFromFileSystemRepresentation(None, raw, len(raw), False)
        if url:
            ct.CTFontManagerRegisterFontsForURL(url, 1, None)  # 1 = kCTFontManagerScopeProcess
            cf.CFRelease(url)
    except Exception:  # noqa: BLE001 - the PDF still uses the font; only the preview falls back
        pass


def load() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    for folder in (bundled_dir(), user_dir()):
        if folder.is_dir():
            for path in sorted(folder.rglob("*")):
                if path.suffix.lower() in (".ttf", ".otf"):
                    _register(path)


def families() -> list[str]:
    """Font names for the designer: the basic three first, then the rest A–Z."""
    load()
    return BUILTIN + sorted(_faces, key=str.lower)


def available(family: str) -> bool:
    load()
    return family in _BUILTIN_FACES or family in _faces


def face(family: str, bold: bool, italic: bool) -> str:
    """The reportlab font name to draw with. A style the font doesn't have uses its nearest style
    (e.g. Oswald has no italic: it stays Oswald); a font this Mac doesn't have prints in Helvetica."""
    bold, italic = bool(bold), bool(italic)
    if family in _BUILTIN_FACES:
        return _BUILTIN_FACES[family][_STYLES.index((bold, italic))]
    load()
    have = _faces.get(family)
    if not have:
        return _BUILTIN_FACES["Helvetica"][_STYLES.index((bold, italic))]
    for style in ((bold, italic), (bold, False), (False, italic), (False, False)):
        if style in have:
            return have[style]
    return next(iter(have.values()))


def add_font_files(paths) -> list[str]:
    """Copy font files into the app's font folder. Returns the families added. Raises FontError,
    without copying anything, if any file can't be used."""
    paths = [Path(p) for p in paths]
    for p in paths:
        _check_file(p)
        _read(p)
    dest_dir = user_dir()
    dest_dir.mkdir(parents=True, exist_ok=True)
    added = []
    for p in paths:
        dest = dest_dir / p.name
        if dest.resolve() != p.resolve():
            shutil.copy2(p, dest)
        family = _register(dest)
        if family and family not in added:
            added.append(family)
    return added
