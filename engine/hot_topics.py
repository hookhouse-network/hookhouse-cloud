"""Hot topics ("most talked-about right now"): a fixed list (config/hot_topics.yaml, e.g. GTA 6) plus the day's
safe trending items from the trend radar. Used to push matching campaigns to the top of the owner's list."""
from __future__ import annotations
from engine.core.quiet import noted

import re
from datetime import date

import yaml

from .config import ROOT

CONFIG = ROOT / "config" / "hot_topics.yaml"


def topics(with_trends: bool = True) -> list[dict]:
    today = date.today()
    out = []
    for t in (yaml.safe_load(CONFIG.read_text(encoding="utf-8")) or []) if CONFIG.exists() else []:
        until = t.get("until")
        if until and date.fromisoformat(str(until)) < today:
            continue
        out.append({"name": t["name"], "keywords": [k.lower() for k in t.get("keywords", [])],
                    "boost": t.get("boost", 10)})
    if with_trends:
        try:
            from .trends import collect
            for it in collect(log=lambda *_: None).get("items", [])[:40]:
                title = str(it.get("title", "")).replace("_", " ").strip()
                if len(title) >= 4:
                    out.append({"name": f"Trending: {title}", "keywords": [title.lower()], "boost": 10})
        except Exception as _swallowed:  # noqa: BLE001 - no trends today just means no extra boosts
            noted("hot_topics.py:31", _swallowed)
            pass
    return out


def match(campaign: dict, tops: list[dict] | None = None) -> tuple[list[str], int]:
    """(hot topic names the campaign matches, total boost)."""
    tops = topics() if tops is None else tops
    text = " ".join(str(campaign.get(k) or "") for k in ("name", "brand", "niche", "content_type", "campaign_type",
                                                          "allowed_sources", "other_rules", "url")).lower()
    names, boost = [], 0
    for t in tops:
        if any(re.search(r"(?<![a-z0-9])" + re.escape(k) + r"(?![a-z0-9])", text) for k in t["keywords"]):
            names.append(t["name"])
            boost += t["boost"]
    return names, boost
