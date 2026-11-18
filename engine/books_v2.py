"""Books v2 (owner, 17 Nov 2026): attractive, trend-following books built from checked AI line art (engine/bookart).

Interior (8.5 x 11 in, 300 dpi, black & white):
  title page -> "This book belongs to" -> colour test page -> designs, each followed by a blank back
  (single-sided: markers don't bleed into the next picture; research: bleed-through is the #1 one-star complaint)
  -> certificate -> free bonus pages (QR to our store) -> thank-you page
Cover (wrap-around, KDP formula): bright background, the hero picture auto-coloured from our own line art,
big kid-friendly title, age badge, three feature chips; back: six real inside pages + description; barcode box.
Also: store cover + thumbnail (Payhip) and kdp_listing.json.
Usage: python -m engine.books_v2 <book id> [--pages N] [--local]"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from . import bookart
from .config import ROOT

PROD = ROOT / "data" / "products"
FONTS = ROOT / "assets" / "fonts"
DPI = 300
PW, PH = 2550, 3300                     # 8.5 x 11 in
ART = (2250, 2700)                      # picture area inside 0.5 in margins (room for the caption)
STORE_URL = "https://payhip.com/HookHouseMedia"
PALETTE = ["#FFD54F", "#FF8A65", "#4FC3F7", "#AED581", "#BA68C8", "#F06292", "#FFB74D", "#81C784", "#64B5F6",
           "#E57373", "#FFF176", "#4DB6AC"]


def font(size: int, name: str = "LuckiestGuy-Regular.ttf") -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS / name), size)


def _rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _blank() -> Image.Image:
    return Image.new("L", (PW, PH), 255)


def _center(d: ImageDraw.ImageDraw, y: int, text: str, f, fill=0, w: int = PW) -> int:
    tw = d.textlength(text, font=f)
    d.text(((w - tw) / 2, y), text, font=f, fill=fill)
    return y + f.size


def design_page(art: Image.Image, caption: str = "") -> Image.Image:
    p = _blank()
    p.paste(art, ((PW - art.width) // 2, 150))
    if caption:                                   # fun-fact books: up to 2 lines under the picture, inside margins
        d = ImageDraw.Draw(p)
        f = font(68, "Poppins-ExtraBold.ttf")
        lines = _wrap(caption, f, PW - 400, d)[:2]
        for i, ln in enumerate(lines):
            _center(d, 2890 + i * 92, ln, f, fill=0)
    return p


def back_page() -> Image.Image:
    p = _blank()
    d = ImageDraw.Draw(p)
    _center(d, PH - 260, "This page is blank so your colors don't bleed onto the next picture.", font(34, "Poppins-ExtraBold.ttf"), fill=150)
    return p


def owner_page(art: Image.Image) -> Image.Image:
    p = _blank()
    d = ImageDraw.Draw(p)
    _center(d, 300, "THIS BOOK BELONGS TO", font(150))
    d.rounded_rectangle((300, 560, PW - 300, 800), radius=60, outline=0, width=12)
    small = art.resize((art.width * 6 // 10, art.height * 6 // 10))
    p.paste(small, ((PW - small.width) // 2, 1000))
    return p


def colour_test_page() -> Image.Image:
    p = _blank()
    d = ImageDraw.Draw(p)
    _center(d, 260, "TEST YOUR COLORS", font(150))
    _center(d, 460, "Try your crayons, pencils and markers here first", font(52, "Poppins-ExtraBold.ttf"), fill=60)
    r, gap = 150, 110
    for row in range(5):
        for col in range(5):
            cx = 330 + col * (2 * r + gap) + r // 2
            cy = 800 + row * (2 * r + gap) + r
            d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=0, width=10)
    return p


def certificate_page(title: str) -> Image.Image:
    p = _blank()
    d = ImageDraw.Draw(p)
    d.rounded_rectangle((150, 150, PW - 150, PH - 150), radius=80, outline=0, width=16)
    d.rounded_rectangle((210, 210, PW - 210, PH - 210), radius=60, outline=0, width=6)
    _center(d, 500, "CERTIFICATE", font(230))
    _center(d, 760, "OF AWESOME COLORING", font(110))
    _center(d, 1150, "This certifies that", font(70, "Poppins-ExtraBold.ttf"))
    d.line((450, 1450, PW - 450, 1450), fill=0, width=8)
    _center(d, 1550, f"finished {title}", font(64, "Poppins-ExtraBold.ttf"))
    _center(d, 1660, "and is a super star artist!", font(64, "Poppins-ExtraBold.ttf"))
    for k in range(5):                                           # five big stars to colour
        cx, cy, R = 520 + k * 380, 2200, 150
        pts = []
        for j in range(10):
            ang = -np.pi / 2 + j * np.pi / 5
            rr = R if j % 2 == 0 else R * 0.45
            pts.append((cx + rr * np.cos(ang), cy + rr * np.sin(ang)))
        d.polygon(pts, outline=0, width=10)
    d.line((450, 2750, 1150, 2750), fill=0, width=6)
    d.line((1400, 2750, PW - 450, 2750), fill=0, width=6)
    d.text((620, 2780), "Date", font=font(60, "Poppins-ExtraBold.ttf"), fill=0)
    d.text((1700, 2780), "Signed", font=font(60, "Poppins-ExtraBold.ttf"), fill=0)
    return p


def bonus_page(url: str) -> Image.Image:
    import qrcode
    p = _blank()
    d = ImageDraw.Draw(p)
    _center(d, 400, "FREE BONUS PAGES!", font(170))
    _center(d, 680, "Scan the code with a grown-up's phone", font(66, "Poppins-ExtraBold.ttf"))
    _center(d, 780, "to print extra pictures to color for free.", font(66, "Poppins-ExtraBold.ttf"))
    qr = qrcode.make(url, box_size=28, border=2).convert("L")
    p.paste(qr, ((PW - qr.width) // 2, 1050))
    _center(d, 1150 + qr.height, url.replace("https://", ""), font(54, "Poppins-ExtraBold.ttf"), fill=60)
    return p


def thanks_page() -> Image.Image:
    p = _blank()
    d = ImageDraw.Draw(p)
    _center(d, 1100, "THANK YOU!", font(240))
    for k, line in enumerate(["We hope you loved coloring these pictures.",
                              "If you did, a short review on Amazon helps",
                              "other families find this book. HookHouse Media"]):
        _center(d, 1500 + k * 110, line, font(62, "Poppins-ExtraBold.ttf"))
    return p


def title_page(spec: dict, art: Image.Image) -> Image.Image:
    p = _blank()
    d = ImageDraw.Draw(p)
    y = 300
    for line in _wrap(spec["title"].upper(), font(170), PW - 300, d):
        y = _center(d, y, line, font(170)) + 20
    _center(d, y + 40, spec["age_label"], font(100))
    small = art.resize((art.width * 7 // 10, art.height * 7 // 10))
    p.paste(small, ((PW - small.width) // 2, y + 260))
    return p


def _wrap(text: str, f, width: int, d: ImageDraw.ImageDraw) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if d.textlength(t, font=f) <= width:
            cur = t
        else:
            lines.append(cur)
            cur = w
    return lines + ([cur] if cur else [])


# ---------------- colour (covers) ----------------
def colourise(art: Image.Image, seed: int = 0) -> Image.Image:
    """Fill the line art's closed areas with a bright palette (the 'what it can look like' cover picture)."""
    import cv2
    a = np.asarray(art.convert("L"))
    white = (a > 128).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(white, connectivity=4)
    border = set(np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]])))
    rng = np.random.default_rng(seed)
    out = np.dstack([a, a, a]).astype(np.uint8)
    for i in range(1, n):
        if i in border or st[i, cv2.CC_STAT_AREA] < 400:
            continue
        out[lab == i] = _rgb(PALETTE[int(rng.integers(len(PALETTE)))])
    rgba = Image.fromarray(out, "RGB").convert("RGBA")
    alpha = np.where(np.isin(lab, list(border)) & (white == 1), 0, 255).astype(np.uint8)
    rgba.putalpha(Image.fromarray(alpha, "L"))
    return rgba


