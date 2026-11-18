"""Our own frame-by-frame video engine (the "After Effects" layer).

Each frame is built in Python (OpenCV + numpy) and streamed straight into ffmpeg, which adds
the audio and burns the text (.ass) in the same pass, so the video is encoded only once.

What it does: smooth camera moves on stills, punch-in zooms + shake on key words, real
footage, "evidence card" framing for old photos, transitions (zoom blur, flash, swipe,
glitch), colour grading, vignette, film grain, 3D emoji pop-ups and a progress bar.
"""
from __future__ import annotations

import math
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from . import ffmpeg
from .stickers import load_rgba

OVERSIZE = 1.3          # stills are prepared 30% bigger than the screen so the camera can move
PUNCH = 1.13            # snap punch-in factor (research: 1.12-1.15x)


@dataclass
class Shot:
    start: float
    end: float
    kind: str = "image"                 # image | video | text
    path: Path | None = None
    move: str = "push_in"               # push_in | pull_out | pan_left | pan_right | drift_up
    frame: str = "full"                 # full | card (framed "evidence" photo / footage)
    transition: str = "zoom"            # how this shot comes in: cut | zoom | flash | swipe | whip | rewind | leak
    punches: list[float] = field(default_factory=list)   # times of punch-in zooms
    sticker: Path | None = None
    sticker_at: float = 0.0
    focus: tuple[float, float] = (0.5, 0.45)            # where to aim in the picture (0-1)
    crop_zoom: float = 1.0              # >1 = start closer (used for a 2nd shot of the same image)
    offset: float = 0.0                 # video: seconds into the clip where this shot starts (continues a split clip)


@dataclass
class Look:
    size: tuple[int, int] = (1080, 1920)
    fps: int = 30
    palette: list[str] = field(default_factory=lambda: ["#0B0F1A", "#8B0000", "#E5E5E5"])
    accent: str = "#FF3B3B"
    contrast: float = 1.12
    saturation: float = 1.2
    warmth: float = 0.0                 # + warm / - cool
    teal_orange: float = 0.25           # cinematic teal shadows / orange highlights
    vignette: float = 0.35
    grain: float = 5.0
    progress_bar: bool = False          # research (round0, podcast spec): no progress bars
    sticker_y: float = 0.56             # emoji position (fraction of height)
    tint: tuple[float, float, float] = (0.0, 0.0, 0.0)   # r, g, b shift in shadows/mids (space: deep blue, ocean: cyan)
    particles: float = 0.0              # drifting embers/dust opacity (mythology spec: 10-20%)
    duo: tuple | None = None            # (shadow hex, highlight hex): tints black-and-white pictures in brand colours
    # Hindi emotion looks (owner, 13 Nov: "feel nostalgic and more devoted"), 0 = off:
    film: float = 0.0                   # old film reel: scratches, dust, flicker, gentle gate weave (nostalgia)
    glow: float = 0.0                   # golden bloom on the bright parts, like diya / temple light (devotion)
    leak: float = 0.0                   # a slow warm light leak drifting across the frame (memories)


def _hex(c: str) -> tuple[int, int, int]:
    c = c.lstrip("#")
    r, g, b = (int(c[i:i + 2], 16) for i in (0, 2, 4))
    return b, g, r


def _ease(p: float) -> float:
    p = min(max(p, 0.0), 1.0)
    return 4 * p ** 3 if p < 0.5 else 1 - (-2 * p + 2) ** 3 / 2


