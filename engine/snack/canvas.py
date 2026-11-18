"""Drawing helpers for Brain Snack v3: neon glow, crisp text sprites, rounded cards, backgrounds.

Everything is drawn by our own code (OpenCV + Pillow) with free commercial-use fonts.
"""
from __future__ import annotations

import colorsys
import math
from functools import lru_cache

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from ..media.fonts import font_file

W, H = 1080, 1920
SAFE = (60, 180, 1000, 1480)          # x0, y0, x1, y1: keep text and key action inside (Shorts UI covers the rest)


def bgr(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[4:6], 16), int(h[2:4], 16), int(h[0:2], 16)


def hue_bgr(h: float, s: float = 0.95, v: float = 1.0) -> tuple[int, int, int]:
    r, g, b = colorsys.hsv_to_rgb(h % 1.0, s, v)
    return int(b * 255), int(g * 255), int(r * 255)


def radial_bg(center_hex: str, edge_hex: str, w: int = W, h: int = H) -> np.ndarray:
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    d = np.sqrt(((xx - w / 2) / (w * 0.78)) ** 2 + ((yy - h / 2) / (h * 0.62)) ** 2).clip(0, 1)[..., None]
    c, e = np.array(bgr(center_hex), np.float32), np.array(bgr(edge_hex), np.float32)
    return (c * (1 - d) + e * d).astype(np.uint8)


def vertical_bg(top_hex: str, bottom_hex: str, w: int = W, h: int = H) -> np.ndarray:
    t = np.linspace(0, 1, h, dtype=np.float32)[:, None, None]
    a, b = np.array(bgr(top_hex), np.float32), np.array(bgr(bottom_hex), np.float32)
    return np.repeat((a * (1 - t) + b * t).astype(np.uint8), w, axis=1)


def add_glow(frame: np.ndarray, layer: np.ndarray, passes=((8, 0.6), (28, 0.35)), scale: int = 4) -> np.ndarray:
    """Adds `layer` (bright shapes on black) to frame with a soft two-pass neon glow.
    The blur runs at 1/scale resolution, which is ~16x cheaper and looks the same."""
    small = cv2.resize(layer, (layer.shape[1] // scale, layer.shape[0] // scale), interpolation=cv2.INTER_AREA)
    acc = np.zeros(small.shape, np.float32)
    for radius, strength in passes:
        k = max(3, int(radius / scale) * 2 + 1)
        acc += cv2.GaussianBlur(small, (k, k), 0).astype(np.float32) * strength
    big = cv2.resize(np.clip(acc, 0, 255).astype(np.uint8), (frame.shape[1], frame.shape[0]),
                     interpolation=cv2.INTER_LINEAR)
    cv2.add(frame, big, dst=frame)
    np.maximum(frame, layer, out=frame)
    return frame


@lru_cache(maxsize=64)
def _font(family: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(font_file(family)), size)


def text_width(text: str, family: str, size: int, stroke: int = 0) -> int:
    f = _font(family, size)
    box = f.getbbox(text, stroke_width=stroke)
    return box[2] - box[0]


def fit_size(text: str, family: str, max_w: int, size: int, min_size: int = 28, stroke: int = 0) -> int:
    while size > min_size and text_width(text, family, size, stroke) > max_w:
        size -= 2
    return size


def wrap(text: str, family: str, size: int, max_w: int, stroke: int = 0) -> list[str]:
    lines, cur = [], ""
    for word in text.split():
        trial = f"{cur} {word}".strip()
        if cur and text_width(trial, family, size, stroke) > max_w:
            lines.append(cur)
            cur = word
        else:
            cur = trial
    if cur:
        lines.append(cur)
    return lines


@lru_cache(maxsize=1024)
def text_sprite(text: str, family: str = "Poppins Black", size: int = 72, fill: str = "#FFFFFF",
                stroke: int = 8, stroke_fill: str = "#000000", shadow: int = 6, align: str = "center",
                line_gap: float = 1.05) -> np.ndarray:
    """BGRA image of (possibly multi-line, '\\n'-separated) text with outline and soft shadow."""
    font = _font(family, size)
    lines = text.split("\n")
    boxes = [font.getbbox(ln or " ", stroke_width=stroke) for ln in lines]
    asc, desc = font.getmetrics()
    line_h = int((asc + desc) * line_gap)
    tw = max(b[2] - b[0] for b in boxes)
    pad = shadow * 2 + stroke + 4
    w, h = tw + pad * 2, line_h * len(lines) + pad * 2
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))

    def draw_lines(target, color, stroke_color, dx=0, dy=0):
        d = ImageDraw.Draw(target)
        for i, (ln, b) in enumerate(zip(lines, boxes)):
            lw = b[2] - b[0]
            x = pad + (0 if align == "left" else (tw - lw) // 2 if align == "center" else tw - lw) - b[0]
            d.text((x + dx, pad + i * line_h + dy), ln, font=font, fill=color,
                   stroke_width=stroke, stroke_fill=stroke_color)

    if shadow:
        sh = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw_lines(sh, (0, 0, 0, 160), (0, 0, 0, 160), dx=shadow // 2, dy=shadow)
        img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(max(1, shadow / 2))))
    draw_lines(img, fill, stroke_fill)
    arr = np.array(img)
    return np.ascontiguousarray(arr[..., [2, 1, 0, 3]])


