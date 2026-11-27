"""P8 relative bar, shadow test (owner 27 Nov: "Keep coaching"). It never blocks a video.

The 1-10 judge's absolute scores did not predict views (32 posts under B: Spearman -0.22; the pointwise 'beat the
channel's median score' rule agreed with above/below-median views on 8 of 16 = a coin flip). Research (Kayal et al.,
ACL 2025 Findings) found LLMs rank popularity well when asked RELATIVELY, and pairwise answers carry position bias,
so each pair is asked in both orders.

For every freshly judged video this records (ledger event 'relbar.shadow'):
  - its card (title + the first spoken words), so later videos can be compared against it;
  - the pointwise prediction: its mean judge score vs the median of the channel's posted videos;
  - the pairwise prediction: "which of these two will get more views?" against one posted video of the channel whose
    views are known (the one nearest the channel's median views), asked in both orders; 'split' when they disagree.
report() scores both predictions against real views once a video is 48 h+ old. The 21:00 review shows it; the bar
becomes a blocker only by the owner's decision when it predicts (>= 65 % on >= 30 videos)."""
from __future__ import annotations

import sqlite3
import statistics as st
import time
from pathlib import Path

from .config import ROOT

EVENT = "relbar.shadow"
MATURE_H = 48                      # views are compared once a video is this old
PROVEN_PCT = 65                    # a prediction "works" at this agreement ...
PROVEN_N = 30                      # ... over at least this many videos
CARD_CHARS = 420
DB = ROOT / "data" / "analytics.db"

PAIR_PROMPT = (
    "Two short videos from the same channel, same audience. Predict which one will get MORE views in its first "
    "two days. Judge only the packaging and the content described: the title, the first seconds' words, the topic.\n\n"
    "VIDEO A:\n{a}\n\nVIDEO B:\n{b}\n\n"
    'Answer as JSON: {{"more_views": "A" or "B", "why": "one short sentence"}}')


def card(it: dict, meta: dict) -> str:
    """Title + the first spoken words: what a viewer sees before deciding to stay."""
    title = str((meta or {}).get("title") or it.get("topic") or "").strip()
    try:
        from .potential_gate import script_text
        said = script_text(it, meta or {})
    except Exception:  # noqa: BLE001 - a title-only card still compares
        said = ""
    return (f"Title: {title}\nOpening: {said}")[:CARD_CHARS]


def views(items: list[str], db: Path | None = None, mature_h: float = MATURE_H) -> dict[str, float]:
    """{item: best views} for items whose stats were fetched at least mature_h after posting."""
    if not items:
        return {}
    try:
        c = sqlite3.connect(str(db or DB))
        q = ",".join("?" * len(items))
        rows = c.execute(f"SELECT item_id, MAX(views) FROM video_metrics WHERE item_id IN ({q}) AND views IS NOT NULL "
                         f"AND hours_after >= ? GROUP BY item_id", (*items, mature_h)).fetchall()
        c.close()
    except sqlite3.Error:
        return {}
    return {i: float(v) for i, v in rows if v is not None}


def _records(led, channel: str = "", since: float = 0.0) -> list[dict]:
    rows = led.events(EVENT, since=since)
    return [r for r in rows if not channel or r.get("channel") == channel]


def _latest(rows: list[dict]) -> dict[str, dict]:
    out = {}
    for r in rows:                                   # oldest first: the newest version of an item wins
        out[r["item"]] = r
    return out


def _ask_pair(brain, a: str, b: str) -> str:
    data, _ = brain.ask_json("checker", PAIR_PROMPT.format(a=a, b=b), temperature=0.0)
    pick = str((data or {}).get("more_views") or "").strip().upper()[:1]
    return pick if pick in ("A", "B") else ""


def pairwise(brain, new_card: str, ref_card: str) -> str:
    """'new' / 'ref' when both orders agree, 'split' when the answer follows the position, '' when unanswered."""
    first = _ask_pair(brain, new_card, ref_card)            # new = A
    second = _ask_pair(brain, ref_card, new_card)           # new = B
    if not first or not second:
        return ""
    a = "new" if first == "A" else "ref"
    b = "new" if second == "B" else "ref"
    return a if a == b else "split"


