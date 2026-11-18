"""3D emoji stickers (Google Noto Emoji, SIL Open Font License — free for commercial use).
Downloaded once per emoji into assets/emoji."""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import requests

from ..config import ROOT

EMOJI_DIR = ROOT / "assets" / "emoji"
BASE = "https://raw.githubusercontent.com/googlefonts/noto-emoji/main"


def _codes(emoji: str) -> str:
    return "_".join(f"{ord(c):x}" for c in emoji if ord(c) != 0xFE0F)


def emoji_png(emoji: str) -> Path | None:
    if not emoji:
        return None
    code = _codes(emoji.strip())
    dest = EMOJI_DIR / f"{code}.png"
    if dest.exists():
        return dest
    EMOJI_DIR.mkdir(parents=True, exist_ok=True)
    for style in ("3D", "2D"):
        try:
            r = requests.get(f"{BASE}/{style}/png/512/emoji_u{code}.png", timeout=30)
        except requests.RequestException:
            return None
        if r.ok and r.content[:4] == b"\x89PNG":
            dest.write_bytes(r.content)
            return dest
    return None


def load_rgba(path: Path, size: int) -> np.ndarray:
    """BGRA image resized to size x size."""
    img = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if img.shape[2] == 3:
        img = np.dstack([img, np.full(img.shape[:2], 255, np.uint8)])
    return cv2.resize(img, (size, size), interpolation=cv2.INTER_AREA)
