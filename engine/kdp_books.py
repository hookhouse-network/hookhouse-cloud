"""KDP book family, built by our own code (no generative AI). Research: docs/kdp_research.md.

Book 1: Preschool Tracing Workbook (ages 3-5), the best-selling preschool format: pen-control lines, A-Z capitals
and lowercase on handwriting lines, numbers 0-20 with counting dots, shapes, and a certificate. ~90 pages,
8.5 x 11 in at 300 dpi with 0.75 in margins, priced for KDP's 60% royalty tier ($9.99+).
Usage: python -m engine.kdp_books tracing"""
from __future__ import annotations
from engine.core.quiet import noted

import json
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .config import ROOT

OUT = ROOT / "data" / "products"
FONTS = ROOT / "assets" / "fonts"
PW, PH, M = 2550, 3300, 225
INK, GUIDE, TRACE = (35, 38, 48), (170, 175, 185), (190, 195, 205)
WORDS = {"A": "Apple", "B": "Ball", "C": "Cupcake", "D": "Duck", "E": "Egg", "F": "Fish", "G": "Grapes", "H": "Hat",
         "I": "Igloo", "J": "Jam", "K": "Kite", "L": "Lion", "M": "Moon", "N": "Nest", "O": "Owl", "P": "Pig",
         "Q": "Queen", "R": "Rainbow", "S": "Star", "T": "Tree", "U": "Umbrella", "V": "Van", "W": "Whale",
         "X": "Xylophone", "Y": "Yo-yo", "Z": "Zebra"}
PICS = {"A": "apple", "B": "ball", "C": "cupcake", "D": "duck", "F": "fish", "S": "star"}


def _f(size: int, name: str = "Poppins-ExtraBold.ttf"):
    return ImageFont.truetype(str(FONTS / name), size)


def _page(title: str = "", sub: str = "") -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGB", (PW, PH), "white")
    d = ImageDraw.Draw(img)
    if title:
        f = _f(120)
        d.text(((PW - d.textlength(title, font=f)) / 2, M - 40), title, font=f, fill=INK)
    if sub:
        f = _f(56)
        d.text(((PW - d.textlength(sub, font=f)) / 2, M + 120), sub, font=f, fill=(110, 115, 125))
    return img, d


def _dotted(d, pts, every: int = 34, r: int = 6, fill=GUIDE):
    """Dots along a polyline (the line children trace)."""
    acc = 0.0
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        seg = math.hypot(x1 - x0, y1 - y0)
        t = (every - acc) if acc else 0.0
        while t <= seg:
            x, y = x0 + (x1 - x0) * t / seg, y0 + (y1 - y0) * t / seg
            d.ellipse([x - r, y - r, x + r, y + r], fill=fill)
            t += every
        acc = (acc + seg) % every


def _start(d, x, y):
    d.ellipse([x - 22, y - 22, x + 22, y + 22], fill=(40, 170, 120))


