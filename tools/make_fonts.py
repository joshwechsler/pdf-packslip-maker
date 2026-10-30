"""Build the bundled fonts (packslip/assets/fonts) from Google Fonts files.

Google ships most families as variable fonts, which PDFs can't use, so this cuts fixed
Regular / Bold / Italic / Bold Italic files out of them and names them so that both the PDF
renderer and the Mac (for the designer preview) see one family with four styles.

    pip install fonttools
    python tools/make_fonts.py <folder with the downloaded .ttf and OFL.txt files>

Sources (SIL Open Font License): github.com/google/fonts, folders ofl/lato, ofl/montserrat,
ofl/oswald, ofl/playfairdisplay, ofl/robotocondensed.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont

OUT = Path(__file__).resolve().parents[1] / "packslip" / "assets" / "fonts"
STYLES = {"Regular": (400, False), "Bold": (700, False), "Italic": (400, True), "Bold Italic": (700, True)}
# family: (upright file, italic file or None, licence file); files ending -VF are variable.
FAMILIES = {
    "Lato": ("Lato-Regular.ttf", "Lato-Italic.ttf", "Lato-OFL.txt"),
    "Montserrat": ("Montserrat-VF.ttf", "Montserrat-Italic-VF.ttf", "Montserrat-OFL.txt"),
    "Oswald": ("Oswald-VF.ttf", None, "Oswald-OFL.txt"),
    "Playfair Display": ("Playfair-VF.ttf", "Playfair-Italic-VF.ttf", "PlayfairDisplay-OFL.txt"),
    "Roboto Condensed": ("RobotoCondensed-VF.ttf", "RobotoCondensed-Italic-VF.ttf", "RobotoCondensed-OFL.txt"),
}
LATO_STATIC = {"Regular": "Lato-Regular.ttf", "Bold": "Lato-Bold.ttf",
               "Italic": "Lato-Italic.ttf", "Bold Italic": "Lato-BoldItalic.ttf"}


def rename(font: TTFont, family: str, style: str, weight: int, italic: bool) -> None:
    bold = weight >= 700
    ps = f"{family.replace(' ', '')}-{style.replace(' ', '')}"
    name = font["name"]
    for nid in (16, 17, 21, 22, 25):
        name.removeNames(nameID=nid)
    for nid, value in ((1, family), (2, style), (3, ps), (4, f"{family} {style}"), (6, ps)):
        name.setName(value, nid, 3, 1, 0x409)
        name.setName(value, nid, 1, 0, 0)
    os2 = font["OS/2"]
    os2.usWeightClass = weight
    sel = os2.fsSelection & ~0b1100001  # clear italic, bold, regular
    os2.fsSelection = sel | (1 if italic else 0) | (0b100000 if bold else 0) | (0b1000000 if not (bold or italic) else 0)
    font["head"].macStyle = (1 if bold else 0) | (2 if italic else 0)


def main(src: Path) -> None:
    shutil.rmtree(OUT, ignore_errors=True)
    for family, (upright, italic_file, licence) in FAMILIES.items():
        folder = OUT / family
        folder.mkdir(parents=True)
        shutil.copy(src / licence, folder / "OFL.txt")
        for style, (weight, italic) in STYLES.items():
            if family == "Lato":
                font = TTFont(src / LATO_STATIC[style])
            else:
                file = italic_file if italic else upright
                if file is None:
                    continue
                font = instantiateVariableFont(TTFont(src / file), {"wght": weight})
            rename(font, family, style, weight, italic)
            font.save(folder / f"{family.replace(' ', '')}-{style.replace(' ', '')}.ttf")
    print("\n".join(str(p.relative_to(OUT)) for p in sorted(OUT.rglob("*.ttf"))))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
