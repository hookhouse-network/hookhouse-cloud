"""Thumbnails v4 (owner, 11 Nov: the v3 red-glow cut-out stickers and text panels looked "too outdated").

The 2026 look, from research_notes/.../thumbnails_titles.md and mrbeast_cocomelon_seo_trends_2026-11-11.md:
- the whole frame is one bright, saturated photo (no panels, stickers, arrows or glow outlines);
- the subject is big (about 80% of the height, at least 45%), sharp and slightly lifted, while the background is
  softly blurred and darkened: depth, like a phone's portrait mode;
- text is 0-3 big words (2-5 for Hindi), in clean white with a soft shadow, on the side away from the subject.
  The second line or last word is in the channel's accent colour;
- nothing in the bottom-right corner, where YouTube shows the video length.
Three variants per long video for YouTube's Test & Compare (V1 no text, V2 hook, V3 other picture + hook), plus a
vertical 1080x1920 cover for Shorts/Reels in the same style.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter

from .thumbnail import TH, TW, _fit, _render_text

# colour grade per channel: saturation, brightness, contrast, tint colour, tint amount
GRADES = {
    "unsolved_after_dark": (1.05, 0.96, 1.12, (20, 60, 90), 0.10),
    "clutch_tales": (1.30, 1.05, 1.12, (255, 170, 60), 0.06),
    "ending_decoded": (1.20, 1.02, 1.14, (14, 80, 90), 0.08),
    "money_cheat_codes": (1.22, 1.08, 1.08, None, 0.0),
    "itihaas_ke_raaz": (1.25, 1.04, 1.12, (255, 153, 51), 0.10),
    "cricket_ke_kisse": (1.30, 1.05, 1.12, (255, 200, 80), 0.05),
    "picture_abhi_baaki_hai": (1.28, 1.05, 1.10, (255, 60, 140), 0.05),
    "cosmos_unboxed": (1.25, 1.02, 1.15, (60, 70, 200), 0.10),
    "deep_blue_files": (1.25, 1.02, 1.12, (0, 140, 200), 0.10),
    "wild_instinct": (1.25, 1.04, 1.10, (240, 180, 80), 0.06),
}
DEFAULT_GRADE = (1.22, 1.04, 1.10, None, 0.0)

# text colours per niche (thumbnails §8 T1-T8): (first line, last line, numbers)
COLORS = {
    "unsolved_after_dark": ("#F5F5F5", "#FF2B2B", None),        # T1: one word in red
    "clutch_tales": ("#FFFFFF", "#FFE600", "#FFE600"),          # T2: the stat in yellow
    "ending_decoded": ("#FFFFFF", "#E50914", None),
    "money_cheat_codes": ("#FFFFFF", "#00E676", None),           # T4: key token in gain green
    "itihaas_ke_raaz": ("#FFD54A", "#FFFFFF", None),             # T6: line 1 gold
    "cricket_ke_kisse": ("#FFFFFF", "#FFFFFF", "#FFD400"),       # T7: numbers in yellow
    "picture_abhi_baaki_hai": ("#FFD23F", "#FFFFFF", None),      # T8: Latin keyword gold, Devanagari payoff white
}
MAX_WORDS = {"ending_decoded": 2}                                # T3: no text by default; variant max 2 words
EXPORT = 3                                                       # thumbnails §8: lay out at 1280x720, export x3 (4K)

_SESSION = None
_MASKS: dict[int, tuple] = {}          # id(image) -> (image, mask): each picture is cut out once per run


def _mask(img: Image.Image) -> np.ndarray | None:
    """Soft 0-1 mask of the main subject, or None when there isn't one clear subject (or rembg is missing)."""
    hit = _MASKS.get(id(img))
    if hit is not None and hit[0] is img:
        return hit[1]
    m = _mask_uncached(img)
    if len(_MASKS) > 32:
        _MASKS.clear()
    _MASKS[id(img)] = (img, m)
    return m


