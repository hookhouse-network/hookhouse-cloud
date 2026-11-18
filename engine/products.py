"""Products from our own characters (owner, 12 Nov 2026: "find more and more things to earn").

Bloop & Friends counting activity book: black-and-white line art made from our code-drawn characters and objects
(not AI images), 8.5 x 11 in at 300 dpi, 26 pages: trace the number, count and colour, find the right group, count and
write, a certificate. Sell as a paperback on Amazon KDP (B&W interior keeps the print cost low) and as a printable PDF
on Gumroad / Teachers Pay Teachers. A listing file with title, description, keywords and the KDP answers sits next to
the PDF. Publishing itself is done by the owner (KDP has no publishing API; about 3 new titles a day allowed).
"""
from __future__ import annotations

import random
import time
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .config import ROOT

OUT = ROOT / "data" / "products"
W, H = 2550, 3300                       # 8.5 x 11 in at 300 dpi
MARGIN = 225                            # 0.75 in (KDP: at least 0.25 in + gutter for a 24-150 page book)
FONTS = ROOT / "assets" / "fonts"
WORDS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"]


def _font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    for name in (["LuckiestGuy-Regular.ttf", "Fredoka-Bold.ttf"] if bold else ["Fredoka-Regular.ttf", "Nunito-Regular.ttf"]):
        hits = list(FONTS.rglob(name))
        if hits:
            return ImageFont.truetype(str(hits[0]), size)
    for p in FONTS.rglob("*.ttf"):
        return ImageFont.truetype(str(p), size)
    return ImageFont.load_default()


