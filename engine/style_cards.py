"""Channel style cards v2 (plan P3r creativity, standard S8 A3 + A16 + A17): angle, voice, pillars, visual style and
humour per story channel (config/style_cards.yaml). The script writer gets the card; the storyboard gets the visual
line, so pictures look like one channel instead of random stock (S10 human-made feel)."""
from __future__ import annotations

import yaml

from .config import ROOT

FILE = ROOT / "config" / "style_cards.yaml"


def card(cid: str) -> dict:
    try:
        data = yaml.safe_load(FILE.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as e:
        print(f"style cards: unreadable ({type(e).__name__}: {e})")
        return {}
    c = data.get(cid) or {}
    return c if isinstance(c, dict) else {}


def writer_text(cid: str) -> str:
    """The card as writer rules (empty when the channel has none)."""
    c = card(cid)
    if not c:
        return ""
    lines = ["CHANNEL STYLE CARD (every video must feel like this channel):"]
    if c.get("angle"):
        lines.append(f"- Angle: {c['angle']}")
    if c.get("voice"):
        lines.append(f"- Narrator voice: {c['voice']}")
    if c.get("pillars"):
        lines.append(f"- Content pillars (stay inside them): {', '.join(c['pillars'])}")
    if c.get("humour"):
        lines.append(f"- Humour: {c['humour']}")
    return "\n".join(lines)


def visual_text(cid: str) -> str:
    c = card(cid)
    return f"CHANNEL LOOK: {c['visual']}" if c.get("visual") else ""
