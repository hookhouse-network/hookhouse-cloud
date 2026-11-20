"""Topic proof: evidence that a topic has demand RIGHT NOW (owner, 20 Nov 2026: "content ... must be perfect, with
quality and has full potential to go viral and it will earn money"; "R&D ... according to channel's niche and
latest viral, most talked and trending topics").

The planner's writer proposes topics from trends, the topic bank, the reviews and the niche winners. This module
checks each proposal against the platform's own numbers before a video is made:
  - YouTube Data API search (official, no scraping): the most-viewed videos on this topic published in the last
    WINDOW_D days in the channel's market/language, then their real view counts (videos.list).
  - Demand = views per day of the best recent videos. Tiers: hot (>= HOT views/day), warm (>= WARM), cold (videos
    exist but few watch), none (nobody made it recently: either a gap or no interest; the potential judge decides
    with this evidence).
Results are cached per topic for CACHE_D days and the searches per day are capped (the search bucket also serves
niche_winners and product research). No API access = no proof (unknown), never a fake pass.

Used by weekly.pick_topics (a cold/none topic is replaced once with the evidence in the prompt) and by the potential
judge (engine/potential_gate.py) as demand evidence."""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timedelta, timezone

from .config import ROOT
from .core.http import HTTP

FILE = ROOT / "data" / "state" / "topic_proof.json"
WINDOW_D = 30
CACHE_D = 3
DAILY_SEARCHES = 30
HOT, WARM = 50_000, 5_000            # views per day of the best recent video on the topic
_NORM = re.compile(r"[^a-z0-9ऀ-ॿ ]+")


def _norm(topic: str) -> str:
    return " ".join(_NORM.sub(" ", str(topic or "").lower()).split())[:120]


def _load() -> dict:
    try:
        return json.loads(FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"topics": {}, "day": "", "searches": 0}


def _save(d: dict) -> None:
    from .core.atomic import write_json
    write_json(FILE, d)


def tier(best_per_day: float, n: int) -> str:
    if n == 0:
        return "none"
    return "hot" if best_per_day >= HOT else "warm" if best_per_day >= WARM else "cold"


def measure(topic: str, ch: dict, session=HTTP, now: float | None = None) -> dict | None:
    """One search + one videos.list. None = could not measure (no access, quota, error)."""
    from .niche_winners import API, SEARCH_UNITS, _auth
    from .publish import add_quota, quota_ok
    auth = _auth(session)
    if not auth or not quota_ok(SEARCH_UNITS, "search"):
        return None
    params, headers = auth
    hindi = ch.get("language") == "hi"
    now = now or time.time()
    after = (datetime.fromtimestamp(now, timezone.utc) - timedelta(days=WINDOW_D)).strftime("%Y-%m-%dT%H:%M:%SZ")
    r = session.get(f"{API}/search", headers=headers, timeout=30, params={
        **params, "part": "snippet", "type": "video", "q": topic[:100], "order": "viewCount", "publishedAfter": after,
        "maxResults": 8, "regionCode": "IN" if hindi else "US", "relevanceLanguage": "hi" if hindi else "en",
        "safeSearch": "strict" if ch.get("made_for_kids") or ch.get("type") == "kids" else "moderate"})
    add_quota(SEARCH_UNITS, "search")
    r.raise_for_status()
    found = [(x["id"]["videoId"], x["snippet"]) for x in r.json().get("items", []) if x.get("id", {}).get("videoId")]
    vids = []
    if found:
        v = session.get(f"{API}/videos", headers=headers, timeout=30,
                        params={**params, "part": "statistics", "id": ",".join(i for i, _ in found)})
        add_quota(1)
        v.raise_for_status()
        stats = {x["id"]: int((x.get("statistics") or {}).get("viewCount") or 0) for x in v.json().get("items") or []}
        for vid, sn in found:
            try:
                pub = datetime.fromisoformat(str(sn.get("publishedAt", "")).replace("Z", "+00:00")).timestamp()
            except ValueError:
                continue
            days = max(1.0, (now - pub) / 86400)
            vids.append({"title": str(sn.get("title") or "")[:100], "views": stats.get(vid, 0),
                         "per_day": round(stats.get(vid, 0) / days)})
    vids.sort(key=lambda x: x["per_day"], reverse=True)
    best = vids[0]["per_day"] if vids else 0
    return {"tier": tier(best, len(vids)), "best_per_day": best, "videos": len(vids), "top": vids[:3], "at": now}


def proof(topic: str, ch: dict, session=HTTP, now: float | None = None, budget: int | None = None,
          log=print) -> dict:
    """Cached evidence for a topic: {tier: hot|warm|cold|none|unknown, best_per_day, top: [...]}."""
    now = now or time.time()
    key = f"{ch.get('market', '')}|{ch.get('language', '')}|{_norm(topic)}"
    d = _load()
    hit = d["topics"].get(key)
    if hit and now - float(hit.get("at") or 0) < CACHE_D * 86400:
        return hit
    day = datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m-%d")
    if d.get("day") != day:
        d["day"], d["searches"] = day, 0
    cap = DAILY_SEARCHES if budget is None else budget
    if d["searches"] >= cap:
        return {"tier": "unknown", "why": "daily search budget used"}
    try:
        res = measure(topic, ch, session=session, now=now)
    except Exception as e:  # noqa: BLE001 - unknown, never a fake pass
        log(f"topic proof failed for {topic[:60]}: {type(e).__name__}: {e}")
        res = None
    if res is None:
        return {"tier": "unknown", "why": "no YouTube access or quota"}
    d["searches"] += 1
    d["topics"][key] = res
    cut = now - 30 * 86400                                   # keep the file small
    d["topics"] = {k: v for k, v in d["topics"].items() if float(v.get("at") or 0) > cut}
    _save(d)
    return res


def evidence_text(p: dict) -> str:
    """One line for the writer / the judge."""
    t = p.get("tier", "unknown")
    if t == "unknown":
        return "demand: unknown (not measured)"
    if t == "none":
        return "demand: no video on this topic in the last 30 days (untested: needs a very strong angle)"
    tops = "; ".join(f"\"{x['title'][:60]}\" {x['per_day']:,}/day" for x in p.get("top") or [])
    return f"demand: {t} (best recent video {p.get('best_per_day', 0):,} views/day; {tops})"
