"""No repeated titles on a channel (owner 17 Nov 2026: two different Brain Snack videos went out with the same title
"Which try reaches the center? 😭" and looked like one video posted twice; "from now on you have to be careful").

used_titles(): every title already uploaded (publish log) or given to a made/approved video in the plans.
pick(): the first option nobody used yet; if all were used, the best option plus a short distinguishing detail.
"""
from __future__ import annotations

import json
import re

from .config import ROOT

LOG = ROOT / "data" / "publish_log.jsonl"


def _norm(t: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(t).lower()).strip()


def used_titles(channel_id: str) -> set[str]:
    out: set[str] = set()
    if LOG.exists():
        for line in LOG.read_text(encoding="utf-8").splitlines():
            try:
                a = json.loads(line)
            except ValueError:
                continue
            if a.get("channel") == channel_id and a.get("done"):
                t = (a.get("details") or {}).get("title")
                if t:
                    out.add(_norm(t))
    try:
        from . import weekly
        for plan in weekly.WEEKS_DIR.glob("*/plan.json"):
            for it in json.loads(plan.read_text(encoding="utf-8")).get("items") or []:
                if it.get("channel") == channel_id and it.get("title"):
                    out.add(_norm(it["title"]))
    except Exception:  # noqa: BLE001
        pass
    folder = ROOT / "output" / channel_id
    for meta in [*folder.glob("*/meta.json"), *folder.glob("*/upload.json")] if folder.exists() else []:
        try:
            t = json.loads(meta.read_text(encoding="utf-8")).get("title")
            if t:
                out.add(_norm(t))
        except (OSError, ValueError):
            continue
    return out


def pick(channel_id: str, options: list[str], detail: str = "", used: set[str] | None = None) -> list[str]:
    """The options reordered so the first one is unused on this channel; a detail is added when all are used."""
    used = used_titles(channel_id) if used is None else used
    fresh = [t for t in options if _norm(t) not in used]
    if fresh:
        return fresh + [t for t in options if t not in fresh]
    base = options[0] if options else "New video"
    for n in range(2, 200):
        extra = detail or f"Round {n}"
        cand = _join(base, extra if detail and n == 2 else f"{extra} {n}" if detail else extra)
        if _norm(cand) not in used:
            return [cand] + options
    return options


def freshest(channel_id: str, options: list[str], past: set[str] | None = None) -> list[str]:
    """Options ordered by how different they are from every earlier title/topic of the channel, measured the way the
    potential gate measures it (normalised text, difflib ratio; >= 0.85 = "title nearly repeats"). 21 Nov: every
    Bloop long title came from one template and was held as a near-repeat."""
    import difflib
    if past is None:
        past = set(used_titles(channel_id))
        try:
            from .weekly import past_topics
            past |= {_norm(t) for t in past_topics(channel_id)}
        except Exception as e:  # noqa: BLE001 - titles still checked against the used ones (said, never silent)
            print(f"uniq: past topics unreadable for {channel_id} ({type(e).__name__}: {e})")

    def worst(t: str) -> float:
        n = _norm(t)
        return max((difflib.SequenceMatcher(None, n, p).ratio() for p in past if p and p != n), default=0.0)
    return sorted(options, key=worst)


def _join(title: str, extra: str) -> str:
    """'Which try reaches the center? 😭' + 'Macy's balloons' -> 'Which try reaches the center? (Macy's balloons) 😭'"""
    m = re.match(r"^(.*?)(\s*[\U0001F300-\U0001FAFF☀-➿]+)?$", title.strip())
    core, emoji = (m.group(1), m.group(2) or "") if m else (title, "")
    return f"{core} ({extra[:40]}){emoji}"
