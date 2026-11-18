"""Big Fun Activity Book v2 (owner 17 Nov: the old books are boring and repetitive; 18 Nov: "attractive, not
repetitive, varied characters ... we are not fixed to Bloop").

The old activity book (kdp_books.activity_book) reused the same 8 procedural sprites on every page. Now every
activity is built from its own FLUX line art (bookart.page, checked and cleaned), so no two pages look alike:
- mazes: a character at START and the thing it wants at FINISH, getting harder through the book
- dot to dot: the picture's own outline becomes numbered dots; the details inside stay as lines
- spot the difference: a scene and a copy with 5 changes made by code (small details removed, little shapes added)
- word search: themed words next to a picture of the same theme
Answers at the back. Pictures are cached in data/products/<id>/v2/act_XX.png; the night worker draws them in
small steps like every other book (books_v2.night_job)."""
from __future__ import annotations

import json
import math
import random

import numpy as np
from PIL import Image, ImageDraw

from . import bookart
from .books_v2 import (DPI, PH, PROD, PW, STORE_URL, _blank, _center, _rgb, back_cover, bonus_page, certificate_page,
                       font, front_cover, owner_page, thanks_page, title_page)

M = 225                                                   # 0.75 in margin
BODY = "Poppins-ExtraBold.ttf"
SMALL = (1000, 1000)                                       # maze START / FINISH pictures
SCENE = (2100, 1250)                                       # spot the difference: two of these on a page
DOTS = (2000, 2300)


def pictures(spec: dict) -> list[tuple[str, str, tuple[int, int], str]]:
    """Every picture the book needs, in drawing order: (key, subject, page_px, check). Keys stay stable when the
    lists grow. Single simple objects use the toddler check (few areas by design); scenes the kids check."""
    out = []
    for k, (who, goal, _) in enumerate(spec["mazes"]):
        out.append((f"maze{k}_start", f"one single cute {who}, whole body, isolated", SMALL, "toddler"))
        out.append((f"maze{k}_goal", f"one single {goal}, isolated, nothing else", SMALL, "toddler"))
    for k, subj in enumerate(spec["dots"]):
        out.append((f"dots{k}", f"one single {subj}, simple bold outline, whole body, isolated", DOTS, "toddler"))
    for k, subj in enumerate(spec["spot"]):
        out.append((f"spot{k}", f"{subj}, wide scene, a few big simple objects", SCENE, "kids"))
    return out


# ---------------- page makers ----------------
def _head(d: ImageDraw.ImageDraw, title: str, sub: str = "") -> None:
    _center(d, M - 60, title, font(120))
    if sub:
        _center(d, M + 95, sub, font(54, BODY), fill=(90, 90, 90) if d.mode == "RGB" else 90)


def _fit(art: Image.Image, box: tuple[int, int]) -> Image.Image:
    f = min(box[0] / art.width, box[1] / art.height)
    return art.resize((max(1, int(art.width * f)), max(1, int(art.height * f))), Image.LANCZOS)


