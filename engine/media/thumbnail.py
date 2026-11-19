"""Thumbnails v2 (1280x720) — 3 styles for YouTube's built-in thumbnail test.

A. "lallantop": news-explainer look. Bold headline on colour strips (white / red / yellow),
   cut-out subject with a white outline, red arrow, channel tag, red bottom bar.
B. "mrbeast":   one huge subject, bright saturated background, 1-3 giant words.
C. "question":  two-picture collage with a big "?" / question headline.

Pictures are built with Pillow; all text is drawn by libass (through ffmpeg) because it shapes
Hindi correctly. Text must match the video (YouTube removes misleading clickbait).
"""
from __future__ import annotations

import os
import textwrap
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

from . import ffmpeg
from .captions import ass_color
from .fonts import FONTS_DIR, ensure_fonts, title_font

TW, TH = 1280, 720


def _cover(img: Image.Image, w: int, h: int, focus_x: float = 0.5) -> Image.Image:
    scale = max(w / img.width, h / img.height)
    img = img.resize((int(img.width * scale) + 1, int(img.height * scale) + 1), Image.LANCZOS)
    left = int((img.width - w) * focus_x)
    top = (img.height - h) // 2
    return img.crop((left, top, left + w, top + h))


def _pop(img: Image.Image, color: float = 1.45, contrast: float = 1.25, sharp: float = 1.6) -> Image.Image:
    img = ImageEnhance.Color(img).enhance(color)
    img = ImageEnhance.Contrast(img).enhance(contrast)
    return ImageEnhance.Sharpness(img).enhance(sharp)


def _fit(text: str, font: str, max_w: int, max_size: int, min_size: int = 60) -> int:
    """Biggest font size (up to max_size) at which `text` fits in max_w pixels."""
    from .captions import _text_width
    w = _text_width(text, font, max_size)
    return max(min_size, min(max_size, int(max_size * max_w / max(w, 1))))


def _card(img: Image.Image, w: int, h: int, rot: float = 3.0, border: int = 12) -> Image.Image:
    """Photo as a white-bordered, slightly tilted card with a soft shadow (RGBA)."""
    photo = _pop(_cover(img, w, h))
    card = Image.new("RGBA", (w + 2 * border, h + 2 * border), "white")
    card.paste(photo, (border, border))
    pad = 40
    out = Image.new("RGBA", (card.width + 2 * pad, card.height + 2 * pad), (0, 0, 0, 0))
    out.alpha_composite(Image.new("RGBA", card.size, (0, 0, 0, 170)), (pad + 10, pad + 14))
    out = out.filter(ImageFilter.GaussianBlur(12))
    out.alpha_composite(card, (pad, pad))
    return out.rotate(rot, resample=Image.BICUBIC, expand=True)


def _cutout(img: Image.Image, source_short_side: int = 9999) -> Image.Image | None:
    """Cut out the main subject — only when there is one clear subject (10-60% of the image)
    and the photo is sharp enough (small photos look blurry once cut out and enlarged)."""
    if source_short_side < 650:
        return None
    try:
        from rembg import new_session, remove
    except ImportError:
        return None
    out = remove(img, session=new_session("u2net"))
    coverage = (np.asarray(out)[..., 3] > 128).mean()
    return out if 0.10 <= coverage <= 0.60 else None


def _outline(subj: Image.Image, color: str = "#FFFFFF", width: int = 10, glow: str | None = None) -> Image.Image:
    """White sticker-style outline (+ optional colour glow) around a cut-out."""
    alpha = subj.split()[3]
    pad = width * 3
    big = Image.new("RGBA", (subj.width + 2 * pad, subj.height + 2 * pad), (0, 0, 0, 0))
    a = Image.new("L", big.size, 0)
    a.paste(alpha, (pad, pad))
    if glow:
        g = Image.new("RGBA", big.size, glow)
        g.putalpha(a.filter(ImageFilter.MaxFilter(width * 2 + 1)).filter(ImageFilter.GaussianBlur(width * 1.5)))
        big.alpha_composite(g)
    o = Image.new("RGBA", big.size, color)
    o.putalpha(a.filter(ImageFilter.MaxFilter(width * 2 + 1)))
    big.alpha_composite(o)
    big.alpha_composite(subj, (pad, pad))
    return big


