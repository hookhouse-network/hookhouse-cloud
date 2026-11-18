"""Documentary graphics for "text" beats (v3): a themed full-screen picture instead of a plain gradient slab.

Each channel gets its own family, so channels never share one template:
- casefile   (mysteries, movies):  a paper case card on a dark desk, typewriter text, red stamp
- scoreboard (sports, cricket):    stadium lights + scoreboard panel with big LED-style numbers
- proof      (money):              clean navy background, white proof card, big number, mini chart
- parchment  (mythology/history):  warm parchment with an ornate border (Devanagari-safe fonts)
- poster     (film business):      retro cinema-poster look with halftone dots
All drawn by our own code with free commercial-use fonts (OFL / Apache-2.0).
"""
from __future__ import annotations

import math
import re
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .fonts import font_file
from .shaping import pil_draw_text, pil_text_length

STYLE_BY_CHANNEL = {
    "unsolved_after_dark": "casefile", "ending_decoded": "casefile", "clutch_tales": "scoreboard",
    "cricket_ke_kisse": "scoreboard", "money_cheat_codes": "proof", "itihaas_ke_raaz": "parchment",
    "picture_abhi_baaki_hai": "poster", "cosmos_unboxed": "proof", "deep_blue_files": "proof",
    "wild_instinct": "parchment",
}


def _font(family: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(font_file(family)), size)


def _fit(draw: ImageDraw.ImageDraw, text: str, family: str, max_w: int, size: int, min_size: int = 40):
    if any("ऀ" <= ch <= "ॿ" for ch in text):   # shaped Devanagari draws wider than measured: keep a margin
        max_w = int(max_w * 0.85)
    while size > min_size:
        f = _font(family, size)
        if pil_text_length(draw, text, f) <= max_w:
            return f
        size -= 4
    return _font(family, min_size)


def _wrap2(draw, text: str, family: str, max_w: int, size: int, min_size: int = 60, max_h: int | None = None):
    """One or two balanced lines at the biggest size that fits the width and (two lines) the panel height."""
    words = text.split()
    one = _fit(draw, text, family, max_w, size, min_size)
    if one.size >= size * 0.8 or len(words) < 2:
        return [text], one
    tall = 1.3 if any("\u0900" <= ch <= "\u097F" for ch in text) else 1.05     # Devanagari matras need room
    best = None
    for k in range(1, len(words)):
        a, b = " ".join(words[:k]), " ".join(words[k:])
        f = _fit(draw, max(a, b, key=len), family, max_w, size, min_size)
        if max_h and f.size * 2 * tall > max_h:
            f = _font(family, max(min_size, int(max_h / (2 * tall))))
        if best is None or f.size > best[1].size:
            best = ([a, b], f)
    if best[1].size <= one.size * 1.15:                 # two lines barely bigger: one line reads better
        return [text], one
    return best