def maze_page(cells, who: str, goal: str, start: Image.Image | None, finish: Image.Image | None,
              path=None) -> Image.Image:
    from .digital_products import _maze_draw
    p = _blank().convert("RGB")                           # _maze_draw draws in RGB
    d = ImageDraw.Draw(p)
    title = f"Help the {who} find the {goal}!" if path is None else f"Answer: the {who} and the {goal}"
    f = font(110)
    while d.textlength(title, font=f) > PW - 2 * M and f.size > 60:
        f = font(f.size - 6)
    _center(d, M - 60, title, f)
    pic = 560
    x0, y0 = M + 40, M + 140 + pic - 60                   # the maze sits between the two pictures
    side_w, side_h = PW - 2 * M - 80, PH - y0 - pic - 40
    _maze_draw(d, cells, x0, y0, side_w, side_h, path=path, width=10)
    for art, xy in ((start, (M - 20, M + 120)), (finish, (PW - M - pic + 20, y0 + side_h + 10))):
        if art is not None:
            a = _fit(art, (pic, pic))
            p.paste(a.convert("RGB"), (xy[0] + (pic - a.width) // 2, xy[1] + (pic - a.height) // 2),
                    a.point(lambda v: 255 - v))
    fs = font(60, BODY)
    d.text((M + 40 + pic, y0 - 90), "START", font=fs, fill=0)
    d.text((PW - M - pic - 280, y0 + side_h + 40), "FINISH", font=fs, fill=0)
    return p


def _outside(fig: np.ndarray, x: float, y: float) -> bool:
    h, w = fig.shape
    xi, yi = int(round(x)), int(round(y))
    return not (0 <= xi < w and 0 <= yi < h) or not fig[yi, xi]


def dot_points(art: Image.Image, n: int) -> tuple[list[tuple[float, float]], np.ndarray]:
    """The picture's outer outline as n points evenly spaced along it (clockwise from the top), plus the figure mask."""
    import cv2
    ink = (np.asarray(art.convert("L")) < 128).astype(np.uint8)
    h, w = ink.shape
    flood = ink.copy() * 255
    mask = np.zeros((h + 2, w + 2), np.uint8)
    cv2.floodFill(flood, mask, (0, 0), 128)                      # background reached from the corner
    fig = (flood != 128).astype(np.uint8)                        # lines + everything they enclose
    cnts, _ = cv2.findContours(fig, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    c = max(cnts, key=cv2.contourArea)[:, 0, :].astype(float)
    # furry / sketchy outlines are long and jagged: dots bunched up there (preview 18 Nov). Smooth the outline first
    # (circular Gaussian, ~1/150 of its length) so equal steps along it are equal steps on the page.
    sigma = max(3.0, len(c) / 150)
    r = int(3 * sigma)
    kern = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2)
    kern /= kern.sum()
    c = np.stack([np.convolve(np.r_[c[-r:, i], c[:, i], c[:r, i]], kern, mode="valid") for i in (0, 1)], axis=1)
    seg = np.r_[0, np.cumsum(np.hypot(*np.diff(np.vstack([c, c[:1]]), axis=0).T))]
    total = seg[-1]
    start = int(np.argmin(c[:, 1]))                               # dot 1 at the top
    seg_from = (seg[:-1] - seg[start]) % total
    order = np.argsort(seg_from)
    targets = np.linspace(0, total, n, endpoint=False)
    idx = order[np.searchsorted(seg_from[order], targets).clip(0, len(order) - 1)]
    return [tuple(c[i]) for i in idx], fig


def dots_page(art: Image.Image, name: str, n: int) -> Image.Image:
    """Numbered dots on the outline; the outline itself is erased, inner details are kept for colouring after."""
    import cv2
    pts, fig = dot_points(art, n)
    a = np.asarray(art.convert("L")).copy()
    band = cv2.erode(fig, np.ones((3, 3), np.uint8), iterations=18)   # keep only lines inside the outline
    a[band == 0] = 255
    p = _blank()
    d = ImageDraw.Draw(p)
    _head(d, f"Connect the dots: {name}", f"Join the dots from 1 to {n}, then color it in")
    ox, oy = (PW - art.width) // 2, M + 280
    p.paste(Image.fromarray(a, "L"), (ox, oy))
    f = font(46, BODY)
    placed: list[tuple[float, float, float, float]] = []
    for k, (x, y) in enumerate(pts):
        X, Y = ox + x, oy + y
        d.ellipse([X - 12, Y - 12, X + 12, Y + 12], fill=0)
        px, py = pts[k - 1], pts[(k + 1) % n]
        nx, ny = -(py[1] - px[1]), py[0] - px[0]               # normal to the outline at this dot
        ln = math.hypot(nx, ny) or 1
        nx, ny = nx / ln, ny / ln
        if not _outside(fig, x + nx * 30, y + ny * 30):        # numbers go on the outside of the shape
            nx, ny = -nx, -ny
        label = str(k + 1)
        tw = d.textlength(label, font=f)
        for off in (46, 80, 115, 150):                          # push out until it clears the labels so far
            bx = (X + nx * off - tw / 2, Y + ny * off - 30)
            box = (bx[0] - 6, bx[1] + 6, bx[0] + tw + 6, bx[1] + 56)
            if not any(box[0] < b[2] and b[0] < box[2] and box[1] < b[3] and b[1] < box[3] for b in placed):
                break
        placed.append(box)
        d.text(bx, label, font=f, fill=0)
    if n:
        X, Y = ox + pts[0][0], oy + pts[0][1]
        d.ellipse([X - 22, Y - 22, X + 22, Y + 22], outline=0, width=6)        # a ring marks where to start
    return p


SHAPES = ("star", "heart", "circle", "triangle")


def _shape(d: ImageDraw.ImageDraw, kind: str, cx: float, cy: float, r: float, width: int) -> None:
    if kind == "circle":
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=0, fill=255, width=width)
        return
    if kind == "star":
        pts = [(cx + (r if i % 2 == 0 else r * 0.45) * math.sin(i * math.pi / 5),
                cy - (r if i % 2 == 0 else r * 0.45) * math.cos(i * math.pi / 5)) for i in range(10)]
    elif kind == "triangle":
        pts = [(cx, cy - r), (cx + r * 0.95, cy + r * 0.7), (cx - r * 0.95, cy + r * 0.7)]
    else:                                                        # heart
        pts = [(cx + r * 16 * math.sin(t) ** 3 / 17,
                cy - r * (13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t)) / 17)
               for t in np.linspace(0, 2 * math.pi, 60)]
    d.polygon(pts, outline=0, fill=255, width=width)