def _hw_lines(d, y, x0=M, x1=PW - M, h=260):
    """Handwriting row: solid top and baseline, dashed midline."""
    d.line([(x0, y), (x1, y)], fill=GUIDE, width=5)
    d.line([(x0, y + h), (x1, y + h)], fill=INK, width=6)
    for x in range(x0, x1, 60):
        d.line([(x, y + h // 2), (x + 30, y + h // 2)], fill=GUIDE, width=4)


def _trace_text(img, text: str, x: int, y: int, size: int, color=TRACE, dotted: bool = True):
    """Light letters to trace over; dotted edge so it reads as 'trace me'."""
    f = _f(size, "Poppins-ExtraBold.ttf" if size > 400 else "Poppins-Black.ttf")
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).text((x, y), text, font=f, fill=255)
    m = np.array(mask) > 128
    light = Image.new("RGB", img.size, color)
    img.paste(light, (0, 0), Image.fromarray((m * 255).astype(np.uint8)))
    if dotted:
        from scipy.ndimage import binary_erosion
        edge = m & ~binary_erosion(m, iterations=4)
        yy, xx = np.mgrid[0:img.size[1], 0:img.size[0]]
        dots = ((yy // 10) % 2 == 0) & ((xx // 10) % 2 == 0)
        img.paste(Image.new("RGB", img.size, GUIDE), (0, 0), Image.fromarray(((edge & dots) * 255).astype(np.uint8)))


MOTIVATION = ["You're doing amazing!", "Practice makes progress!", "Keep going, superstar!", "One more page, you can do it!",
              "Slow and neat wins the race!", "Your brain is growing!", "Wow, look at you go!", "Be proud of your work!",
              "Mistakes help us learn!", "High five!"]
FACTS = ["An octopus has three hearts.", "A group of flamingos is called a flamboyance.", "Honey never spoils.",
         "Bananas grow pointing up.", "Butterflies taste with their feet.", "A snail can sleep for three years.",
         "Elephants can't jump.", "Sea otters hold hands while they sleep.", "A day on Venus is longer than its year.",
         "Cows have best friends.", "Owls can turn their heads almost all the way around.", "Stars twinkle because of air.",
         "A baby kangaroo is called a joey.", "Penguins can't fly, but they swim fast.", "The Moon has moonquakes.",
         "Dolphins sleep with one eye open.", "Rainbows are full circles from up high.", "Ants never sleep like we do.",
         "Giraffes have purple tongues.", "Snow can be blue, not just white."]


def _star(d, cx, cy, r, outline=INK, width=5):
    pts = [(cx + (r if k % 2 == 0 else r * 0.45) * math.cos(-math.pi / 2 + k * math.pi / 5),
            cy + (r if k % 2 == 0 else r * 0.45) * math.sin(-math.pi / 2 + k * math.pi / 5)) for k in range(11)]
    d.line(pts, fill=outline, width=width, joint="curve")


def decorate(pages: list[Image.Image], book: str, rate: bool = True, skip_first: int = 1) -> list[Image.Image]:
    """Owner, 14 Nov: page numbers, header and footer, 'Did you know?' facts, motivation, a star self-rating.
    Every interior page gets a small header (book name), a footer with the page number and, alternating, a
    motivational line or a fun fact; activity pages get 'How did I do?' with 5 stars to color in."""
    fh, ff = _f(34, "Poppins-ExtraBold.ttf"), _f(40, "Poppins-ExtraBold.ttf")
    for i, img in enumerate(pages):
        if i < skip_first:
            continue
        d = ImageDraw.Draw(img)
        d.text((M, 80), book, font=fh, fill=(150, 155, 165))
        d.line([(M, 135), (PW - M, 135)], fill=(225, 228, 233), width=3)
        d.line([(M, PH - 175), (PW - M, PH - 175)], fill=(225, 228, 233), width=3)
        num = str(i + 1)
        d.text(((PW - d.textlength(num, font=ff)) / 2, PH - 150), num, font=ff, fill=INK)
        line = (f"Did you know? {FACTS[(i // 2) % len(FACTS)]}" if i % 2 else MOTIVATION[(i // 2) % len(MOTIVATION)])
        d.text((M, PH - 150), line, font=_f(34), fill=(110, 115, 125))
        if rate:
            x0 = PW - M - 5 * 62
            d.text((x0 - 300, PH - 150), "How did I do?", font=_f(34), fill=(110, 115, 125))
            for k in range(5):
                _star(d, x0 + 30 + k * 62, PH - 128, 26, outline=(230, 170, 40), width=4)
    return pages


def _pic(name: str, size: int):
    try:
        from .products import _objects, line_art
        return line_art(_objects()[name], size, thick=9)
    except Exception as _swallowed:  # noqa: BLE001
        noted("kdp_books.py:133", _swallowed)
        return None


def cover_page() -> Image.Image:
    img, d = _page()
    d.rectangle([0, 0, PW, PH], fill=(255, 248, 230))
    for k, (txt, size, col) in enumerate((("MY FIRST", 220, INK), ("TRACING", 300, (230, 90, 60)),
                                          ("WORKBOOK", 300, (40, 140, 200)))):
        f = _f(size, "Anton-Regular.ttf")
        d.text(((PW - d.textlength(txt, font=f)) / 2, 500 + k * 330), txt, font=f, fill=col)
    sub = "Letters, Numbers, Shapes & Pen Control  |  Ages 3-5"
    f = _f(64)
    d.text(((PW - d.textlength(sub, font=f)) / 2, 1600), sub, font=f, fill=INK)
    _trace_text(img, "Aa 123", 520, 1850, 420)
    return img


def owner_page() -> Image.Image:
    img, d = _page("This book belongs to:")
    _hw_lines(d, 700, M + 200, PW - M - 200, 300)
    tips = ["Hold the pencil gently, like a little bird.", "Start at the green dot and follow the dots.",
            "Go slowly. Neat is better than fast.", "Do one or two pages a day, then celebrate!"]
    f = _f(60)
    d.text((M, 1300), "Tips for grown-ups", font=_f(80), fill=(230, 90, 60))
    for k, t in enumerate(tips):
        d.text((M + 40, 1460 + k * 130), "•  " + t, font=f, fill=INK)
    return img


def pen_control(kind: str) -> Image.Image:
    titles = {"straight": "Straight Lines", "zigzag": "Zig Zags", "wave": "Waves", "loop": "Loops",
              "curve": "Hills", "spiral": "Spirals"}
    img, d = _page(titles[kind], "Start at the green dot and follow the dots")
    rows, x0, x1 = 6, M + 120, PW - M - 60
    for r in range(rows):
        y = 650 + r * 420
        pts = []
        n = 240
        for i in range(n + 1):
            t = i / n
            x = x0 + (x1 - x0) * t
            if kind == "straight":
                yy = y
            elif kind == "zigzag":
                yy = y + (120 if int(t * 10) % 2 else -120) * (1 - abs((t * 10) % 1 * 2 - 1)) * 2 - 0
                yy = y + 120 * (abs(((t * 10) % 2) - 1) * 2 - 1)
            elif kind == "wave":
                yy = y + 110 * math.sin(t * math.pi * 8)
            elif kind == "curve":
                yy = y + 110 - 220 * abs(math.sin(t * math.pi * 4))
            elif kind == "loop":
                a = t * math.pi * 2 * 7
                x = x0 + (x1 - x0 - 200) * t + 90 * math.cos(a) + 100
                yy = y - 110 * math.sin(a)
            else:
                break
            pts.append((x, yy))
        if kind == "spiral":
            cx, cy = (r % 3) * 700 + M + 330, 900 + (r // 3) * 1150
            pts = [(cx + 18 * a * math.cos(a), cy + 18 * a * math.sin(a)) for a in np.linspace(0.5, 6 * math.pi, 400)]
        _dotted(d, pts)
        _start(d, *pts[0])
    return img


def v2_art(book: str, k: int):
    """A picture already drawn for a v2 book (data/products/<book>/v2/art_XX.png, k from 0), or None. The tracing
    workbook borrows the Fun Alphabet animals and the counting-book objects: no extra drawing (18 Nov)."""
    from .books_v2 import PROD as P2
    f = P2 / book / "v2" / f"art_{k + 1:02d}.png"
    return Image.open(f).convert("L") if f.exists() else None


def _ink_paste(img: Image.Image, art: Image.Image, box: tuple[int, int], xy: tuple[int, int]) -> None:
    """Paste black-on-white line art onto an RGB page (only the lines, in the page's ink colour)."""
    from PIL import ImageFilter
    a = art.copy()
    shrink = min(box[0] / a.width, box[1] / a.height)
    a.thumbnail(box, Image.LANCZOS)
    a = a.point(lambda v: 0 if v < 215 else 255)                 # shrunk lines stay solid, not grey
    if shrink < 0.35:
        a = a.filter(ImageFilter.MinFilter(3))                   # and thick enough to see on small copies
    mask = a.point(lambda v: 255 - v)
    img.paste(INK, (xy[0] + (box[0] - a.width) // 2, xy[1] + (box[1] - a.height) // 2,
                    xy[0] + (box[0] - a.width) // 2 + a.width, xy[1] + (box[1] - a.height) // 2 + a.height), mask)


def letter_page(ch: str) -> Image.Image:
    from .book_specs import ALPHABET
    up = ch.isupper()
    k = ord(ch.upper()) - 65
    art = v2_art("fun_alphabet", k)
    word = ALPHABET[k][1] if art is not None else WORDS[ch.upper()]
    img, d = _page(f"{ch.upper()}{ch.lower()}" if up else f"{ch.lower()}", f"{ch.upper()} is for {word}")
    _trace_text(img, ch, M + 60, 520, 900)                      # one giant letter to trace
    if art is not None:                                         # the Fun Alphabet animal, ready to colour
        _ink_paste(img, art, (820, 820), (PW - M - 860, 560))
        return _letter_rows(img, d, ch)
    pic = _pic(PICS.get(ch.upper(), ""), 720) if ch.upper() in PICS else None
    if pic is not None:
        img.paste(pic.convert("RGB"), (PW - M - 800, 640), pic.getchannel("A"))
    else:
        f = _f(150)
        d.text((PW - M - 120 - d.textlength(word, font=f), 900), word, font=f, fill=(200, 205, 215))
    return _letter_rows(img, d, ch)


def _letter_rows(img: Image.Image, d, ch: str) -> Image.Image:
    f = _f(230, "Poppins-ExtraBold.ttf")
    for r in range(4):                                          # rows of letters to trace on handwriting lines
        y = 1650 + r * 380
        _hw_lines(d, y)
        step = 300
        for k in range(7):
            x = M + 40 + k * step
            if k == 0:
                d.text((x, y - 55), ch, font=f, fill=INK)       # a solid model letter first
            else:
                _trace_text(img, ch, x, y - 55, 230, dotted=False)
    return img


def number_page(n: int) -> Image.Image:
    names = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven",
             "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen", "twenty"]
    from .book_specs import NUMBERS
    art = v2_art("numbers_counting", n - 1) if 1 <= n <= len(NUMBERS) else None
    if art is not None:                                         # count real pictures (the counting book's objects)
        from .books_v2 import plural
        img, d = _page(f"Number {n}", f"Trace {names[n]} and count the {plural(n, NUMBERS[n - 1][2])}")
    else:
        img, d = _page(f"Number {n}", f"Trace {names[n]} and count the dots")
    _trace_text(img, str(n), M + 60, 480, 900)
    if art is not None and n:                                   # count real pictures, as big as the space allows
        bx0, by0, bw, bh = PW - M - 1150, 540, 1150, 950
        cols = max(1, math.ceil(math.sqrt(n * bw / bh)))
        rows = math.ceil(n / cols)
        cell = int(min(bw / cols, bh / rows))
        for k in range(n):
            r, c = divmod(k, cols)
            in_row = min(cols, n - r * cols)                     # the last row is centred
            x = bx0 + (bw - in_row * cell) // 2 + c * cell
            y = by0 + (bh - rows * cell) // 2 + r * cell
            _ink_paste(img, art, (int(cell * 0.9), int(cell * 0.9)), (x + int(cell * 0.05), y + int(cell * 0.05)))
    cols = 5
    for k in range(n if art is None else 0):                    # counting dots (no picture yet)
        cx = PW - M - 900 + (k % cols) * 170
        cy = 700 + (k // cols) * 170
        d.ellipse([cx - 55, cy - 55, cx + 55, cy + 55], outline=INK, width=8)
    for r in range(4):
        y = 1650 + r * 380
        _hw_lines(d, y)
        for k in range(7 if n < 10 else 5):
            x = M + 40 + k * (300 if n < 10 else 420)
            if k == 0:
                d.text((x, y - 55), str(n), font=_f(230), fill=INK)
            else:
                _trace_text(img, str(n), x, y - 55, 230, dotted=False)
    return img


def shape_page(shape: str) -> Image.Image:
    img, d = _page(shape.capitalize(), f"Trace the {shape}s, then color them in")

    def pts(cx, cy, s):
        if shape == "circle":
            return [(cx + s * math.cos(a), cy + s * math.sin(a)) for a in np.linspace(0, 2 * math.pi, 120)]
        if shape == "square":
            return [(cx - s, cy - s), (cx + s, cy - s), (cx + s, cy + s), (cx - s, cy + s), (cx - s, cy - s)]
        if shape == "triangle":
            return [(cx, cy - s), (cx + s, cy + s * 0.8), (cx - s, cy + s * 0.8), (cx, cy - s)]
        if shape == "rectangle":
            return [(cx - s * 1.4, cy - s * 0.8), (cx + s * 1.4, cy - s * 0.8), (cx + s * 1.4, cy + s * 0.8),
                    (cx - s * 1.4, cy + s * 0.8), (cx - s * 1.4, cy - s * 0.8)]
        if shape == "star":
            return [(cx + (s if k % 2 == 0 else s * 0.45) * math.cos(-math.pi / 2 + k * math.pi / 5),
                     cy + (s if k % 2 == 0 else s * 0.45) * math.sin(-math.pi / 2 + k * math.pi / 5)) for k in range(11)]
        if shape == "heart":
            return [(cx + s * 0.06 * 16 * math.sin(t) ** 3,
                     cy - s * 0.06 * (13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t)))
                    for t in np.linspace(0, 2 * math.pi, 160)]
        if shape == "oval":
            return [(cx + s * 1.3 * math.cos(a), cy + s * 0.8 * math.sin(a)) for a in np.linspace(0, 2 * math.pi, 120)]
        return [(cx, cy - s), (cx + s * 0.75, cy), (cx, cy + s), (cx - s * 0.75, cy), (cx, cy - s)]   # diamond
    big = pts(PW / 2, 1050, 520)
    _dotted(d, big, every=40, r=9)
    _start(d, *big[0])
    for k in range(6):
        p = pts(M + 330 + (k % 3) * 700, 2050 + (k // 3) * 650, 220)
        _dotted(d, p, every=30, r=6)
        _start(d, *p[0])
    return img


WATCH_URL = "https://hookhouse-media.clipping-system.workers.dev/bloop"
# Owner, 14 Nov: no QR code until the Bloop & Friends channel is live (roadmap). Flip to True then.
WATCH_QR = False


def watch_along_page(what: str = "trace along") -> Image.Image:
    """QR code to our own watch-along videos (KDP allows links to the author's own bonus material). The QR opens a
    page on our site that forwards to the Bloop & Friends channel once it exists (site/bloop.html)."""
    import qrcode
    img, d = _page("Watch Along with Bloop!", f"Ask a grown-up to scan this code and {what} with Bloop")
    q = qrcode.QRCode(box_size=28, border=2)
    q.add_data(WATCH_URL)
    q.make(fit=True)
    qi = q.make_image(fill_color="black", back_color="white").convert("RGB")
    img.paste(qi, ((PW - qi.width) // 2, 700))
    pic = _pic("star", 420)
    if pic is not None:
        img.paste(pic.convert("RGB"), (M, 2350), pic.getchannel("A"))
        img.paste(pic.convert("RGB"), (PW - M - 420, 2350), pic.getchannel("A"))
    f = _f(60)
    t = "Free videos: watch, pause, and practice together!"
    d.text(((PW - d.textlength(t, font=f)) / 2, 700 + qi.height + 80), t, font=f, fill=INK)
    return img


def certificate() -> Image.Image:
    img, d = _page()
    d.rectangle([M, M, PW - M, PH - M], outline=(230, 170, 40), width=30)
    for k, (t, s) in enumerate((("CERTIFICATE", 230), ("OF TRACING", 180))):
        f = _f(s, "Anton-Regular.ttf")
        d.text(((PW - d.textlength(t, font=f)) / 2, 700 + k * 260), t, font=f, fill=(230, 90, 60))
    f = _f(80)
    for k, t in enumerate(("This certifies that", "", "finished the whole workbook!", "Great job!")):
        if t:
            d.text(((PW - d.textlength(t, font=f)) / 2, 1450 + k * 230), t, font=f, fill=INK)
    _hw_lines(d, 1640, M + 300, PW - M - 300, 200)
    return img


# ---------------- Book 2: Color by Number (ages 4-8) ----------------
NAMED = {"Red": (220, 50, 50), "Orange": (245, 140, 40), "Yellow": (250, 210, 50), "Green": (70, 170, 80),
         "Light Green": (160, 215, 110), "Blue": (50, 110, 210), "Light Blue": (130, 200, 240), "Purple": (140, 80, 190),
         "Pink": (240, 140, 180), "Brown": (140, 90, 50), "Gray": (150, 150, 150), "Black": (30, 30, 30),
         "Peach": (250, 205, 170), "White": (250, 250, 250)}


def _nearest(rgb) -> str:
    return min(NAMED, key=lambda n: sum((a - b) ** 2 for a, b in zip(NAMED[n], rgb)))


def _sprites() -> list[tuple[str, np.ndarray]]:
    from .products import _mascot, _objects
    out = [(n.capitalize(), v) for n, v in _objects().items()]
    out += [(n, _mascot(n, 900)) for n in ("Bloop", "Pip", "Mo", "Dee")]
    return out


def cbn_regions(bgra: np.ndarray, size: int, k: int = 5):
    """Split a colored sprite into color regions -> (label image, legend {number: color name}).
    Colors are clustered, mapped to kid color names (crayons), regions under 0.4% of the picture merge away."""
    import cv2
    h, w = bgra.shape[:2]
    s = size / max(h, w)
    img = cv2.resize(bgra, (int(w * s), int(h * s)), interpolation=cv2.INTER_NEAREST)
    alpha = img[..., 3] > 128
    rgb = img[..., [2, 1, 0]][alpha].astype(np.float32)
    k = max(1, min(k, len(np.unique(rgb.astype(int), axis=0))))
    _, lab, centers = cv2.kmeans(rgb, k, None, (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 1.0), 3,
                                 cv2.KMEANS_PP_CENTERS)
    names = [_nearest(c) for c in centers]
    order = list(dict.fromkeys(names))                         # same crayon -> same number
    num_of = {n: i + 1 for i, n in enumerate(order)}
    L = np.zeros(alpha.shape, np.int32)
    L[alpha] = [num_of[names[c]] for c in lab.ravel()]
    L = cv2.medianBlur(L.astype(np.uint8), 5).astype(np.int32)     # smooth speckles
    L[~alpha] = 0
    if "Black" in num_of:                                       # the sprite's own outline: a line, not a color
        L[L == num_of["Black"]] = -1
    # tiny bits (shine, specks, outline crumbs) join the biggest neighbouring color
    area = alpha.sum()
    for _ in range(3):
        for n in [v for v in set(L.ravel().tolist()) if v != 0]:
            cnt, comp = cv2.connectedComponents((L == n).astype(np.uint8))
            for c in range(1, cnt):
                m = comp == c
                if m.sum() >= area * 0.012 and n != -1:
                    continue
                ring = cv2.dilate(m.astype(np.uint8), np.ones((9, 9), np.uint8)).astype(bool) & ~m
                nb = L[ring]
                nb = nb[(nb > 0) & (nb != n)]
                if len(nb):
                    L[m] = np.bincount(nb).argmax()
    L[(L == -1)] = 0
    L[~alpha] = 0
    used = [n for n in range(1, len(order) + 1) if (L == n).any()]
    remap = {old: i + 1 for i, old in enumerate(used)}
    L2 = np.zeros_like(L)
    for old, new in remap.items():
        L2[L == old] = new
    L2[alpha & (L2 == 0)] = 0
    return L2, {remap[o]: order[o - 1] for o in used}


def cbn_page(title: str, bgra: np.ndarray, colored: bool = False) -> tuple[Image.Image, dict]:
    import cv2
    named = title.split()[0] in ("Bloop", "Pip", "Mo", "Dee")       # names take no "the"
    img, d = _page((f"Color {title}!" if named else f"Color the {title}!") if not colored else title)
    wide = bgra.shape[1] > 1.3 * bgra.shape[0]
    L, legend = cbn_regions(bgra, 2050 if wide else 1700)
    edges = np.zeros(L.shape, bool)
    edges[:-1] |= L[:-1] != L[1:]
    edges[:, :-1] |= L[:, :-1] != L[:, 1:]
    edges = cv2.dilate(edges.astype(np.uint8), np.ones((7, 7), np.uint8)) > 0
    canvas = np.full(L.shape + (3,), 255, np.uint8)
    if colored:
        for n, name in legend.items():
            canvas[L == n] = NAMED[name]
    canvas[edges] = (30, 30, 30)
    pic = Image.fromarray(canvas)
    ox, oy = (PW - pic.width) // 2, 420
    img.paste(pic, (ox, oy))
    d = ImageDraw.Draw(img)
    if not colored:
        f = _f(52)
        for n in legend:
            cnt, comp = cv2.connectedComponents((L == n).astype(np.uint8))
            for c in range(1, cnt):
                m = comp == c
                if m.sum() < L.size * 0.004:
                    continue
                dist = cv2.distanceTransform(m.astype(np.uint8), cv2.DIST_L2, 5)
                y, x = np.unravel_index(dist.argmax(), dist.shape)
                if dist[y, x] < 18:
                    continue
                t = str(n)
                d.text((ox + x - d.textlength(t, font=f) / 2, oy + y - 34), t, font=f, fill=INK)
        ly = PH - 560                                            # the color key
        x = M
        for n, name in legend.items():
            d.rounded_rectangle([x, ly, x + 90, ly + 90], 18, fill=NAMED[name], outline=INK, width=4)
            d.text((x + 110, ly + 14), f"{n} = {name}", font=_f(48), fill=INK)
            x += 110 + d.textlength(f"{n} = {name}", font=_f(48)) + 70
            if x > PW - M - 400:
                x, ly = M, ly + 120
    return img, legend


def _pair(a: np.ndarray, b: np.ndarray, gap: int = 40) -> np.ndarray:
    """Two sprites side by side on one transparent canvas (a little scene), same height."""
    import cv2
    h = 600
    a = cv2.resize(a, (int(a.shape[1] * h / a.shape[0]), h), interpolation=cv2.INTER_NEAREST)
    hb = int(h * 0.7)
    b = cv2.resize(b, (int(b.shape[1] * hb / b.shape[0]), hb), interpolation=cv2.INTER_NEAREST)
    out = np.zeros((h, a.shape[1] + gap + b.shape[1], 4), np.uint8)
    out[:, :a.shape[1]] = a
    out[h - hb:, a.shape[1] + gap:] = b
    return out


def color_by_number(log=print) -> Path:
    folder = OUT / "color_by_number"
    folder.mkdir(parents=True, exist_ok=True)
    sprites = _sprites()
    pages = [_cbn_cover(sprites)]
    pages.append(owner_page())
    if WATCH_QR:
        pages.append(watch_along_page("color along"))
    key = []
    for name, spr in sprites:                                   # 12 single pictures
        pages.append(cbn_page(name, spr)[0])
        key.append((name, spr))
    chars = [x for x in sprites if x[0] in ("Bloop", "Pip", "Mo", "Dee")]
    things = [x for x in sprites if x[0] not in ("Bloop", "Pip", "Mo", "Dee")]
    for k in range(12):                                         # 12 different two-picture scenes (no repeats)
        (cn, cs), (tn, ts) = chars[k % len(chars)], things[(k * 3) % len(things)]
        scene = _pair(cs, ts)
        title = f"{cn} and the {tn}"
        pages.append(cbn_page(title, scene)[0])
        key.append((title, scene))
    pages.append(_page("Answer Key", "Peek here only after you finish!")[0])
    for name, spr in key:
        pages.append(cbn_page(f"{name} (colored)", spr, colored=True)[0])
    pages.append(certificate())
    if len(pages) % 2:
        pages.append(_page("My Own Drawing")[0])
    pages = decorate(pages, "Bloop & Friends Color by Number", skip_first=1)
    pdf = folder / "Color_by_Number_Ages_4-8.pdf"
    pages[0].save(pdf, save_all=True, append_images=pages[1:], resolution=300)
    info = {"title": "Bloop & Friends Color by Number: Fun Coloring Activity Book for Kids Ages 4-8",
            "files": [pdf.name], "pages": len(pages), "price_usd": "$4", "price_inr": "₹99",
            "description": f"{len(sprites) * 2} cheerful pictures to color by number (12 friends and things, 12 little scenes), a color key on "
                           "every page, an answer key and a certificate.",
            "stores": ["Amazon KDP", "Payhip", "Gumroad"], "channel": "bloop_and_friends",
            "tags": ["color by number for kids", "coloring book ages 4-8", "kids activity book", "color by number",
                     "learn colors", "preschool coloring", "kindergarten activity book"]}
    (folder / "product.json").write_text(json.dumps(info, indent=1, ensure_ascii=False), encoding="utf-8")
    log(f"  color by number ({len(pages)} pages) -> {folder}")
    return folder


def _cbn_cover(sprites) -> Image.Image:
    img, d = _page()
    d.rectangle([0, 0, PW, PH], fill=(235, 246, 255))
    for k, (txt, size, col) in enumerate((("COLOR", 300, (230, 90, 60)), ("BY NUMBER", 260, (40, 140, 200)))):
        f = _f(size, "Anton-Regular.ttf")
        d.text(((PW - d.textlength(txt, font=f)) / 2, 380 + k * 330), txt, font=f, fill=col)
    f = _f(70)
    t = "Bloop & Friends  |  Ages 4-8"
    d.text(((PW - d.textlength(t, font=f)) / 2, 1080), t, font=f, fill=INK)
    page, _ = cbn_page("Bloop", dict(sprites)["Bloop"], colored=True)
    thumb = page.crop((M, 400, PW - M, 2300)).resize((1400, 1330))
    img.paste(thumb, ((PW - 1400) // 2, 1300))
    return img


# ---------------- Book 3: Large Print Word Search for Seniors, Nostalgia Edition ----------------
EASY_DIRS = [(0, 1), (1, 0), (1, 1)]                            # seniors: forward, down, diagonal down only


def _ws_grid(words: list[str], size: int, seed: int):
    import random
    rng = random.Random(seed)
    grid = [[""] * size for _ in range(size)]
    where = {}
    for w in sorted(words, key=len, reverse=True):
        for _ in range(2000):
            dr, dc = rng.choice(EASY_DIRS)
            r0, c0 = rng.randrange(size), rng.randrange(size)
            cells = [(r0 + dr * k, c0 + dc * k) for k in range(len(w))]
            if all(0 <= r < size and 0 <= c < size and grid[r][c] in ("", w[k]) for k, (r, c) in enumerate(cells)):
                for k, (r, c) in enumerate(cells):
                    grid[r][c] = w[k]
                where[w] = cells
                break
    letters = "ABCDEFGHIJKLMNOPRSTUVWY"
    for r in range(size):
        for c in range(size):
            if not grid[r][c]:
                grid[r][c] = rng.choice(letters)
    return grid, where


def _ws_draw(img, grid, where, x0, y0, side, solution=False):
    d = ImageDraw.Draw(img)
    n = len(grid)
    cell = side / n
    if solution:
        for cells in where.values():
            (r0, c0), (r1, c1) = cells[0], cells[-1]
            d.line([(x0 + (c0 + .5) * cell, y0 + (r0 + .5) * cell), (x0 + (c1 + .5) * cell, y0 + (r1 + .5) * cell)],
                   fill=(255, 214, 102), width=int(cell * 0.7))
    f = _f(int(cell * 0.62))
    for r in range(n):
        for c in range(n):
            ch = grid[r][c]
            d.text((x0 + c * cell + (cell - d.textlength(ch, font=f)) / 2, y0 + r * cell + cell * 0.1), ch, font=f, fill=INK)
    d.rectangle([x0 - 15, y0 - 15, x0 + side + 15, y0 + side + 15], outline=INK, width=6)


def seniors_puzzle_page(i: int, theme: str, words: list[str]):
    """One large-print puzzle (14 x 14, easy directions, tick boxes). Returns (page, (theme, grid, where))."""
    words = [w for w in words if len(w) <= 13][:12]
    grid, where = _ws_grid(words, 14, seed=100 + i)
    img, d = _page(f"{i + 1}. {theme}")
    side = PW - 2 * M - 100
    _ws_draw(img, grid, where, M + 50, 420, side)
    f = _f(66)
    for k, w in enumerate(sorted(where)):
        col, row = k % 3, k // 3
        x = M + 40 + col * (PW - 2 * M) / 3
        y = 420 + side + 70 + row * 95
        d.rectangle([x, y + 18, x + 46, y + 64], outline=INK, width=4)
        d.text((x + 70, y), w, font=f, fill=INK)
    return img, (theme, grid, where)


def seniors_answer_pages(sols: list) -> list[Image.Image]:
    out = []
    for k in range(0, len(sols), 4):                            # answers: 4 per page
        img, d = _page("Answers")
        for j, (theme, grid, where) in enumerate(sols[k:k + 4]):
            x0 = M + (j % 2) * ((PW - 2 * M) / 2) + 40
            y0 = 520 + (j // 2) * 1300
            d.text((x0, y0 - 100), f"{k + j + 1}. {theme}", font=_f(50), fill=INK)
            _ws_draw(img, grid, where, x0, y0, (PW - 2 * M) / 2 - 120, solution=True)
        out.append(img)
    return out


def seniors_word_search(log=print) -> Path:
    from .nostalgia_words import THEMES
    folder = OUT / "seniors_word_search"
    folder.mkdir(parents=True, exist_ok=True)
    cover, d = _page()
    d.rectangle([0, 0, PW, PH], fill=(250, 244, 230))
    for k, (t, s, c) in enumerate((("LARGE PRINT", 200, (150, 60, 40)), ("WORD SEARCH", 260, INK),
                                   ("NOSTALGIA EDITION", 150, (40, 110, 140)))):
        f = _f(s, "Anton-Regular.ttf")
        d.text(((PW - d.textlength(t, font=f)) / 2, 600 + k * 300), t, font=f, fill=c)
    t = "50 Easy-to-Read Puzzles from the Good Old Days"
    d.text(((PW - d.textlength(t, font=_f(70))) / 2, 1650), t, font=_f(70), fill=INK)
    pages = [cover]
    how, d = _page("How to Play")
    for k, t in enumerate(["Find each word from the list in the grid.", "Words go across, down, or diagonally down.",
                           "No backwards words: easy on the eyes.", "Circle each word, then tick it off the list.",
                           "Answers are at the back of the book."]):
        d.text((M + 60, 700 + k * 170), "•  " + t, font=_f(76), fill=INK)
    pages.append(how)
    sols = []
    for i, (theme, words) in enumerate(THEMES.items()):
        img, sol = seniors_puzzle_page(i, theme, words)
        pages.append(img)
        sols.append(sol)
    pages += seniors_answer_pages(sols)
    if len(pages) % 2:
        pages.append(_page("Notes")[0])
    pages = decorate(pages, "Large Print Word Search: Nostalgia Edition", rate=False, skip_first=1)
    pdf = folder / "Large_Print_Word_Search_Nostalgia.pdf"
    pages[0].save(pdf, save_all=True, append_images=pages[1:], resolution=300)
    info = {"title": "Large Print Word Search for Seniors: Nostalgia Edition", "files": [pdf.name], "pages": len(pages),
            "price_usd": "$5", "price_inr": "₹129", "channel": "",
            "description": "50 large-print word search puzzles from the good old days, one per page, easy directions, "
                           "answers at the back.",
            "stores": ["Amazon KDP", "Payhip", "Gumroad"],
            "tags": ["large print word search", "word search for seniors", "nostalgia puzzles", "puzzle book adults"]}
    (folder / "product.json").write_text(json.dumps(info, indent=1, ensure_ascii=False), encoding="utf-8")
    log(f"  seniors word search ({len(pages)} pages) -> {folder}")
    return folder


# ---------------- Book 4: Kids Activity Book (ages 4-8) ----------------
KID_WS = {"Animals": ["CAT", "DOG", "COW", "PIG", "HEN", "FOX", "OWL", "BEE"],
          "Fruit": ["APPLE", "PEAR", "PLUM", "LIME", "KIWI", "FIG", "GRAPE", "MANGO"],
          "Colors": ["RED", "BLUE", "PINK", "GREEN", "GOLD", "TAN", "GRAY", "BLACK"],
          "Space": ["SUN", "MOON", "STAR", "MARS", "COMET", "ORBIT", "ROCKET", "SKY"],
          "Ocean": ["FISH", "CRAB", "SHELL", "WAVE", "SEAL", "WHALE", "SAND", "BOAT"],
          "Weather": ["RAIN", "SNOW", "WIND", "SUNNY", "CLOUD", "STORM", "FOG", "HAIL"],
          "Food": ["CAKE", "RICE", "SOUP", "BREAD", "MILK", "PIZZA", "TACO", "EGG"],
          "School": ["BOOK", "PEN", "DESK", "BELL", "BAG", "MATH", "ART", "CLASS"],
          "Body": ["HAND", "FOOT", "NOSE", "EYES", "EARS", "KNEE", "HAIR", "TOES"],
          "Shapes": ["CIRCLE", "SQUARE", "STAR", "HEART", "OVAL", "CUBE", "CONE", "LINE"]}


def _dot_to_dot(name: str, bgra: np.ndarray, n_dots: int = 30) -> Image.Image:
    import cv2
    img, d = _page(f"Connect the Dots: {name}", "Join the dots from 1 to the end, then color it in")
    a = (bgra[..., 3] > 128).astype(np.uint8)
    cnts, _ = cv2.findContours(a, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    c = max(cnts, key=cv2.contourArea)[:, 0, :].astype(float)
    idx = np.linspace(0, len(c) - 1, n_dots, endpoint=False).astype(int)
    pts = c[idx]
    h, w = a.shape
    s = 1700 / max(h, w)
    ox, oy = (PW - w * s) / 2, 520 + (1900 - h * s) / 2
    f = _f(40)
    for k, (x, y) in enumerate(pts):
        X, Y = ox + x * s, oy + y * s
        d.ellipse([X - 11, Y - 11, X + 11, Y + 11], fill=INK)
        d.text((X + 16, Y - 48), str(k + 1), font=f, fill=INK)
    return img


def _spot_scene(rng, items, n=5):
    """A row-by-row scene of line-art things; returns [(name, x, y, size)]."""
    out = []
    for k in range(n):
        out.append((rng.choice(items), (k % 3) * 0.33 + 0.05 + rng.random() * 0.05, (k // 3) * 0.45 + 0.05, 0.26))
    return out


def _spot_page(seed: int) -> tuple[Image.Image, Image.Image]:
    import random
    rng = random.Random(seed)
    names = ["apple", "ball", "balloon", "cupcake", "duck", "fish", "flower", "star"]
    scene = _spot_scene(rng, names, 6)
    changed = scene[:]
    diffs = rng.sample(range(len(scene)), 5)
    for i in diffs:                                             # each difference: a different thing in that spot
        nm, x, y, sz = changed[i]
        changed[i] = (rng.choice([o for o in names if o != nm]), x, y, sz)

    def draw(sc, title, circles=False):
        img, d = _page(title, "Find 5 differences between the two pictures")
        for half, box_y in ((0, 480), (1, 1820)):
            d.rounded_rectangle([M, box_y, PW - M, box_y + 1220], 40, outline=INK, width=6)
            for k, (nm, x, y, sz) in enumerate(sc[half]):
                pic = _pic(nm, int(380))
                if pic is not None:
                    X, Y = int(M + 60 + x * (PW - 2 * M - 120)), int(box_y + 60 + y * 1100)
                    img.paste(pic.convert("RGB"), (X, Y), pic.getchannel("A"))
                    if circles and half == 1 and k in diffs:
                        d.ellipse([X - 30, Y - 30, X + 410, Y + 410], outline=(230, 60, 60), width=10)
        return img
    return draw((scene, changed), "Spot the Difference"), draw((scene, changed), "Spot the Difference: Answer", True)


def activity_book(log=print) -> Path:
    from .digital_products import _maze_draw, maze, maze_path
    folder = OUT / "activity_book"
    folder.mkdir(parents=True, exist_ok=True)
    cover, d = _page()
    d.rectangle([0, 0, PW, PH], fill=(235, 250, 240))
    for k, (t, s, c) in enumerate((("BIG FUN", 260, (230, 90, 60)), ("ACTIVITY BOOK", 230, (40, 140, 90)))):
        f = _f(s, "Anton-Regular.ttf")
        d.text(((PW - d.textlength(t, font=f)) / 2, 500 + k * 300), t, font=f, fill=c)
    t = "Mazes · Dot to Dot · Spot the Difference · Word Search · Coloring  |  Ages 4-8"
    d.text(((PW - d.textlength(t, font=_f(54))) / 2, 1200), t, font=_f(54), fill=INK)
    pages, answers = [cover, owner_page()], []
    sprites = _sprites()
    for k in range(12):                                         # mazes, easy -> harder
        n = 6 + k
        cells = maze(n, n, seed=500 + k)
        img, d = _page(f"Maze {k + 1}", "Help Bloop find the way from START to FINISH")
        side = PW - 2 * M - 100
        _maze_draw(d, cells, M + 50, 520, side, side, width=8)
        d.text((M + 50, 440), "START", font=_f(48), fill=(40, 170, 120))
        d.text((PW - M - 260, 520 + side + 20), "FINISH", font=_f(48), fill=(230, 90, 60))
        pages.append(img)
        sol, d2 = _page(f"Maze {k + 1}: Answer")
        _maze_draw(d2, cells, M + 50, 520, side, side, path=maze_path(cells), width=8)
        answers.append(sol)
    for name, spr in sprites:                                   # dot to dot
        pages.append(_dot_to_dot(name, spr, 24 if name in ("Bloop", "Pip", "Mo", "Dee") else 20))
    for k in range(8):                                          # spot the difference
        q, a = _spot_page(900 + k)
        pages.append(q)
        answers.append(a)
    for i, (theme, words) in enumerate(KID_WS.items()):         # word search, kid sized
        grid, where = _ws_grid(words, 10, seed=300 + i)
        img, d = _page(f"Word Search: {theme}", "Words go across, down or diagonally")
        side = PW - 2 * M - 300
        _ws_draw(img, grid, where, M + 150, 520, side)
        for k, w in enumerate(sorted(where)):
            d.text((M + 150 + (k % 4) * 500, 520 + side + 90 + (k // 4) * 110), w, font=_f(70), fill=INK)
        pages.append(img)
        sol = Image.new("RGB", (PW, PH), "white")
        ImageDraw.Draw(sol).text((M, M), f"Word Search: {theme} (answer)", font=_f(90), fill=INK)
        _ws_draw(sol, grid, where, M + 150, 520, side, solution=True)
        answers.append(sol)
    for name, spr in sprites:                                   # coloring pages
        img, d = _page(f"Color {name}!" if name in ("Bloop", "Pip", "Mo", "Dee") else f"Color the {name}!")
        art = _pic(name.lower(), 1600) if name.lower() in PICS.values() or name.lower() in (
            "balloon", "flower") else None
        if art is None:
            from .products import line_art
            art = line_art(spr, 1600, thick=10)
        img.paste(art.convert("RGB"), ((PW - art.width) // 2, 600), art.getchannel("A"))
        pages.append(img)
    pages.append(_page("Answers", "No peeking until you've tried!")[0])
    pages += answers
    pages.append(certificate())
    if len(pages) % 2:
        pages.append(_page("My Own Drawing")[0])
    pages = decorate(pages, "Big Fun Activity Book", skip_first=1)
    pdf = folder / "Activity_Book_Ages_4-8.pdf"
    pages[0].save(pdf, save_all=True, append_images=pages[1:], resolution=300)
    info = {"title": "Big Fun Activity Book for Kids Ages 4-8", "files": [pdf.name], "pages": len(pages),
            "price_usd": "$5", "price_inr": "₹129", "channel": "bloop_and_friends",
            "description": "Mazes, dot-to-dot, spot the difference, word search and coloring with answers.",
            "stores": ["Amazon KDP", "Payhip", "Gumroad"],
            "tags": ["activity book for kids 4-8", "mazes for kids", "dot to dot", "spot the difference", "word search kids"]}
    (folder / "product.json").write_text(json.dumps(info, indent=1, ensure_ascii=False), encoding="utf-8")
    log(f"  activity book ({len(pages)} pages) -> {folder}")
    return folder


def tracing(log=print) -> Path:
    folder = OUT / "tracing_workbook"
    folder.mkdir(parents=True, exist_ok=True)
    pages = [cover_page(), owner_page()] + ([watch_along_page("trace along")] if WATCH_QR else [])
    pages += [pen_control(k) for k in ("straight", "zigzag", "wave", "curve", "loop", "spiral")]
    pages += [letter_page(c) for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"]
    pages += [letter_page(c) for c in "abcdefghijklmnopqrstuvwxyz"]
    pages += [number_page(n) for n in range(21)]
    pages += [shape_page(s) for s in ("circle", "square", "triangle", "rectangle", "oval", "diamond", "star", "heart")]
    pages.append(certificate())
    if len(pages) % 2:
        pages.append(_page("Notes & Practice")[0])
    pages = decorate(pages, "My First Tracing Workbook", skip_first=2)
    pdf = folder / "Tracing_Workbook_Ages_3-5.pdf"
    pages[0].save(pdf, save_all=True, append_images=pages[1:], resolution=300)
    info = {"title": "My First Tracing Workbook: Letters, Numbers, Shapes & Pen Control for Ages 3-5",
            "files": [pdf.name], "pages": len(pages), "price_usd": "$5", "price_inr": "₹129",
            "description": "A first tracing workbook for ages 3-5: pen-control lines, A-Z capitals and lowercase on "
                           "handwriting lines, numbers 0-20 with counting dots, 8 shapes and a certificate.",
            "stores": ["Amazon KDP", "Payhip", "Gumroad"], "channel": "bloop_and_friends",
            "tags": ["tracing workbook", "preschool workbook", "handwriting practice", "letter tracing",
                     "number tracing", "pre k workbook", "kindergarten prep"]}
    (folder / "product.json").write_text(json.dumps(info, indent=1, ensure_ascii=False), encoding="utf-8")
    log(f"  tracing workbook ({len(pages)} pages) -> {folder}")
    return folder


if __name__ == "__main__":
    {"tracing": tracing, "cbn": color_by_number, "seniors": seniors_word_search, "activity": activity_book}[sys.argv[1] if len(sys.argv) > 1 else "tracing"]()
