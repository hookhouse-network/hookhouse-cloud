"""Research before building (owner, 16 Nov, from the two income articles: "find one problem that keeps appearing in
different places"; "views are attention, questions are intent"). Once a week it ranks the ideas in
config/product_ideas.yaml and sends the top ones to Telegram; the owner says which to build (nothing is built or
listed without that).

Signals, all free and official (no scraping):
- demand: the median views of the most-viewed YouTube videos of the last 12 months for what buyers type
  (YouTube Data API search + videos, ~101 units per idea, inside the daily quota)
- intent: our own viewers' buying questions ("where can I get this planner?", "pdf link do") from engine/comments
- season: the months the idea sells best (planners peak Nov-Jan, coloring pages before holidays...)
- effort: an existing maker can be re-used (easy) or new code is needed
Usage: python -m engine.product_research        rank now and print (no Telegram)"""
from __future__ import annotations

import json
import math
import statistics
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
import yaml

from .config import ROOT

IDEAS = ROOT / "config" / "product_ideas.yaml"
OUT = ROOT / "data" / "state" / "product_research.json"
API = "https://www.googleapis.com/youtube/v3"
UNITS = 101
EFFORT = {"easy": 1.0, "new": 0.7, "have": 0.0}         # "have": measured, but not suggested as a new product


def ideas() -> list[dict]:
    return yaml.safe_load(IDEAS.read_text(encoding="utf-8")) or []


def demand(query: str, session=requests) -> dict:
    """{'median': views, 'top': [(title, views)]} for the most-viewed videos of the last 12 months."""
    from .niche_winners import _auth
    from .publish import add_quota, quota_ok
    auth = _auth(session)
    if not auth or not quota_ok(UNITS, "search"):
        return {}
    params, headers = auth
    after = (datetime.now(timezone.utc) - timedelta(days=365)).strftime("%Y-%m-%dT%H:%M:%SZ")
    r = session.get(f"{API}/search", headers=headers, timeout=30, params={
        **params, "part": "snippet", "type": "video", "q": query, "order": "viewCount", "publishedAfter": after,
        "maxResults": 10, "safeSearch": "moderate"})
    add_quota(UNITS - 1, "search")                          # search.list has its own bucket (since Jun 2026)
    r.raise_for_status()
    found = {it["id"]["videoId"]: it["snippet"]["title"] for it in r.json().get("items", [])
             if it.get("id", {}).get("videoId")}
    if not found:
        return {"median": 0, "top": []}
    v = session.get(f"{API}/videos", headers=headers, timeout=30,
                    params={**params, "part": "statistics", "id": ",".join(found)})
    add_quota(1)                                            # videos.list: general bucket
    v.raise_for_status()
    views = {it["id"]: int(it.get("statistics", {}).get("viewCount", 0)) for it in v.json().get("items", [])}
    ranked = sorted(((found[k], n) for k, n in views.items()), key=lambda x: -x[1])
    return {"median": int(statistics.median([n for _, n in ranked])) if ranked else 0, "top": ranked[:3]}


def intent(idea: dict, signals: list[tuple[str, str]]) -> int:
    """How many of our viewers' buying questions mention this idea (any word of its search, 4+ letters)."""
    words = [w for w in idea["search"].lower().split() if len(w) >= 4 and w not in ("printable", "for", "kids")]
    return sum(1 for _, text in signals if any(w in text.lower() for w in words))


def score(idea: dict, dem: dict, buys: int, month: int) -> float:
    d = math.log10(1 + (dem.get("median") or 0))              # 10k views -> 4, 1M -> 6
    season = 1.3 if month in idea.get("months", []) else (1.1 if ((month % 12) + 1) in idea.get("months", []) else 1.0)
    return round(d * season * (1 + 0.5 * min(buys, 4)) * EFFORT.get(idea.get("build", "new"), 0.7), 2)


def run(session=requests, now: datetime | None = None, log=print) -> list[dict]:
    from . import comments
    now = now or datetime.now()
    try:
        signals = comments.buy_signals(30)
    except Exception:  # noqa: BLE001 - no comment database yet
        signals = []
    rows = []
    for idea in ideas():
        try:
            dem = demand(idea["search"], session)
        except Exception as e:  # noqa: BLE001
            log(f"research {idea['id']}: {str(e)[:100]}")
            dem = {}
        buys = intent(idea, signals)
        rows.append({**idea, "median_views": dem.get("median"), "top": dem.get("top", []), "buy_questions": buys,
                     "score": score(idea, dem, buys, now.month)})
    rows.sort(key=lambda r: -r["score"])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"at": time.time(), "ideas": rows}, indent=1, ensure_ascii=False), encoding="utf-8")
    return rows


def text(rows: list[dict], k: int = 3) -> str:
    new = [r for r in rows if r.get("build") != "have" and r["score"] > 0][:k]
    have = [r for r in rows if r.get("build") == "have"]
    if not new:
        return ""
    lines = ["🔎 Weekly product research: what people already want (research first, build second)"]
    for i, r in enumerate(new, 1):
        views = f"{r['median_views']:,}" if r.get("median_views") is not None else "?"
        why = [f"top videos ~{views} views/yr"]
        if r["buy_questions"]:
            why.append(f"{r['buy_questions']} of our viewers asked for it")
        if datetime.now().month in r.get("months", []):
            why.append("selling season now")
        lines.append(f"{i}. {r['name']} (fits {r['fits']}): " + ", ".join(why))
    if have:
        best = max(have, key=lambda r: r.get("median_views") or 0)
        lines.append(f"\nOf what we already sell, the strongest demand is: {best['name'].replace(' (have)', '')}.")
    lines.append("Reply to Claude \"build <name>\" to make one (it comes back here for ✅ before it is listed).")
    return "\n".join(lines)


def weekly(log=print) -> int:
    rows = run(log=log)
    msg = text(rows)
    if msg:
        from .telegram_bot import notify
        notify(msg)
    return len(rows)


if __name__ == "__main__":
    from .config import load_env
    load_env()
    for r in run():
        print(f"{r['score']:5}  {r['name'][:45]:45}  views~{r.get('median_views')}  buys={r['buy_questions']}")