class Grader:
    """Colour grade via lookup tables (fast enough for every frame)."""

    def __init__(self, look: Look):
        x = np.arange(256) / 255.0
        s = 0.5 + (x - 0.5) * look.contrast
        s = np.clip(s + 0.04 * np.sin((x - 0.5) * math.pi) * (look.contrast - 1) * 4, 0, 1)
        to = look.teal_orange
        b = np.clip(s + to * 0.10 * (1 - x) - to * 0.06 * x - look.warmth * 0.05, 0, 1)
        g = np.clip(s + to * 0.03 * (1 - x) + look.warmth * 0.01, 0, 1)
        r = np.clip(s - to * 0.06 * (1 - x) + to * 0.07 * x + look.warmth * 0.05, 0, 1)
        tr, tg, tb = look.tint
        w = 1 - 0.6 * x                                  # strongest in the shadows, lighter in the highlights
        r, g, b = (np.clip(r + tr * w, 0, 1), np.clip(g + tg * w, 0, 1), np.clip(b + tb * w, 0, 1))
        self.lut = np.dstack([(b * 255), (g * 255), (r * 255)]).astype(np.uint8).reshape(1, 256, 3)
        self.sat = look.saturation
        self.duo_lut = None
        if look.duo:                     # duotone ramp: shadow colour -> highlight colour over the brightness
            lo, hi = (np.array(_hex(c), np.float32) for c in look.duo)
            ramp = lo[None, :] + (hi - lo)[None, :] * (x[:, None] ** 0.9)
            self.duo_lut = ramp.astype(np.uint8).reshape(1, 256, 3)

    def __call__(self, img: np.ndarray) -> np.ndarray:
        out = cv2.LUT(img, self.lut)
        if self.duo_lut is not None and img.ndim == 3:   # an (almost) black-and-white picture: brand duotone
            small = cv2.resize(img, (64, 64), interpolation=cv2.INTER_AREA)
            if float(cv2.cvtColor(small, cv2.COLOR_BGR2HSV)[..., 1].mean()) < 22:
                gray = cv2.cvtColor(out, cv2.COLOR_BGR2GRAY)
                duo = cv2.LUT(cv2.merge([gray, gray, gray]), self.duo_lut).astype(np.float32)
                a = (0.65 * (1 - np.clip((gray.astype(np.float32) - 185) / 60, 0, 1)))[..., None]   # paper stays white
                return (out.astype(np.float32) * (1 - a) + duo * a).astype(np.uint8)
        if abs(self.sat - 1) > 0.01:
            hsv = cv2.cvtColor(out, cv2.COLOR_BGR2HSV)
            hsv[..., 1] = cv2.convertScaleAbs(hsv[..., 1], alpha=self.sat)
            out = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
        return out


def _cover(img: np.ndarray, w: int, h: int) -> np.ndarray:
    ih, iw = img.shape[:2]
    k = max(w / iw, h / ih)
    nw, nh = max(w, int(iw * k + 0.5)), max(h, int(ih * k + 0.5))
    interp = cv2.INTER_CUBIC if k > 1 else cv2.INTER_AREA
    img = cv2.resize(img, (nw, nh), interpolation=interp)
    x, y = (nw - w) // 2, (nh - h) // 2
    return img[y:y + h, x:x + w]


def _fit(img: np.ndarray, max_w: int, max_h: int) -> np.ndarray:
    ih, iw = img.shape[:2]
    k = min(max_w / iw, max_h / ih)
    interp = cv2.INTER_CUBIC if k > 1 else cv2.INTER_AREA
    return cv2.resize(img, (max(2, int(iw * k)), max(2, int(ih * k))), interpolation=interp)


def _sharpen(img: np.ndarray, amount: float = 0.6) -> np.ndarray:
    blur = cv2.GaussianBlur(img, (0, 0), 2.0)
    return cv2.addWeighted(img, 1 + amount, blur, -amount, 0)


def _rounded_mask(w: int, h: int, r: int) -> np.ndarray:
    m = np.zeros((h, w), np.uint8)
    cv2.rectangle(m, (r, 0), (w - r, h), 255, -1)
    cv2.rectangle(m, (0, r), (w, h - r), 255, -1)
    for cx, cy in ((r, r), (w - r, r), (r, h - r), (w - r, h - r)):
        cv2.circle(m, (cx, cy), r, 255, -1, cv2.LINE_AA)
    return m


def _blend(dst: np.ndarray, sprite: np.ndarray, x: int, y: int) -> None:
    """Alpha-blend a BGRA sprite onto dst (in place), clipped to the frame."""
    h, w = sprite.shape[:2]
    H, W = dst.shape[:2]
    x0, y0, x1, y1 = max(x, 0), max(y, 0), min(x + w, W), min(y + h, H)
    if x0 >= x1 or y0 >= y1:
        return
    sp = sprite[y0 - y:y1 - y, x0 - x:x1 - x]
    a = sp[..., 3:4].astype(np.float32) / 255.0
    roi = dst[y0:y1, x0:x1]
    roi[:] = (sp[..., :3].astype(np.float32) * a + roi.astype(np.float32) * (1 - a)).astype(np.uint8)