def blit(frame: np.ndarray, sprite: np.ndarray, cx: float, cy: float, scale: float = 1.0,
         alpha: float = 1.0, anchor: str = "center") -> None:
    """Alpha-blends a BGRA sprite onto a BGR frame (clipped at the edges)."""
    if alpha <= 0.01 or scale <= 0.01:
        return
    if abs(scale - 1.0) > 0.01:
        sprite = cv2.resize(sprite, (max(1, int(sprite.shape[1] * scale)), max(1, int(sprite.shape[0] * scale))),
                            interpolation=cv2.INTER_LINEAR if scale > 1 else cv2.INTER_AREA)
    sh, sw = sprite.shape[:2]
    if anchor == "center":
        x0, y0 = int(round(cx - sw / 2)), int(round(cy - sh / 2))
    elif anchor == "top":
        x0, y0 = int(round(cx - sw / 2)), int(round(cy))
    else:  # top-left
        x0, y0 = int(round(cx)), int(round(cy))
    fx0, fy0 = max(0, x0), max(0, y0)
    fx1, fy1 = min(frame.shape[1], x0 + sw), min(frame.shape[0], y0 + sh)
    if fx1 <= fx0 or fy1 <= fy0:
        return
    s = sprite[fy0 - y0:fy1 - y0, fx0 - x0:fx1 - x0]
    a = s[..., 3:4].astype(np.float32) * (alpha / 255.0)
    roi = frame[fy0:fy1, fx0:fx1]
    roi[:] = (roi.astype(np.float32) * (1 - a) + s[..., :3].astype(np.float32) * a).astype(np.uint8)


def rounded_rect(frame: np.ndarray, x0: int, y0: int, x1: int, y1: int, r: int, color: tuple[int, int, int],
                 alpha: float = 1.0, border: int = 0, border_color: tuple[int, int, int] = (0, 0, 0)) -> None:
    x0, y0, x1, y1 = int(x0), int(y0), int(x1), int(y1)
    r = max(0, min(r, (x1 - x0) // 2, (y1 - y0) // 2))
    pad = border + 2
    bx0, by0 = max(0, x0 - pad), max(0, y0 - pad)
    bx1, by1 = min(frame.shape[1], x1 + pad), min(frame.shape[0], y1 + pad)
    if bx1 <= bx0 or by1 <= by0:
        return
    mask = np.zeros((by1 - by0, bx1 - bx0), np.uint8)

    def shape(m, inset, value):
        ox, oy = x0 - bx0 + inset, y0 - by0 + inset
        ex, ey = x1 - bx0 - inset, y1 - by0 - inset
        rr = max(0, r - inset)
        cv2.rectangle(m, (ox + rr, oy), (ex - rr, ey), value, -1, cv2.LINE_AA)
        cv2.rectangle(m, (ox, oy + rr), (ex, ey - rr), value, -1, cv2.LINE_AA)
        for cx_, cy_ in ((ox + rr, oy + rr), (ex - rr, oy + rr), (ox + rr, ey - rr), (ex - rr, ey - rr)):
            cv2.circle(m, (cx_, cy_), rr, value, -1, cv2.LINE_AA)

    roi = frame[by0:by1, bx0:bx1]
    if border:
        shape(mask, -border, 255)
        a = mask.astype(np.float32)[..., None] / 255.0 * alpha
        roi[:] = (roi * (1 - a) + np.array(border_color, np.float32) * a).astype(np.uint8)
        mask[:] = 0
    shape(mask, 0, 255)
    a = mask.astype(np.float32)[..., None] / 255.0 * alpha
    roi[:] = (roi * (1 - a) + np.array(color, np.float32) * a).astype(np.uint8)


def ease_out_back(t: float, s: float = 1.7) -> float:
    t = min(max(t, 0.0), 1.0) - 1
    return t * t * ((s + 1) * t + s) + 1


def ease_out(t: float) -> float:
    t = min(max(t, 0.0), 1.0)
    return 1 - (1 - t) ** 3


def pop_scale(t: float, dur: float = 0.24, overshoot: float = 1.08) -> float:
    """0 -> overshoot -> 1.0 pop-in (the 'card pops onto the screen' motion)."""
    if t <= 0:
        return 0.0
    if t >= dur:
        return 1.0
    p = t / dur
    return overshoot * math.sin(p * math.pi / 2) if p < 0.7 else overshoot + (1 - overshoot) * (p - 0.7) / 0.3


def zoom(frame: np.ndarray, scale: float, cx: float = W / 2, cy: float = H / 2) -> np.ndarray:
    """Camera push-in: scale around (cx, cy) keeping the frame size."""
    if abs(scale - 1.0) < 1e-3:
        return frame
    m = np.float32([[scale, 0, cx - scale * cx], [0, scale, cy - scale * cy]])
    return cv2.warpAffine(frame, m, (frame.shape[1], frame.shape[0]), flags=cv2.INTER_LINEAR,
                          borderMode=cv2.BORDER_REFLECT)
