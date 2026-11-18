"""Profile pictures and banners for all 14 channels (owner, 12 Nov: "make the profile pictures and banners").

Per channel, in output/brand/<id>/:
- avatar.png           1080x1080 (YouTube, Instagram and the Facebook Page). Text stays inside the circle crop.
- youtube_banner.jpg   2560x1440. Text inside the 1546x423 area that every device shows.
- facebook_cover.jpg   1640x624. Text in the centre that phones keep.
Plus output/brand/preview.png, a contact sheet showing the circle crops and banner safe areas.
Uses each channel's own palette and fonts; Hindi text is shaped with HarfBuzz (engine/media/shaping.py).
Usage: python scripts/make_brand_assets.py
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from engine.media.shaping import text_rgba  # noqa: E402

FONTS = ROOT / "assets" / "fonts"
OUT = ROOT / "output" / "brand"
ANTON, BEBAS, LUCKY = "Anton-Regular.ttf", "BebasNeue-Regular.ttf", "LuckiestGuy-Regular.ttf"
ROZHA, MUKTA, POP = "RozhaOne-Regular.ttf", "Mukta-ExtraBold.ttf", "Poppins-ExtraBold.ttf"

# id: background top / bottom, wordmark lines [(text, colour)], font, decoration, banner tagline, extra banner line
BRANDS = {
    "hot_take_hq": dict(bg=("#FFE600", "#FFB800"), lines=[("HOT TAKE", "#111111"), ("HQ", "#E00000")], font=ANTON,
                        deco="bubble", ink="#111111", tag="The 60 seconds of every podcast you actually need.",
                        extra="NEW CLIPS DAILY"),
    "unsolved_after_dark": dict(bg=("#0B0F1A", "#2A0606"), lines=[("CREEPY", "#F5F5F5"), ("CASE CLUB", "#FF2B2B")],   # renamed 14 Nov
                                font=BEBAS, deco="question", tag="Real stories. No answers. Watch if you dare.",
                                extra="NEW MYSTERIES EVERY DAY"),
    "clutch_tales": dict(bg=("#0A1F44", "#050E22"), lines=[("CLUTCH", "#FFFFFF"), ("TALES", "#FFC21A")], font=ANTON,
                         deco="clock", tag="The greatest moments in sports, told like movies.",
                         extra="NEW STORIES EVERY DAY"),
    "ending_decoded": dict(bg=("#1A1A1A", "#000000"), lines=[("ENDING", "#F5F5F1"), ("DECODED", "#E50914")],
                           font=BEBAS, deco="fin", tag="Every ending explained. Every secret found.",
                           extra="NEW EXPLAINERS EVERY DAY"),
    "money_cheat_codes": dict(bg=("#0E1116", "#05301A"), lines=[("MONEY", "#FFFFFF"), ("CHEAT CODES", "#00E676")],
                              font=ANTON, deco="dollar", tag="Money tricks school never taught you.",
                              extra="EDUCATION ONLY · NOT FINANCIAL ADVICE"),
    "itihaas_ke_raaz": dict(bg=("#3A2410", "#120A04"), lines=[("इतिहास के", "#FFF4E0"), ("राज़", "#FFD54A")],
                            font=ROZHA, deco="glow", banner_lines=[("ITIHAAS KE ", "#FFF4E0"), ("RAAZ", "#FFD54A")],
                            banner_font=ANTON, tag="इतिहास के राज़  ·  Har kahani mein chhupa hai ek raaz.",
                            tag_font=MUKTA, extra="ROZ NAYI KAHANI"),
    "cricket_ke_kisse": dict(bg=("#0B3D2E", "#03150E"), lines=[("CRICKET", "#FFFFFF"), ("KE KISSE", "#FFD400")],
                             font=ANTON, deco="six", tag="क्रिकेट के किस्से  ·  Cricket ki woh kahaniyan jo rongte khade kar dein.",
                             tag_font=MUKTA, extra="ROZ NAYA KISSA"),
    "picture_abhi_baaki_hai": dict(bg=("#2E0B3A", "#12041A"),
                                   lines=[("PICTURE", "#FFD700"), ("ABHI BAAKI", "#FFFFFF"), ("HAI", "#FF2E93")],
                                   font=BEBAS, deco="spot",
                                   banner_lines=[("PICTURE ", "#FFD700"), ("ABHI BAAKI ", "#FFFFFF"), ("HAI", "#FF2E93")],
                                   tag="पिक्चर अभी बाकी है  ·  Bollywood ke raaz, ek minute mein.", tag_font=MUKTA,
                                   extra="ROZ NAYE RAAZ"),
    "brain_snack": dict(bg=("#14002E", "#000000"), lines=[("BRAIN", "#00E5FF"), ("SNACK", "#FF00E5")], font=LUCKY,
                        deco="question", tag="Your daily dose of useless genius.", extra="NEW QUIZZES DAILY"),
    "bloop_and_friends": dict(bg=("#7FD6FA", "#C9F0FF"), lines=[("Bloop", "#FF4FD8"), ("& Friends", "#2E3A59")],
                              font=LUCKY, deco="bloop", ink="#2E3A59", tag="Sing, count and giggle with Bloop!",
                              extra="NEW SONGS EVERY WEEK"),
    "cosmos_unboxed": dict(bg=("#151A4A", "#05060F"), lines=[("COSMOS", "#E8ECFF"), ("UNBOXED", "#7C8CFF")],
                           font=BEBAS, deco="stars", tag="The universe, one jaw-dropping fact at a time.",
                           extra="NEW SPACE STORIES EVERY DAY"),
    "deep_blue_files": dict(bg=("#003A52", "#021820"), lines=[("DEEP BLUE", "#E6FAFF"), ("FILES", "#00D1FF")],
                            font=BEBAS, deco="waves", tag="95% of the ocean is unexplored. Let's go.",
                            extra="NEW OCEAN STORIES EVERY DAY"),
    "wild_instinct": dict(bg=("#2A2210", "#10140C"), lines=[("WILD", "#F4F1E8"), ("INSTINCT", "#F2B33D")],
                          font=ANTON, deco="claws", tag="Nature's most incredible true stories.",
                          extra="NEW WILDLIFE STORIES EVERY DAY"),
    "stream_clips": dict(bg=("#2A0F4F", "#0D0618"), lines=[("STREAM", "#FFFFFF"), ("CLIPS", "#9B5CFF")], font=ANTON,
                         deco="live", tag="The best moments from every stream.", extra="NEW CLIPS DAILY"),
}


def rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def text(t: str, font: str, color: str, size: int, alpha: int = 255) -> Image.Image:
    return Image.fromarray(text_rgba(t, str(FONTS / font), size, fill=(*rgb(color), alpha)), "RGBA")


def fit(t: str, font: str, color: str, max_w: float, max_h: float, alpha: int = 255) -> Image.Image:
    probe = text(t, font, color, 200)
    s = min(max_w / probe.width, max_h / probe.height)
    return text(t, font, color, max(8, int(200 * s)), alpha)


def background(w: int, h: int, top: str, bot: str, seed: int) -> Image.Image:
    a, b = np.array(rgb(top), np.float32), np.array(rgb(bot), np.float32)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    t = np.clip((yy / h) * 0.75 + (xx / w) * 0.25, 0, 1)[..., None]           # soft diagonal gradient
    img = a * (1 - t) + b * t
    r = np.sqrt(((xx - w / 2) / (w / 2)) ** 2 + ((yy - h / 2) / (h / 2)) ** 2)
    img *= (1 - 0.22 * np.clip(r - 0.55, 0, 1))[..., None]                      # light vignette
    img += np.random.default_rng(seed).normal(0, 3.0, (h, w, 1))                # fine grain
    return Image.fromarray(np.clip(img, 0, 255).astype(np.uint8), "RGB").convert("RGBA")


def glow(img: Image.Image, color: str, cx: float, cy: float, radius: float, alpha: int) -> None:
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill=(*rgb(color), alpha))
    img.alpha_composite(layer.filter(ImageFilter.GaussianBlur(radius * 0.45)))


def decorate(img: Image.Image, b: dict, accent: str, banner: bool, seed: int) -> None:
    """Faint background motif: adds texture without competing with the name."""
    W, H = img.size
    d, rng = b["deco"], np.random.default_rng(seed)
    big = H * (0.95 if not banner else 0.8)

    def faint(t: str, font: str, alpha: int = 34, scale: float = 1.0, at: tuple | None = None):
        g = fit(t, font, accent, W * 0.9 * scale, big * scale, alpha)
        x, y = at or ((W - g.width) / 2, (H - g.height) / 2)
        img.alpha_composite(g, (int(x), int(y)))

    if d in ("question", "quote", "dollar", "six", "fin", "clock"):
        glyph = {"question": "?", "quote": "“", "dollar": "$", "six": "6", "fin": "FIN", "clock": "0:01"}[d]
        font = POP if d == "quote" else (BEBAS if d in ("fin", "clock") else ANTON)
        if banner:                                                                 # motif on both sides of the name
            for x in (0.08, 0.80):
                faint(glyph, font, 30, 0.42, (W * x, H * 0.28))
        else:
            faint(glyph, font, 40 if d != "quote" else 55, 0.9 if d in ("fin", "clock") else 1.0)
    elif d == "bubble":                                                            # faint speech bubbles
        layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
        dr = ImageDraw.Draw(layer)
        spots = [(0.5, 0.5, 0.8)] if not banner else [(0.12, 0.45, 0.5), (0.88, 0.45, 0.5)]
        for cx, cy, k in spots:
            bw2, bh2 = H * 0.62 * k * (1.25 if not banner else 1.6), H * 0.42 * k * (1.2 if not banner else 1.4)
            x1, y1 = W * cx - bw2 / 2, H * cy - bh2 / 2
            dr.rounded_rectangle([x1, y1, x1 + bw2, y1 + bh2], radius=bh2 * 0.3, fill=(0, 0, 0, 22))
            dr.polygon([(x1 + bw2 * 0.22, y1 + bh2 - 2), (x1 + bw2 * 0.42, y1 + bh2 - 2), (x1 + bw2 * 0.16,
                        y1 + bh2 * 1.32)], fill=(0, 0, 0, 22))
        img.alpha_composite(layer)
    elif d in ("glow", "spot"):
        glow(img, accent, W / 2, H * 0.42, min(W, H) * 0.42, 70)
        if d == "spot":                                                            # stage spotlight beams
            layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
            dr = ImageDraw.Draw(layer)
            for sx in (0.15, 0.85):
                dr.polygon([(W * sx, 0), (W * sx - W * 0.06, 0), (W / 2 - W * 0.2, H), (W / 2 + W * 0.2, H)],
                           fill=(255, 255, 255, 18))
            img.alpha_composite(layer.filter(ImageFilter.GaussianBlur(W * 0.02)))
    elif d == "stars":
        dr = ImageDraw.Draw(img)
        for _ in range(int(W * H / 2500)):
            x, y, r = rng.uniform(0, W), rng.uniform(0, H), rng.choice([1, 1, 1, 2, 2, 3]) * W / 1600
            dr.ellipse([x - r, y - r, x + r, y + r], fill=(255, 255, 255, int(rng.uniform(70, 230))))
        glow(img, accent, W * 0.5, H * 0.5, min(W, H) * 0.45, 55)
    elif d == "waves":
        layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
        dr = ImageDraw.Draw(layer)
        for k in range(9):
            y0, amp, ph = H * (0.12 + k * 0.1), H * 0.025, k * 0.9
            pts = [(x, y0 + amp * math.sin(x / W * 6 * math.pi + ph)) for x in range(0, W + 20, 20)]
            dr.line(pts, fill=(*rgb(accent), 26), width=max(2, int(W / 400)))
        img.alpha_composite(layer)
        for _ in range(int(W * H / 30000)):                                        # rising bubbles
            x, y, r = rng.uniform(0, W), rng.uniform(0, H), rng.uniform(3, 10) * W / 1600
            ImageDraw.Draw(img).ellipse([x - r, y - r, x + r, y + r], outline=(230, 250, 255, 60),
                                        width=max(1, int(W / 900)))
    elif d == "claws":
        layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
        dr = ImageDraw.Draw(layer)
        spots = [(0.5, 0.5, 0.75)] if not banner else [(0.12, 0.5, 0.55), (0.88, 0.5, 0.55)]
        for cx, cy, s in spots:
            for k in (-1, 0, 1):
                x = W * cx + k * H * 0.13 * s
                dr.line([(x + H * 0.12 * s, H * cy - H * 0.38 * s), (x - H * 0.12 * s, H * cy + H * 0.38 * s)],
                        fill=(*rgb(accent), 38), width=int(H * 0.05 * s))
        img.alpha_composite(layer.filter(ImageFilter.GaussianBlur(H * 0.004)))
    elif d == "live":
        glow(img, accent, W / 2, H / 2, min(W, H) * 0.45, 60)


def live_badge(img: Image.Image, cx: float, y: float, h: float) -> None:
    lab = fit("LIVE", ANTON, "#FFFFFF", h * 4, h * 0.62)
    w = lab.width + h * 1.25
    x0 = cx - w / 2
    dr = ImageDraw.Draw(img)
    dr.rounded_rectangle([x0, y, x0 + w, y + h], radius=h / 2, fill=(229, 9, 20, 255))
    dr.ellipse([x0 + h * 0.3, y + h * 0.36, x0 + h * 0.58, y + h * 0.64], fill=(255, 255, 255, 255))
    img.alpha_composite(lab, (int(x0 + h * 0.8), int(y + (h - lab.height) / 2)))


def mascots(names: list[str], size: int) -> list[Image.Image]:
    import cv2
    from engine.kids import CAST
    from engine.media.mascot import Mascot
    out = []
    for i, n in enumerate(names):
        col, shape = CAST[n][0], CAST[n][1]
        bgra = Mascot(size=size, body=col, outline="#2E3A59", seed=i + 1, shape=shape).draw(0.2, mouth=0.5,
                                                                                            look=0.3)
        out.append(Image.fromarray(cv2.cvtColor(bgra, cv2.COLOR_BGRA2RGBA), "RGBA"))
    return out


def stack(img: Image.Image, lines: list[tuple[str, str]], font: str, box: tuple, gap: float = 0.06,
          shadow: bool = True) -> None:
    """Draw wordmark lines stacked and centred in box (x0, y0, w, h), each line as wide as the box allows."""
    x0, y0, bw, bh = box
    n = len(lines)
    parts = [fit(t, font, c, bw, bh / n * 0.95) for t, c in lines]
    total = sum(p.height for p in parts) + gap * bh * (n - 1)
    if total > bh:                                                                 # shrink everything to fit height
        k = bh / total
        parts = [fit(t, font, c, p.width * k, p.height * k) for (t, c), p in zip(lines, parts)]
        total = bh
    y = y0 + (bh - total) / 2
    for p in parts:
        x = x0 + (bw - p.width) / 2
        if shadow:
            sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
            a = np.array(p)
            a[..., :3] = 0
            a[..., 3] = (a[..., 3] * 0.55).astype(np.uint8)
            sh.alpha_composite(Image.fromarray(a, "RGBA"), (int(x), int(y + p.height * 0.05)))
            img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(p.height * 0.05)))
        img.alpha_composite(p, (int(x), int(y)))
        y += p.height + gap * bh


def row(img: Image.Image, parts: list[tuple[str, str]], font: str, box: tuple) -> float:
    """One line made of differently coloured words, fitted to box; returns the bottom y.
    Pieces are drawn separately (text images are tightly cropped), so the word space is added here."""
    x0, y0, bw, bh = box
    parts = [(t.strip(), c) for t, c in parts]
    probe = [text(t, font, c, 200) for t, c in parts]
    sp = 200 * 0.22
    w = sum(p.width for p in probe) + sp * (len(probe) - 1)
    s = min(bw / w, bh / max(p.height for p in probe))
    pcs = [text(t, font, c, int(200 * s)) for t, c in parts]
    sp *= s
    w, h = sum(p.width for p in pcs) + sp * (len(pcs) - 1), max(p.height for p in pcs)
    y = y0
    sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
    x = x0 + (bw - w) / 2
    for p in pcs:
        a = np.array(p)
        a[..., :3] = 0
        a[..., 3] = (a[..., 3] * 0.55).astype(np.uint8)
        sh.alpha_composite(Image.fromarray(a, "RGBA"), (int(x), int(y + h - p.height + h * 0.05)))
        x += p.width + sp
    img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(h * 0.05)))
    x = x0 + (bw - w) / 2
    for p in pcs:
        img.alpha_composite(p, (int(x), int(y + h - p.height)))                   # bottoms aligned
        x += p.width + sp
    return y + h


def avatar(cid: str, b: dict) -> Image.Image:
    S = 1080
    accent = b["lines"][-1][1]
    img = background(S, S, *b["bg"], seed=hash(cid) % 1000)
    decorate(img, b, accent, False, 7)
    if b["deco"] == "bloop":
        m = mascots(["Bloop"], 760)[0]
        img.alpha_composite(m, ((S - m.width) // 2, int(S * 0.47 - m.height / 2)))
        return img.convert("RGB")
    box = (S * 0.17, S * 0.24, S * 0.66, S * 0.52)                                 # inside the circle crop
    if b["deco"] == "live":
        live_badge(img, S / 2, S * 0.17, S * 0.085)
        box = (S * 0.17, S * 0.30, S * 0.66, S * 0.48)
    stack(img, b["lines"], b["font"], box, gap=0.04)
    return img.convert("RGB")


def banner(cid: str, b: dict, W: int, H: int, safe: tuple[int, int]) -> Image.Image:
    accent = b["lines"][-1][1]
    img = background(W, H, *b["bg"], seed=hash(cid) % 1000 + 1)
    decorate(img, b, accent, True, 11)
    sw, sh = safe
    x0, y0 = (W - sw) / 2, (H - sh) / 2
    ink = b.get("ink", "#FFFFFF")
    if b["deco"] == "bloop":                                                       # the cast on both sides
        cast = mascots(["Bloop", "Pip", "Mo", "Dee"], int(sh * 0.9))
        for i, m in enumerate(cast):                                               # 2 left, 2 right, mirrored
            x = x0 - sh * (1.15 if i in (0, 3) else 0.5)
            x = x if i < 2 else W - x - m.width
            img.alpha_composite(m, (int(x), int(y0 + sh - m.height)))
        bottom = row(img, [("Bloop", "#FF4FD8"), ("&", "#FFB300"), ("Friends", "#2E3A59")], LUCKY,
                     (x0 + sw * 0.12, y0 + sh * 0.12, sw * 0.76, sh * 0.42))
        g = fit(b["tag"], POP, ink, sw * 0.8, sh * 0.15)
        img.alpha_composite(g, (int((W - g.width) / 2), int(bottom + sh * 0.1)))
        return img.convert("RGB")
    parts = b.get("banner_lines") or [(t + " ", c) for t, c in b["lines"][:-1]] + [b["lines"][-1]]
    bottom = row(img, parts, b.get("banner_font", b["font"]), (x0 + sw * 0.04, y0 + sh * 0.06, sw * 0.92, sh * 0.5))
    g = fit(b["tag"], b.get("tag_font", POP), ink, sw * 0.86, sh * 0.13)
    img.alpha_composite(g, (int((W - g.width) / 2), int(bottom + sh * 0.07)))
    pill_h = sh * 0.14
    lab = fit(b["extra"], POP, b["bg"][1] if b.get("ink") is None else "#FFFFFF", sw * 0.6, pill_h * 0.5)
    pw = lab.width + pill_h * 1.2
    py = bottom + sh * 0.07 + g.height + sh * 0.07
    py = min(py, y0 + sh - pill_h)
    dr = ImageDraw.Draw(img)
    dr.rounded_rectangle([(W - pw) / 2, py, (W + pw) / 2, py + pill_h], radius=pill_h / 2,
                         fill=(*rgb(accent if b.get("ink") is None else b["ink"]), 255))
    img.alpha_composite(lab, (int((W - lab.width) / 2), int(py + (pill_h - lab.height) / 2)))
    if b["deco"] == "live":
        live_badge(img, W / 2, y0 - sh * 0.2, sh * 0.14)                         # above the name, clear of it
    return img.convert("RGB")


def preview(items: list[tuple[str, Path]]) -> None:
    """Contact sheet: each avatar as a circle (how the platforms crop it) + its banner with the safe area marked."""
    th, gap = 427, 24
    sheet = Image.new("RGB", (th + 760 + gap * 3, len(items) * (th + gap) + gap), (40, 40, 46))
    dr = ImageDraw.Draw(sheet)
    for i, (cid, d) in enumerate(items):
        y = gap + i * (th + gap)
        a = Image.open(d / "avatar.png").resize((th, th))
        mask = Image.new("L", (th, th), 0)
        ImageDraw.Draw(mask).ellipse([0, 0, th, th], fill=255)
        sheet.paste(a, (gap, y), mask)
        bn = Image.open(d / "youtube_banner.jpg").resize((760, int(760 * 1440 / 2560)))
        bx = gap * 2 + th
        sheet.paste(bn, (bx, y + (th - bn.height) // 2))
        k = 760 / 2560
        sx, sy = bx + (2560 - 1546) / 2 * k, y + (th - bn.height) // 2 + (1440 - 423) / 2 * k
        dr.rectangle([sx, sy, sx + 1546 * k, sy + 423 * k], outline=(0, 255, 0), width=1)
    sheet.save(OUT / "preview.png")


def main(only: list[str]) -> None:
    done = []
    for cid, b in BRANDS.items():
        if only and cid not in only:
            continue
        d = OUT / cid
        d.mkdir(parents=True, exist_ok=True)
        avatar(cid, b).save(d / "avatar.png", optimize=True)
        banner(cid, b, 2560, 1440, (1546, 423)).save(d / "youtube_banner.jpg", quality=92)
        if cid != "bloop_and_friends":                                             # no Facebook Page for the kids channel
            banner(cid, b, 1640, 624, (1100, 330)).save(d / "facebook_cover.jpg", quality=92)
        done.append((cid, d))
        print("made", cid, flush=True)
    preview(done)
    print("preview:", OUT / "preview.png")


if __name__ == "__main__":
    main(sys.argv[1:])