class ShotRenderer:
    def __init__(self, shot: Shot, look: Look, grader: Grader, seed: int = 0):
        self.s, self.look, self.grade = shot, look, grader
        self.W, self.H = look.size
        self.rng = np.random.default_rng(seed)
        self.cap = None
        self.last_video = None
        self.card = None
        if shot.kind == "image":
            img = cv2.imread(str(shot.path), cv2.IMREAD_COLOR)
            if img is None:
                raise ValueError(f"Cannot read image {shot.path}")
            if min(img.shape[:2]) < 1000:
                img = _sharpen(img, 0.5)
            raw = img
            img = self.grade(img)
            if shot.frame == "card":
                self._prepare_card(img)
            elif shot.frame == "parallax":           # v3: full-screen 2.5D "3D photo" camera move
                from .parallax import Parallax, depth_map
                if shot.crop_zoom > 1.01:            # 2nd shot of the same picture: a closer detail
                    h0, w0 = img.shape[:2]
                    cw, ch = int(w0 / shot.crop_zoom), int(h0 / shot.crop_zoom)
                    x0 = int(min(max(shot.focus[0] * w0 - cw / 2, 0), w0 - cw))
                    y0 = int(min(max(shot.focus[1] * h0 - ch / 2, 0), h0 - ch))
                    img, raw = img[y0:y0 + ch, x0:x0 + cw], raw[y0:y0 + ch, x0:x0 + cw]
                cache = Path(str(shot.path) + (f".z{shot.crop_zoom:.2f}" if shot.crop_zoom > 1.01 else "")
                             + ".depth.png")
                depth = depth_map(raw, cache)
                move = {"push_in": "push", "pull_out": "pull", "pan_left": "pan_left", "pan_right": "pan_right",
                        "drift_up": "rise"}.get(shot.move, "orbit")
                self.px = Parallax(img, (self.W, self.H), move, depth=depth)
            elif shot.frame == "graphic":            # designed full-frame card: no oversize crop
                self.src = _cover(img, self.W, self.H)
            else:
                self.src = _cover(img, int(self.W * OVERSIZE) // 2 * 2, int(self.H * OVERSIZE) // 2 * 2)
        elif shot.kind == "video":
            self.cap = cv2.VideoCapture(str(shot.path))
            self.vfps = self.cap.get(cv2.CAP_PROP_FPS) or 30
            self.vidx = -1
            k0 = int(shot.offset * self.vfps)
            if k0 > 0:                               # 2nd part of a split clip: carry on where the 1st part stopped
                self.cap.set(cv2.CAP_PROP_POS_FRAMES, k0)
                self.vidx = k0 - 1
            if shot.frame == "card":
                ok, first = self.cap.read()
                self.cap.set(cv2.CAP_PROP_POS_FRAMES, k0)
                self._prepare_card(self.grade(first) if ok else np.zeros((self.H, self.W, 3), np.uint8),
                                   video=True)
        else:   # text shot: animated gradient background, the words come from the .ass file
            self.src = self._text_background()

    # ----- backgrounds -----
    def _text_background(self) -> np.ndarray:
        w, h = int(self.W * OVERSIZE) // 2 * 2, int(self.H * OVERSIZE) // 2 * 2
        pal = [_hex(c) for c in self.look.palette] + [_hex(self.look.accent)]
        k = np.linspace(0, 1, h)[:, None, None]
        top, bottom = np.array(pal[0], np.float32), np.array(pal[1 % len(pal)], np.float32)
        img = (top * (1 - k) + bottom * k).repeat(w, axis=1).astype(np.float32)
        glow = np.zeros((h, w), np.float32)
        for _ in range(6):     # soft light blobs (bokeh)
            cx, cy = self.rng.uniform(0, w), self.rng.uniform(0, h)
            r = self.rng.uniform(0.12, 0.3) * w
            yy, xx = np.ogrid[:h, :w]
            glow += np.exp(-(((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * r * r)))
        acc = np.array(pal[-1], np.float32)
        img += glow[..., None] * acc * 0.35
        # diagonal light streaks
        streak = np.zeros((h, w), np.float32)
        for i in range(3):
            x0 = int(self.rng.uniform(0, w))
            cv2.line(streak, (x0, 0), (x0 - h // 2, h), 1.0, int(w * 0.04))
        streak = cv2.GaussianBlur(streak, (0, 0), w * 0.02)
        img += streak[..., None] * 40
        return np.clip(img, 0, 255).astype(np.uint8)

    def _prepare_card(self, img: np.ndarray, video: bool = False) -> None:
        W, H = self.W, self.H
        bg = _cover(img, W, H)
        bg = cv2.GaussianBlur(bg, (0, 0), 28)
        self.card_bg = cv2.convertScaleAbs(bg, alpha=0.45)
        portrait = H > W
        max_w, max_h = int(W * (0.86 if portrait else 0.62)), int(H * (0.5 if portrait else 0.78))
        inner = _fit(img, max_w, max_h)
        self.card_inner_size = inner.shape[1], inner.shape[0]
        self.card_border = max(10, W // 90)
        self.card_angle = float(self.rng.choice([-2.5, -1.5, 1.5, 2.5])) if not video else 0.0
        if not video:
            self.card = self._card_sprite(inner)

    def _card_sprite(self, inner: np.ndarray) -> np.ndarray:
        b = self.card_border
        h, w = inner.shape[:2]
        pad = b * 4
        canvas = np.zeros((h + 2 * b + 2 * pad, w + 2 * b + 2 * pad, 4), np.uint8)
        # shadow
        sh = np.zeros(canvas.shape[:2], np.uint8)
        cv2.rectangle(sh, (pad + b, pad + 2 * b), (pad + w + 2 * b, pad + h + 3 * b), 200, -1)
        sh = cv2.GaussianBlur(sh, (0, 0), b * 1.5)
        canvas[..., 3] = sh
        # white border + picture with rounded corners
        r = max(8, b * 2)
        frame = np.full((h + 2 * b, w + 2 * b, 3), 245, np.uint8)
        frame[b:b + h, b:b + w] = inner
        m = _rounded_mask(w + 2 * b, h + 2 * b, r)
        region = canvas[pad:pad + h + 2 * b, pad:pad + w + 2 * b]
        a = (m.astype(np.float32) / 255.0)[..., None]
        region[..., :3] = (frame * a + region[..., :3] * (1 - a)).astype(np.uint8)
        region[..., 3] = np.maximum(region[..., 3], m)
        if self.card_angle:
            ch, cw = canvas.shape[:2]
            M = cv2.getRotationMatrix2D((cw / 2, ch / 2), self.card_angle, 1.0)
            canvas = cv2.warpAffine(canvas, M, (cw, ch), flags=cv2.INTER_LINEAR, borderValue=(0, 0, 0, 0))
        return canvas

    # ----- camera -----
    def _zoom_center(self, t: float) -> tuple[float, float, float]:
        s = self.s
        # constant speed (owner 13 Nov: easing in and out on every short shot made the picture "breathe");
        # research: push-in 3-6% (mystery spec) / 3-8% (mythology spec); lateral pans 2-4% of the width
        p = min(max((t - s.start) / max(s.end - s.start, 0.01), 0.0), 1.0)
        z = {"push_in": 1.0 + 0.04 * p, "pull_out": 1.04 - 0.04 * p}.get(s.move, 1.03)
        fx, fy = s.focus
        cx, cy = fx, fy
        if s.move == "pan_left":
            cx = fx + 0.015 - 0.03 * p
        elif s.move == "pan_right":
            cx = fx - 0.015 + 0.03 * p
        elif s.move == "drift_up":
            cy = fy + 0.015 - 0.03 * p
        return z * s.crop_zoom * self._punch(t), cx, cy

    def _punch(self, t: float) -> float:
        """Snap punch-in on the payoff word (research: 1.12-1.15x, held, no bounce): one frame up, held until the cut."""
        return PUNCH if self.s.punches and t >= min(self.s.punches) else 1.0

    def _shake(self, t: float) -> tuple[float, float]:
        return 0.0, 0.0                          # research: constant shake reads as dated

    def _camera(self, src: np.ndarray, t: float) -> np.ndarray:
        sh, sw = src.shape[:2]
        z, cx, cy = self._zoom_center(t)
        ww, wh = sw / OVERSIZE / z * 1.0, sh / OVERSIZE / z
        ww, wh = min(ww, sw), min(wh, sh)
        x = min(max(cx * sw - ww / 2, 0), sw - ww)
        y = min(max(cy * sh - wh / 2, 0), sh - wh)
        k = self.W / ww
        dx, dy = self._shake(t)
        M = np.float32([[k, 0, -x * k + dx], [0, k, -y * k + dy]])
        return cv2.warpAffine(src, M, (self.W, self.H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)

    def _video_frame(self, t: float) -> np.ndarray:
        want = int((t - self.s.start + self.s.offset) * self.vfps)
        frame = self.last_video
        while self.vidx < want:
            ok, f = self.cap.read()
            if not ok:
                break
            self.vidx += 1
            frame = f
        if frame is None:
            frame = np.zeros((self.H, self.W, 3), np.uint8)
        self.last_video = frame
        return frame

    def frame(self, t: float) -> np.ndarray:
        s = self.s
        if s.kind == "video":
            raw = self.grade(self._video_frame(t))
            if s.frame == "card":
                return self._card_frame(t, raw)
            if s.frame == "graphic":
                return self._gentle(cv2.resize(raw, (self.W, self.H), interpolation=cv2.INTER_AREA), t)
            src = _cover(raw, int(self.W * 1.12) // 2 * 2, int(self.H * 1.12) // 2 * 2)
            sh, sw = src.shape[:2]
            z, _cx, _cy = self._zoom_center(t)
            z = max(z, 1.0)
            ww, wh = sw / 1.12 / z * 1.0, sh / 1.12 / z
            x, y = (sw - ww) / 2, (sh - wh) / 2
            k = self.W / ww
            dx, dy = self._shake(t)
            M = np.float32([[k, 0, -x * k + dx], [0, k, -y * k + dy]])
            return cv2.warpAffine(src, M, (self.W, self.H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
        if s.frame == "card":
            return self._card_frame(t)
        if s.frame == "graphic":
            return self._gentle(self.src, t)
        if s.frame == "parallax":
            out = self.px.frame((t - s.start) / max(s.end - s.start, 0.01))
            z = self._punch(t)
            if z > 1.001:                            # snap punch-in on key words, no shake
                M = cv2.getRotationMatrix2D((self.W / 2, self.H * 0.45), 0, z)
                out = cv2.warpAffine(out, M, (self.W, self.H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
            return out
        return self._camera(self.src, t)

    def _card_frame(self, t: float, video_raw: np.ndarray | None = None) -> np.ndarray:
        s = self.s
        p = (t - s.start) / max(s.end - s.start, 0.01)
        out = self.card_bg.copy()
        if video_raw is not None:
            inner = cv2.resize(video_raw, self.card_inner_size, interpolation=cv2.INTER_AREA)
            sprite = self._card_sprite(inner)
        else:
            sprite = self.card
        intro = _ease(min((t - s.start) / 0.25, 1.0))
        scale = (0.82 + 0.18 * intro) * (1.0 + 0.05 * p)
        scale *= self._punch(t)
        sw, sh = int(sprite.shape[1] * scale), int(sprite.shape[0] * scale)
        sp = cv2.resize(sprite, (sw, sh), interpolation=cv2.INTER_LINEAR)
        dx, dy = self._shake(t)
        cx, cy = self.W // 2 + int(dx), int(self.H * (0.46 if self.H > self.W else 0.5) + dy - 14 * p)
        _blend(out, sp, cx - sw // 2, cy - sh // 2)
        return out

    def _gentle(self, img: np.ndarray, t: float) -> np.ndarray:
        """Graphics: a slow 4% push so the card breathes, never cropping into its text."""
        s = self.s
        p = min(max((t - s.start) / max(s.end - s.start, 0.01), 0.0), 1.0)          # steady, no breathing
        z = (1.0 + 0.03 * p) * self._punch(t) * max(1.0, min(s.crop_zoom, 1.12))   # re-frame cut stays clear of text
        M = cv2.getRotationMatrix2D((self.W / 2, self.H * 0.45), 0, z)
        return cv2.warpAffine(img, M, (self.W, self.H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)

    def close(self):
        if self.cap is not None:
            self.cap.release()


# ---------- whole-frame effects ----------
class Finisher:
    def __init__(self, look: Look, total: float, seed: int = 7):
        W, H = look.size
        self.look, self.total = look, total
        yy, xx = np.ogrid[:H, :W]
        d = np.sqrt(((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2) / math.sqrt(2)
        v = 1 - look.vignette * np.clip(d - 0.25, 0, 1) ** 1.6 / 0.56
        self.vig = cv2.merge([(v * 255).astype(np.uint8)] * 3)
        rng = np.random.default_rng(seed)
        self.grain = []
        if look.grain > 0:
            for _ in range(6):
                n = rng.normal(0, look.grain, (H // 2, W // 2)).astype(np.float32)
                n = cv2.resize(n, (W, H), interpolation=cv2.INTER_LINEAR)
                self.grain.append((cv2.merge([np.clip(n, 0, 255).astype(np.uint8)] * 3),
                                   cv2.merge([np.clip(-n, 0, 255).astype(np.uint8)] * 3)))
        self.accent = _hex(look.accent)
        # mythology spec: slow drifting embers / dust motes at 10-20% opacity
        self.parts = rng.uniform(0, 1, (46, 4)) if look.particles > 0 else None
        self.rng = np.random.default_rng(seed + 1)
        if look.leak > 0:                    # coordinates of a 1/8-size grid for the soft warm blob
            self.leak_img = np.mgrid[0:H // 8, 0:W // 8].astype(np.float32)
        else:
            self.leak_img = None

    def _particles(self, frame: np.ndarray, t: float) -> np.ndarray:
        H, W = frame.shape[:2]
        layer = np.zeros_like(frame)
        for x0, y0, sp, sz in self.parts:
            y = (y0 - t * (0.015 + 0.03 * sp)) % 1.0                       # rise slowly
            x = (x0 + 0.012 * math.sin(t * (0.6 + sp) + x0 * 9)) % 1.0     # sway
            r = int(2 + 5 * sz)
            cv2.circle(layer, (int(x * W), int(y * H)), r, (90, 190, 255), -1, cv2.LINE_AA)   # warm ember (BGR)
        layer = cv2.GaussianBlur(layer, (0, 0), 2.5)
        return cv2.addWeighted(frame, 1.0, layer, self.look.particles * 2.2, 0)

    def _glow(self, frame: np.ndarray) -> np.ndarray:
        """Golden bloom: worked out at 1/8 size, added back with saturating 8-bit maths (fast)."""
        H, W = frame.shape[:2]
        small = cv2.resize(frame, (W // 8, H // 8), interpolation=cv2.INTER_AREA).astype(np.float32)
        lum = small.mean(axis=2, keepdims=True)
        bright = np.clip((lum - 150) / 105, 0, 1) * small * np.array([0.55, 0.85, 1.0], np.float32)   # gold
        bloom = cv2.GaussianBlur(bright, (0, 0), max(W, H) / 180) * self.look.glow
        up = cv2.resize(np.clip(bloom, 0, 255).astype(np.uint8), (W, H), interpolation=cv2.INTER_LINEAR)
        return cv2.add(frame, up)

    def _leak(self, frame: np.ndarray, t: float) -> np.ndarray:
        """A warm light leak drifting slowly, screen-blended with 8-bit operations."""
        H, W = frame.shape[:2]
        yy, xx = self.leak_img
        cx = (0.15 + 0.7 * (0.5 + 0.5 * math.sin(t * 0.21))) * W / 8
        cy = (0.1 + 0.5 * (0.5 + 0.5 * math.cos(t * 0.13))) * H / 8
        sig = max(W, H) / 8 * 0.28
        a = self.look.leak * (0.75 + 0.25 * math.sin(t * 0.7))
        blob = np.exp(-((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * sig * sig)) * a
        q = (blob[..., None] * np.array([40, 140, 255], np.float32)).astype(np.uint8)   # warm orange (BGR)
        layer = cv2.resize(q, (W, H), interpolation=cv2.INTER_LINEAR)
        return cv2.bitwise_not(cv2.multiply(cv2.bitwise_not(frame), cv2.bitwise_not(layer), scale=1 / 255))

    def _film(self, frame: np.ndarray, t: float, i: int) -> np.ndarray:
        H, W = frame.shape[:2]
        k, rng = self.look.film, np.random.default_rng(i * 7919 + 13)
        dy = int(round(float(rng.normal(0, 1.4 * k))))                   # gate weave: a pixel or two of drift
        if dy:
            frame = np.roll(frame, dy, axis=0)
        frame = cv2.convertScaleAbs(frame, alpha=1.0 + float(rng.normal(0, 0.025 * k)))   # flicker
        for _ in range(int(rng.integers(0, 3))):                         # vertical scratches
            x = int(rng.uniform(0.05, 0.95) * W)
            y0, y1 = sorted(int(v) for v in rng.uniform(0, H, 2))
            shade = 255 if rng.random() < 0.6 else 20
            cv2.line(frame, (x, y0), (x + int(rng.normal(0, 3)), y1), (shade,) * 3, 1, cv2.LINE_AA)
        for _ in range(int(rng.integers(0, int(1 + 6 * k)))):            # dust specks
            c = (int(rng.uniform(0, W)), int(rng.uniform(0, H)))
            cv2.circle(frame, c, int(rng.integers(1, 4)), (int(rng.choice([15, 235])),) * 3, -1, cv2.LINE_AA)
        return frame

    def __call__(self, frame: np.ndarray, t: float, i: int) -> np.ndarray:
        if self.look.glow > 0:
            frame = self._glow(frame)
        if self.leak_img is not None:
            frame = self._leak(frame, t)
        if self.look.film > 0:
            frame = self._film(frame, t, i)
        frame = cv2.multiply(frame, self.vig, scale=1 / 255)
        if self.parts is not None:
            frame = self._particles(frame, t)
        if self.grain:
            pos, neg = self.grain[i % len(self.grain)]
            frame = cv2.subtract(cv2.add(frame, pos), neg)
        if self.look.progress_bar:
            H, W = frame.shape[:2]
            bh = max(8, H // 190)
            frame[H - bh:H] = (frame[H - bh:H] * 0.45).astype(np.uint8)
            cv2.rectangle(frame, (0, H - bh), (int(W * min(t / self.total, 1)), H), self.accent, -1)
        return frame


def _zoom_blur(img: np.ndarray, z: float) -> np.ndarray:
    H, W = img.shape[:2]
    acc = np.zeros_like(img, dtype=np.float32)
    for k in (1.0, 1.035, 1.07):
        zz = z * k
        M = cv2.getRotationMatrix2D((W / 2, H / 2), 0, zz)
        acc += cv2.warpAffine(img, M, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
    return (acc / 3).astype(np.uint8)


def transition(kind: str, prev: np.ndarray, new: np.ndarray, p: float, rng) -> np.ndarray:
    """p goes 0 -> 1 across the transition."""
    if kind == "zoom":
        return _zoom_blur(prev, 1 + 0.5 * _ease(p * 2)) if p < 0.5 else _zoom_blur(new, 1 + 0.5 * (1 - _ease((p - 0.5) * 2)))
    if kind == "flash":
        white = 1 - _ease(p)
        return cv2.addWeighted(new, 1 - white, np.full_like(new, 255), white, 0)
    if kind == "swipe":
        W = new.shape[1]
        nw = int(W * _ease(p))                      # how much of the new shot has slid in
        if nw <= 0:
            out = prev.copy()
        elif nw >= W:
            out = new.copy()
        else:                                        # old shot pushed left, new one enters from the right
            out = np.concatenate([prev[:, nw:], new[:, :nw]], axis=1)
        return cv2.blur(out, (int(40 * (1 - abs(p - 0.5) * 2)) + 1, 1))
    if kind == "whip":                               # research: whip-blur ~6 frames on section changes (max 2)
        W = new.shape[1]
        e = _ease(p)
        src = prev if p < 0.5 else new
        shift = int(W * (e if p < 0.5 else e - 1))
        out = np.roll(src, -shift, axis=1)
        k = int(90 * (1 - abs(p - 0.5) * 2)) + 1
        return cv2.blur(out, (k, 1))
    if kind == "rewind":                             # sports spec: tape-rewind into the backstory
        src = prev if p < 0.6 else new
        out = cv2.cvtColor(cv2.cvtColor(src, cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR) if p < 0.6 else src.copy()
        H, W = out.shape[:2]
        for _ in range(7 if p < 0.6 else 3):         # tracking lines + jitter
            y = int(rng.uniform(0, H - 30))
            h = int(rng.uniform(6, 26))
            out[y:y + h] = np.roll(out[y:y + h], int(rng.uniform(-80, 80)), axis=1)
            out[y:y + 2] = 230
        return out
    if kind == "leak":                               # mythology spec: warm gold light-leak flash on transitions
        H, W = new.shape[:2]
        a = math.sin(math.pi * min(max(p, 0.0), 1.0)) * 0.55
        xx = np.linspace(0, 1, W, dtype=np.float32)[None, :, None]
        glow = (np.array([60, 170, 255], np.float32)[None, None, :] * (1 - xx) ** 1.5)   # gold from the left
        base = (prev if p < 0.5 else new).astype(np.float32)
        return np.clip(base + glow * a * 1.6, 0, 255).astype(np.uint8)
    if kind == "glitch":
        out = new.copy()
        shift = int(30 * (1 - p))
        if shift:
            out[..., 2] = np.roll(new[..., 2], shift, axis=1)
            out[..., 0] = np.roll(new[..., 0], -shift, axis=1)
            H = out.shape[0]
            for _ in range(5):
                y = int(rng.uniform(0, H - 40))
                h = int(rng.uniform(10, 60))
                out[y:y + h] = np.roll(out[y:y + h], int(rng.uniform(-60, 60)), axis=1)
        return out
    return new


@dataclass
class Sticker:
    path: Path
    start: float
    end: float
    size: int = 300


def _sticker_frame(st: Sticker, sprite: np.ndarray, t: float, look: Look, frame: np.ndarray) -> None:
    d = t - st.start
    if d < 0 or t > st.end:
        return
    pop = 1.15 * _ease(min(d / 0.12, 1)) - 0.15 * _ease(min(max(d - 0.12, 0) / 0.12, 1))
    fade = min(1.0, (st.end - t) / 0.15)
    scale = max(pop * (0.6 + 0.4 * fade), 0.05)
    bob = 10 * math.sin(d * 5)
    s = max(int(st.size * scale), 4)
    sp = cv2.resize(sprite, (s, s), interpolation=cv2.INTER_LINEAR)
    if fade < 1:
        sp = sp.copy()
        sp[..., 3] = (sp[..., 3] * fade).astype(np.uint8)
    W, H = look.size
    _blend(frame, sp, W // 2 - s // 2, int(H * look.sticker_y) - s // 2 + int(bob))


def render(shots: list[Shot], look: Look, total: float, out: Path, *, audio: Path | None = None,
           ass: Path | None = None, fonts_dir: Path | None = None, stickers: list[Sticker] | None = None,
           transition_s: float = 0.22, log=print, alt: dict | None = None, mascot: dict | None = None) -> Path:
    """Render all shots to `out` (H.264 + AAC), burning `ass` text in the same pass.
    alt = {"ass": Path, "out": Path, "trim_end": float}: also write an Instagram Reel from the SAME frames with a
    different text file (other hook wording) and a slightly shorter ending, so the two uploads are never identical."""
    W, H = look.size
    fps = look.fps
    n_frames = int(math.ceil(total * fps))
    if shots and shots[0].start > 0:          # the voice has a short lead-in: the picture must still show at frame 0
        import dataclasses
        shots = [dataclasses.replace(shots[0], start=0.0)] + list(shots[1:])
    grader = Grader(look)
    finisher = Finisher(look, total)
    rng = np.random.default_rng(3)
    sprites = {}
    for st in stickers or []:
        if st.path not in sprites:
            sprites[st.path] = load_rgba(st.path, st.size)

    work = out.parent
    vf = []
    if ass is not None:
        fonts_rel = os.path.relpath(fonts_dir, ass.parent).replace("\\", "/") if fonts_dir else None
        vf.append(f"subtitles={ass.name}" + (f":fontsdir={fonts_rel}" if fonts_rel else ""))
    cmd = [ffmpeg.ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-y",
           "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}", "-r", str(fps), "-i", "-"]
    if audio:
        cmd += ["-i", str(audio.resolve())]
    if alt and ass is not None and alt.get("ass") and alt.get("out"):
        fonts_rel = os.path.relpath(fonts_dir, ass.parent).replace("\\", "/") if fonts_dir else None
        fd = f":fontsdir={fonts_rel}" if fonts_rel else ""
        cmd += ["-filter_complex", f"[0:v]split=2[a][b];[a]subtitles={ass.name}{fd}[va];"
                                   f"[b]subtitles={Path(alt['ass']).name}{fd}[vb]"]
        cmd += ["-map", "[va]"] + (["-map", "1:a"] if audio else [])
        cmd += ffmpeg.H264 + (ffmpeg.AAC if audio else []) + ["-shortest", "-movflags", "+faststart", str(out.resolve())]
        cmd += ["-map", "[vb]"] + (["-map", "1:a"] if audio else [])
        cmd += ffmpeg.H264 + (ffmpeg.AAC if audio else []) + [
            "-t", f"{max(1.0, total - float(alt.get('trim_end', 0.5))):.3f}", "-movflags", "+faststart",
            str(Path(alt["out"]).resolve())]
    else:
        if vf:
            cmd += ["-vf", ",".join(vf)]
        cmd += ["-map", "0:v"] + (["-map", "1:a"] if audio else [])
        cmd += ffmpeg.H264 + (ffmpeg.AAC if audio else []) + ["-shortest", "-movflags", "+faststart", str(out.resolve())]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE,
                            cwd=str(ass.parent if ass is not None else work))

    renderers: dict[int, ShotRenderer] = {}

    def get(i: int) -> ShotRenderer:
        if i not in renderers:
            renderers[i] = ShotRenderer(shots[i], look, grader, seed=i)
            for j in list(renderers):
                if j < i - 1:
                    renderers.pop(j).close()
        return renderers[i]

    starts = [s.start for s in shots]
    try:
        for fi in range(n_frames):
            t = fi / fps
            idx = max(0, int(np.searchsorted(starts, t, side="right")) - 1)
            shot = shots[idx]
            frame = get(idx).frame(t)
            since = t - shot.start
            dur = 0.4 if shot.transition == "rewind" else transition_s
            if idx > 0 and since < dur and shot.transition != "cut":
                prev = get(idx - 1).frame(t)
                frame = transition(shot.transition, prev, frame, since / dur, rng)
            for st in stickers or []:
                _sticker_frame(st, sprites[st.path], t, look, frame)
            frame = finisher(frame, t, fi)
            if mascot and t >= mascot.get("start", 0.0):     # recurring channel character, lip-synced to the voice
                mouth = mascot["mouth"]
                spr = mascot["sprite"].draw(t, mouth=float(mouth[min(fi, len(mouth) - 1)]) if len(mouth) else 0.0,
                                            look=mascot.get("look", -0.4))
                age = t - mascot.get("start", 0.0)
                if mascot.get("start") and age < 0.3:                # small pop-in when it first appears
                    k = max(0.05, min(1.0, age / 0.3)) * (1.0 + 0.12 * (1 - abs(age / 0.15 - 1)) if age < 0.3 else 1.0)
                    spr = cv2.resize(spr, (max(2, int(spr.shape[1] * k)), max(2, int(spr.shape[0] * k))))
                _blend(frame, spr, mascot["x"] - spr.shape[1] // 2, mascot["y"] - spr.shape[0] // 2)
            proc.stdin.write(frame.tobytes())
            if fi % (fps * 10) == 0:
                log(f"  frame {fi}/{n_frames}")
        proc.stdin.close()
        err = proc.stderr.read().decode("utf-8", "replace")
        proc.wait()
    finally:
        for r in renderers.values():
            r.close()
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed while rendering:\n{err[-2000:]}")
    return out