def _gradient(size, c1, c2) -> Image.Image:
    w, h = size
    t = np.linspace(0, 1, h)[:, None]
    a, b = np.array(_rgb(c1)), np.array(_rgb(c2))
    g = (a * (1 - t) + b * t).astype(np.uint8)
    return Image.fromarray(np.repeat(g[:, None, :], w, axis=1).reshape(h, w, 3), "RGB")


def front_cover(spec: dict, hero: Image.Image, extras: list[Image.Image], size=(2588, 3375)) -> Image.Image:
    W, H = size
    img = _gradient(size, *spec["theme_bg"]).convert("RGBA")
    d = ImageDraw.Draw(img)
    # badge
    fb = font(90)
    bw = d.textlength(spec["age_label"], font=fb) + 120
    d.rounded_rectangle((130, 150, 130 + bw, 300), radius=75, fill=_rgb(spec["accent"]))
    d.text((190, 175), spec["age_label"], font=fb, fill=(40, 20, 0))
    y = 380
    for line in _wrap(spec["title"].upper(), font(210), W - 260, d):
        d.text((133, y + 10), line, font=font(210), fill=(0, 0, 0, 120))
        d.text((125, y), line, font=font(210), fill="white", stroke_width=6, stroke_fill=(30, 30, 30))
        y += 220
    hero_c = colourise(hero, seed=3)
    s = min((W - 300) / hero_c.width, (H - y - 650) / hero_c.height)
    hero_c = hero_c.resize((int(hero_c.width * s), int(hero_c.height * s)))
    plate = Image.new("RGBA", (hero_c.width + 80, hero_c.height + 80), (255, 255, 255, 235))
    mask = Image.new("L", plate.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, plate.width, plate.height), radius=90, fill=255)
    px, py = (W - plate.width) // 2, y + 60
    shadow = Image.new("RGBA", plate.size, (0, 0, 0, 90))
    img.paste(shadow, (px + 18, py + 22), mask.filter(ImageFilter.GaussianBlur(4)))
    img.paste(plate, (px, py), mask)
    img.alpha_composite(hero_c, (px + 40, py + 40))
    fy = py + plate.height + 70
    fchip = font(66, "Poppins-ExtraBold.ttf")
    for k, ft in enumerate(spec["feats"]):
        tw = d.textlength("✓ " + ft, font=fchip)
        x0 = (W - tw - 100) // 2
        d.rounded_rectangle((x0, fy, x0 + tw + 100, fy + 110), radius=55, fill=(255, 255, 255, 230))
        d.text((x0 + 50, fy + 18), "✓ " + ft, font=fchip, fill=(30, 30, 30))
        fy += 135
    d.text((W - 620, H - 170), "HookHouse Media", font=font(60, "Poppins-ExtraBold.ttf"), fill="white")
    return img


