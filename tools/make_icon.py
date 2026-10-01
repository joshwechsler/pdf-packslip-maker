"""Draw packaging/icon.png (1024px). PyInstaller converts it to .icns at build time."""

from pathlib import Path

from PIL import Image, ImageDraw

S = 1024
NAVY, GOLD, PAPER, LINE = (31, 58, 95, 255), (200, 162, 74, 255), (255, 255, 255, 255), (196, 204, 214, 255)

im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(im)
d.rounded_rectangle((100, 100, 924, 924), radius=185, fill=NAVY)
d.rounded_rectangle((270, 190, 754, 834), radius=28, fill=PAPER)          # the slip
d.rectangle((270, 190, 754, 270), fill=GOLD)                              # header bar
d.rounded_rectangle((270, 190, 754, 300), radius=28, outline=None)
for i, w in enumerate((330, 260, 360, 300, 220)):
    y = 360 + i * 82
    d.rounded_rectangle((330, y, 330 + w, y + 28), radius=14, fill=LINE)
    d.rounded_rectangle((640, y, 694, y + 28), radius=14, fill=LINE)
out = Path(__file__).resolve().parent.parent / "packaging" / "icon.png"
im.save(out)
print(out)