def differences(art: Image.Image, n: int = 5, seed: int = 0) -> tuple[Image.Image, list[tuple[int, int, int]]]:
    """A copy of the scene with n changes: small closed details erased first (eyes, buttons, windows), then little
    shapes added in open white space. Returns (changed picture, [(x, y, radius)] for the answer circles)."""
    import cv2
    rng = random.Random(seed)
    a = np.asarray(art.convert("L")).copy()
    ink = (a < 128).astype(np.uint8)
    h, w = ink.shape
    changes: list[tuple[int, int, int]] = []
    n_lab, lab, st, cen = cv2.connectedComponentsWithStats(ink, connectivity=8)
    lo, hi = 0.0004 * a.size, 0.012 * a.size                     # big enough to spot, small enough not to ruin it
    small = [i for i in range(1, n_lab) if lo <= st[i, cv2.CC_STAT_AREA] <= hi]
    rng.shuffle(small)
    for i in small[:min(3, n - 2)]:
        x, y, bw, bh = st[i, :4]
        if any(math.hypot(x + bw / 2 - cx, y + bh / 2 - cy) < r + max(bw, bh) for cx, cy, r in changes):
            continue
        a[lab == i] = 255
        changes.append((int(x + bw / 2), int(y + bh / 2), int(max(bw, bh) / 2 + 40)))
    out = Image.fromarray(a, "L")
    d = ImageDraw.Draw(out)
    white = (a >= 128).astype(np.uint8)
    white[:30], white[-30:], white[:, :30], white[:, -30:] = 0, 0, 0, 0
    flood = (1 - white) * 255
    flood[:30], flood[-30:], flood[:, :30], flood[:, -30:] = 0, 0, 0, 0
    cv2.floodFill(flood, np.zeros((h + 2, w + 2), np.uint8), (0, 0), 128)
    inside = white * (flood != 128)                               # white areas enclosed by the drawing
    dist_in = cv2.distanceTransform(inside.astype(np.uint8), cv2.DIST_L2, 5)
    dist = cv2.distanceTransform(white, cv2.DIST_L2, 5)
    stroke = max(6, int(round(2 * float(np.median(cv2.distanceTransform(ink, cv2.DIST_L2, 3)[ink > 0]))))) if ink.any() else 8
    tries = 0
    while len(changes) < n and tries < 400:
        tries += 1
        ys, xs = np.nonzero(dist_in > 55)
        if not len(xs) or tries > 250:                            # no room left inside: the background then
            ys, xs = np.nonzero(dist > 55)
        if not len(xs):
            break
        j = rng.randrange(len(xs))
        x, y = int(xs[j]), int(ys[j])
        r = int(min(dist[y, x] * 0.6, 75))
        if r < 32 or any(math.hypot(x - cx, y - cy) < r + cr + 60 for cx, cy, cr in changes):
            continue
        _shape(d, SHAPES[len(changes) % len(SHAPES)], x, y, r, stroke)
        cv2.circle(dist, (x, y), r + 70, 0, -1)
        cv2.circle(dist_in, (x, y), r + 70, 0, -1)
        changes.append((x, y, r + 30))
    return out, changes


