"""Christmas colouring book (owner 17 Nov 2026: "as per the research message, prepare the books and videos
accordingly"). The weekly product research ranked "Christmas coloring pages for kids" #1 (score 8.6, median 3.9M
views on the top Shorts, season Nov-Dec, easy to build, fits Bloop & Friends).

Everything is drawn by our own code: Bloop & friends in Santa hats + Christmas objects (tree, gift, snowman, candy
cane, bell, stocking, ornament, star, gingerbread man, reindeer face) as thick, simple outlines for ages 2-6.
Also a "Letter to Santa" page and a "My Christmas drawing" page (popular in this niche). No third-party art.
"""
from __future__ import annotations

import math

import numpy as np
from PIL import Image, ImageDraw

from .digital_products import INK, M, PH, PW, _cover, _font, _kit, _listing, _new, _save_pdf, _thumb
from .products import _mascot, line_art

OBJECTS = ["tree", "gift", "snowman", "candy_cane", "bell", "stocking", "ornament", "star", "gingerbread", "reindeer"]
NAMES = {"tree": "Christmas tree", "gift": "present", "snowman": "snowman", "candy_cane": "candy cane",
         "bell": "jingle bell", "stocking": "stocking", "ornament": "ornament", "star": "star",
         "gingerbread": "gingerbread man", "reindeer": "reindeer"}


def _rgba(size: int) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    return img, ImageDraw.Draw(img)


