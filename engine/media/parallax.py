"""2.5D "3D photo" motion: the modern replacement for Ken Burns zooms on still images.

A free depth model (Depth-Anything-V2-Small, Apache-2.0 - the Base/Large versions are NON-commercial, never
use them) estimates how far each pixel is. The virtual camera then dollies/pans a few percent: near things
move more than far things, so a flat photo gets real depth. Runs on CPU (about 1 s per image).
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np

MODEL_ID = "depth-anything/Depth-Anything-V2-Small-hf"     # Apache-2.0 (Small only)
MOVES = ("push", "pan_left", "pan_right", "rise")         # no random pull-outs (in-out pulsing)


@lru_cache(maxsize=1)
def _pipe():
    from transformers import pipeline
    return pipeline("depth-estimation", model=MODEL_ID, device=-1)


def depth_map(img_bgr: np.ndarray, cache_path: Path | None = None) -> np.ndarray:
    """Depth in 0..1 (1 = near), same size as the image. Cached as a PNG next to the image if asked."""
    if cache_path and Path(cache_path).exists():
        d = cv2.imread(str(cache_path), cv2.IMREAD_GRAYSCALE)
        if d is not None and d.shape[:2] == img_bgr.shape[:2]:
            return d.astype(np.float32) / 255.0
    from PIL import Image
    pil = Image.fromarray(cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB))
    out = _pipe()(pil)
    d = np.array(out["depth"]).astype(np.float32)
    d = cv2.resize(d, (img_bgr.shape[1], img_bgr.shape[0]), interpolation=cv2.INTER_CUBIC)
    d = (d - d.min()) / max(1e-6, d.max() - d.min())
    d = cv2.GaussianBlur(d, (0, 0), max(2.0, img_bgr.shape[1] / 300))     # soft edges = fewer tearing artifacts
    if cache_path:
        cv2.imwrite(str(cache_path), (d * 255).astype(np.uint8))
    return d


class Parallax:
    """Renders frames of a slow 2.5D camera move over one still image, at the output size."""

    def __init__(self, img_bgr: np.ndarray, size: tuple[int, int], move: str = "push", strength: float = 1.0,
                 depth: np.ndarray | None = None, cache_path: Path | None = None):
        out_w, out_h = size
        h, w = img_bgr.shape[:2]
        scale = max(out_w / w, out_h / h) * 1.12          # 12% overscan so edges never show
        self.img = cv2.resize(img_bgr, (int(w * scale) + 1, int(h * scale) + 1), interpolation=cv2.INTER_LANCZOS4)
        d = depth if depth is not None else depth_map(img_bgr, cache_path)
        self.depth = cv2.resize(d, (self.img.shape[1], self.img.shape[0]), interpolation=cv2.INTER_LINEAR)
        self.size, self.move, self.k = size, move, strength
        H, W = self.img.shape[:2]
        self.cx, self.cy = W / 2, H / 2
        # the motion field is smooth, so it is computed at half resolution and upscaled (about 5x faster)
        self.half = (out_w // 2, out_h // 2)
        ys, xs = np.mgrid[0:self.half[1], 0:self.half[0]].astype(np.float32)
        self.gx = xs * 2 - out_w / 2                        # output pixel grid (full-res units), centred
        self.gy = ys * 2 - out_h / 2

    def frame(self, p: float) -> np.ndarray:
        """p in 0..1 = progress through the shot (ease applied here)."""
        # constant speed with only a short soft start (owner 13 Nov: easing in and out on every short shot looked
        # like the picture breathing in and out)
        e = p if p > 0.08 else p * p / 0.16
        out_w, out_h = self.size
        k = self.k
        zoom, dx, dy = 1.0, 0.0, 0.0
        par_x = par_y = 0.0                                  # how much near pixels move extra (px)
        if self.move == "push":
            zoom = 1.0 + 0.04 * k * e
            par_x, par_y = 0.0, 0.0
        elif self.move == "pull":
            zoom = 1.04 - 0.04 * k * e
        elif self.move in ("pan_left", "pan_right"):
            sgn = 1 if self.move == "pan_right" else -1
            dx = sgn * (e - 0.5) * 0.04 * out_w * k
            par_x = sgn * (e - 0.5) * 0.022 * out_w * k
            zoom = 1.03
        elif self.move == "rise":
            dy = -(e - 0.5) * 0.03 * out_h * k
            par_y = -(e - 0.5) * 0.02 * out_h * k
            zoom = 1.03
        else:  # orbit: small circular drift
            ang = e * np.pi
            par_x = np.cos(ang) * 0.025 * out_w * k
            par_y = np.sin(ang) * 0.015 * out_h * k
            zoom = 1.04
        # depth-dependent displacement: near pixels (depth ~1) move/zoom more than far ones
        dzoom = (zoom - 1.0) * 1.0                           # gentle depth: near objects no longer swell
        sample_scale = 1.0 / zoom
        mx = self.cx + dx + self.gx * sample_scale
        my = self.cy + dy + self.gy * sample_scale
        dep = cv2.remap(self.depth, mx.astype(np.float32), my.astype(np.float32), cv2.INTER_LINEAR,
                        borderMode=cv2.BORDER_REPLICATE)
        near = dep - 0.5
        mx = mx - near * par_x - self.gx * sample_scale * near * dzoom * 0.5
        my = my - near * par_y - self.gy * sample_scale * near * dzoom * 0.5
        mx = cv2.resize(mx.astype(np.float32), (out_w, out_h), interpolation=cv2.INTER_LINEAR)
        my = cv2.resize(my.astype(np.float32), (out_w, out_h), interpolation=cv2.INTER_LINEAR)
        return cv2.remap(self.img, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)


def pick_move(i: int, rng: np.random.Generator | None = None) -> str:
    rng = rng or np.random.default_rng(i)
    return MOVES[int(rng.integers(0, len(MOVES)))]