def _mask_uncached(img: Image.Image) -> np.ndarray | None:
    global _SESSION
    if min(img.size) < 480:
        return None
    try:
        from rembg import new_session, remove
    except ImportError:
        return None
    if _SESSION is None:
        _SESSION = new_session("u2net")
    small = img.copy()
    small.thumbnail((1024, 1024))
    a = np.asarray(remove(small, session=_SESSION, only_mask=True), np.float32) / 255.0
    cover = (a > 0.5).mean()
    if not 0.05 <= cover <= 0.70:
        return None
    return np.asarray(Image.fromarray((a * 255).astype(np.uint8)).resize(img.size, Image.BILINEAR), np.float32) / 255


def _grade(img: Image.Image, grade: tuple) -> Image.Image:
    sat, bright, contrast, tint, amt = grade
    img = ImageEnhance.Color(img).enhance(sat)
    img = ImageEnhance.Brightness(img).enhance(bright)
    img = ImageEnhance.Contrast(img).enhance(contrast)
    if tint and amt:
        img = Image.blend(img, Image.new("RGB", img.size, tint), amt)
    return img


def _frame(img: Image.Image, W: int, H: int, target_x: float, subj_h: float, top: float,
           mask: np.ndarray | None) -> tuple[Image.Image, np.ndarray | None, float]:
    """Scale and crop img to W x H so the subject is about subj_h*H tall, its centre near target_x*W and its top near
    top*H. Returns the crop, the matching mask and the subject's centre x (0-1) in the crop."""
    cover = max(W / img.width, H / img.height)
    if mask is not None:
        ys, xs = np.nonzero(mask > 0.5)
        x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
        s = max(cover, min(subj_h * H / max(1, y1 - y0), 2.0, 2.2 * cover))   # never blow a photo up past 2x
        cx, ty = (x0 + x1) / 2 * s, y0 * s
    else:
        s, cx, ty = cover, img.width * cover / 2, 0.0
    rw, rh = int(img.width * s) + 1, int(img.height * s) + 1
    left = int(np.clip(cx - target_x * W, 0, rw - W))
    up = int(np.clip(ty - top * H, 0, rh - H)) if mask is not None else (rh - H) // 2
    crop = img.resize((rw, rh), Image.LANCZOS).crop((left, up, left + W, up + H))
    m = None
    if mask is not None:
        m_img = Image.fromarray((mask * 255).astype(np.uint8)).resize((rw, rh), Image.BILINEAR)
        m = np.asarray(m_img.crop((left, up, left + W, up + H)), np.float32) / 255
    return crop, m, (cx - left) / W