def spot_page(art: Image.Image, changed: Image.Image, n: int, circles: list | None = None) -> Image.Image:
    p = _blank().convert("RGB") if circles else _blank()
    d = ImageDraw.Draw(p)
    _head(d, "Spot the difference" + (": answer" if circles else ""),
          f"Find {n} things that are different in the bottom picture")
    top, gap = M + 260, 90
    x0 = (PW - art.width) // 2
    for k, im in enumerate((art, changed)):
        y = top + k * (art.height + gap)
        p.paste(im.convert(p.mode), (x0, y))
        d.rounded_rectangle([x0 - 30, y - 30, x0 + art.width + 30, y + art.height + 30], 36, outline=0, width=8)
    if circles:
        y = top + art.height + gap
        for cx, cy, r in circles:
            d.ellipse([x0 + cx - r, y + cy - r, x0 + cx + r, y + cy + r], outline=(220, 40, 40), width=12)
    return p


def word_search_page(theme: str, words: list[str], seed: int, art: Image.Image | None,
                     solution: bool = False) -> Image.Image:
    from .kdp_books import _ws_draw, _ws_grid
    grid, where = _ws_grid(words, 11, seed=seed)
    p = Image.new("RGB", (PW, PH), "white")
    d = ImageDraw.Draw(p)
    _head(d, f"Word search: {theme}" + (" (answer)" if solution else ""), "Words go across, down or diagonally")
    side = 1750
    gx = (PW - side) // 2
    _ws_draw(p, grid, where, gx, M + 300, side, solution=solution)
    if not solution:
        f = font(66, BODY)
        y = M + 300 + side + 80
        for k, w in enumerate(sorted(where)):
            d.text((M + 60 + (k % 3) * 620, y + (k // 3) * 105), w, font=f, fill=(35, 38, 48))
        if art is not None:
            a = _fit(art, (560, 560))
            p.paste(a.convert("RGB"), (PW - M - a.width + 40, PH - M - a.height + 60), a.point(lambda v: 255 - v))
    return p


# ---------------- the book ----------------
def build_activity(pid: str, log=print, allow_local: bool = True, max_new: int | None = None) -> dict | None:
    """Pictures first (cached, max_new per call), then the PDF + covers. None while pictures are missing."""
    from .book_specs import BOOKS
    from .digital_products import maze, maze_path
    from .kdp import BLEED, TRIM_H, TRIM_W, _px, spine_in
    spec = BOOKS[pid]
    out = PROD / pid
    (out / "v2").mkdir(parents=True, exist_ok=True)
    arts: dict[str, Image.Image] = {}
    used: list[int] = []
    new, missing = 0, False
    for k, (key, subj, px, check) in enumerate(pictures(spec)):
        cached = out / "v2" / f"act_{key}.png"
        if cached.exists():
            arts[key] = Image.open(cached).convert("L")
            continue
        if max_new is not None and new >= max_new:
            missing = True
            continue
        try:
            pg = bookart.page(subj, age=check, seed=spec["seed"] + k * 23, used=used, page_px=px, log=log,
                              allow_local=allow_local)
        except bookart.NoPicture:
            log(f"{pid}: picture quota used up after {new} new picture(s); continuing next time")
            return None
        new += 1
        if pg:
            pg.image.save(cached)
            arts[key] = pg.image
        else:
            log(f"  {key} '{subj[:40]}': no clean drawing after 5 tries (left out)")
    if missing:
        return None
    groups: list[list[Image.Image]] = [[], [], [], []]       # mazes, dots, spot the difference, word search
    answers: list[Image.Image] = []
    for k, (who, goal, size) in enumerate(spec["mazes"]):
        cells = maze(size, max(4, int(size * 0.85)), seed=spec["seed"] + k)
        s, g = arts.get(f"maze{k}_start"), arts.get(f"maze{k}_goal")
        groups[0].append(maze_page(cells, who, goal, s, g))
        answers.append(maze_page(cells, who, goal, s, g, path=maze_path(cells)))
    for k, subj in enumerate(spec["dots"]):
        art = arts.get(f"dots{k}")
        if art is not None:
            groups[1].append(dots_page(art, spec["dot_names"][k], 20 + 2 * k))
    for k, _ in enumerate(spec["spot"]):
        art = arts.get(f"spot{k}")
        if art is None:
            continue
        changed, circles = differences(art, 5, seed=spec["seed"] + k)
        groups[2].append(spot_page(art, changed, len(circles)))
        answers.append(spot_page(art, changed, len(circles), circles))
    for k, (theme, words, pic) in enumerate(spec["word_search"]):
        groups[3].append(word_search_page(theme, words, spec["seed"] + 50 + k, arts.get(pic)))
        answers.append(word_search_page(theme, words, spec["seed"] + 50 + k, None, solution=True))
    hero = arts["dots0"] if "dots0" in arts else next(iter(arts.values()))
    interior = [title_page(spec, hero), owner_page(hero)]
    order = interleave(groups)        # maze, dots, spot, word search, maze ...: never one long worksheet
    interior += order
    head = _blank()
    _center(ImageDraw.Draw(head), PH // 2 - 200, "ANSWERS", font(200))
    _center(ImageDraw.Draw(head), PH // 2 + 60, "No peeking until you've tried!", font(70, BODY), fill=90)
    interior += [head] + answers + [certificate_page(spec["title"]), bonus_page(STORE_URL), thanks_page()]
    if len(interior) % 2:
        interior.append(_blank())
    pdf = out / f"{pid}_v2_interior.pdf"
    interior[0].convert("RGB").save(pdf, save_all=True, append_images=[q.convert("RGB") for q in interior[1:]],
                                    resolution=DPI)
    n = len(interior)
    sp = spine_in(n)
    Wt, Ht = _px(BLEED * 2 + TRIM_W * 2 + sp), _px(BLEED * 2 + TRIM_H)
    half = (_px(BLEED + TRIM_W), Ht)
    extras = [arts[k] for k in ("maze0_start", "dots1", "maze2_start") if k in arts]
    front = front_cover(spec, hero, extras, size=half)
    back = back_cover(spec, [q.convert("L") for q in order[:6]], size=half)
    wrap = Image.new("RGB", (Wt, Ht), _rgb(spec["theme_bg"][1]))
    wrap.paste(back.convert("RGB"), (0, 0))
    wrap.paste(front.convert("RGB"), (Wt - half[0], 0))
    wrap.save(out / "kdp_cover_v2.pdf", resolution=DPI)
    front.convert("RGB").save(out / "cover_v2.jpg", quality=92)
    front.convert("RGB").resize((1280, int(1280 * front.height / front.width))).save(out / "store_cover_v2.jpg", quality=90)
    listing = {"title": spec["title"], "subtitle": spec["subtitle"], "price": spec["price"], "pages": n,
               "designs": len(arts), "trim": "8.5 x 11 in", "interior": pdf.name, "cover": "kdp_cover_v2.pdf",
               "spine_in": sp, "paper": "black & white (answer circles print grey; the Payhip PDF keeps colour)",
               "ai_content": "Yes: the drawings are AI-generated and edited by our code; puzzles made by our code"}
    (out / "kdp_listing_v2.json").write_text(json.dumps(listing, indent=1), encoding="utf-8")
    log(f"{pid}: {len(arts)} pictures, {n} pages -> {pdf.name}")
    return listing


def interleave(groups: list[list]) -> list:
    out, i = [], 0
    while any(groups):
        g = groups[i % len(groups)]
        if g:
            out.append(g.pop(0))
        i += 1
    return out


# ---------------- tracing workbook v2: borrows the alphabet + counting pictures ----------------
def build_tracing(pid: str = "tracing_workbook", log=print, allow_local: bool = True,
                  max_new: int | None = None) -> dict | None:
    """The tracing workbook with the Fun Alphabet animals on the letter pages and the counting-book objects to count
    on the number pages (kdp_books.letter_page / number_page pick them up). Draws nothing itself: waits until both
    books are built (they come earlier in books_v2.QUEUE)."""
    from . import kdp_books
    from .book_specs import BOOKS
    from .kdp import BLEED, TRIM_H, TRIM_W, _px, spine_in
    if not all((PROD / b / "kdp_listing_v2.json").exists() for b in ("fun_alphabet", "numbers_counting")):
        return None
    spec = BOOKS[pid]
    folder = kdp_books.tracing(log)
    info = json.loads((folder / "product.json").read_text(encoding="utf-8"))
    pdf = info["files"][0]
    hero = kdp_books.v2_art("fun_alphabet", 0)
    extras = [a for a in (kdp_books.v2_art("fun_alphabet", 1), kdp_books.v2_art("numbers_counting", 2)) if a is not None]
    n = info["pages"]
    sp = spine_in(n)
    Wt, Ht = _px(BLEED * 2 + TRIM_W * 2 + sp), _px(BLEED * 2 + TRIM_H)
    half = (_px(BLEED + TRIM_W), Ht)
    front = front_cover(spec, hero, extras, size=half)
    thumbs = [a for a in (kdp_books.v2_art("fun_alphabet", k) for k in range(2, 8)) if a is not None]
    back = back_cover(spec, thumbs, size=half)
    wrap = Image.new("RGB", (Wt, Ht), _rgb(spec["theme_bg"][1]))
    wrap.paste(back.convert("RGB"), (0, 0))
    wrap.paste(front.convert("RGB"), (Wt - half[0], 0))
    wrap.save(folder / "kdp_cover_v2.pdf", resolution=DPI)
    front.convert("RGB").save(folder / "cover_v2.jpg", quality=92)
    listing = {"title": spec["title"], "subtitle": spec["subtitle"], "price": spec["price"], "pages": n,
               "trim": "8.5 x 11 in", "interior": pdf, "cover": "kdp_cover_v2.pdf", "spine_in": sp,
               "ai_content": "Yes: the animal/object drawings are AI-generated and edited by our code"}
    (folder / "kdp_listing_v2.json").write_text(json.dumps(listing, indent=1), encoding="utf-8")
    log(f"{pid}: {n} pages -> {pdf}")
    return listing


# ---------------- large-print word search & coloring for seniors ----------------
SENIOR_ART = (2100, 2200)


def memory_page(i: int, theme: str, art: Image.Image | None, prompt: str) -> Image.Image:
    """Left-hand page of each spread: the theme, a calm bold & easy picture to colour, a memory to share."""
    from .books_v2 import _wrap
    p = _blank()
    d = ImageDraw.Draw(p)
    _center(d, M - 60, f"{i + 1}. {theme}", font(110))
    if art is not None:
        a = _fit(art, SENIOR_ART)
        p.paste(a, ((PW - a.width) // 2, M + 140 + (SENIOR_ART[1] - a.height) // 2))
    f = font(70, BODY)
    for k, ln in enumerate(_wrap(prompt, f, PW - 2 * M - 60, d)[:2]):
        _center(d, PH - M - 250 + k * 100, ln, f, fill=0)
    return p


def build_seniors(pid: str = "seniors_word_search", log=print, allow_local: bool = True,
                  max_new: int | None = None) -> dict | None:
    """Two-page spreads (owner 18 Nov: books must be attractive): picture + memory prompt on the left, the
    large-print puzzle on the right. Pictures cached in v2/art_XX.png; None while pictures are missing."""
    from . import kdp_books
    from .book_specs import BOOKS, SENIORS
    from .kdp import BLEED, TRIM_H, TRIM_W, _px, spine_in
    from .nostalgia_words import THEMES
    spec = BOOKS[pid]
    out = PROD / pid
    (out / "v2").mkdir(parents=True, exist_ok=True)
    arts: dict[int, Image.Image] = {}
    used: list[int] = []
    new, missing = 0, False
    for k, (subj, _) in enumerate(SENIORS):
        cached = out / "v2" / f"art_{k + 1:02d}.png"
        if cached.exists():
            arts[k] = Image.open(cached).convert("L")
            continue
        if max_new is not None and new >= max_new:
            missing = True
            continue
        try:
            pg = bookart.page(subj, age="older", seed=spec["seed"] + k * 29, used=used, page_px=SENIOR_ART, log=log,
                              allow_local=allow_local)
        except bookart.NoPicture:
            log(f"{pid}: picture quota used up after {new} new picture(s); continuing next time")
            return None
        new += 1
        if pg:
            pg.image.save(cached)
            arts[k] = pg.image
    if missing or not arts:
        return None
    hero = next(iter(arts.values()))
    how, d = kdp_books._page("How to Play")
    for k, t in enumerate(["Find each word from the list in the grid.", "Words go across, down, or diagonally down.",
                           "No backwards words: easy on the eyes.", "Circle each word, then tick it off the list.",
                           "Color the picture on the left page as you like,", "and share the memory with someone.",
                           "Answers are at the back of the book."]):
        d.text((M + 60, 700 + k * 170), "•  " + t if k != 5 else "    " + t, font=kdp_books._f(70), fill=kdp_books.INK)
    interior = [title_page(spec, hero), how.convert("L"), owner_page(hero)]      # pictures land on left pages
    sols = []
    for i, (theme, words) in enumerate(THEMES.items()):
        page, sol = kdp_books.seniors_puzzle_page(i, theme, words)
        interior += [memory_page(i, theme, arts.get(i), SENIORS[i][1]), page]
        sols.append(sol)
    interior += kdp_books.seniors_answer_pages(sols) + [bonus_page(STORE_URL), thanks_page()]
    if len(interior) % 2:
        interior.append(_blank())
    pdf = out / f"{pid}_v2_interior.pdf"
    interior[0].convert("RGB").save(pdf, save_all=True, append_images=[q.convert("RGB") for q in interior[1:]],
                                    resolution=DPI)
    n = len(interior)
    sp = spine_in(n)
    Wt, Ht = _px(BLEED * 2 + TRIM_W * 2 + sp), _px(BLEED * 2 + TRIM_H)
    half = (_px(BLEED + TRIM_W), Ht)
    front = front_cover(spec, hero, [arts[k] for k in list(arts)[1:4]], size=half)
    back = back_cover(spec, [arts[k] for k in list(arts)[4:10]], size=half)
    wrap = Image.new("RGB", (Wt, Ht), _rgb(spec["theme_bg"][1]))
    wrap.paste(back.convert("RGB"), (0, 0))
    wrap.paste(front.convert("RGB"), (Wt - half[0], 0))
    if n >= 79:                                                   # KDP: spine text from 79 pages
        sf = font(int(_px(sp) * 0.55))
        txt = Image.new("RGBA", (Ht, _px(sp)), (0, 0, 0, 0))
        ImageDraw.Draw(txt).text((200, 4), spec["title"].upper(), font=sf, fill="white")
        rot = txt.rotate(-90, expand=True)
        wrap.paste(rot, (half[0], 0), rot)
    wrap.save(out / "kdp_cover_v2.pdf", resolution=DPI)
    front.convert("RGB").save(out / "cover_v2.jpg", quality=92)
    front.convert("RGB").resize((1280, int(1280 * front.height / front.width))).save(out / "store_cover_v2.jpg", quality=90)
    listing = {"title": spec["title"], "subtitle": spec["subtitle"], "price": spec["price"], "pages": n,
               "designs": len(arts), "trim": "8.5 x 11 in", "interior": pdf.name, "cover": "kdp_cover_v2.pdf",
               "spine_in": sp, "ai_content": "Yes: the drawings are AI-generated and edited by our code"}
    (out / "kdp_listing_v2.json").write_text(json.dumps(listing, indent=1), encoding="utf-8")
    log(f"{pid}: {len(arts)} pictures, {n} pages -> {pdf.name}")
    return listing
