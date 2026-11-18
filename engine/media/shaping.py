"""Correct text shaping for Hindi (Devanagari) and other complex scripts in images we draw ourselves.

Pillow on Windows has no text-shaping engine (no raqm), so it breaks Devanagari conjuncts and vowel signs
("पुत्र" comes out as "पुतर"). Here HarfBuzz (uharfbuzz, Apache-2.0) shapes the text and FreeType
(freetype-py, BSD; FreeType licence) draws the glyphs. Video captions don't need this: libass already shapes.
"""
from __future__ import annotations

import re
from functools import lru_cache

import cv2
import numpy as np

COMPLEX = re.compile(r"[ऀ-෿؀-ۿ]")       # Indic + Arabic ranges


def needs_shaping(text: str) -> bool:
    return bool(COMPLEX.search(text or ""))


@lru_cache(maxsize=32)
def _hb_font(path: str):
    import uharfbuzz as hb
    blob = hb.Blob.from_file_path(path)
    face = hb.Face(blob)
    font = hb.Font(face)
    return font, face.upem


@lru_cache(maxsize=32)
def _ft_face(path: str):
    import freetype
    return freetype.Face(path)


def _shape(text: str, path: str, size: int):
    import uharfbuzz as hb
    font, upem = _hb_font(path)
    buf = hb.Buffer()
    buf.add_str(text)
    buf.guess_segment_properties()
    hb.shape(font, buf, {"kern": True, "liga": True})
    k = size / upem
    glyphs, pen = [], 0.0
    for info, pos in zip(buf.glyph_infos, buf.glyph_positions):
        glyphs.append((info.codepoint, pen + pos.x_offset * k, pos.y_offset * k))
        pen += pos.x_advance * k
    return glyphs, pen


def text_width(text: str, path: str, size: int) -> float:
    return _shape(text, path, size)[1]


def render_line(text: str, path: str, size: int) -> tuple[np.ndarray, int]:
    """Grey mask (uint8) of one shaped line and its baseline y."""
    import freetype
    face = _ft_face(path)
    face.set_char_size(int(size * 64))
    glyphs, width = _shape(text, path, size)
    asc = face.size.ascender / 64
    desc = -face.size.descender / 64
    pad = int(size * 0.3)
    h = int(asc + desc) + 2 * pad
    w = int(width) + 2 * pad + size
    mask = np.zeros((h, w), np.uint8)
    base = int(pad + asc)
    for gid, x, y in glyphs:
        face.load_glyph(gid, freetype.FT_LOAD_DEFAULT | freetype.FT_LOAD_TARGET_NORMAL)
        face.glyph.render(freetype.FT_RENDER_MODE_NORMAL)
        bmp = face.glyph.bitmap
        if bmp.width == 0 or bmp.rows == 0:
            continue
        g = np.array(bmp.buffer, np.uint8).reshape(bmp.rows, bmp.pitch)[:, :bmp.width]
        x0 = int(round(pad + x + face.glyph.bitmap_left))
        y0 = int(round(base - y - face.glyph.bitmap_top))
        x1, y1 = min(w, x0 + g.shape[1]), min(h, y0 + g.shape[0])
        if x1 <= max(0, x0) or y1 <= max(0, y0):
            continue
        sub = g[max(0, -y0):y1 - y0, max(0, -x0):x1 - x0]
        region = mask[max(0, y0):y1, max(0, x0):x1]
        np.maximum(region, sub, out=region)
    return mask, base


def text_rgba(text: str, path: str, size: int, fill=(255, 255, 255, 255), stroke: int = 0,
              stroke_fill=(0, 0, 0, 255), line_gap: float = 1.15, align: str = "center") -> np.ndarray:
    """RGBA image of (multi-line) text, tightly cropped, with optional outline."""
    lines = text.split("\n")
    masks = [render_line(ln, path, size)[0] for ln in lines]
    lh = int(size * line_gap)
    w = max(m.shape[1] for m in masks) + 2 * stroke
    h = lh * (len(lines) - 1) + masks[-1].shape[0] + 2 * stroke
    full = np.zeros((h, w), np.uint8)
    for i, m in enumerate(masks):
        x = stroke + ((w - 2 * stroke - m.shape[1]) // 2 if align == "center" else 0)
        y = stroke + i * lh
        region = full[y:y + m.shape[0], x:x + m.shape[1]]
        np.maximum(region, m[:region.shape[0], :region.shape[1]], out=region)
    out = np.zeros((h, w, 4), np.uint8)
    if stroke:
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * stroke + 1, 2 * stroke + 1))
        sm = cv2.dilate(full, k)
        out[..., :3] = stroke_fill[:3]
        out[..., 3] = (sm.astype(np.float32) * stroke_fill[3] / 255).astype(np.uint8)
    a = full.astype(np.float32) / 255.0 * (fill[3] / 255.0)
    for c in range(3):
        out[..., c] = (fill[c] * a + out[..., c] * (1 - a)).astype(np.uint8)
    out[..., 3] = np.maximum(out[..., 3], (a * 255).astype(np.uint8))
    ys, xs = np.where(out[..., 3] > 0)
    if len(xs):
        out = out[max(0, ys.min() - 2):ys.max() + 3, max(0, xs.min() - 2):xs.max() + 3]
    return out


def pil_draw_text(img, xy, text: str, font, fill, stroke_width: int = 0, stroke_fill=None) -> None:
    """Drop-in for ImageDraw.text(xy, text, font=font, fill=fill) that shapes complex scripts correctly.
    `img` is a PIL RGBA image; xy is the top-left like Pillow (approximately)."""
    from PIL import Image, ImageColor, ImageDraw
    if not needs_shaping(text):
        ImageDraw.Draw(img).text(xy, text, font=font, fill=fill, stroke_width=stroke_width, stroke_fill=stroke_fill)
        return
    rgba = ImageColor.getrgb(fill) if isinstance(fill, str) else tuple(fill)
    rgba = tuple(rgba) + (255,) * (4 - len(rgba))
    sf = stroke_fill or (0, 0, 0, 255)
    sf = (ImageColor.getrgb(sf) if isinstance(sf, str) else tuple(sf))
    sf = tuple(sf) + (255,) * (4 - len(sf))
    arr = text_rgba(text, font.path, font.size, rgba, stroke_width, sf)
    asc = font.getmetrics()[0]
    # place so the shaped text's top roughly matches where Pillow would put it
    top_offset = int(asc - font.size * 0.80)
    img.alpha_composite(Image.fromarray(arr), (int(xy[0]), int(xy[1] + top_offset)))


def pil_text_length(draw, text: str, font) -> float:
    if needs_shaping(text):
        return text_width(text, font.path, font.size)
    return draw.textlength(text, font=font) if draw is not None else font.getlength(text)