def back_cover(spec: dict, thumbs: list[Image.Image], size=(2588, 3375)) -> Image.Image:
    W, H = size
    img = _gradient(size, spec["theme_bg"][1], spec["theme_bg"][0]).convert("RGBA")
    d = ImageDraw.Draw(img)
    y = 220
    for line in _wrap("WHAT'S INSIDE", font(150), W - 300, d):
        d.text((150, y), line, font=font(150), fill="white")
        y += 170
    tw, th = (W - 150 * 2 - 60 * 2) // 3, int((W - 420) / 3 * 1.27)
    for k, t in enumerate(thumbs[:6]):
        im = t.convert("RGB").resize((tw, th))
        x, yy = 150 + (k % 3) * (tw + 60), y + 40 + (k // 3) * (th + 60)
        d.rounded_rectangle((x - 12, yy - 12, x + tw + 12, yy + th + 12), radius=30, fill="white")
        img.paste(im, (x, yy))
    y += 40 + 2 * (th + 60) + 40
    f = font(62, "Poppins-ExtraBold.ttf")
    for line in _wrap(spec["subtitle"], f, W - 300, d)[:4]:
        d.text((150, y), line, font=f, fill="white")
        y += 85
    for ft in spec["feats"]:
        d.text((150, y + 20), "★ " + ft, font=f, fill=_rgb(spec["accent"]))
        y += 95
    d.rectangle((W - 150 - 600, H - 150 - 360, W - 150, H - 150), fill="white")      # barcode box (2 x 1.2 in)
    return img


# ---------------- build ----------------
QUEUE = ["christmas_colouring_book", "bloop_colouring_book", "fun_alphabet", "usa_states", "world_countries",
         "incredible_india", "color_by_number", "activity_book",      # rebuild order (owner 17 Nov)
         "seniors_word_search",
         "dinosaurs_everyday", "numbers_counting", "tracing_workbook", "kawaii_food", "ocean_animals", "space_adventure",
         "things_that_go", "nature_walk", "cozy_days"]               # new line-up (owner 18 Nov)


def _book_time(mins: int) -> str:
    """'cloud' 20:45-05:15 (leftover Cloudflare quota after the 20:00 video render, before the 05:30 reset),
    'local' 00:00-06:00 is also allowed for the PC's own FLUX (owner, 18 Nov: "use cloud + night backup"), '' else."""
    if mins >= 20 * 60 + 45 or mins <= 5 * 60 + 15:
        return "cloud"
    if mins < 6 * 60:
        return "local"
    return ""


def _send_book(pid: str, res: dict, log=print) -> None:
    out = PROD / pid
    try:
        from . import telegram_bot as tb
        pdf = out / res["interior"]
        with (out / "cover_v2.jpg").open("rb") as fh:
            tb.api("sendPhoto", files={"photo": ("cover.jpg", fh, "image/jpeg")}, chat_id=tb._chat(),
                   caption=f"📚 New design ready: {res['title']} ({res.get('designs', '')} pictures, {res['pages']} pages). "
                           "The full PDF follows; it goes on Amazon/Payhip only after your ✅.")
        if pdf.stat().st_size < 49 * 1024 * 1024:
            with pdf.open("rb") as fh:
                tb.api("sendDocument", files={"document": (pdf.name, fh, "application/pdf")}, chat_id=tb._chat(),
                       http_timeout=300)
    except Exception as e:  # noqa: BLE001 - the book is saved either way
        log(f"{pid}: telegram: {e}")


def night_job(log=print, per_run: int = 6, local: bool = False) -> str:
    """One step on the next unfinished book: up to per_run new pages from the cloud (or 1 from the PC's FLUX when
    local=True). A finished book goes to Telegram as a PDF for the owner's check."""
    from .book_specs import BOOKS
    for pid in QUEUE:
        out = PROD / pid
        if (out / "kdp_listing_v2.json").exists():
            continue
        kind = BOOKS[pid]["kind"]
        if kind == "activity":
            from .activity_v2 import build_activity as maker
        elif kind == "tracing":                              # no drawing: alphabet + counting pictures reused
            from .activity_v2 import build_tracing as maker
        elif kind == "seniors_ws":
            from .activity_v2 import build_seniors as maker
        else:
            maker = (build_learning if kind in ("alphabet", "states", "world", "india", "numbers")
                     else build_cbn if kind == "cbn" else build)
        bookart.SKIP_CLOUD = local
        try:
            res = maker(pid, log=log, allow_local=local, max_new=1 if local else per_run)
        finally:
            bookart.SKIP_CLOUD = False
        if res is None:
            return f"{pid}: pages in progress"
        _send_book(pid, res, log)
        return f"{pid}: built"
    return "all queued books built"


NIGHT_PORT = 47615                       # one night worker per PC


def night_worker(log=print) -> None:
    """The book worker (own process, started by the PC helper): cloud pages while leftover quota lasts, then the
    PC's own FLUX 00:00-06:00 (slow, ~30 min a page); stops itself and the local FLUX server at 06:00."""
    import datetime as dt
    import socket
    import subprocess
    sock = socket.socket()
    try:
        sock.bind(("127.0.0.1", NIGHT_PORT))
    except OSError:
        log("book night worker already running")
        return
    cloud_dry = False
    try:
        while True:
            now = dt.datetime.now()
            slot = _book_time(now.hour * 60 + now.minute)
            if not slot:
                break
            if slot == "cloud" and not cloud_dry:
                msg = night_job(log, per_run=6)
                if "in progress" in msg and not _cloud_open():
                    cloud_dry = True                         # quota gone: local FLUX takes over after midnight
            elif now.hour < 6:
                msg = night_job(log, local=True)
            else:                                            # cloud used up before midnight: wait for 00:00
                time.sleep(300)
                continue
            log("book night worker: " + msg)
            if msg == "all queued books built":
                break
            time.sleep(5 if slot == "cloud" and not cloud_dry else 1)
    finally:
        subprocess.run(["taskkill", "/IM", "sd-server.exe", "/F"], capture_output=True)   # free the CPU for videos
        sock.close()


def _cloud_open() -> bool:
    try:
        import os
        from .storyboard import _open
        hf = bool(os.environ.get("HF_TOKEN")) and _open("hf") and bookart._hf_room()     # 2nd free source (18 Nov)
        return bool(_open("cloudflare") and _open("cf_flux")) or hf
    except Exception:  # noqa: BLE001
        return False


def ensure_night_worker(log=print) -> str:
    """PC helper: start the night worker in the background during book time (it exits by itself at 06:00)."""
    import datetime as dt
    import socket
    import subprocess
    now = dt.datetime.now()
    if not _book_time(now.hour * 60 + now.minute):
        return "not book time"
    probe = socket.socket()
    try:
        probe.bind(("127.0.0.1", NIGHT_PORT))
    except OSError:
        return "night worker running"
    finally:
        probe.close()
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    logf = open(ROOT / "data" / "book_night.log", "ab")
    subprocess.Popen([sys.executable, "-m", "engine.books_v2", "--night"], cwd=str(ROOT), stdout=logf, stderr=logf,
                     creationflags=flags)
    return "night worker started"


def build(pid: str, pages: int | None = None, prefer_cloud: bool = True, log=print, allow_local: bool = True,
          max_new: int | None = None) -> dict | None:
    """Make the missing pages (cached in data/products/<id>/v2/), then the PDF + covers once every page exists.
    max_new: draw at most this many new pages in this call (the nightly job works in small steps). Returns None
    while pages are still missing."""
    from .book_specs import BOOKS
    from .kdp import BLEED, TRIM_H, TRIM_W, _px, spine_in
    spec = BOOKS[pid]
    out = PROD / pid
    (out / "v2").mkdir(parents=True, exist_ok=True)
    subjects = spec["subjects"][:pages] if pages else spec["subjects"]
    used: list[int] = []
    arts: list[tuple[Image.Image, str]] = []
    new = 0
    missing = False
    for k, subj in enumerate(subjects):
        subj, fact = subj if isinstance(subj, tuple) else (subj, "")      # fun-fact books: (picture, true fact)
        cached = out / "v2" / f"page_{k + 1:02d}.png"
        if cached.exists():
            im = Image.open(cached).convert("L")
            used.append(bookart.dhash(im))
            arts.append((im, fact))
            continue
        if max_new is not None and new >= max_new:
            missing = True
            continue
        try:
            pg = bookart.page(subj, age=spec["age"], seed=spec["seed"] + k * 31, used=used, prefer_cloud=prefer_cloud,
                              page_px=ART, log=log, allow_local=allow_local)
        except bookart.NoPicture:
            log(f"{pid}: picture quota used up after {new} new page(s); continuing next time")
            return None
        new += 1
        if pg is None:
            log(f"  page {k + 1} '{subj[:40]}': no clean drawing after 5 tries (skipped)")
            continue
        pg.image.save(cached)
        arts.append((pg.image, fact))
        log(f"  page {k + 1}/{len(subjects)} ok ({pg.source}, {pg.stats['regions']} areas, ink {pg.stats['ink']:.0%})")
    if missing:
        return None
    if not arts:
        raise RuntimeError("no pages")
    hero = arts[0][0]
    interior = [title_page(spec, hero)]
    ex = spec.get("extras") or []
    if "owner" in ex:
        interior += [owner_page(arts[min(1, len(arts) - 1)][0]), back_page()]
    if "colour_test" in ex:
        interior += [colour_test_page(), back_page()]
    for im, fact in arts:
        interior += [design_page(im, f"Fun fact: {fact}" if fact else ""), back_page()]
    if "certificate" in ex:
        interior += [certificate_page(spec["title"]), back_page()]
    if "bonus" in ex:
        interior += [bonus_page(f"{STORE_URL}")]
    interior.append(thanks_page())
    if len(interior) % 2:
        interior.append(_blank())
    pdf = out / f"{pid}_v2_interior.pdf"
    interior[0].convert("1").save(pdf, save_all=True, append_images=[p.convert("1") for p in interior[1:]],
                                  resolution=DPI)
    n = len(interior)
    sp = spine_in(n)
    Wt, Ht = _px(BLEED * 2 + TRIM_W * 2 + sp), _px(BLEED * 2 + TRIM_H)
    half = (_px(BLEED + TRIM_W), Ht)
    front = front_cover(spec, hero, [a for a, _ in arts[1:4]], size=half)
    back = back_cover(spec, [a for a, _ in arts[1:7]], size=half)
    wrap = Image.new("RGB", (Wt, Ht), _rgb(spec["theme_bg"][1]))
    wrap.paste(back.convert("RGB"), (0, 0))
    wrap.paste(front.convert("RGB"), (Wt - half[0], 0))
    if n >= 79:                                                       # KDP: spine text only from 79 pages
        sdraw = ImageDraw.Draw(wrap)
        sf = font(int(_px(sp) * 0.55))
        txt = Image.new("RGBA", (Ht, _px(sp)), (0, 0, 0, 0))
        ImageDraw.Draw(txt).text((200, 4), spec["title"].upper(), font=sf, fill="white")
        wrap.paste(txt.rotate(-90, expand=True), (half[0], 0), txt.rotate(-90, expand=True))
        del sdraw
    wrap.save(out / "kdp_cover_v2.pdf", resolution=DPI)
    front.convert("RGB").save(out / "cover_v2.jpg", quality=92)
    front.convert("RGB").resize((1280, int(1280 * front.height / front.width))).save(out / "store_cover_v2.jpg", quality=90)
    front.convert("RGB").resize((600, int(600 * front.height / front.width))).save(out / "store_thumb_v2.jpg", quality=88)
    listing = {"title": spec["title"] + (f" {spec['age_label'].title()}" if spec["age_label"] not in spec["title"] else ""),
               "subtitle": spec["subtitle"], "price": spec["price"], "pages": n, "trim": "8.5 x 11 in",
               "designs": len(arts), "interior": pdf.name, "cover": "kdp_cover_v2.pdf", "spine_in": sp,
               "ai_content": "Yes: the drawings are AI-generated (FLUX / DreamShaper) and edited by our code"}
    (out / "kdp_listing_v2.json").write_text(json.dumps(listing, indent=1), encoding="utf-8")
    log(f"{pid}: {len(arts)} designs, {n} pages, spine {sp} in -> {pdf.name}")
    return listing


# ---------------- learning books: Fun Alphabet, The 50 States ----------------
def hollow_text(d: ImageDraw.ImageDraw, xy, text: str, size: int, stroke: int = 14, anchor: str = "mm") -> None:
    """Big outline letters a child can colour in."""
    d.text(xy, text, font=font(size), fill=255, stroke_width=stroke, stroke_fill=0, anchor=anchor)


def alphabet_pages(letter: str, word: str, art: Image.Image | None) -> list[Image.Image]:
    p1 = _blank()
    d = ImageDraw.Draw(p1)
    hollow_text(d, (PW // 2 - 300, 560), letter, 640, stroke=18)
    d.text((PW // 2 + 330, 760), letter.lower(), font=font(520, "Poppins-ExtraBold.ttf"), fill=255, stroke_width=16,
           stroke_fill=0, anchor="ls")
    hollow_text(d, (PW // 2, 1050), f"{letter} is for {word}", 150, stroke=8)
    if art is not None:
        a = art.resize((int(art.width * 0.78), int(art.height * 0.78)))
        p1.paste(a, ((PW - a.width) // 2, 1220))
    p2 = _blank()
    d = ImageDraw.Draw(p2)
    _center(d, 200, f"Trace the letter {letter}", font(120))
    trace = font(300, "Poppins-ExtraBold.ttf")              # real lowercase letters (LuckiestGuy is caps only)
    cap_h = -d.textbbox((0, 0), "H", font=trace, anchor="ls")[1]               # real capital height
    x_h = -d.textbbox((0, 0), "x", font=trace, anchor="ls")[1]                 # real small-letter height
    for row, ch in enumerate([letter, letter.lower(), letter, letter.lower()]):
        base = 800 + row * 560                                                  # letters sit ON the writing line
        d.line((150, base, PW - 150, base), fill=0, width=6)
        for x in range(150, PW - 150, 60):                                      # dashed line at x-height
            d.line((x, base - x_h, x + 30, base - x_h), fill=120, width=4)
        d.line((150, base - cap_h, PW - 150, base - cap_h), fill=170, width=4)  # top line (capital height)
        d.text((180, base), ch, font=trace, fill=0, anchor="ls")                # first one solid (the model)
        for k in range(1, 6):
            x0 = 180 + k * 380
            d.text((x0, base), ch, font=trace, fill=205, anchor="ls")           # grey ones to trace over
            top = base + d.textbbox((0, 0), ch, font=trace, anchor="ls")[1]
            d.ellipse((x0 + 10, top - 50, x0 + 42, top - 18), fill=0)           # start dot above the letter
    _center(d, 2850, word, font(220, "Poppins-ExtraBold.ttf"), fill=205)
    return [p1, back_page(), p2, back_page()]


def plural(n: int, word: str) -> str:
    if n == 1:
        return word
    irregular = {"fish": "fish", "leaf": "leaves", "mouse": "mice", "sheep": "sheep"}
    if word in irregular:
        return irregular[word]
    if word.endswith("y") and word[-2:-1] not in "aeiou":
        return word[:-1] + "ies"
    if word.endswith(("s", "sh", "ch", "x")):
        return word + "es"
    return word + "s"


def number_grid(n: int) -> tuple[int, int]:
    """Columns x rows for n objects (rows of at most 5, so children can count in fives)."""
    cols = min(5, n) if n > 4 else n
    return cols, -(-n // cols)


def numbers_pages(n: int, word: str, obj: str, art: Image.Image | None) -> list[Image.Image]:
    """Counting book: page 1 = the hollow numeral and word + exactly n copies of one picture to count and colour;
    page 2 = trace the numeral and the word. The count is drawn by code, never by the AI (AI miscounts)."""
    p1 = _blank()
    d = ImageDraw.Draw(p1)
    hollow_text(d, (PW // 2, 470), str(n), 560, stroke=18)
    hollow_text(d, (PW // 2, 900), word, 190, stroke=9)
    _center(d, 1060, f"Count and color {n} {plural(n, obj)}", font(90, "Poppins-ExtraBold.ttf"))
    if art is not None:
        cols, rows = number_grid(n)
        box_w, box_h = PW - 300, PH - 1250 - 200
        cell = int(min(box_w / cols, box_h / rows) * 0.92)
        ys, xs = np.nonzero(np.asarray(art) < 128)
        a = art.crop((xs.min(), ys.min(), xs.max() + 1, ys.max() + 1)) if len(xs) else art
        f = min(cell * 0.82, 900) / max(a.width, a.height)       # a gap between copies: each one countable
        a = a.resize((max(1, int(a.width * f)), max(1, int(a.height * f))))
        y0 = 1250 + (box_h - rows * cell) // 2
        for i in range(n):
            r, c = divmod(i, cols)
            in_row = min(cols, n - r * cols)                     # centre a short last row
            x0 = (PW - in_row * cell) // 2
            p1.paste(a, (x0 + c * cell + (cell - a.width) // 2, y0 + r * cell + (cell - a.height) // 2))
    p2 = _blank()
    d = ImageDraw.Draw(p2)
    _center(d, 200, f"Trace the number {n}", font(120))
    trace = font(300, "Poppins-ExtraBold.ttf")
    for row in range(3):
        base = 800 + row * 560
        d.line((150, base, PW - 150, base), fill=0, width=6)
        d.text((180, base), str(n), font=trace, fill=0, anchor="ls")
        step = 380 if n < 10 else 560
        for k, x0 in enumerate(range(180 + step, PW - 300, step)):
            d.text((x0, base), str(n), font=trace, fill=205, anchor="ls")
    wf = font(230, "Poppins-ExtraBold.ttf")
    d.line((150, 2700, PW - 150, 2700), fill=0, width=6)
    d.text((PW // 2, 2700), word.lower(), font=wf, fill=205, anchor="ms")
    return [p1, back_page(), p2, back_page()]


def state_page(name: str, facts: tuple, bird_art: Image.Image | None, stroke: int = 12) -> Image.Image:
    import math
    import shapefile
    r = shapefile.Reader(str(ROOT / "data" / "geo" / "us_states" / "cb_2023_us_state_20m.shp"))
    names = [rec["NAME"] for rec in r.records()]
    shp = r.shape(names.index(name))
    pts, parts = shp.points, list(shp.parts) + [len(shp.points)]
    if name == "Alaska":                                   # the Aleutians cross 180 degrees: keep one side
        pts = [(x if x < 0 else x - 360, y) for x, y in pts]
    lat0 = sum(y for _, y in pts) / len(pts)
    proj = [(x * math.cos(math.radians(lat0)), y) for x, y in pts]
    xs, ys = [q[0] for q in proj], [q[1] for q in proj]
    box_w, box_h, top = PW - 300, 1500, 520
    s = min(box_w / (max(xs) - min(xs)), box_h / (max(ys) - min(ys)))
    ox = 150 + (box_w - (max(xs) - min(xs)) * s) / 2
    oy = top + (box_h - (max(ys) - min(ys)) * s) / 2
    p = _blank()
    d = ImageDraw.Draw(p)
    hollow_text(d, (PW // 2, 300), name.upper(), 230 if len(name) < 11 else 170, stroke=10)
    for a, b in zip(parts[:-1], parts[1:]):
        poly = [(ox + (x - min(xs)) * s, oy + (max(ys) - y) * s) for x, y in proj[a:b]]
        if len(poly) > 2:
            w_ = max(q[0] for q in poly) - min(q[0] for q in poly)
            h_ = max(q[1] for q in poly) - min(q[1] for q in poly)
            if w_ * h_ > 400:                                # skip specks of tiny islands
                d.line(poly + [poly[0]], fill=0, width=stroke, joint="curve")
    cap, nick, bird, flower, year = facts
    fy = 2150
    d.rounded_rectangle((150, fy, 1500, PH - 150), radius=50, outline=0, width=8)
    f = font(58, "Poppins-ExtraBold.ttf")
    for k, (lab, val) in enumerate([("Capital", cap), ("Nickname", nick), ("State bird", bird),
                                     ("State flower", flower), ("Joined the USA", str(year))]):
        d.text((200, fy + 45 + k * 190), f"{lab}:", font=f, fill=0)
        d.text((200, fy + 115 + k * 190), _wrap(val, f, 1250, d)[0], font=f, fill=60)
    if bird_art is not None:
        b = bird_art.resize((880, int(880 * bird_art.height / bird_art.width)))
        p.paste(b, (1560, fy + 40))
    return p


def _outline(d: ImageDraw.ImageDraw, shp, box: tuple[int, int, int, int], stroke: int, min_area: float = 400) -> None:
    """Draw a shapefile shape's outline fitted into box (equal-area-ish: x scaled by cos(latitude))."""
    import math
    pts, parts = shp.points, list(shp.parts) + [len(shp.points)]
    if not pts:
        return
    if max(x for x, _ in pts) - min(x for x, _ in pts) > 180:      # crosses the date line (Russia, NZ, USA, Fiji)
        pts = [(x if x < 0 else x - 360, y) for x, y in pts]
    lat0 = sum(y for _, y in pts) / len(pts)
    proj = [(x * math.cos(math.radians(lat0)), y) for x, y in pts]
    xs, ys = [q[0] for q in proj], [q[1] for q in proj]
    x0, y0, x1, y1 = box
    s = min((x1 - x0) / max(1e-9, max(xs) - min(xs)), (y1 - y0) / max(1e-9, max(ys) - min(ys)))
    ox = x0 + ((x1 - x0) - (max(xs) - min(xs)) * s) / 2
    oy = y0 + ((y1 - y0) - (max(ys) - min(ys)) * s) / 2
    for a, b in zip(parts[:-1], parts[1:]):
        poly = [(ox + (x - min(xs)) * s, oy + (max(ys) - y) * s) for x, y in proj[a:b]]
        if len(poly) > 2:
            w_ = max(q[0] for q in poly) - min(q[0] for q in poly)
            h_ = max(q[1] for q in poly) - min(q[1] for q in poly)
            if w_ * h_ > min_area:
                d.line(poly + [poly[0]], fill=0, width=stroke, joint="curve")


_WORLD: list = []


def _world_shape(name: str):
    """Natural Earth admin-0, India point of view (public domain): India per its official boundaries."""
    import glob
    import shapefile
    if not _WORLD:
        r = shapefile.Reader(glob.glob(str(ROOT / "data" / "geo" / "world_ind" / "*.shp"))[0])
        _WORLD.append(({rec["NAME"]: k for k, rec in enumerate(r.records())}, r))
    idx, r = _WORLD[0]
    return r.shape(idx[name])


def _facts_box(d, rows: list[tuple[str, str]], box: tuple[int, int, int, int]) -> None:
    x0, y0, x1, y1 = box
    d.rounded_rectangle(box, radius=50, outline=0, width=8)
    f = font(56, "Poppins-ExtraBold.ttf")
    step = (y1 - y0 - 60) // max(1, len(rows))
    for k, (lab, val) in enumerate(rows):
        d.text((x0 + 50, y0 + 40 + k * step), f"{lab}:", font=f, fill=0)
        d.text((x0 + 50, y0 + 105 + k * step), _wrap(val, f, x1 - x0 - 100, d)[0], font=f, fill=60)


def world_page(name: str, facts: tuple, art: Image.Image | None) -> Image.Image:
    show = {"Republic of Korea": "South Korea", "United Arab Emirates": "UAE"}.get(name, name)
    cap, landmark, animal, food, hello = facts
    p = _blank()
    d = ImageDraw.Draw(p)
    hollow_text(d, (PW // 2, 260), show.upper(), 200 if len(show) < 12 else 150, stroke=10)
    _outline(d, _world_shape(name), (150, 420, 1150, 1500), stroke=10)
    _facts_box(d, [("Capital", cap), ("Animal", animal), ("Food", food), ("Say hello", hello)],
               (1250, 420, PW - 150, 1500))
    if art is not None:
        a = art.resize((2000, int(2000 * art.height / art.width)))
        p.paste(a, ((PW - a.width) // 2, 1580))
    return p


def india_page(name: str, facts: tuple, art: Image.Image | None) -> Image.Image:
    cap, monument, dance, food = facts
    p = _blank()
    d = ImageDraw.Draw(p)
    hollow_text(d, (PW // 2, 260), name.upper(), 190 if len(name) < 13 else 140, stroke=10)
    if art is not None:
        a = art.resize((2100, int(2100 * art.height / art.width)))
        p.paste(a, ((PW - a.width) // 2, 430))
    _facts_box(d, [("Capital", cap), ("Famous place", monument.replace("the ", "", 1).capitalize()),
                   ("Folk dance", dance), ("Famous food", food)], (150, 2230, PW - 150, PH - 150))
    return p


CBN_COLORS = [("Yellow", "#FFE082"), ("Orange", "#FFB74D"), ("Red", "#E57373"), ("Pink", "#F48FB1"),
              ("Purple", "#BA68C8"), ("Blue", "#64B5F6"), ("Green", "#81C784"), ("Brown", "#A1887F"),
              ("Gray", "#9E9E9E")]              # gray: black/dark parts of the picture (a penguin's back)


def nearest_key(rgb) -> int | None:
    """Index of the closest crayon in CBN_COLORS (weighted RGB distance), None for white/near-white (left blank)."""
    r, g, b = (float(x) for x in rgb)
    if min(r, g, b) > 215:
        return None
    if max(r, g, b) - min(r, g, b) < 28:                      # no colour in it: black / gray parts -> Gray
        return next(k for k, (name, _) in enumerate(CBN_COLORS) if name == "Gray")
    best, bd = 0, 1e18
    for k, (_, hx) in enumerate(CBN_COLORS):
        R, G, B = _rgb(hx)
        rm = (r + R) / 2
        dd = (2 + rm / 256) * (r - R) ** 2 + 4 * (g - G) ** 2 + (2 + (255 - rm) / 256) * (b - B) ** 2
        if dd < bd:
            best, bd = k, dd
    return best


def color_by_number(art: Image.Image, seed: int = 0, colour: Image.Image | None = None) -> tuple[Image.Image, Image.Image]:
    """(page with a number in every area + colour key, coloured answer). Areas get colours 1-8: from the drawing's
    own colours when we have them (white areas stay unnumbered), else random; tiny areas stay blank."""
    import cv2
    a = np.asarray(art.convert("L"))
    white = (a > 128).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(white, connectivity=4)
    border = set(np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]])))
    rng = np.random.default_rng(seed)
    page = _blank()
    page.paste(art, ((PW - art.width) // 2, 150))
    d = ImageDraw.Draw(page)
    ans = np.dstack([a, a, a]).astype(np.uint8)
    fnum = font(64, "Poppins-ExtraBold.ttf")
    ox, oy = (PW - art.width) // 2, 150
    for i in range(1, n):
        if i in border or st[i, cv2.CC_STAT_AREA] < 9000:
            continue
        if colour is not None:
            px = np.asarray(colour)[lab == i]
            k = nearest_key(np.median(px, axis=0))
            if k is None:
                continue                                                # white in the picture: nothing to colour
        else:
            k = int(rng.integers(len(CBN_COLORS)))
        ans[lab == i] = _rgb(CBN_COLORS[k][1])
        m = (lab == i).astype(np.uint8)
        dist = cv2.distanceTransform(m, cv2.DIST_L2, 3)
        y, x = np.unravel_index(int(np.argmax(dist)), dist.shape)       # the roomiest spot in the area
        if dist[y, x] >= 40:
            d.text((ox + x, oy + y), str(k + 1), font=fnum, fill=0, anchor="mm")
    ky = PH - 330
    fk = font(46, "Poppins-ExtraBold.ttf")
    for k, (name, _) in enumerate(CBN_COLORS):
        x = 140 + (k % 5) * 460
        y = ky + (k // 5) * 90
        d.ellipse((x, y, x + 60, y + 60), outline=0, width=6)
        d.text((x + 80, y + 4), f"{k + 1} = {name}", font=fk, fill=0)
    return page, Image.fromarray(ans, "RGB")


def build_cbn(pid: str, log=print, allow_local: bool = True, max_new: int | None = None) -> dict | None:
    """Color by Number: AI pictures (cached), each turned into a numbered page; coloured answer key at the back."""
    from .book_specs import BOOKS
    from .kdp import BLEED, TRIM_H, TRIM_W, _px, spine_in
    spec = BOOKS[pid]
    out = PROD / pid
    (out / "v2").mkdir(parents=True, exist_ok=True)
    used: list[int] = []
    arts: list[Image.Image] = []
    colours: list[Image.Image | None] = []
    new = 0
    for k, subj in enumerate(spec["subjects"]):
        cached = out / "v2" / f"page_{k + 1:02d}.png"
        ccache = cached.with_name(cached.stem + "_colour.png")
        if cached.exists():
            arts.append(Image.open(cached).convert("L"))
            colours.append(Image.open(ccache).convert("RGB") if ccache.exists() else None)
            continue
        if max_new is not None and new >= max_new:
            return None
        try:
            pg = bookart.page(subj, age="toddler", seed=spec["seed"] + k * 17, used=used, page_px=(2250, 2500),
                              log=log, allow_local=allow_local, style=bookart.CBN_STYLE)
        except bookart.NoPicture:
            return None
        new += 1
        if pg:
            pg.image.save(cached)
            if pg.colour is not None:
                pg.colour.save(ccache)
            arts.append(pg.image)
            colours.append(pg.colour)
    if not arts:
        return None
    interior = [title_page(spec, arts[0]), owner_page(arts[0]), back_page()]
    answers = []
    for k, art in enumerate(arts):
        page, ans = color_by_number(art, seed=k, colour=colours[k])
        interior += [page, back_page()]
        answers.append(ans)
    key = _blank().convert("RGB")
    dk = ImageDraw.Draw(key)
    _center(dk, 150, "ANSWER KEY", font(140))
    per = 6
    for j in range(0, len(answers), per):
        sheet = key.copy() if j == 0 else _blank().convert("RGB")
        for i, ans in enumerate(answers[j:j + per]):
            t = ans.resize((1000, int(1000 * ans.height / ans.width)))
            sheet.paste(t, (175 + (i % 2) * 1200, 400 + (i // 2) * 950))
        interior.append(sheet)
    interior += [certificate_page(spec["title"]), bonus_page(STORE_URL), thanks_page()]
    if len(interior) % 2:
        interior.append(_blank())
    pdf = out / f"{pid}_v2_interior.pdf"
    interior[0].convert("RGB").save(pdf, save_all=True, append_images=[q.convert("RGB") for q in interior[1:]],
                                    resolution=DPI)
    n = len(interior)
    sp = spine_in(n)
    Wt, Ht = _px(BLEED * 2 + TRIM_W * 2 + sp), _px(BLEED * 2 + TRIM_H)
    half = (_px(BLEED + TRIM_W), Ht)
    front = front_cover(spec, arts[0], [], size=half)
    back = back_cover(spec, [a for a in arts[1:7]], size=half)
    wrap = Image.new("RGB", (Wt, Ht), _rgb(spec["theme_bg"][1]))
    wrap.paste(back.convert("RGB"), (0, 0))
    wrap.paste(front.convert("RGB"), (Wt - half[0], 0))
    wrap.save(out / "kdp_cover_v2.pdf", resolution=DPI)
    front.convert("RGB").save(out / "cover_v2.jpg", quality=92)
    listing = {"title": spec["title"], "subtitle": spec["subtitle"], "price": spec["price"], "pages": n,
               "designs": len(arts), "trim": "8.5 x 11 in", "interior": pdf.name, "cover": "kdp_cover_v2.pdf",
               "spine_in": sp, "paper": "black & white (the answer key prints in greys; the Payhip PDF keeps colour)",
               "ai_content": "Yes: the drawings are AI-generated and edited by our code"}
    (out / "kdp_listing_v2.json").write_text(json.dumps(listing, indent=1), encoding="utf-8")
    log(f"{pid}: {len(arts)} pictures, {n} pages -> {pdf.name}")
    return listing


def build_learning(pid: str, log=print, allow_local: bool = True, max_new: int | None = None) -> dict | None:
    """Fun Alphabet / 50 States: pictures first (cached), then the PDF + covers. None while pictures are missing."""
    from .book_specs import ALPHABET, BOOKS, INDIA, NUMBERS, USA, WORLD
    from .kdp import BLEED, TRIM_H, TRIM_W, _px, spine_in
    spec = BOOKS[pid]
    out = PROD / pid
    (out / "v2").mkdir(parents=True, exist_ok=True)
    kind = spec["kind"]
    items = {"alphabet": ALPHABET, "states": list(USA.items()), "world": list(WORLD.items()),
             "india": list(INDIA.items()), "numbers": NUMBERS}[kind]
    used: list[int] = []
    arts: dict[int, Image.Image] = {}
    new, missing = 0, False
    for k, item in enumerate(items):
        cached = out / "v2" / f"art_{k + 1:02d}.png"
        if cached.exists():
            arts[k] = Image.open(cached).convert("L")
            continue
        if max_new is not None and new >= max_new:
            missing = True
            continue
        subj = {"alphabet": lambda: f"a cute smiling cartoon {item[1].lower()}",
                "states": lambda: f"a cute cartoon {item[1][2].lower()} bird sitting on a branch",
                "world": lambda: f"{item[1][1]}, with a cute cartoon {item[1][2].lower()} in front",
                "india": lambda: f"{item[1][1]}, simple cute cartoon style",
                "numbers": lambda: f"one single cute smiling cartoon {item[2]}, isolated, nothing else"}[kind]()
        try:
            # one simple animal or object (alphabet, counting) has few areas by design: toddler check (3+), not 8+
            check = "toddler" if kind in ("numbers", "alphabet") else "kids"
            pg = bookart.page(subj, age=check, seed=spec["seed"] + k * 13, used=used, page_px=(1800, 1500), log=log,
                              allow_local=allow_local)
        except bookart.NoPicture:
            return None
        new += 1
        if pg:
            pg.image.save(cached)
            arts[k] = pg.image
    if missing or not arts:
        return None
    hero = next(iter(arts.values()))
    interior = [title_page(spec, hero), owner_page(hero), back_page()]
    for k, item in enumerate(items):
        if kind == "alphabet":
            interior += alphabet_pages(item[0], item[1], arts.get(k))
        elif kind == "numbers":
            interior += numbers_pages(item[0], item[1], item[2], arts.get(k))
        elif kind == "states":
            interior += [state_page(item[0], item[1], arts.get(k)), back_page()]
        elif kind == "world":
            interior += [world_page(item[0], item[1], arts.get(k)), back_page()]
        else:
            interior += [india_page(item[0], item[1], arts.get(k)), back_page()]
    interior += [certificate_page(spec["title"]), back_page(), bonus_page(STORE_URL), thanks_page()]
    if len(interior) % 2:
        interior.append(_blank())
    pdf = out / f"{pid}_v2_interior.pdf"
    interior[0].convert("L").save(pdf, save_all=True, append_images=[q.convert("L") for q in interior[1:]],
                                  resolution=DPI)
    n = len(interior)
    sp = spine_in(n)
    Wt, Ht = _px(BLEED * 2 + TRIM_W * 2 + sp), _px(BLEED * 2 + TRIM_H)
    half = (_px(BLEED + TRIM_W), Ht)
    front = front_cover(spec, hero, [], size=half)
    back = back_cover(spec, [q for q in interior[3:60:2]][:6], size=half)
    wrap = Image.new("RGB", (Wt, Ht), _rgb(spec["theme_bg"][1]))
    wrap.paste(back.convert("RGB"), (0, 0))
    wrap.paste(front.convert("RGB"), (Wt - half[0], 0))
    wrap.save(out / "kdp_cover_v2.pdf", resolution=DPI)
    front.convert("RGB").save(out / "cover_v2.jpg", quality=92)
    listing = {"title": spec["title"], "subtitle": spec["subtitle"], "price": spec["price"], "pages": n,
               "trim": "8.5 x 11 in", "interior": pdf.name, "cover": "kdp_cover_v2.pdf", "spine_in": sp,
               "ai_content": "Yes: the animal/bird drawings are AI-generated; maps from US Census public-domain data"}
    (out / "kdp_listing_v2.json").write_text(json.dumps(listing, indent=1), encoding="utf-8")
    log(f"{pid}: {n} pages -> {pdf.name}")
    return listing


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--night" in args:
        night_worker(log=lambda m: print(time.strftime("%H:%M"), m, flush=True))
        sys.exit(0)
    pages = int(args[args.index("--pages") + 1]) if "--pages" in args else None
    build(args[0], pages=pages, prefer_cloud="--local" not in args)