def observe(it: dict, ch: dict, meta: dict, verdict: dict, brain, led=None, db: Path | None = None) -> dict | None:
    """Record the shadow predictions for a freshly judged video. Never raises, never blocks."""
    try:
        if led is None:
            from .core import ledger
            led = ledger.default()
        scores = {k: float(v) for k, v in (verdict.get("scores") or {}).items() if k != "human_feel"}
        if not scores:
            return None
        mean = round(st.mean(scores.values()), 2)
        mine = card(it, meta)
        chan = ch.get("id") or it.get("channel") or ""
        past = {i: r for i, r in _latest(_records(led, chan)).items() if i != it.get("id")}
        seen = views(list(past), db=db)
        rec = {"mean": mean, "card": mine, "median_score": None, "pointwise": None,
               "ref": None, "ref_views": None, "pairwise": None}
        posted = [past[i]["data"].get("mean") for i in seen if past[i]["data"].get("mean") is not None]
        if len(posted) >= 3:
            rec["median_score"] = st.median(posted)
            rec["pointwise"] = "above" if mean > rec["median_score"] else "below"
        if len(seen) >= 3 and brain is not None:
            mid = st.median(seen.values())
            ref = min(seen, key=lambda i: abs(seen[i] - mid))
            ref_card = past[ref]["data"].get("card") or ""
            if ref_card:
                rec.update(ref=ref, ref_views=seen[ref], pairwise=pairwise(brain, mine, ref_card) or None)
        led.event(EVENT, item=it.get("id") or "", channel=chan, data=rec)
        return rec
    except Exception as e:  # noqa: BLE001 - the shadow test never decides a video
        from .core.quiet import noted
        noted("relative_bar.observe", e)
        return None


def report(led=None, db: Path | None = None, days: float = 30) -> dict:
    """How often each shadow prediction matched real views (videos 48 h+ old).
    {pointwise: {right, n, pct}, pairwise: {right, n, pct, split}, proven: [...], line: str}"""
    if led is None:
        from .core import ledger
        led = ledger.default()
    latest = _latest(_records(led, since=time.time() - days * 86400))
    got = views(list(latest), db=db)
    by_ch: dict[str, list[float]] = {}
    for i, v in got.items():
        by_ch.setdefault(latest[i].get("channel") or "", []).append(v)
    pw = {"right": 0, "n": 0}
    pr = {"right": 0, "n": 0, "split": 0}
    for i, v in got.items():
        d = latest[i]["data"]
        ch_views = by_ch.get(latest[i].get("channel") or "", [])
        if d.get("pointwise") and len(ch_views) >= 3 and v != st.median(ch_views):
            pw["n"] += 1
            pw["right"] += (d["pointwise"] == "above") == (v > st.median(ch_views))
        if d.get("pairwise") == "split":
            pr["split"] += 1
        elif d.get("pairwise") in ("new", "ref") and d.get("ref_views") is not None and v != d["ref_views"]:
            pr["n"] += 1
            pr["right"] += (d["pairwise"] == "new") == (v > float(d["ref_views"]))
    for p in (pw, pr):
        p["pct"] = round(100 * p["right"] / p["n"]) if p["n"] else None
    proven = [name for name, p in (("pointwise", pw), ("pairwise", pr))
              if p["n"] >= PROVEN_N and (p["pct"] or 0) >= PROVEN_PCT]
    def pct(p: dict) -> str:
        return f" ({p['pct']} %)" if p["pct"] is not None else ""
    line = (f"Relative bar (shadow, never blocks): pointwise right {pw['right']}/{pw['n']}{pct(pw)}; "
            f"pairwise right {pr['right']}/{pr['n']}{pct(pr)}, {pr['split']} split by position; "
            f"proven at {PROVEN_PCT} % on {PROVEN_N}+: {', '.join(proven) or 'none yet'}")
    return {"pointwise": pw, "pairwise": pr, "proven": proven, "line": line}