def _depth(crop: Image.Image, m: np.ndarray | None, grade: tuple) -> Image.Image:
    """Sharp, slightly lifted subject over a softly blurred, darker background. Without a mask: a soft vignette."""
    sharp = ImageEnhance.Sharpness(_grade(crop, grade)).enhance(1.35)
    W, H = crop.size
    if m is None:
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        d = np.sqrt(((xx - W / 2) / (W * 0.65)) ** 2 + ((yy - H / 2) / (H * 0.65)) ** 2)
        k = np.clip(1 - 0.35 * d ** 2, 0.45, 1)[..., None]
        return Image.fromarray((np.asarray(sharp, np.float32) * k).clip(0, 255).astype(np.uint8))
    bg = ImageEnhance.Brightness(sharp.filter(ImageFilter.GaussianBlur(max(3, W // 220)))).enhance(0.72)
    fg = ImageEnhance.Brightness(sharp).enhance(1.06)
    a = np.asarray(Image.fromarray((m * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(2)), np.float32)[..., None] / 255
    out = np.asarray(fg, np.float32) * a + np.asarray(bg, np.float32) * (1 - a)
    return Image.fromarray(out.clip(0, 255).astype(np.uint8))


def _shade(img: Image.Image, side: str, strength: float = 0.5) -> Image.Image:
    """Gentle dark gradient under the text (no hard panel), so white words read on any photo."""
    W, H = img.size
    if side in ("left", "right"):
        r = np.clip(1 - np.linspace(0, 1, W, dtype=np.float32) / 0.55, 0, 1)
        r = r if side == "left" else r[::-1]
        k = 1 - strength * r[None, :, None] ** 1.5
    else:
        r = np.clip(1 - np.linspace(0, 1, H, dtype=np.float32) / 0.45, 0, 1)
        r = r if side == "top" else r[::-1]
        k = 1 - strength * r[:, None, None] ** 1.5
    return Image.fromarray((np.asarray(img, np.float32) * k).clip(0, 255).astype(np.uint8))


ARTICLES = {"a", "an", "the", "of", "to", "and", "in", "on", "at", "for", "with", "from", "by", "is", "are", "was",
            "were", "almost", "every", "each", "all", "more", "most", "just", "very", "so", "but", "or", "their",
            "his", "its", "this", "that", "ek", "ki", "ka", "ke", "se", "ne", "ko", "aur", "mein"}


def _trim(words: list[str]) -> list[str]:
    while len(words) > 1 and words[-1].lower().strip(".,!?") in ARTICLES:   # never end on "A", "THE", "KI"...
        words = words[:-1]
    return words


def hook_lines(hook: str, language: str, max_words: int | None = None) -> list[str]:
    """At most 2 short lines. The writer's 'line 1 | line 2' is kept whole when it is short (<= 5 words); a longer
    hook keeps only its first line. Lines never end on a dangling article."""
    hook = (hook or "").strip()
    if not hook:
        return []
    parts = [p.strip() for p in hook.split("|") if p.strip()][:2]
    # research (thumbnails §8): US 0-3 words and 15 characters max; Hindi 2-5 words
    limit = max_words or (5 if language == "hi" else 3)
    if language != "hi":
        if len(parts) == 2 and (sum(len(p.split()) for p in parts) > limit or len("".join(parts).replace(" ", "")) > 15):
            parts = parts[:1]
        ws = _trim(parts[0].split()[:limit])
        while len(ws) > 1 and len("".join(ws)) > 15:
            ws = _trim(ws[:-1])
        if len(parts) == 2:                     # a line may end on "THE" when the next line completes it
            return [parts[0], " ".join(_trim(parts[1].split()))]
        if len(ws) == 1 or len(" ".join(ws)) <= 9:
            return [" ".join(ws)]
        k = (len(ws) + 1) // 2 if len(ws) > 3 else len(ws) - 1
        return [" ".join(ws[:k]), " ".join(ws[k:])]
    if len(parts) == 2 and sum(len(p.split()) for p in parts) > limit:
        parts = parts[:1]
    if len(parts) == 2:
        return [" ".join(_trim(p.split())) for p in parts]
    ws = parts[0].split()
    if len(ws) > limit:                       # too long: stop at a sentence end, else keep it whole if nearly short
        ends = [i for i, w in enumerate(ws[:limit]) if w[-1:] in ".!?…"]
        ws = ws[:ends[-1] + 1] if ends else (ws if len(ws) <= limit + 2 else _trim(ws[:limit]))
    if len(ws) == 1 or len(" ".join(ws)) <= 9:
        return [" ".join(ws)]
    k = (len(ws) + 1) // 2 if len(ws) > 3 else len(ws) - 1     # short hooks: the last word alone, as the accent
    return [" ".join(ws[:k]), " ".join(ws[k:])]


def cover_lines(label: str, language: str) -> list[str]:
    """Vertical covers: the whole hook (up to 9 words) in up to 3 lines, never cut mid-sentence on a dangling word."""
    ws = _trim(label.replace("|", " ").split()[:6])            # cover C1: 2-6 words
    n = 1 if len(ws) <= 2 else 2 if len(ws) <= 4 else 3       # big C1 label (Anton ~110 px cap): short lines
    sizes = [len(ws) // n + (1 if i < len(ws) % n else 0) for i in range(n)]     # balanced: 7 words -> 3, 2, 2
    out, i = [], 0
    for k in sizes:
        out.append(" ".join(ws[i:i + k]))
        i += k
    return out


def text_items(lines: list[str], language: str, accent: str, x: int, y: int, max_w: int, max_size: int,
               align: int, colors: tuple | None = None, min_size: int | None = None) -> list[dict]:
    """White words, accent on the last line, soft shadow. align: 7 top-left, 9 top-right, 1 bottom-left, 8 top-centre.
    Research minimums (1280x720 layout, measured in libass): Anton cap = 0.50 x size -> 220 = 110 px cap;
    Mukta Devanagari body ~0.42 x size -> 200 = ~85 px."""
    import re as _re
    from .shaping import needs_shaping
    items = []
    sizes = []
    for ln in lines:
        font = "Mukta ExtraBold" if needs_shaping(ln) else "Anton"
        txt = ln if font == "Mukta ExtraBold" else ln.upper()
        lo = min_size or (200 if font == "Mukta ExtraBold" else 220)
        sizes.append((txt, font, _fit(txt, font, max_w, max(max_size, lo), lo)))
    step = [int(fs * (0.80 if f == "Mukta ExtraBold" else 0.62)) for _, f, fs in sizes]
    if align in (1, 2, 3):                                   # bottom-anchored: stack upwards
        y -= sum(step[1:])
    yy = y
    for i, (txt, font, fs) in enumerate(sizes):
        last = i == len(sizes) - 1 and len(sizes) > 1
        first_c, last_c, num_c = colors or ("#FFFFFF", accent, None)
        fg = last_c if last else first_c
        if num_c and _re.search(r"\d", txt):                     # T2/T7: the number carries the colour
            fg = num_c
        items.append({"text": txt, "font": font, "size": fs, "x": x, "y": yy, "align": align,
                      "fg": fg, "outline": 3, "shadow": 7, "shadow_alpha": 0x50, "blur": 1.5})
        yy += step[i]
    return items


def _hero_pick(images: list[Image.Image]) -> list[Image.Image]:
    """Prefer, among the 3 most relevant pictures, one with a clear subject (the list arrives sorted by relevance)."""
    if len(images) < 2:
        return images
    top = images[:3]
    scored = [(0 if _mask(im) is None else 1, -i, im) for i, im in enumerate(top)]
    scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
    return [im for _, _, im in scored] + images[3:]


def _text_spot(crop: Image.Image, m: np.ndarray | None) -> str:
    """Where the words cover the least: top-left ('left'), top-right ('right') or bottom-left ('bottom').
    Cost = how much of the subject is there + how busy (edgy) the picture is there. Never bottom-right (the badge)."""
    g = np.asarray(crop.convert("L").resize((128, 72)), np.float32)
    edges = np.abs(np.diff(g, axis=0))[:, :-1] + np.abs(np.diff(g, axis=1))[:-1, :]
    edges = edges / (edges.mean() + 1e-6)
    subj = (np.asarray(Image.fromarray((m * 255).astype(np.uint8)).resize((127, 71)), np.float32) / 255
            if m is not None else np.zeros_like(edges))
    boxes = {"left": (slice(0, 32), slice(0, 58)), "right": (slice(0, 32), slice(69, 127)),
             "bottom": (slice(42, 71), slice(0, 72))}
    cost = {k: 6.0 * subj[b].mean() + 0.25 * edges[b].mean() for k, b in boxes.items()}
    cost["bottom"] -= 0.05                       # slight preference: bottom-left reads naturally
    return min(cost, key=cost.get)


def landscape(img: Image.Image, hook: str, language: str, accent: str, grade: tuple, out: Path,
              alt: bool = False, colors: tuple | None = None, max_words: int | None = None) -> Path:
    """One 1280x720 thumbnail. Subject on the right third, text top-left; a wide subject stays centred with the text
    bottom-left (never bottom-right: the video-length badge)."""
    m = _mask(img)
    wide = m is not None and np.ptp(np.nonzero(m > 0.5)[1]) > 0.55 * img.width
    target = 0.5 if (m is None or wide) else 0.66
    if alt:                                   # same subject, other side and a closer frame (Test & Compare V3)
        target = 1.0 - target if target != 0.5 else 0.34
    crop, cm, cx = _frame(img, TW, TH, target, 0.95 if alt else 0.82, 0.05 if alt else 0.08, m)
    canvas = _depth(crop, cm, grade)
    lines = hook_lines(hook, language, max_words)
    if not lines:
        return _save(canvas, out)
    big = canvas.resize((TW * EXPORT, TH * EXPORT), Image.LANCZOS)     # text is drawn at 4K (layout stays 1280x720)
    spot = _text_spot(crop, cm)
    if alt and spot != "bottom":
        spot = "left" if spot == "right" else "right"
    side = {"bottom": "bottom", "left": "left"}.get(spot, "right")
    big = _shade(big, side, 0.55 if side == "bottom" else 0.5)
    if spot == "bottom":
        items = text_items(lines, language, accent, 56, TH - 40, 820, 240, 1, colors)
    elif spot == "left":
        items = text_items(lines, language, accent, 56, 48, 620, 260, 7, colors)
    else:
        items = text_items(lines, language, accent, TW - 56, 48, 620, 260, 9, colors)
    return _small_enough(_render_text(big, items, out, language))


def vertical_cover(img: Image.Image, label: str, language: str, out: Path, strip: str | None = None,
                   accent: str = "#FFD400", grade: tuple = DEFAULT_GRADE, colors: tuple | None = None) -> Path:
    """1080x1920 Shorts/Reels cover: subject in the middle (inside Instagram's 3:4 grid crop), boxless words on top.
    `strip` is accepted for older callers and ignored (no text boxes any more)."""
    from . import thumbnail as T
    W, H = 1080, 1920
    m = _mask(img)
    # cover C1: subject centred around y 600-1250 and >= 45% of the height; nothing important above y 300
    crop, cm, _ = _frame(img, W, H, 0.5, 0.46, 0.27, m)
    canvas = _shade(_depth(crop, cm, grade), "top", 0.55)
    lines = cover_lines(label or "", language)
    old = (T.TW, T.TH)
    try:                                   # the shared text renderer works in TW x TH coordinates
        T.TW, T.TH = W, H
        if not lines:
            return _save(canvas, out)
        # C1: label block at y 430-800, kept left of x 850 (x 90-850), 2-6 words
        return _render_text(canvas, text_items(lines, language, accent, 470, 430, 760, 260, 8, colors), out, language)
    finally:
        T.TW, T.TH = old


def make_set(channel: dict, images: list[Path], hook: str, out_dir: Path, cover_label: str = "",
             v3_same: bool = False) -> list[Path]:
    """3 long-form variants (V1 no text, V2 hook, V3 other picture + hook) and a vertical cover."""
    lang = channel.get("language", "en")
    accent = (channel.get("style") or {}).get("highlight_color") or "#FFD400"
    grade = GRADES.get(channel.get("id", ""), DEFAULT_GRADE)
    colors = COLORS.get(channel.get("id", ""))
    mw = MAX_WORDS.get(channel.get("id", ""))
    imgs = [Image.open(p).convert("RGB") for p in images if Path(p).exists()] or [Image.new("RGB", (TW, TH), (20, 20, 30))]
    # keep the relevance order from rank_heroes (subject + first-shot rule); re-sorting by "clean cut-out" once swapped
    # the real 1980 game photo for a posed 1950s team photo
    out = []
    v3_img = imgs[0] if v3_same else imgs[1 % len(imgs)]
    for name, img, text, alt in (("v1_notext", imgs[0], "", False), ("v2_hook", imgs[0], hook, False),
                                 ("v3_alt", v3_img, hook, v3_same or v3_img is imgs[0])):
        out.append(landscape(img, text, lang, accent, grade, out_dir / f"thumbnail_{name}.jpg", alt=alt,
                             colors=colors, max_words=mw))
    out.append(vertical_cover(imgs[0], cover_label or hook.split("|")[0], lang, out_dir / "cover_vertical.jpg",
                              accent=accent, grade=grade, colors=colors))
    return out


def cover_for(channel: dict, img: Image.Image, label: str, out: Path) -> Path:
    """Vertical cover with the channel's accent and grade (used for Reel covers)."""
    return vertical_cover(img, label, channel.get("language", "en"), out,
                          accent=(channel.get("style") or {}).get("highlight_color") or "#FFD400",
                          grade=GRADES.get(channel.get("id", ""), DEFAULT_GRADE), colors=COLORS.get(channel.get("id", "")))


def _save(canvas: Image.Image, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if canvas.size == (TW, TH):                                  # 4K export (thumbnails §8)
        canvas = canvas.resize((TW * EXPORT, TH * EXPORT), Image.LANCZOS)
    canvas.convert("RGB").save(path, quality=92)
    return _small_enough(path)


def _small_enough(path: Path, limit: int = 1_950_000) -> Path:
    """YouTube's thumbnail upload limit is 2 MB: re-save with lower JPEG quality until it fits."""
    q = 90
    while path.exists() and path.stat().st_size > limit and q >= 60:
        Image.open(path).convert("RGB").save(path, quality=q, optimize=True)
        q -= 6
    return path
