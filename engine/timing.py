"""Best posting time per channel, learned from our OWN numbers (owner, 18 Nov 2026: "best upload time according to
the target audience of the channel and by analysing the actual analytics of that channel").

The YouTube Analytics API has no hour dimension (checked 18 Nov: only day/month), so the "when your viewers are
on YouTube" chart can't be read. Instead every video is a small experiment: its views after 24 hours, divided by
the channel's median, is the score of the slot (India time) it went out in. Per slot the scores are averaged with a
prior of 1.0 worth PRIOR videos, so one lucky video can't move the schedule.
- A learned slot replaces a research default only when it has MIN_PER_SLOT videos and beats it by MARGIN.
- Exploration: twice a week (Wed, Sat) the channel's last Short slot of the day tries the least-tested candidate
  for its audience, so the system keeps learning instead of freezing on the first answer.
Candidates are the research peak windows (research_notes, 10 Nov: US lunch 12-15 ET and evening 18-21 ET;
India 12:30-14:00 and 19:00-22:00 IST), all in India time. Output: data/state/timing.json, read by weekly.slots_for.
"""
from __future__ import annotations
from engine.core.quiet import noted

import json
import time
from collections import defaultdict
from datetime import datetime

from .config import ROOT

STATE = ROOT / "data" / "state" / "timing.json"
CANDIDATES = {"US": ["22:30", "23:45", "01:00", "04:00", "05:00", "06:30", "07:30"],
              "IN": ["08:00", "12:30", "14:00", "18:00", "19:00", "20:00", "21:00", "22:00"]}
PRIOR, MIN_PER_SLOT, MARGIN, MIN_VIDEOS = 3, 4, 1.15, 8
EXPLORE_DAYS = (2, 5)                    # Wednesday, Saturday


def _round_slot(ts: float) -> str:
    d = datetime.fromtimestamp(ts)
    m = (d.minute // 15) * 15
    return f"{d.hour:02d}:{m:02d}"


def scores(rows: list[tuple[str, float, float]]) -> dict[str, dict[str, dict]]:
    """rows: (channel, posted_at, views at ~24 h) -> {channel: {slot: {n, score}}}."""
    import statistics
    by_ch: dict[str, list] = defaultdict(list)
    for ch, at, views in rows:
        if views is not None:
            by_ch[ch].append((_round_slot(at), float(views)))
    out: dict[str, dict[str, dict]] = {}
    for ch, vals in by_ch.items():
        med = statistics.median(v for _, v in vals) or 1.0
        acc: dict[str, list] = defaultdict(list)
        for slot, v in vals:
            acc[slot].append(v / med)
        out[ch] = {s: {"n": len(r), "score": round((sum(r) + PRIOR * 1.0) / (len(r) + PRIOR), 3)}
                   for s, r in acc.items()}
    return out


def choose(ch: dict, slot_scores: dict[str, dict], n_videos: int) -> dict:
    from .weekly import _default_times
    default = [f"{h:02d}:{m:02d}" for h, m in _default_times(ch)]
    cands = sorted(set(CANDIDATES.get(ch.get("market", "US"), []) + default))
    rec = {"default": default, "slots": default, "explore": None, "evidence": slot_scores, "videos": n_videos}
    tried = {s: slot_scores.get(s, {}).get("n", 0) for s in cands}
    rec["explore"] = min(cands, key=lambda s: (tried[s], s in default, s))
    if n_videos < MIN_VIDEOS:
        rec["why"] = f"only {n_videos} measured videos; keeping the research slots"
        return rec
    trusted = {s: v["score"] for s, v in slot_scores.items() if v["n"] >= MIN_PER_SLOT}
    chosen = list(default)
    for i, s in enumerate(default):                  # replace a default slot only by a clearly better one
        mine = slot_scores.get(s, {}).get("score", 1.0)
        better = [(sc, c) for c, sc in trusted.items() if c not in chosen and sc >= mine * MARGIN]
        if better:
            chosen[i] = max(better)[1]
    rec["slots"] = sorted(chosen)
    rec["why"] = ("learned: " + ", ".join(f"{s} ({trusted[s]:.2f}x)" for s in rec["slots"] if s in trusted)) \
        if rec["slots"] != sorted(default) else "research slots are still the best measured"
    return rec


def learn(log=print, conn=None) -> dict:
    """Nightly (with the end-of-day review): recompute every channel's slots."""
    from . import analytics
    from .config import channels
    conn = conn or analytics.connect()
    # SQLite: bare columns next to MIN() come from the row holding the minimum (the earliest snapshot >= 20 h)
    rows = [r[:3] for r in conn.execute(
        "SELECT channel, posted_at, views, MIN(hours_after) FROM video_metrics WHERE hours_after BETWEEN 20 AND 48 "
        "AND posted_at > ? GROUP BY item_id, platform", (time.time() - 90 * 86400,)).fetchall()]
    sc = scores(rows)
    counts = defaultdict(int)
    for ch, _, v in rows:
        if v is not None:
            counts[ch] += 1
    out = {"at": time.time(), "channels": {}}
    changed = []
    old = load().get("channels", {})
    for ch in channels():
        rec = choose(ch, sc.get(ch["id"], {}), counts[ch["id"]])
        out["channels"][ch["id"]] = rec
        if rec["slots"] != (old.get(ch["id"]) or {}).get("slots", rec["default"]):
            changed.append(f"{ch['name']}: {', '.join(rec['slots'])} ({rec['why']})")
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(out, indent=1), encoding="utf-8")
    if changed:
        try:
            from .telegram_bot import notify
            notify("⏰ Posting times updated from our own numbers:\n• " + "\n• ".join(changed[:10]))
        except Exception as _swallowed:  # noqa: BLE001
            noted("timing.py:105", _swallowed)
            pass
    log(f"timing: {len(changed)} channel(s) changed slots")
    return out


def load() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def slots_for_channel(channel_id: str) -> tuple[list[str] | None, str | None]:
    rec = load().get("channels", {}).get(channel_id) or {}
    return rec.get("slots"), rec.get("explore")