def xmas_object(kind: str, size: int = 420) -> np.ndarray:
    """A flat coloured sprite (BGRA) that line_art() turns into a colouring outline."""
    s = size
    img, d = _rgba(s)
    G, R, Y, W, B, Br = (60, 150, 70, 255), (210, 50, 50, 255), (245, 200, 60, 255), (235, 240, 250, 255), \
        (70, 110, 200, 255), (150, 95, 50, 255)
    if kind == "tree":
        for k, (top, bot, half) in enumerate(((0.08, 0.38, 0.22), (0.25, 0.58, 0.32), (0.42, 0.80, 0.42))):
            d.polygon([(s / 2, s * top), (s / 2 - s * half, s * bot), (s / 2 + s * half, s * bot)], fill=G)
        d.rectangle([s * 0.43, s * 0.80, s * 0.57, s * 0.95], fill=Br)
        for x, y in ((0.42, 0.33), (0.6, 0.5), (0.36, 0.62), (0.55, 0.72), (0.66, 0.74)):
            d.ellipse([s * x - s * 0.035, s * y - s * 0.035, s * x + s * 0.035, s * y + s * 0.035], fill=R)
        _star(d, s / 2, s * 0.08, s * 0.08, Y)
    elif kind == "gift":
        d.rectangle([s * 0.18, s * 0.38, s * 0.82, s * 0.9], fill=R)
        d.rectangle([s * 0.13, s * 0.28, s * 0.87, s * 0.4], fill=R)
        d.rectangle([s * 0.45, s * 0.28, s * 0.55, s * 0.9], fill=Y)
        d.ellipse([s * 0.28, s * 0.12, s * 0.5, s * 0.3], fill=Y)
        d.ellipse([s * 0.5, s * 0.12, s * 0.72, s * 0.3], fill=Y)
    elif kind == "snowman":
        for cy, r in ((0.74, 0.22), (0.45, 0.16), (0.22, 0.11)):
            d.ellipse([s / 2 - s * r, s * cy - s * r, s / 2 + s * r, s * cy + s * r], fill=W)
        d.rectangle([s * 0.38, s * 0.04, s * 0.62, s * 0.13], fill=(40, 40, 40, 255))
        d.rectangle([s * 0.32, s * 0.12, s * 0.68, s * 0.15], fill=(40, 40, 40, 255))
        for x in (0.46, 0.54):
            d.ellipse([s * x - s * 0.015, s * 0.2 - s * 0.015, s * x + s * 0.015, s * 0.2 + s * 0.015], fill=(40, 40, 40, 255))
        d.polygon([(s * 0.5, s * 0.235), (s * 0.62, s * 0.25), (s * 0.5, s * 0.265)], fill=(240, 140, 40, 255))
        d.rectangle([s * 0.36, s * 0.31, s * 0.64, s * 0.35], fill=R)
        for y in (0.42, 0.5, 0.7):
            d.ellipse([s * 0.485, s * y, s * 0.515, s * y + s * 0.03], fill=(40, 40, 40, 255))
    elif kind == "candy_cane":
        d.arc([s * 0.3, s * 0.08, s * 0.7, s * 0.45], 180, 360, fill=R, width=int(s * 0.1))
        d.rectangle([s * 0.6, s * 0.26, s * 0.7, s * 0.92], fill=R)
        for y in np.arange(0.34, 0.9, 0.1):
            d.polygon([(s * 0.6, s * y), (s * 0.7, s * (y - 0.05)), (s * 0.7, s * (y - 0.01)), (s * 0.6, s * (y + 0.04))], fill=W)
    elif kind == "bell":
        d.polygon([(s * 0.5, s * 0.15), (s * 0.3, s * 0.35), (s * 0.24, s * 0.72), (s * 0.76, s * 0.72), (s * 0.7, s * 0.35)], fill=Y)
        d.ellipse([s * 0.3, s * 0.12, s * 0.7, s * 0.42], fill=Y)
        d.rectangle([s * 0.18, s * 0.7, s * 0.82, s * 0.76], fill=Y)
        d.ellipse([s * 0.44, s * 0.74, s * 0.56, s * 0.86], fill=Y)
        d.ellipse([s * 0.42, s * 0.04, s * 0.58, s * 0.16], fill=R)
    elif kind == "stocking":
        d.rectangle([s * 0.3, s * 0.1, s * 0.62, s * 0.22], fill=W)
        d.polygon([(s * 0.32, s * 0.22), (s * 0.6, s * 0.22), (s * 0.6, s * 0.62), (s * 0.82, s * 0.72),
                   (s * 0.78, s * 0.92), (s * 0.4, s * 0.88), (s * 0.32, s * 0.7)], fill=R)
        d.ellipse([s * 0.62, s * 0.7, s * 0.84, s * 0.92], fill=W)
    elif kind == "ornament":
        d.ellipse([s * 0.2, s * 0.25, s * 0.8, s * 0.85], fill=B)
        d.rectangle([s * 0.43, s * 0.16, s * 0.57, s * 0.27], fill=Y)
        d.arc([s * 0.44, s * 0.05, s * 0.56, s * 0.18], 180, 360, fill=Y, width=int(s * 0.025))
        d.rectangle([s * 0.21, s * 0.5, s * 0.79, s * 0.58], fill=W)
    elif kind == "star":
        _star(d, s / 2, s / 2, s * 0.42, Y)
    elif kind == "gingerbread":
        Br2 = (190, 120, 60, 255)
        d.ellipse([s * 0.35, s * 0.05, s * 0.65, s * 0.33], fill=Br2)
        d.rounded_rectangle([s * 0.3, s * 0.3, s * 0.7, s * 0.72], radius=int(s * 0.08), fill=Br2)
        for poly in (((0.3, 0.33), (0.1, 0.45), (0.15, 0.53), (0.32, 0.45)), ((0.7, 0.33), (0.9, 0.45), (0.85, 0.53), (0.68, 0.45)),
                     ((0.33, 0.68), (0.25, 0.95), (0.4, 0.95), (0.48, 0.72)), ((0.67, 0.68), (0.75, 0.95), (0.6, 0.95), (0.52, 0.72))):
            d.polygon([(s * x, s * y) for x, y in poly], fill=Br2)
        for y in (0.42, 0.52, 0.62):
            d.ellipse([s * 0.47, s * y, s * 0.53, s * y + s * 0.05], fill=W)
        for x in (0.44, 0.56):
            d.ellipse([s * x - s * 0.02, s * 0.15, s * x + s * 0.02, s * 0.19], fill=W)
        d.arc([s * 0.42, s * 0.16, s * 0.58, s * 0.27], 20, 160, fill=W, width=int(s * 0.015))
    elif kind == "reindeer":
        Br2 = (160, 105, 60, 255)
        for side in (-1, 1):
            x0 = s / 2 + side * s * 0.16
            d.line([(x0, s * 0.3), (x0 + side * s * 0.12, s * 0.06)], fill=Br, width=int(s * 0.04))
            d.line([(x0 + side * s * 0.06, s * 0.18), (x0 + side * s * 0.2, s * 0.14)], fill=Br, width=int(s * 0.035))
        d.ellipse([s * 0.25, s * 0.25, s * 0.75, s * 0.85], fill=Br2)
        for x in (0.4, 0.6):
            d.ellipse([s * x - s * 0.04, s * 0.45, s * x + s * 0.04, s * 0.53], fill=W)
        d.ellipse([s * 0.42, s * 0.65, s * 0.58, s * 0.8], fill=R)
    else:
        raise ValueError(kind)
    return _inked(np.array(img), max(3, s // 90))


def _inked(rgba: np.ndarray, width: int) -> np.ndarray:
    """Dark lines wherever two colour areas meet (red ornaments on a green tree have almost the same grey, so the
    edge finder lost them), returned as BGRA."""
    import cv2
    rgb = rgba[..., :3].astype(np.int16)
    a = rgba[..., 3] > 40
    diff = np.zeros(a.shape, bool)
    for dy, dx in ((0, 1), (1, 0)):
        d_ = np.abs(rgb - np.roll(rgb, (dy, dx), axis=(0, 1))).sum(axis=2) > 60
        diff |= d_
    diff &= a
    diff = cv2.dilate(diff.astype(np.uint8), np.ones((width, width), np.uint8)) > 0
    out = rgba.copy()
    out[diff & a, :3] = (40, 40, 40)
    return out[..., [2, 1, 0, 3]].copy()


def _star(d, cx, cy, r, fill):
    pts = []
    for k in range(10):
        ang = -math.pi / 2 + k * math.pi / 5
        rr = r if k % 2 == 0 else r * 0.45
        pts.append((cx + rr * math.cos(ang), cy + rr * math.sin(ang)))
    d.polygon(pts, fill=fill)


def santa_hat(sprite: np.ndarray) -> np.ndarray:
    """Put a big Santa hat on a mascot sprite (BGRA): brim across the upper head, cone flopping to one side."""
    h, w = sprite.shape[:2]
    a = sprite[..., 3] > 40
    rows = np.where(a.any(axis=1))[0]
    top, bottom = (int(rows[0]), int(rows[-1])) if len(rows) else (int(h * 0.1), int(h * 0.9))
    body = bottom - top
    brim_y = top + int(body * 0.22)
    cols = np.where(a[min(h - 1, brim_y)])[0]
    left, right = (int(cols[0]), int(cols[-1])) if len(cols) else (int(w * 0.25), int(w * 0.75))
    pad = int(h * 0.35)
    canvas = np.zeros((h + pad, w, 4), np.uint8)
    canvas[pad:] = sprite
    img = Image.fromarray(canvas[..., [2, 1, 0, 3]].copy(), "RGBA")
    d = ImageDraw.Draw(img)
    by = pad + brim_y
    cx, half = (left + right) // 2, int((right - left) * 0.55)
    tip = (cx + int(half * 1.1), pad + top - int(body * 0.32))
    d.polygon([(cx - half, by), (cx + half, by), (cx + int(half * 0.5), pad + top - int(body * 0.1)), tip],
              fill=(210, 50, 50, 255))
    r = max(28, int(body * 0.07))
    d.ellipse([tip[0] - r, tip[1] - r, tip[0] + r, tip[1] + r], fill=(240, 240, 245, 255))
    d.rounded_rectangle([cx - half - int(body * 0.05), by - int(body * 0.06), cx + half + int(body * 0.05),
                         by + int(body * 0.06)], radius=int(body * 0.06), fill=(240, 240, 245, 255))
    return _inked(np.array(img), max(3, h // 120))


def letter_to_santa() -> Image.Image:
    img, d = _new("My Letter to Santa")
    y = M + 420
    for line in ("Dear Santa,", "My name is", "I am ____ years old.", "This year I was very good because",
                 "", "For Christmas I would love", "", "Love,"):
        d.text((M + 40, y), line, font=_font(90), fill=INK)
        if line in ("My name is", "Love,"):
            d.line([(M + 40 + d.textlength(line, font=_font(90)) + 30, y + 95), (PW - M - 40, y + 95)], fill=INK, width=5)
        elif line == "":
            d.line([(M + 40, y + 95), (PW - M - 40, y + 95)], fill=INK, width=5)
        y += 250
    star = line_art(xmas_object("star", 420), 420, thick=8)
    img.paste(star.convert("RGB"), (PW - M - 460, PH - M - 520), star.getchannel("A"))
    return img


def build(log=print):
    folder = _kit("christmas_colouring_book")
    pages = []
    title, d = _new()
    for txt, sz, y in (("Merry Christmas", 190, 0.3), ("with Bloop & Friends!", 130, 0.4),
                       ("A Christmas coloring book for little hands", 72, 0.5)):
        tw = d.textlength(txt, font=_font(sz))
        d.text(((PW - tw) / 2, PH * y), txt, font=_font(sz), fill=INK)
    tree = line_art(xmas_object("tree", 900), 900, thick=10)
    title.paste(tree.convert("RGB"), ((PW - 900) // 2, int(PH * 0.58)), tree.getchannel("A"))
    pages.append(title)
    cast = ["Bloop", "Pip", "Mo", "Dee"]
    heroes = {n: line_art(santa_hat(_mascot(n, 900)), 1750, thick=11) for n in cast}
    arts = {k: line_art(xmas_object(k, 900), 760, thick=10) for k in OBJECTS}
    big = {k: line_art(xmas_object(k, 1200), 1900, thick=13) for k in OBJECTS}
    for k in range(20):
        if k % 5 == 4:                                  # every 5th page: one big Christmas object alone (easiest)
            obj = OBJECTS[(k // 5) % len(OBJECTS)]
            img, d = _new(f"Color the {NAMES[obj]}!")
            a = big[obj]
            img.paste(a.convert("RGB"), ((PW - a.width) // 2, (PH - a.height) // 2 + 100), a.getchannel("A"))
        else:
            name, obj = cast[k % 4], OBJECTS[k % len(OBJECTS)]
            img, d = _new(f"{name} and the {NAMES[obj]}")
            hero = heroes[name]
            img.paste(hero.convert("RGB"), (M - 60, PH - M - hero.height - 120), hero.getchannel("A"))
            a = arts[obj]
            img.paste(a.convert("RGB"), (PW - M - a.width + 40, PH - M - a.width - 160), a.getchannel("A"))
            if k % 2:
                a2 = arts[OBJECTS[(k + 3) % len(OBJECTS)]]
                img.paste(a2.convert("RGB"), (PW - M - a2.width + 40, M + 330), a2.getchannel("A"))
        pages.append(img)
    pages.append(letter_to_santa())
    pages.append(_new("My Christmas drawing")[0])
    if len(pages) % 2:
        pages.append(_new("Merry Christmas!")[0])
    _save_pdf(pages, folder / "Christmas_Coloring_Book_Bloop.pdf")
    art = Image.fromarray(np.ascontiguousarray(santa_hat(_mascot("Bloop", 900))[..., [2, 1, 0, 3]]), "RGBA")
    cover = _cover("Merry Christmas with Bloop!", "Christmas coloring book · 20 big pages · ages 2-6", (190, 40, 50), art)
    _thumb(cover, folder)
    _listing(folder, {
        "title": "Christmas Coloring Book for Kids Ages 2-6: Merry Christmas with Bloop!",
        "subtitle": "20 Big, Easy Christmas Coloring Pages with Santa Hats, Trees, Snowmen and Presents, plus a Letter to Santa",
        "description": ("A cozy Christmas coloring book for toddlers and preschoolers: Bloop, Pip, Mo and Dee in Santa "
                        "hats with Christmas trees, presents, snowmen, candy canes, bells, stockings, ornaments, stars, "
                        "gingerbread men and reindeer. Thick lines and one big picture per page for little hands, a "
                        "Letter to Santa page and a page for their own Christmas drawing. A perfect stocking stuffer."),
        "files": ["Christmas_Coloring_Book_Bloop.pdf"], "pages": len(pages), "price_usd": "$3 (printable PDF)",
        "price_inr": "₹79", "kdp_price": "$5.99 paperback", "grades": "PreK-K",
        "tags": ["christmas coloring book for kids", "christmas coloring pages", "toddler christmas activity book",
                 "christmas gifts for kids", "stocking stuffers for kids", "christmas coloring book ages 2-4",
                 "preschool christmas activities"],
        "kdp_categories": "Children's Books > Holidays & Celebrations > Christmas; Children's Books > Activities, "
                          "Crafts & Games > Coloring Books",
        "stores": ["Amazon KDP", "Payhip", "Gumroad"], "channel": "bloop_and_friends",
        "note": "Kids channel: no shop links in Made-for-Kids video descriptions. Season: sell Nov-Dec."})
    log(f"  christmas coloring book ({len(pages)} pages) -> {folder}")
    return folder
