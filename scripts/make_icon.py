"""HookHouse desktop icon (scripts/hookhouse.ico): dark rounded tile, "HH" in the brand blue with a small red play
mark. python scripts/make_icon.py"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
S = 256
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
d.rounded_rectangle([8, 8, S - 8, S - 8], radius=56, fill=(17, 22, 34, 255), outline=(124, 140, 255, 255), width=10)
font = None
for f in sorted((ROOT / "assets" / "fonts").glob("*.ttf")):
    if "bold" in f.name.lower() or "black" in f.name.lower():
        font = ImageFont.truetype(str(f), 118)
        break
font = font or ImageFont.load_default()
box = d.textbbox((0, 0), "HH", font=font)
w, h = box[2] - box[0], box[3] - box[1]
d.text(((S - w) / 2 - box[0], (S - h) / 2 - box[1] - 14), "HH", font=font, fill=(233, 237, 244, 255))
d.polygon([(104, 196), (104, 236), (140, 216)], fill=(255, 59, 59, 255))
out = ROOT / "scripts" / "hookhouse.ico"
img.save(out, sizes=[(256, 256), (64, 64), (48, 48), (32, 32), (16, 16)])
print(out)