def _noise(h: int, w: int, rng, scale: float = 1.0) -> np.ndarray:
    small = rng.normal(0, 1, (max(2, h // 8), max(2, w // 8))).astype(np.float32)
    big = cv2.resize(small, (w, h), interpolation=cv2.INTER_CUBIC)
    fine = rng.normal(0, 0.5, (h, w)).astype(np.float32)
    return (big + fine) * scale


def _vignette(img: np.ndarray, strength: float = 0.55) -> np.ndarray:
    h, w = img.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    d = np.sqrt(((xx - w / 2) / (w * 0.7)) ** 2 + ((yy - h / 2) / (h * 0.7)) ** 2)
    k = np.clip(1 - strength * d ** 1.6, 0.15, 1)[..., None]
    return (img.astype(np.float32) * k).clip(0, 255).astype(np.uint8)


def _to_pil(bgr: np.ndarray) -> Image.Image:
    return Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))


def _to_bgr(img: Image.Image) -> np.ndarray:
    return cv2.cvtColor(np.array(img.convert("RGB")), cv2.COLOR_RGB2BGR)


# ---------- styles ----------

def casefile(big: str, sub: str, size, rng, language="en", accent="#B3261E") -> np.ndarray:
    W, H = size
    yy = np.arange(H, dtype=np.float32)[:, None]
    grain = np.sin(yy / 9 + _noise(H, W, rng, 2.5)) * 10           # wood grain
    desk = np.dstack([18 + grain + _noise(H, W, rng, 4), 22 + grain * 1.1 + _noise(H, W, rng, 4),
                      30 + grain * 1.2 + _noise(H, W, rng, 4)]).clip(0, 255).astype(np.uint8)
    desk = _vignette(desk, 0.6)
    base = _to_pil(desk).convert("RGBA")
    pw, ph = (int(W * 0.72), int(H * 0.46)) if H > W else (int(W * 0.46), int(H * 0.74))   # 16:9: a real page, not a strip
    paper = Image.new("RGBA", (pw, ph), (239, 230, 210, 255))
    pn = (_noise(ph, pw, rng, 6) + 0).clip(-20, 20)
    arr = np.array(paper).astype(np.float32)
    arr[..., :3] += pn[..., None]
    paper = Image.fromarray(arr.clip(0, 255).astype(np.uint8))
    d = ImageDraw.Draw(paper)
    typew = "Special Elite" if language == "en" else "Mukta ExtraBold"
    d.text((50, 40), "CASE FILE  No. " + str(rng.integers(1000, 9999)), font=_font(typew, 40), fill=(60, 50, 40))
    d.line((50, 100, pw - 50, 100), fill=(120, 100, 80), width=3)
    for k in range(7):                                             # faint typed lines
        y = ph - 330 + k * 34
        d.rectangle((50, y, 50 + int(rng.uniform(0.45, 0.85) * (pw - 100)), y + 10), fill=(205, 195, 175))
    family = "Bebas Neue" if language == "en" else "Khand"
    lines, f = _wrap2(d, big.upper() if language == "en" else big, family, pw - 110, min(230, int(ph * 0.3)),
                      max_h=max(200, ph - 520))
    y = 150
    for ln in lines:
        w = pil_text_length(d, ln, f)
        pil_draw_text(paper, ((pw - w) / 2, y), ln, f, (28, 26, 24))
        y += int(f.size * 0.95)
    if sub:                                                         # red rubber stamp
        st = sub.upper() if language == "en" else sub
        words = st.split()
        if len(words) > 4:                                          # a stamp is a few words, not a sentence
            words = words[:4]
            while len(words) > 1 and words[-1].lower().strip(",;:") in ("with", "and", "of", "the", "a", "to", "in",
                                                                         "on", "for", "at", "from", "by", "or"):
                words.pop()
            st = " ".join(words).rstrip(",;:")
        sf = _fit(d, st, "Poppins Black" if language == "en" else "Mukta ExtraBold", int(pw * 0.62), 74, 30)
        tw = int(pil_text_length(d, st, sf))
        stamp = Image.new("RGBA", (tw + 60, sf.size + 50), (0, 0, 0, 0))
        sd = ImageDraw.Draw(stamp)
        r, g, b = int(accent[1:3], 16), int(accent[3:5], 16), int(accent[5:7], 16)
        sd.rectangle((4, 4, tw + 56, sf.size + 46), outline=(r, g, b, 230), width=8)
        pil_draw_text(stamp, (30, 18), st, sf, (r, g, b, 230))
        stamp = stamp.rotate(-7, expand=True, resample=Image.BICUBIC)
        room = ph - 20 - (y + 24)                                   # space left under the headline
        if stamp.height > room and room > 40:                       # shrink to fit; never cover the headline
            k = room / stamp.height
            stamp = stamp.resize((max(1, int(stamp.width * k)), max(1, int(stamp.height * k))), Image.LANCZOS)
        if stamp.height <= room:
            paper.alpha_composite(stamp, (int((pw - stamp.width) / 2), y + 24))
    clip_ = Image.new("RGBA", (70, 170), (0, 0, 0, 0))              # paper clip
    ImageDraw.Draw(clip_).rounded_rectangle((10, 10, 60, 160), radius=25, outline=(170, 170, 175, 255), width=9)
    paper.alpha_composite(clip_, (pw - 150, -40 if False else 0))
    shadow = Image.new("RGBA", (pw + 80, ph + 80), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rectangle((40, 50, pw + 40, ph + 60), fill=(0, 0, 0, 150))
    shadow = shadow.filter(ImageFilter.GaussianBlur(22))
    rot = float(rng.uniform(-2.2, 2.2))
    shadow, paper = shadow.rotate(rot, expand=True, resample=Image.BICUBIC), paper.rotate(rot, expand=True, resample=Image.BICUBIC)
    cx, cy = W // 2, int(H * (0.37 if H > W else 0.47))     # Shorts: page ends ~0.60 H, above the caption band (~1250)
    base.alpha_composite(shadow, (cx - shadow.width // 2 + 10, cy - shadow.height // 2 + 20))
    base.alpha_composite(paper, (cx - paper.width // 2, cy - paper.height // 2))
    return _to_bgr(base)


def scoreboard(big: str, sub: str, size, rng, language="en", accent="#FFB000") -> np.ndarray:
    W, H = size
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    bg = np.zeros((H, W, 3), np.float32)
    bg[..., 0], bg[..., 1], bg[..., 2] = 40, 22, 10                  # deep navy (BGR)
    for cx_, cy_ in ((W * 0.15, H * 0.08), (W * 0.85, H * 0.06), (W * 0.5, H * 0.02)):   # floodlights
        g = np.exp(-(((xx - cx_) ** 2 + (yy - cy_) ** 2) / (2 * (W * 0.22) ** 2)))
        bg += g[..., None] * np.array([190, 220, 255], np.float32) * 0.55
    rows = (np.sin(yy / 7) > 0.6) * (yy > H * 0.62) * 14             # crowd rows hint
    bg += rows[..., None]
    img = _to_pil(_vignette(bg.clip(0, 255).astype(np.uint8), 0.5)).convert("RGBA")
    d = ImageDraw.Draw(img)
    pw, ph = int(W * 0.86), int(H * (0.27 if H > W else 0.30))
    x0, y0 = (W - pw) // 2, int(H * (0.25 if H > W else 0.33))       # Shorts: sub-line ends above the captions
    d.rounded_rectangle((x0 - 10, y0 - 10, x0 + pw + 10, y0 + ph + 10), radius=30, fill=(15, 15, 18, 255),
                        outline=(80, 80, 90, 255), width=6)
    for k in range(0, pw, 14):                                       # LED dot texture
        d.line((x0 + k, y0 + 8, x0 + k, y0 + ph - 8), fill=(22, 22, 26, 255), width=2)
    family = "Teko" if language == "en" else "Khand"
    lines, f = _wrap2(d, big.upper() if language == "en" else big, family, pw - 80, 300, 80, max_h=ph - 40)
    r, g, b = int(accent[1:3], 16), int(accent[3:5], 16), int(accent[5:7], 16)
    total_h = int(len(lines) * f.size * 0.92)
    y = y0 + (ph - total_h) // 2 - int(f.size * 0.08)
    glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    for ln in lines:
        w = pil_text_length(d, ln, f)
        pil_draw_text(glow, ((W - w) / 2, y), ln, f, (r, g, b, 255))
        y += int(f.size * 0.92)
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(14)))
    img.alpha_composite(glow)
    if sub:
        sf = _fit(d, sub.upper() if language == "en" else sub, "Poppins Black" if language == "en" else "Mukta ExtraBold",
                  pw - 60, 70, 34)
        st = sub.upper() if language == "en" else sub
        w = pil_text_length(d, st, sf)
        pil_draw_text(img, ((W - w) / 2, y0 + ph + 50), st, sf, (255, 255, 255, 255))
    return _to_bgr(img)


def proof(big: str, sub: str, size, rng, language="en", accent="#22C55E") -> np.ndarray:
    W, H = size
    t = np.linspace(0, 1, H, dtype=np.float32)[:, None, None]
    top, bot = np.array([60, 30, 14], np.float32), np.array([30, 14, 8], np.float32)
    bg = np.repeat((top * (1 - t) + bot * t), W, axis=1)
    img = _to_pil(bg.clip(0, 255).astype(np.uint8)).convert("RGBA")
    grid = Image.new("RGBA", img.size, (0, 0, 0, 0))                # subtle grid on its own layer
    gd_ = ImageDraw.Draw(grid)
    for k in range(0, W, 60):
        gd_.line((k, 0, k, H), fill=(255, 255, 255, 14), width=1)
    for k in range(0, H, 60):
        gd_.line((0, k, W, k), fill=(255, 255, 255, 14), width=1)
    img.alpha_composite(grid)
    d = ImageDraw.Draw(img)
    cw, ch = int(W * 0.84), int(H * (0.40 if H > W else 0.44))
    x0, y0 = (W - cw) // 2, int(H * (0.20 if H > W else 0.27))       # Shorts: card ends ~0.60 H (captions below)
    shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle((x0 + 10, y0 + 24, x0 + cw + 10, y0 + ch + 24), radius=40, fill=(0, 0, 0, 120))
    img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(20)))
    d.rounded_rectangle((x0, y0, x0 + cw, y0 + ch), radius=40, fill=(255, 255, 255, 255))
    r, g, b = int(accent[1:3], 16), int(accent[3:5], 16), int(accent[5:7], 16)
    lines, f = _wrap2(d, big, "Poppins Black", cw - 90, 200, 70, max_h=ch - 260)
    y = y0 + 70
    for ln in lines:
        w = pil_text_length(d, ln, f)
        pil_draw_text(img, (x0 + (cw - w) / 2, y), ln, f, (r, g, b, 255))
        y += int(f.size * 1.05)
    if sub:                                    # measured: Poppins digits reach ~1.25 x size below the line top
        sf = _fit(d, sub, "Poppins ExtraBold", cw - 90, 60, 30)
        w = pil_text_length(d, sub, sf)
        pil_draw_text(img, (x0 + (cw - w) / 2, y + int(f.size * 0.25) + 14), sub, sf, (40, 40, 50, 255))
    pts, v = [], 0.5                                                  # mini rising chart at the bottom of the card
    for k in range(12):
        v = min(0.95, max(0.05, v + rng.uniform(-0.08, 0.14)))
        pts.append((x0 + 60 + k * (cw - 120) / 11, y0 + ch - 60 - v * 150))
    d.line(pts, fill=(r, g, b, 255), width=10, joint="curve")
    return _to_bgr(img)


def parchment(big: str, sub: str, size, rng, language="hi", accent="#8B1E1E") -> np.ndarray:
    W, H = size
    base = np.dstack([np.full((H, W), 175, np.float32), np.full((H, W), 214, np.float32), np.full((H, W), 236, np.float32)])
    n = _noise(H, W, rng, 9)
    stain = cv2.GaussianBlur((rng.random((H // 20, W // 20)) * 40).astype(np.float32), (0, 0), 3)
    stain = cv2.resize(stain, (W, H))
    base = (base + n[..., None] - stain[..., None] * np.array([1.0, 0.8, 0.5])).clip(0, 255).astype(np.uint8)
    img = _to_pil(_vignette(base, 0.75)).convert("RGBA")
    d = ImageDraw.Draw(img)
    r, g, b = int(accent[1:3], 16), int(accent[3:5], 16), int(accent[5:7], 16)
    for inset, wdt in ((50, 8), (72, 3)):                            # double ornate border
        d.rectangle((inset, inset, W - inset, H - inset), outline=(r, g, b, 255), width=wdt)
    for cx_, cy_ in ((50, 50), (W - 50, 50), (50, H - 50), (W - 50, H - 50)):
        d.ellipse((cx_ - 22, cy_ - 22, cx_ + 22, cy_ + 22), fill=(r, g, b, 255))
    family = "Rozha One" if language == "hi" else "Bebas Neue"
    lines, f = _wrap2(d, big, family, W - 220, 200, 70, max_h=int(H * 0.30))
    total_h = int(len(lines) * f.size * 1.15)
    y = int(H * 0.42) - total_h // 2
    for ln in lines:
        w = pil_text_length(d, ln, f)
        pil_draw_text(img, ((W - w) / 2, y), ln, f, (60, 20, 15, 255))
        y += int(f.size * 1.15)
    if sub:
        sf = _fit(d, sub, "Mukta ExtraBold", W - 260, 70, 34)
        w = pil_text_length(d, sub, sf)
        pil_draw_text(img, ((W - w) / 2, y + 20), sub, sf, (r, g, b, 255))
    if H > W:                                  # Shorts: darken behind the caption band (white words on light paper)
        fade = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        fd = ImageDraw.Draw(fade)
        y0 = int(H * 0.575)
        for yy in range(y0, H):
            fd.line((0, yy, W, yy), fill=(30, 15, 10, int(190 * min(1.0, (yy - y0) / (H * 0.04)))))
        img.alpha_composite(fade)
    return _to_bgr(img)


def poster(big: str, sub: str, size, rng, language="hi", accent="#E63946") -> np.ndarray:
    W, H = size
    r, g, b = int(accent[1:3], 16), int(accent[3:5], 16), int(accent[5:7], 16)
    img = Image.new("RGBA", (W, H), (245, 225, 190, 255))
    d = ImageDraw.Draw(img)
    for yy in range(0, H, 28):                                        # halftone dots
        for xx in range(0, W, 28):
            rad = 2 + 9 * (yy / H)
            d.ellipse((xx - rad, yy - rad, xx + rad, yy + rad), fill=(r, g, b, 70))
    top_f, bot_f = (0.28, 0.555) if H > W else (0.36, 0.64)       # Shorts: band ends above the caption line (y~1250)
    d.rectangle((0, int(H * top_f), W, int(H * bot_f)), fill=(25, 20, 30, 255))
    family = "Bebas Neue" if language == "en" else "Khand"
    band_h = int(H * (bot_f - top_f))
    room = int(H * 0.075) if (H > W and sub) else 0         # Shorts: keep the sub line clear of a 2-line headline
    lines, f = _wrap2(d, big.upper() if language == "en" else big, family, W - 120, 260, 80,
                      max_h=min(int(H * 0.27), band_h - room - 40))
    total_h = int(len(lines) * f.size * 0.95)
    portrait = H > W
    mid = (top_f + bot_f) / 2 - (room / H / 2 if (portrait and sub) else 0.0)   # Shorts: headline centred above the sub
    y = int(H * mid) - total_h // 2
    for ln in lines:
        w = pil_text_length(d, ln, f)
        pil_draw_text(img, ((W - w) / 2 + 8, y + 8), ln, f, (r, g, b, 255))
        pil_draw_text(img, ((W - w) / 2, y), ln, f, (255, 240, 210, 255))
        y += int(f.size * 0.95)
    if sub:
        sf = _fit(d, sub, "Poppins Black" if language == "en" else "Mukta ExtraBold", W - 200, 64, 30)
        w = pil_text_length(d, sub, sf)
        if portrait:                           # inside the dark band, clear of the caption line below
            pil_draw_text(img, ((W - w) / 2, int(H * bot_f) - int(sf.size * 1.6)), sub, sf, (r, g, b, 255))
        else:
            pil_draw_text(img, ((W - w) / 2, int(H * 0.68)), sub, sf, (25, 20, 30, 255))
    if H > W:                                  # Shorts: darken behind the caption line (white words on yellow are hard)
        fade = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        fd = ImageDraw.Draw(fade)
        y0 = int(H * 0.565)                    # dark from ~y 1150 so the caption band (centre ~1250) reads clearly
        for yy in range(y0, H):
            a_ = int(215 * min(1.0, (yy - y0) / (H * 0.035)))
            fd.line((0, yy, W, yy), fill=(20, 16, 24, a_))
        img.alpha_composite(fade)
    return _to_bgr(img)


STYLES = {"casefile": casefile, "scoreboard": scoreboard, "proof": proof, "parchment": parchment, "poster": poster}


NUM = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?")
MONTHS = re.compile(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\b", re.I)


def count_frames(big: str, n: int) -> list[str]:
    """Texts for a count-up: every number in `big` rises from 0 to its value (keeps commas, *, $, words)."""
    if MONTHS.search(big or ""):                                    # dates never count up
        return [big] * n
    nums = [m for m in NUM.finditer(big) if not (len(m.group(0)) == 4 and 1000 <= int(m.group(0)) <= 2100)]
    if not nums:
        return [big] * n
    out = []
    for k in range(n):
        p = (k + 1) / n
        p = 1 - (1 - p) ** 3                                       # fast start, gentle landing
        s, last = "", 0
        for m in nums:
            raw = m.group(0)
            val = float(raw.replace(",", ""))
            cur = val * p
            txt = (f"{cur:,.0f}" if "," in raw else f"{cur:.0f}") if "." not in raw else f"{cur:.1f}"
            s += big[last:m.start()] + txt
            last = m.end()
        out.append(s + big[last:])
    return out


def animated_text_graphic(channel: dict, big: str, sub: str, size: tuple[int, int], out_mp4: Path, seed: int = 0,
                          count_s: float = 0.9, fps: int = 30) -> Path | None:
    """Short clip: the graphic's numbers count up, then hold (the camera keeps moving in the shot).
    Returns None when the text has no number (use the still graphic instead)."""
    if count_frames(big or "", 2)[0] == (big or ""):              # nothing to count (dates, years, words)
        return None
    import subprocess
    from . import ffmpeg as ff
    texts = count_frames(big, max(2, int(count_s * fps)))
    frames_dir = out_mp4.with_suffix("")
    frames_dir.mkdir(parents=True, exist_ok=True)
    for k, txt in enumerate(dict.fromkeys(texts)):                # unique texts only, then repeat by index
        text_graphic(channel, txt, sub, size, frames_dir / f"u{k:03d}.png", seed=seed)
    uniq = list(dict.fromkeys(texts))
    lst = frames_dir / "list.txt"
    with open(lst, "w", encoding="utf-8") as fh:
        for txt in texts:
            fh.write(f"file 'u{uniq.index(txt):03d}.png'\nduration {1 / fps:.4f}\n")
        fh.write(f"file 'u{len(uniq) - 1:03d}.png'\nduration 4\nfile 'u{len(uniq) - 1:03d}.png'\n")
    subprocess.run([ff.ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0",
                    "-i", str(lst), "-vf", f"fps={fps},format=yuv420p", "-c:v", "libx264", "-preset", "veryfast",
                    "-crf", "16", str(out_mp4)], check=True)
    return out_mp4


def text_graphic(channel: dict, big: str, sub: str, size: tuple[int, int], out_path: Path, seed: int = 0) -> Path:
    style = (channel.get("style") or {}).get("graphics") or STYLE_BY_CHANNEL.get(channel.get("id", ""), "casefile")
    accent = (channel.get("style") or {}).get("highlight_color")
    fn = STYLES.get(style, casefile)
    rng = np.random.default_rng(seed)
    kwargs = {"language": channel.get("language", "en")}
    if accent and style in ("scoreboard", "proof", "poster"):
        kwargs["accent"] = accent
    img = fn(big or "", sub or "", size, rng, **kwargs)
    cv2.imwrite(str(out_path), img, [cv2.IMWRITE_PNG_COMPRESSION, 3])
    return out_path
