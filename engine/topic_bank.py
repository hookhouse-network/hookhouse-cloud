"""Topic bank: candidate subjects per channel ranked by real demand (English Wikipedia pageviews, last 12 months).
Built by data/review/topic_demand*.py into config/topic_bank.json. The weekly planner offers the writer a rotating
handful of high-demand subjects that the channel hasn't covered yet (owner, 11 Nov: research every niche for what is
popular, famous and money-worthy). Research: research_notes/Viral faceless video formats 2026/niche_playbooks_2026-11-11.md
"""
from __future__ import annotations

import json
import random
import re

from .config import ROOT

BANK = ROOT / "config" / "topic_bank.json"
NICHE_OF = {"unsolved_after_dark": "mystery", "clutch_tales": "sports_us", "ending_decoded": "movies",
            "money_cheat_codes": "money", "itihaas_ke_raaz": "mythology", "cricket_ke_kisse": "cricket",
            "picture_abhi_baaki_hai": "bollywood", "cosmos_unboxed": "space", "deep_blue_files": "ocean",
            "wild_instinct": "wildlife"}


def _key(t: str) -> str:
    return re.sub(r"\s*\(.*?\)", "", t).lower().strip()


def load() -> dict:
    return json.loads(BANK.read_text(encoding="utf-8")) if BANK.exists() else {}


def hints(channel_id: str, avoid: list[str] | None = None, k: int = 8, top: int = 40, seed: int | None = None) -> list[str]:
    """Up to k high-demand subjects for this channel, skipping ones already in past topics."""
    rows = load().get(NICHE_OF.get(channel_id, ""), [])
    seen = " ".join(avoid or []).lower()
    fresh = [(t, v) for t, v in rows[:top] if v > 0 and _key(t) not in seen]
    rng = random.Random(seed)
    pick = rng.sample(fresh, min(k, len(fresh))) if fresh else []
    pick.sort(key=lambda r: r[1], reverse=True)
    return [f"{_key(t).title()} (high search demand: {v / 1e6:.1f}M Wikipedia views in the last year)" for t, v in pick]
