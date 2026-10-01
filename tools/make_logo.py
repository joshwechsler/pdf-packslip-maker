"""Draw the default logo, packslip/assets/meal_prep_logo.png: black "MEAL (+) PREP" lettering.

Rendered once at high resolution and committed, so the build doesn't need any font files.
Usage: python tools/make_logo.py [path/to/Bold.ttf]
"""

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONT = sys.argv[1] if len(sys.argv) > 1 else "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
H = 300                  # cap height target in px
TRACK = int(H * 0.06)    # letter spacing
BLACK, WHITE = (0, 0, 0, 255), (255, 255, 255, 255)

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
circle = int(cap_h * 0.92)
gap = int(cap_h * 0.32)
W = int(word_width("MEAL") + gap + circle + gap + word_width("PREP")) + 2 * pad
im = Image.new("RGBA", (W, cap_h + 2 * pad), (0, 0, 0, 0))
d = ImageDraw.Draw(im)
x = draw_word(d, pad, "MEAL") + gap
cy = pad + cap_h / 2
d.ellipse((x, cy - circle / 2, x + circle, cy + circle / 2), fill=BLACK)
arm, thick = circle * 0.30, circle * 0.12
cx = x + circle / 2
d.rectangle((cx - arm, cy - thick / 2, cx + arm, cy + thick / 2), fill=WHITE)
d.rectangle((cx - thick / 2, cy - arm, cx + thick / 2, cy + arm), fill=WHITE)
draw_word(d, x + circle + gap, "PREP")

im = im.crop(im.getbbox())
# ~1400px wide is >400 dpi at the default 250pt (3.5 in) logo width — sharp in print, small in the PDF.
im = im.resize((1400, round(im.height * 1400 / im.width)), Image.LANCZOS)
out = Path(__file__).resolve().parent.parent / "packslip" / "assets" / "meal_prep_logo.png"
im.save(out, optimize=True)
print(out, im.size)
