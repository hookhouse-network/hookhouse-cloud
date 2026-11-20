"""Analytics-driven volume (docs/ARCHITECTURE.md, phase 7: capacity-aware planning).

Owner, 20 Nov: "generate more and more videos ... as per the analytics data and its limitations"; "the system must
learn from its analytics data ... to earn more and more".

Before: every story channel got a fixed 1 Short a day from config/channels.yaml, whatever it earned, so a channel
whose Shorts get 20x the views of another got the same share of the scarce making capacity (AI writing, pictures,
render time).

Now, once a week before planning:
1. Score each channel by its median views per Short across every platform (the latest numbers per video, last
   SCORE_DAYS), shrunk towards the all-channel median when it has few videos (empirical-Bayes shrinkage, so two
   lucky videos don't take over and a new channel still gets a fair trial).
2. Daily total = the UPLOAD budget (owner 20 Nov: "there will be no limitations for generating the content, it just
   limits the upload amount so we need to follow that"): YouTube's videos.insert bucket (100 a day per project, 80
   with our safety stop) minus what clip/kids channels and long videos use. Instagram/Facebook/Threads limits are per
   account and higher than MAX_PER_CHANNEL. Made-vs-planned is still measured and reported (a making gap shows).
3. Every channel keeps at least 1 a day (exploration: you can't learn about a channel you stop posting on); the rest
   goes to the best scorers (largest-remainder rounding), capped by the channel's peak posting times.
Clip channels keep their configured number: their volume depends on campaign footage, not on this budget.
The result is data/state/allocation.json; weekly.slots_for uses it for shorts_per_day."""
from __future__ import annotations

import json
import statistics
import time
from datetime import datetime, timedelta
from pathlib import Path

from .config import ROOT

FILE = ROOT / "data" / "state" / "allocation.json"
SCORE_DAYS = 21
SHRINK_K = 5            # a channel's own median counts like K videos of evidence against the all-channel median
MAX_TOTAL = 120
MAX_PER_CHANNEL = 8     # Instagram spacing (40 min) and quality: 8 a day per account at most
FRESH_DAYS = 10
FIXED_TYPES = {"clips", "kids"}


def channel_views(conn, days: int = SCORE_DAYS, now: float | None = None) -> dict[str, list[float]]:
    """{channel: [views per Short summed over platforms]} from the newest snapshot of each video."""
    now = now or time.time()
    rows = conn.execute(
        "SELECT channel, item_id, platform, MAX(views) FROM video_metrics WHERE posted_at>? AND views IS NOT NULL "
        "AND (format IS NULL OR format!='long') GROUP BY channel, item_id, platform", (now - days * 86400,)).fetchall()
    per_item: dict[tuple[str, str], float] = {}
    for ch, item, _p, v in rows:
        per_item[(ch, item)] = per_item.get((ch, item), 0.0) + float(v or 0)
    out: dict[str, list[float]] = {}
    for (ch, _item), v in per_item.items():
        out.setdefault(ch, []).append(v)
    return out


def shrunk_scores(views: dict[str, list[float]], channels: list[str], k: int = SHRINK_K) -> dict[str, dict]:
    allv = [v for vs in views.values() for v in vs]
    prior = statistics.median(allv) if allv else 1.0
    out = {}
    for c in channels:
        vs = views.get(c, [])
        med = statistics.median(vs) if vs else prior
        out[c] = {"n": len(vs), "median": round(med, 1), "score": round((len(vs) * med + k * prior) / (len(vs) + k), 2)}
    return out


def youtube_daily_uploads() -> int:
    """YouTube uploads a day for the whole project (videos.insert bucket, our 80 % safety stop)."""
    import os
    from .publish import QUOTA_STOP, UPLOAD_UNITS
    units = int(os.environ.get("YOUTUBE_UPLOAD_QUOTA", os.environ.get("YOUTUBE_DAILY_QUOTA", "10000")))
    return int(units / max(1, UPLOAD_UNITS) * QUOTA_STOP)


def upload_budget(all_chans: list[dict], flexible: list[dict]) -> int:
    """Shorts a day the flexible channels may plan: the YouTube project budget minus what the fixed channels (clips,
    kids, clip-first) and every long video use. Instagram (25), Facebook (25) and Threads (50) are per account and
    far above MAX_PER_CHANNEL, so YouTube is the binding limit."""
    flex = {c["id"] for c in flexible}
    fixed = 0.0
    for c in all_chans:
        if c.get("active") is False:
            continue
        sc = c.get("schedule") or {}
        fixed += float(sc.get("long_per_week", 0)) / 7
        if c["id"] not in flex:
            fixed += float(sc.get("shorts_per_day", 0)) + float(sc.get("shorts_per_week", 0)) / 7
    return max(len(flexible), int(youtube_daily_uploads() - fixed + 0.0001))


def made_ratio(items: list[dict], now: datetime, days: int = 7) -> tuple[int, int]:
    """(made, planned) Shorts whose slot was in the last `days`."""
    made = planned = 0
    for it in items:
        if it.get("kind") == "long":
            continue
        try:
            w = datetime.fromisoformat(it["publish_at"])
        except (KeyError, ValueError, TypeError):
            continue
        if now - timedelta(days=days) <= w <= now:
            planned += 1
            made += bool(it.get("made_at")) or it.get("status") in ("made", "approved", "posted")
    return made, planned


