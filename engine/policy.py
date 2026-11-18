"""Never-topics: one list (config/never_topics.yaml) that every part of the system obeys - the trend radar, the week
planner, the script writer and the campaign gate. Owner's rule: "avoid these topics"."""
from __future__ import annotations

import re
from functools import lru_cache

from .config import CONFIG_DIR


@lru_cache(maxsize=1)
def _load() -> dict:
    import yaml
    path = CONFIG_DIR / "never_topics.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
    cats = {}
    for key, c in (data.get("categories") or {}).items():
        pats = [re.compile(p, re.I) for p in c.get("patterns") or []]
        cats[key] = {"why": c.get("why", key), "patterns": pats}
    return {"categories": cats, "modes": data.get("modes") or {},
            "writer_rules": [" ".join(str(r).split()) for r in data.get("writer_rules") or []]}


def topic_flags(text: str, mode: str = "trend") -> list[str]:
    """Names of the never-categories the text touches ([] = fine). mode: trend (strict) | topic | campaign."""
    d = _load()
    allowed = set(d["modes"].get(mode) or d["categories"])
    t = text or ""
    return [k for k, c in d["categories"].items() if k in allowed and any(p.search(t) for p in c["patterns"])]


def never_rules_text() -> str:
    """Plain-language rules for prompts (topic picker and script writer)."""
    d = _load()
    lines = ["Never make a video about: " + "; ".join(c["why"] for c in d["categories"].values()) + "."]
    return "\n".join(lines + d["writer_rules"])
