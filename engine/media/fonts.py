"""Free fonts (SIL Open Font License / Apache 2.0 — commercial use allowed), downloaded once
from the official Google Fonts repository into assets/fonts."""
from __future__ import annotations

from pathlib import Path

import requests

from ..config import ROOT

FONTS_DIR = ROOT / "assets" / "fonts"
BASE = "https://github.com/google/fonts/raw/main"

# family name (as libass sees it) -> (repo path, local file)
FONTS = {
    "Poppins Black": ("ofl/poppins/Poppins-Black.ttf", "Poppins-Black.ttf"),          # captions, EN + Hindi
    "Poppins ExtraBold": ("ofl/poppins/Poppins-ExtraBold.ttf", "Poppins-ExtraBold.ttf"),
    "Bebas Neue": ("ofl/bebasneue/BebasNeue-Regular.ttf", "BebasNeue-Regular.ttf"),   # tall cinematic titles
    "Anton": ("ofl/anton/Anton-Regular.ttf", "Anton-Regular.ttf"),                    # heavy thumbnail text
    "Luckiest Guy": ("apache/luckiestguy/LuckiestGuy-Regular.ttf", "LuckiestGuy-Regular.ttf"),  # playful
    "Bangers": ("ofl/bangers/Bangers-Regular.ttf", "Bangers-Regular.ttf"),            # comic / kids
    "Khand": ("ofl/khand/Khand-Bold.ttf", "Khand-Bold.ttf"),                          # Hindi headlines (condensed)
    "Rozha One": ("ofl/rozhaone/RozhaOne-Regular.ttf", "RozhaOne-Regular.ttf"),       # Hindi history titles
    "Mukta ExtraBold": ("ofl/mukta/Mukta-ExtraBold.ttf", "Mukta-ExtraBold.ttf"),      # Hindi body
    "Hind": ("ofl/hind/Hind-Bold.ttf", "Hind-Bold.ttf"),
    "Oswald": ("ofl/oswald/Oswald%5Bwght%5D.ttf", "Oswald.ttf"),
    "Special Elite": ("apache/specialelite/SpecialElite-Regular.ttf", "SpecialElite-Regular.ttf"),   # typewriter
    "Teko": ("ofl/teko/Teko%5Bwght%5D.ttf", "Teko.ttf"),                                   # scoreboard numbers
}

# Look per channel type: caption font, title font (English / Hindi)
LOOKS = {
    "story": {"caption": "Poppins Black", "title_en": "Bebas Neue", "title_hi": "Khand"},
    "history": {"caption": "Poppins Black", "title_en": "Bebas Neue", "title_hi": "Rozha One"},
    "clips": {"caption": "Poppins Black", "title_en": "Anton", "title_hi": "Khand"},
    "brainrot": {"caption": "Luckiest Guy", "title_en": "Luckiest Guy", "title_hi": "Poppins Black"},
    "kids": {"caption": "Luckiest Guy", "title_en": "Bangers", "title_hi": "Poppins Black"},
}


def ensure_fonts() -> Path:
    FONTS_DIR.mkdir(parents=True, exist_ok=True)
    for _family, (remote, local) in FONTS.items():
        dest = FONTS_DIR / local
        if dest.exists() and dest.stat().st_size > 10_000:
            continue
        resp = requests.get(f"{BASE}/{remote}", timeout=60)
        resp.raise_for_status()
        dest.write_bytes(resp.content)
    return FONTS_DIR


def look(kind: str) -> dict:
    return LOOKS.get(kind, LOOKS["story"])


def caption_font(language: str, kind: str = "story") -> str:
    f = look(kind)["caption"]
    # Playful Latin fonts have no Devanagari letters
    return "Poppins Black" if language == "hi" and f in ("Luckiest Guy", "Bangers") else f


def title_font(language: str, kind: str = "story") -> str:
    return look(kind)["title_hi" if language == "hi" else "title_en"]


def font_for(language: str) -> str:
    """Older helper: caption font for a language."""
    return caption_font(language)


def font_file(family: str) -> Path:
    ensure_fonts()
    return FONTS_DIR / FONTS[family][1]
