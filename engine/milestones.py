"""Money milestones (owner 18 Nov: "earning more and more from every possible way"; YouTube Creator Roundup 30 Oct 2026:
Shopping affiliate in India opened to Partner Program creators from 500 subscribers).

Each morning every channel's public numbers (stats_fetch.live_stats) are compared with the YouTube thresholds; the
owner gets one Telegram message per channel per milestone, the moment it can apply (applying is the owner's tap).
Shorts views use the channel's lifetime views: a channel only reaches these numbers through Shorts in its first months,
and YouTube's own check in Studio decides in the end.
"""
from __future__ import annotations

import json

from .config import ROOT

STATE = ROOT / "data" / "state" / "milestones.json"
# (key, subscribers, Shorts views, what it unlocks, where to apply)
MILESTONES = [
    ("ypp_expanded", 500, 3_000_000, "the expanded YouTube Partner Program: Super Thanks, memberships and the YouTube "
     "Shopping affiliate (Flipkart, Amazon, Myntra... commission on products in our videos)",
     "YouTube Studio > Earn > Apply"),
    ("ypp_full", 1000, 10_000_000, "full YouTube Partner Program: a share of ad revenue on Shorts and long videos",
     "YouTube Studio > Earn > Apply"),
]


def _state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def due(stats: dict, done: dict) -> list[tuple[str, tuple]]:
    """[(channel id, milestone)] reached and not announced yet."""
    out = []
    for cid, c in (stats.get("channels") or {}).items():
        subs, views = int(c.get("subs") or 0), int(c.get("views") or 0)
        for m in MILESTONES:
            if subs >= m[1] and views >= m[2] and m[0] not in done.get(cid, []):
                out.append((cid, m))
    return out


def check(send=None, log=print) -> int:
    from .config import channels
    from .stats_fetch import live_stats
    if send is None:
        from .telegram_bot import notify as send
    names = {c["id"]: c["name"] for c in channels()}
    st = _state()
    n = 0
    for cid, (key, subs, views, what, where) in due(live_stats(), st):
        send(f"💰 {names.get(cid, cid)} can now join {what}.\n"
             f"It has {subs:,}+ subscribers and {views:,}+ views. Apply in {where} (your tap: it accepts YouTube's "
             "terms). Tell me when it's approved and I'll switch the product tags on.")
        st.setdefault(cid, []).append(key)
        n += 1
        log(f"milestone: {cid} {key}")
    if n:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(st), encoding="utf-8")
    return n