def allocate(chans: list[dict], scores: dict[str, dict], total: int, caps: dict[str, int]) -> dict[str, int]:
    ids = [c["id"] for c in chans]
    if not ids:
        return {}
    total = max(total, len(ids))
    alloc = {c: 1 for c in ids}
    left = total - len(ids)
    weights = {c: max(scores.get(c, {}).get("score", 1.0), 0.01) for c in ids}
    while left > 0:
        open_ = [c for c in ids if alloc[c] < caps.get(c, MAX_PER_CHANNEL)]
        if not open_:
            break
        w_sum = sum(weights[c] for c in open_)
        quota = {c: left * weights[c] / w_sum for c in open_}
        grants = {c: int(quota[c]) for c in open_}
        for c in open_:
            grants[c] = min(grants[c], caps.get(c, MAX_PER_CHANNEL) - alloc[c])
        given = sum(grants.values())
        if given == 0:                                      # largest remainder: one at a time to the best claim
            c = max(open_, key=lambda x: (quota[x] - int(quota[x]), weights[x]))
            grants = {c: 1}
            given = 1
        for c, g in grants.items():
            alloc[c] += g
        left -= given
    return alloc


def build(log=print, conn=None, now: datetime | None = None, plan_items: list[dict] | None = None) -> dict:
    from . import weekly
    from .config import channels
    now = now or datetime.now(weekly._zone())
    chans = [c for c in channels() if c.get("active") is not False and c.get("type") in weekly.BUILDABLE
             and c.get("type") not in FIXED_TYPES and not c.get("clips_first") and int((c.get("schedule") or {}).get("shorts_per_day", 0)) >= 1]
    base_total = sum(int(c["schedule"]["shorts_per_day"]) for c in chans)
    if plan_items is None:
        plan_items = []
        for p in sorted(weekly.WEEKS_DIR.glob("*/plan.json")) if weekly.WEEKS_DIR.exists() else []:
            try:
                plan_items += json.loads(p.read_text(encoding="utf-8")).get("items") or []
            except (OSError, ValueError) as e:
                log(f"allocation: skipped unreadable {p.parent.name}: {e}")
    ids = {c["id"] for c in chans}
    made, planned = made_ratio([i for i in plan_items if i.get("channel") in ids], now)
    # owner 20 Nov: "there will be no limitations for generating the content, it just limits the upload amount":
    # the daily total is what the platforms let us upload, not what was made last week
    budget = upload_budget(channels(), chans)
    total, reason = max(base_total, min(MAX_TOTAL, budget)), f"upload budget {budget}/day"
    if conn is None:
        from . import analytics
        conn = analytics.connect()
    views = channel_views(conn)
    scores = shrunk_scores(views, [c["id"] for c in chans])
    caps = {c["id"]: MAX_PER_CHANNEL for c in chans}     # weekly.spread_times adds slots past the peak times
    alloc = allocate(chans, scores, total, caps)
    out = {"at": time.time(), "day": now.date().isoformat(), "total": total, "reason": reason,
           "made_last_7d": made, "planned_last_7d": planned,
           "channels": {c: {"shorts_per_day": alloc[c], **scores[c]} for c in alloc}}
    from .core.atomic import write_json
    write_json(FILE, out)
    from .core import ledger
    ledger.event("allocation", data={"total": total, "reason": reason,
                                     "channels": {c: alloc[c] for c in alloc}})
    log(f"allocation: {total}/day ({reason}); made {made}/{planned} last week; "
        + ", ".join(f"{c} {n}" for c, n in sorted(alloc.items(), key=lambda x: -x[1])))
    return out


def load(any_age: bool = False) -> dict:
    try:
        d = json.loads(FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not any_age and time.time() - float(d.get("at") or 0) > FRESH_DAYS * 86400:
        return {}
    return d


def shorts_per_day(ch: dict) -> int:
    """The planner's number for this channel: the allocation when fresh, else the configured one."""
    base = int((ch.get("schedule") or {}).get("shorts_per_day", 0))
    if base < 1 or ch.get("type") in FIXED_TYPES or ch.get("clips_first"):
        return base
    got = (load().get("channels") or {}).get(ch["id"], {}).get("shorts_per_day")
    return int(got) if got else base


def text(d: dict | None = None) -> str:
    """Telegram / Studio summary."""
    d = d or load(any_age=True)
    if not d:
        return "No allocation yet (made before the next weekly plan)."
    best = sorted(d["channels"].items(), key=lambda x: -x[1]["shorts_per_day"])
    lines = [f"📊 Volume plan: {d['total']} Shorts a day ({d['reason']}; made {d['made_last_7d']}/"
             f"{d['planned_last_7d']} last week)"]
    lines += [f"• {c}: {v['shorts_per_day']}/day (median {v['median']:.0f} views, {v['n']} videos)" for c, v in best]
    return "\n".join(lines)