def _arrow(draw: ImageDraw.ImageDraw, tip: tuple[int, int], angle_deg: float, length: int = 230,
           color: str = "#FF1E1E") -> None:
    """Thick red arrow with white outline pointing at `tip`."""
    a = np.radians(angle_deg)
    d = np.array([np.cos(a), np.sin(a)])
    n = np.array([-d[1], d[0]])
    tip = np.array(tip, float)
    head_len, head_w, shaft_w = length * 0.42, length * 0.36, length * 0.14
    base = tip - d * head_len
    tail = tip - d * length
    pts = [tip, base + n * head_w, base + n * shaft_w / 2, tail + n * shaft_w / 2,
           tail - n * shaft_w / 2, base - n * shaft_w / 2, base - n * head_w]
    pts = [tuple(map(int, p)) for p in pts]
    draw.polygon(pts, fill="white")
    shrink = [tuple(map(int, tip + (np.array(p) - tip) * 0.86 - d * 10)) for p in pts]
    draw.polygon(shrink, fill=color)


def _text_ass(items: list[dict], language: str) -> str:
    """items: {text, font, size, x, y, fg, bg (strip colour or None), outline, align (7=top-left, 5=center), rot}"""
    sp = 0   # letter spacing 0 keeps Hindi letters joined
    head = ["[Script Info]", "ScriptType: v4.00+", f"PlayResX: {TW}", f"PlayResY: {TH}", "WrapStyle: 2",
            "ScaledBorderAndShadow: yes", "", "[V4+ Styles]",
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, "
            "Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
            "MarginL, MarginR, MarginV, Encoding",
            f"Style: T,Anton,80,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,{sp},0,1,8,0,7,0,0,0,1",
            "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]
    for i, it in enumerate(items):
        tags = [f"\\an{it.get('align', 7)}", f"\\pos({it['x']},{it['y']})", f"\\fn{it['font']}",
                f"\\fs{it['size']}", f"\\1c{ass_color(it.get('fg', '#FFFFFF'))}"]
        if it.get("bg"):
            r, g, b = (int(it["bg"].lstrip("#")[k:k + 2], 16) for k in (0, 2, 4))
            if (0.299 * r + 0.587 * g + 0.114 * b) / 255 > 0.6:     # light strip (yellow/white): black text
                tags[4] = f"\\1c{ass_color('#000000')}"
            tags += ["\\bord14" if it.get("pad") is None else f"\\bord{it['pad']}", f"\\3c{ass_color(it['bg'])}",
                     "\\shad0"]
            style_box = True
        else:
            tags += [f"\\bord{it.get('outline', 10)}", "\\3c&H000000&", f"\\shad{it.get('shadow', 6)}",
                     "\\4c&H000000&"]
            if it.get("shadow_alpha") is not None:                 # 0 = solid, 255 = invisible (soft drop shadow)
                tags.append(f"\\4a&H{int(it['shadow_alpha']):02X}&")
            if it.get("blur"):
                tags.append(f"\\blur{it['blur']}")
            style_box = False
        if it.get("rot"):
            tags.append(f"\\frz{it['rot']}")
        text = it["text"].replace("{", "(").replace("}", ")")
        # Strips use the "Box" style (opaque box behind the text), the rest the outlined "T" style
        if style_box:
            head.append(f"Dialogue: {i * 2},0:00:00.00,0:00:05.00,Box,,0,0,0,,{{{''.join(tags)}}}{text}")
        else:
            head.append(f"Dialogue: {i * 2 + 1},0:00:00.00,0:00:05.00,T,,0,0,0,,{{{''.join(tags)}}}{text}")
    # strip style with opaque box
    box_style = (f"Style: Box,Anton,80,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,{sp},0,3,14,0,7,"
                 f"0,0,0,1")
    head.insert(head.index("[Events]") - 1, box_style)
    return "\n".join(head) + "\n"


def _render_text(base: Image.Image, items: list[dict], out: Path, language: str) -> Path:
    ensure_fonts()
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp_png = out.with_suffix(".base.png")
    tmp_ass = out.with_suffix(".ass")
    base.convert("RGB").save(tmp_png)
    tmp_ass.write_text(_text_ass(items, language), encoding="utf-8")
    fonts_rel = os.path.relpath(FONTS_DIR, out.parent).replace("\\", "/")
    ffmpeg.run(["-i", tmp_png.name, "-vf", f"subtitles={tmp_ass.name}:fontsdir={fonts_rel}",
                "-frames:v", "1", "-q:v", "2", out.name], cwd=out.parent)
    tmp_png.unlink(missing_ok=True)
    tmp_ass.unlink(missing_ok=True)
    return out


def _lines(text: str, width: int) -> list[str]:
    return textwrap.wrap(text, width=width)[:3] or [text]


# ---------------- styles ----------------
def lallantop(image: Path, headline: str, out: Path, *, sub: str = "", channel_name: str = "",
              accent: str = "#E50914", language: str = "en") -> Path:
    src = Image.open(image).convert("RGB")
    subj = _cutout(_cover(src, TW, TH, 0.6), min(src.size))
    bg = _pop(_cover(src, TW, TH, 0.6)).filter(ImageFilter.GaussianBlur(14))   # subject/card sits sharp on top
    # darken the left side where the headline sits
    grad = np.linspace(0.3, 0.85, TW)[None, :, None] ** 0.8
    canvas = Image.fromarray((np.asarray(bg).astype(np.float32) * grad).astype(np.uint8)).convert("RGBA")
    if subj is not None:
        bbox = subj.getbbox() or (0, 0, TW, TH)
        crop = subj.crop(bbox)
        k = min(TH * 0.98 / crop.height, TW * 0.5 / crop.width)
        crop = crop.resize((int(crop.width * k), int(crop.height * k)), Image.LANCZOS)
        sticker = _outline(crop, "#FFFFFF", 9, glow=accent)
        x, y = TW - sticker.width + 20, TH - sticker.height + 25
        canvas.alpha_composite(sticker, (x, max(y, -20)))
        tip = (x + 40, TH // 2 - 30)
    else:                     # no clean cut-out: show the photo as a tilted "evidence" card
        card = _card(src, 560, 400, rot=-4)
        x, y = TW - card.width + 10, (TH - 64 - card.height) // 2
        canvas.alpha_composite(card, (x, y))
        tip = (x + 50, TH // 2 - 20)
    draw = ImageDraw.Draw(canvas)
    _arrow(draw, tip, 200, 210)
    # red bottom bar + channel tag
    draw.rectangle((0, TH - 64, TW, TH), fill=accent)
    upper = language == "en"
    font = title_font(language, "clips" if language == "en" else "story")
    lines = _lines(headline.upper() if upper else headline, 11 if upper else 14)
    gap = 18
    max_h = (TH - 64 - 60 - gap * (len(lines) - 1)) / len(lines)
    items, y = [], 40
    colors = [("#FFFFFF", "#000000"), ("#FFE600", None), ("#FFFFFF", accent)]
    for i, line in enumerate(lines):
        fg, bg_col = colors[i % 3]
        size = min(_fit(line, font, 560, 170), int(max_h / 1.15))
        if bg_col:
            items.append({"text": line, "font": font, "size": size, "x": 50, "y": y, "fg": fg, "bg": bg_col,
                          "rot": -2 if i % 2 == 0 else 0})
        else:
            items.append({"text": line, "font": font, "size": size, "x": 44, "y": y, "fg": fg,
                          "outline": 12, "rot": -2})
        y += int(size * 1.15) + gap
    if sub:
        sub_t = sub.upper() if upper else sub
        items.append({"text": sub_t, "font": "Poppins Black", "size": min(42, _fit(sub_t, "Poppins Black", TW - 60, 42)),
                      "x": 30, "y": TH - 58, "fg": "#FFFFFF", "outline": 0, "shadow": 0})
    if channel_name:
        items.append({"text": channel_name.upper(), "font": "Poppins Black", "size": 30, "x": TW - 30, "y": 22,
                      "fg": "#FFFFFF", "bg": "#000000", "align": 9, "pad": 8})
    return _render_text(canvas, items, out, language)


def mrbeast(image: Path, words: str, out: Path, *, accent: str = "#FFE600", language: str = "en") -> Path:
    src = Image.open(image).convert("RGB")
    bg = _pop(_cover(src, TW, TH, 0.5), color=1.6, contrast=1.3)
    canvas = bg.filter(ImageFilter.GaussianBlur(6)).convert("RGBA")
    subj = _cutout(_cover(src, TW, TH, 0.5), min(src.size))
    if subj is not None:
        bbox = subj.getbbox() or (0, 0, TW, TH)
        crop = subj.crop(bbox)
        k = min(TH * 1.05 / crop.height, TW * 0.62 / crop.width)
        crop = crop.resize((int(crop.width * k), int(crop.height * k)), Image.LANCZOS)
        sticker = _outline(crop, "#FFFFFF", 7, glow=accent)
        canvas.alpha_composite(sticker, (int(TW * 0.36), TH - sticker.height + 30))
    else:
        canvas = bg.convert("RGBA")
    upper = language == "en"
    lines = _lines(words.upper() if upper else words, 9 if upper else 11)
    font = "Anton" if language == "en" else title_font(language)
    # one size for all lines: the biggest that fits the left ~55% and the frame height
    size = min(min(_fit(l, font, 640, 230) for l in lines), int((TH - 80) / (len(lines) * 1.12)))
    items, y = [], 40
    for i, line in enumerate(lines):
        items.append({"text": line, "font": font, "size": size, "x": 40, "y": y,
                      "fg": accent if i == len(lines) - 1 else "#FFFFFF", "outline": 13, "shadow": 8,
                      "rot": -4})
        y += int(size * 1.12)
    return _render_text(canvas, items, out, language)


def question(images: list[Path], headline: str, out: Path, *, accent: str = "#E50914", language: str = "en") -> Path:
    imgs = [Image.open(p).convert("RGB") for p in images[:2]]
    if len(imgs) == 1:     # one photo: wide shot on the left, tight close-up on the right
        im = imgs[0]
        cw, ch = int(im.width * 0.55), int(im.height * 0.55)
        x0, y0 = int(im.width * 0.4) - cw // 2 + cw // 4, int(im.height * 0.42) - ch // 2
        x0, y0 = max(0, min(x0, im.width - cw)), max(0, min(y0, im.height - ch))
        imgs.append(im.crop((x0, y0, x0 + cw, y0 + ch)))
    left = _pop(_cover(imgs[0], TW // 2, TH))
    right = _pop(_cover(imgs[1], TW // 2, TH))
    canvas = Image.new("RGBA", (TW, TH))
    canvas.paste(left, (0, 0))
    canvas.paste(right, (TW // 2, 0))
    draw = ImageDraw.Draw(canvas)
    draw.polygon([(TW // 2 - 14, 0), (TW // 2 + 30, 0), (TW // 2 + 14, TH), (TW // 2 - 30, TH)], fill="white")
    upper = language == "en"
    font = title_font(language, "clips" if upper else "story")
    lines = _lines(headline.upper() if upper else headline, 16)[:2]
    size = min(_fit(l, font, TW - 160, 110) for l in lines)
    step = int(size * 1.25)
    items = [{"text": "?", "font": "Anton", "size": 300, "x": TW // 2, "y": TH // 2 - 60, "fg": "#FFE600",
              "outline": 14, "align": 5, "rot": 8}]
    y = TH - 40 - step * len(lines)
    for i, line in enumerate(lines):
        items.append({"text": line, "font": font, "size": size, "x": TW // 2, "y": y, "align": 8,
                      "fg": "#FFFFFF", "bg": accent if i % 2 == 0 else "#000000"})
        y += step
    return _render_text(canvas, items, out, language)


def make_set(images: list[Path], thumb: dict, out_dir: Path, *, accent: str, language: str,
             channel_name: str = "", pair: list[Path] | None = None) -> list[Path]:
    """3 thumbnails for the A/B test. `thumb` = the script's thumbnail plan."""
    images = [p for p in images if p and Path(p).exists()]
    if not images:
        return []
    head = " ".join(x for x in (thumb.get("text"), thumb.get("text_line2")) if x) or "WATCH THIS"
    q = thumb.get("question") or head
    out = [lallantop(images[0], head, out_dir / "thumbnail_1_lallantop.jpg", sub=thumb.get("question", ""),
                     channel_name=channel_name, accent=accent, language=language),
           mrbeast(images[0], thumb.get("text") or head, out_dir / "thumbnail_2_mrbeast.jpg",
                   accent="#FFE600", language=language),
           question([p for p in (pair or images[:2]) if Path(p).exists()] or images[:1], q, out_dir / "thumbnail_3_question.jpg", accent=accent, language=language)]
    return out


# Older helper kept for the CLI
