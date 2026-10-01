"""Draw the default logo, packslip/assets/meal_prep_logo.png: black "MEAL + PREP" lettering.

Rendered once at high resolution and committed, so the build doesn't need any font files.
Usage: python tools/make_logo.py [path/to/Bold.ttf]
"""

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONT = sys.argv[1] if len(sys.argv) > 1 else "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
H = 300                  # cap height target in px
TRACK = int(H * 0.06)    # letter spacing
BLACK = (0, 0, 0, 255)

font = ImageFont.truetype(FONT, int(H * 1.38))
cap_top = font.getbbox("M")[1]
cap_h = font.getbbox("M")[3] - cap_top


def word_width(word):
    return sum(font.getlength(ch) for ch in word) + TRACK * (len(word) - 1)


def draw_word(d, x, word):
    for ch in word:
        d.text((x, -cap_top + pad), ch, font=font, fill=BLACK)
        x += font.getlength(ch) + TRACK
    return x - TRACK


pad = 20
plus = int(cap_h * 0.72)        # width/height of the plus sign
thick = int(cap_h * 0.17)       # bar thickness, close to the letters' stroke weight
gap = int(cap_h * 0.32)
W = int(word_width("MEAL") + gap + plus + gap + word_width("PREP")) + 2 * pad
im = Image.new("RGBA", (W, cap_h + 2 * pad), (0, 0, 0, 0))
d = ImageDraw.Draw(im)
x = draw_word(d, pad, "MEAL") + gap
cy, cx = pad + cap_h / 2, x + plus / 2
d.rectangle((x, cy - thick / 2, x + plus, cy + thick / 2), fill=BLACK)
d.rectangle((cx - thick / 2, cy - plus / 2, cx + thick / 2, cy + plus / 2), fill=BLACK)
draw_word(d, x + plus + gap, "PREP")

im = im.crop(im.getbbox())
# ~1400px wide is >400 dpi at the default 250pt (3.5 in) logo width — sharp in print, small in the PDF.
im = im.resize((1400, round(im.height * 1400 / im.width)), Image.LANCZOS)
out = Path(__file__).resolve().parent.parent / "packslip" / "assets" / "meal_prep_logo.png"
im.save(out, optimize=True)
print(out, im.size)
