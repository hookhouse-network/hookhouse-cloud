"""P8 experiment log (27 Nov): every AUTOMATIC change the system makes to a channel, with its baseline and, 7 days
later, its measured effect, so the daily brief shows what each change did (P8 acceptance: "each automatic change is
visible in the brief with its measured effect").

The changers keep their own logic (and their own keep/step-back rules): the scorecard's writer-rule experiments
(keep or revert after RUN_DAYS), the allocator's volume per channel (one less after a rise when views fall), the
posting-time learner's slots. Each one calls record() when it changes something; record() stores the channel's
numbers of the 14 days before (scorecard.measure: videos, views per video, hook/watch/shares/likes) as the baseline.
effects() measures the same numbers on the videos posted since the change once it is EFFECT_DAYS old, and says
helped / hurt / no clear change / too few videos (fewer than MIN_VIDEOS posted since)."""
from __future__ import annotations

import time
from pathlib import Path

EVENT = "learn.change"
BASE_DAYS = 14
EFFECT_DAYS = 7
MIN_VIDEOS = 3
CLEAR = 0.10                       # a change of 10 %+ in views per video is "clear"


def _numbers(cid: str, since: float, until: float | None = None, db: Path | None = None) -> dict:
    from . import scorecard
    m = scorecard.measure(cid, since, db=db)
    n = int(m.get("videos") or 0)
    sig = m.get("signals") or {}
    return {"videos": n, "views_per_video": round(float(m.get("views") or 0) / n, 1) if n else None,
            **{k: sig.get(k) for k in ("hook", "watch", "shares", "likes")}}


def record(kind: str, channel: str, what: str, led=None, now: float | None = None, db: Path | None = None) -> None:
    """Log one automatic change (kind: rule | volume | slots | ...). Never raises."""
    try:
        now = now or time.time()
        if led is None:
            from .core import ledger
            led = ledger.default()
        led.event(EVENT, channel=channel, data={"kind": kind, "what": what[:300], "at": now,
                                                "baseline": _numbers(channel, now - BASE_DAYS * 86400, db=db)})
    except Exception as e:  # noqa: BLE001 - logging a change never stops it
        from .core.quiet import noted
        noted("experiments.record", e)


def verdict(base: dict, after: dict) -> str:
    if int(after.get("videos") or 0) < MIN_VIDEOS:
        return "too few videos"
    b, a = base.get("views_per_video"), after.get("views_per_video")
    if not b or a is None:
        return "no baseline"
    ch = (a - b) / b
    return "helped" if ch >= CLEAR else "hurt" if ch <= -CLEAR else "no clear change"


def effects(led=None, now: float | None = None, days: float = 30, db: Path | None = None) -> list[dict]:
    """Every change of the last `days` days, newest first, with its measured effect once EFFECT_DAYS old."""
    now = now or time.time()
    if led is None:
        from .core import ledger
        led = ledger.default()
    out = []
    for r in led.events(EVENT):
        d = r.get("data") or {}
        at = float(d.get("at") or r.get("at") or now)
        if at < now - days * 86400:
            continue
        row = {"channel": r.get("channel") or "", "kind": d.get("kind"), "what": d.get("what"), "at": at,
               "baseline": d.get("baseline") or {}, "after": None, "verdict": "measuring"}
        if now - at >= EFFECT_DAYS * 86400:
            row["after"] = _numbers(row["channel"], at, db=db)
            row["verdict"] = verdict(row["baseline"], row["after"])
        out.append(row)
    return sorted(out, key=lambda x: -x["at"])


def brief_text(led=None, now: float | None = None, db: Path | None = None, limit: int = 8) -> str:
    """Lines for the morning brief: measured changes first, then the ones still measuring."""
    now = now or time.time()
    rows = effects(led=led, now=now, db=db)
    if not rows:
        return "Experiments: no automatic change in the last 30 days."
    done = [r for r in rows if r["verdict"] != "measuring"]
    running = [r for r in rows if r["verdict"] == "measuring"]
    lines = []
    for r in done[:limit]:
        b, a = r["baseline"].get("views_per_video"), (r["after"] or {}).get("views_per_video")
        nums = f" (views/video {b:g} -> {a:g})" if b and a is not None else ""
        lines.append(f"• {r['channel']} {r['kind']}: {r['what'][:90]} -> {r['verdict']}{nums}")
    if running:
        lines.append(f"• measuring ({len(running)}): " + "; ".join(
            f"{r['channel']} {r['kind']} day {int((now - r['at']) // 86400) + 1}" for r in running[:limit]))
    return "Experiments:\n" + "\n".join(lines)