def line_art(sprite_bgra: np.ndarray, size: int, thick: int = 7) -> Image.Image:
    """Colouring-page line art from a coloured sprite: outer outline + inner edges (eyes, mouth, details)."""
    spr = cv2.resize(sprite_bgra, (size, size), interpolation=cv2.INTER_AREA)
    a = spr[..., 3]
    white = np.full(spr.shape[:2] + (3,), 255, np.uint8)
    rgb = (spr[..., :3].astype(np.float32) * (a[..., None] / 255.0) + white * (1 - a[..., None] / 255.0)).astype(np.uint8)
    edges = cv2.Canny(cv2.cvtColor(rgb, cv2.COLOR_BGR2GRAY), 60, 140)
    cnts, _ = cv2.findContours((a > 40).astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    cv2.drawContours(edges, cnts, -1, 255, thick)
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=max(1, thick // 4))
    img = Image.fromarray(255 - edges).convert("L")
    alpha = Image.fromarray(np.where(edges > 0, 255, 0).astype(np.uint8))
    out = Image.new("LA", img.size, (255, 0))
    out.paste(img, (0, 0), alpha)
    return out


def _objects():
    from . import kids
    return {k: kids.draw_object(k, 420) for k in kids.OBJECTS}


def _mascot(name: str, size: int = 600) -> np.ndarray:
    from . import kids
    from .media.mascot import Mascot
    col, shape, _sz, _v, _x = kids._BASE_CAST[name]
    return Mascot(size=size, body=col, outline="#2E3A59", seed=1, shape=shape).draw(0.3)


def _page(title: str) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("L", (W, H), 255)
    d = ImageDraw.Draw(img)
    d.text((W // 2, MARGIN + 40), title, font=_font(120), fill=0, anchor="mt")
    return img, d


_ART: dict = {}


def art_at(objs: dict, kind: str, size: int) -> Image.Image:
    """Line art drawn at its final size (bold lines for little hands: about 1/30 of the object)."""
    key = (kind, size)
    if key not in _ART:
        _ART[key] = line_art(objs[kind], size, thick=max(6, size // 30))
    return _ART[key]


def _paste_art(img: Image.Image, art: Image.Image, cx: int, cy: int) -> None:
    img.paste(art.convert("L"), (cx - art.width // 2, cy - art.height // 2), art.getchannel("A"))


def _grid(n: int, box: tuple[int, int, int, int]) -> list[tuple[int, int]]:
    x0, y0, x1, y1 = box
    cols = min(n, 5)
    rows = (n + cols - 1) // cols
    cw, ch = (x1 - x0) / cols, (y1 - y0) / max(1, rows)
    return [(int(x0 + cw * (i % cols + 0.5)), int(y0 + ch * (i // cols + 0.5))) for i in range(n)]


def trace_page(k: int, obj: str, art: dict) -> Image.Image:
    img, d = _page(f"Trace and count: {k}")
    d.text((W // 2, 560), str(k), font=_font(900), fill=255, stroke_width=16, stroke_fill=110, anchor="mt")   # trace it
    d.text((W // 2, 1470), WORDS[k], font=_font(190), fill=255, stroke_width=8, stroke_fill=110, anchor="mt")
    size = {1: 900, 2: 700, 3: 640}.get(k, 520 if k <= 5 else 420)
    for x, y in _grid(k, (MARGIN, 1750, W - MARGIN, H - MARGIN - 230)):
        _paste_art(img, art_at(art, obj, size), x, y)
    d.text((W // 2, H - MARGIN - 120), f"Colour {WORDS[k]} {obj if k == 1 else obj + 's'}!", font=_font(80, False),
           fill=0, anchor="mt")
    return img


def group_page(k: int, obj: str, art: dict, rng: random.Random) -> Image.Image:
    img, d = _page(f"Circle the group with {k}")
    counts = sorted({k, max(1, k - 1), min(10, k + 1)} | ({k + 2} if k <= 2 else set()))[:3]
    rng.shuffle(counts)
    band = (H - 2 * MARGIN - 300) // len(counts)
    for i, n in enumerate(counts):
        y0 = MARGIN + 300 + i * band
        d.rounded_rectangle((MARGIN, y0 + 20, W - MARGIN, y0 + band - 20), radius=60, outline=0, width=6)
        size = min(400, int(band * 0.62), int((W - 2 * MARGIN - 120) / max(1, min(n, 5)) * 0.9))
        for x, y in _grid(n, (MARGIN + 60, y0 + 40, W - MARGIN - 60, y0 + band - 40)):
            _paste_art(img, art_at(art, obj, size), x, y)
    return img


def count_write_page(rng: random.Random, art: dict) -> Image.Image:
    img, d = _page("Count and write the number")
    objs = list(art)
    rows = 4
    band = (H - 2 * MARGIN - 300) // rows
    for i in range(rows):
        y0 = MARGIN + 300 + i * band
        n, obj = rng.randint(1, 10), rng.choice(objs)
        size = min(300, band // 2 - 20)
        for x, y in _grid(n, (MARGIN, y0 + 30, W - MARGIN - 420, y0 + band - 30)):
            _paste_art(img, art_at(art, obj, size), x, y)
        d.rounded_rectangle((W - MARGIN - 330, y0 + band // 2 - 150, W - MARGIN, y0 + band // 2 + 150), radius=40,
                            outline=0, width=8)
    return img


def cover_page() -> Image.Image:
    img, d = _page("Count with Bloop!")
    d.text((W // 2, 420), "A 1 to 10 counting activity book", font=_font(90, False), fill=0, anchor="mt")
    for i, name in enumerate(("Bloop", "Pip", "Mo", "Dee")):
        _paste_art(img, line_art(_mascot(name), 900), int(W * (0.2 + 0.2 * i)), 1500 + (i % 2) * 260)
    d.text((W // 2, H - MARGIN - 300), "Ages 3-5 · trace · count · colour · find the group", font=_font(80, False),
           fill=0, anchor="mt")
    d.text((W // 2, H - MARGIN - 160), "Bloop & Friends", font=_font(110), fill=0, anchor="mt")
    return img


def certificate_page() -> Image.Image:
    img, d = _page("Great counting!")
    _paste_art(img, line_art(_mascot("Bloop"), 1100), W // 2, 1300)
    d.text((W // 2, 2150), "This certificate goes to", font=_font(90, False), fill=0, anchor="mt")
    d.line((MARGIN + 250, 2450, W - MARGIN - 250, 2450), fill=0, width=6)
    d.text((W // 2, 2550), "who can count from 1 to 10!", font=_font(90, False), fill=0, anchor="mt")
    return img


def activity_book(seed: int = 7, log=print) -> Path:
    rng = random.Random(seed)
    art = _objects()                                     # coloured sprites; line art is drawn per size
    pages = [cover_page()]
    names = list(art)
    for k in range(1, 11):
        obj = names[(k - 1) % len(names)]
        pages += [trace_page(k, obj, art), group_page(k, obj, art, rng)]
    pages += [count_write_page(rng, art) for _ in range(4)]
    pages.append(certificate_page())
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d")
    pdf = OUT / f"bloop_counting_activity_book_{stamp}.pdf"
    rgb = [p.convert("RGB") for p in pages]
    rgb[0].save(pdf, save_all=True, append_images=rgb[1:], resolution=300)
    (OUT / f"bloop_counting_activity_book_{stamp}_listing.md").write_text(LISTING.format(pages=len(pages)),
                                                                           encoding="utf-8")
    log(f"Activity book: {pdf} ({len(pages)} pages)")
    return pdf


LISTING = """# Listing: Count with Bloop! (Bloop & Friends counting activity book)

**Title:** Count with Bloop!
**Subtitle:** A 1 to 10 Counting Activity Book for Ages 3-5 – Trace, Count, Colour and Find the Group
**Author / brand:** Bloop & Friends (HookHouse)
**Pages:** {pages} · **Trim:** 8.5 x 11 in · **Interior:** black & white, no bleed · **Paper:** white

**Description:**
Learn to count from 1 to 10 with Bloop, Pip, Mo and Dee! Each number has two pages: trace the big number and its word,
count and colour the objects, then circle the group with the right amount. Four count-and-write pages and a certificate
at the end. Big, simple line art for little hands. Made by the creators of the Bloop & Friends counting videos.

**Keywords (7):** counting book for toddlers · numbers 1-10 activity book · preschool math workbook · trace numbers
for kids · coloring and counting book · kindergarten counting practice · learn to count ages 3-5

**Categories:** Children's Books > Education & Reference > Math > Counting; Children's Books > Activities > Coloring
**Reading age:** 3-5 · **Grade:** Preschool–Kindergarten

**KDP questions:**
- AI-generated images? **No**: all drawings are made by our own code from our own characters (not AI image tools).
- AI-generated text? Short instructions written by us (no AI-generated text).
- Low-content / activity book: yes (activity). Expect a longer review (up to ~10 business days).

**Also sell as a printable PDF:** Gumroad (free account, pay-as-you-sell) and Teachers Pay Teachers (free basic seller
account). Same file; title "Count with Bloop! Printable 1-10 Counting Worksheets (26 pages)".
"""
