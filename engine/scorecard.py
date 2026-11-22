"""The 6-signal scorecard and ONE measured change per channel per day (plan P3r execution workstream; standards S6
and S8 A19). Owner 21 Nov: "review the analytics everyday and update/improve content ... applies to all the channels".

Six signals from each channel's own numbers (data/analytics.db video_metrics, newest snapshot per video, videos with
at least MIN_VIEWS views from the last LOOKBACK_D days):
  hook      % of viewers who did not swipe away (stayed_pct, else engaged/views)      target 65 %
  watch     average % of the video watched (avg_pct_viewed)                           target 75 %
  shares    shares per 1,000 views                                                    target 5
  likes     likes per 1,000 views (the daily review's 2 % bar)                        target 20
  saves     saves per 1,000 views                                                     target 5
  comments  comments per 1,000 views                                                  target 2
Every evening (daily_review.run) each channel gets exactly one decision, written down:
  - an experiment is running (< RUN_DAYS days): "no change today, because the <signal> experiment is on day N";
    until the first video is posted under it, it follows the newest pick (re-aimed when the numbers point elsewhere);
  - an experiment is due: verdict KEEP (its signal on the videos made since its start beat the baseline by >= 10 %;
    the rule stays as a learned rule) or REVERT; too few new videos -> it runs on, then ends as inconclusive;
  - too little data: "no change today, because ...";
  - otherwise a new RUN_DAYS-day experiment on the weakest signal (largest shortfall against its target; near-ties go
    to the platforms' own top signals, PRIORITY): one concrete rule for the script writer (content_tuning.writer_rules
    adds the active rule and the kept ones).
22 Nov S6 review: the first run gave Brain Snack a "saves" experiment, a 1.00 shortfall against 0.98 for shares,
while Instagram names watch time, likes per reach and sends per reach as its top ranking signals (sends weigh most for
reaching non-followers) and saves are not among them; likes were not measured at all. And the rules must never ask for
engagement: Instagram does not recommend posts to non-followers when they explicitly ask for shares, comments or tags
(engagement bait)."""
from __future__ import annotations

import sqlite3
import statistics
import time
from datetime import datetime
from pathlib import Path

from .config import ROOT

DB = ROOT / "data" / "analytics.db"
STATE = ROOT / "data" / "state" / "experiments.json"
LOOKBACK_D, MIN_VIDEOS, MIN_VIEWS, RUN_DAYS, MAX_DAYS, KEEP_GAIN = 14, 3, 50, 7, 14, 0.10
TARGETS = {"hook": 65.0, "watch": 75.0, "shares": 5.0, "likes": 20.0, "saves": 5.0, "comments": 2.0}
UNITS = {"hook": "% stayed", "watch": "% watched", "shares": " shares/1k views", "likes": " likes/1k views",
         "saves": " saves/1k views", "comments": " comments/1k views"}
# Near-ties (shortfalls within TIE of the largest) go to the signal the platforms rank on first: YouTube Shorts'
# viewed-vs-swiped and share watched, then Instagram's watch time, sends per reach and likes per reach.
PRIORITY = ("hook", "watch", "shares", "likes", "comments", "saves")
TIE = 0.10
NO_ASK = ("Never ask for likes, shares, sends, tags or comments: Instagram does not recommend posts that ask for "
          "engagement.")
RULES = {
    "hook": "Open on the single most striking moment or claim of the whole video in the first second (8 words or "
            "fewer, no setup, no date or name first); the first frame already shows the subject moving.",
    "watch": "Cut every line that does not raise the stakes; plant a new question every 8-10 seconds; keep the reveal "
             "for the last two seconds and end on a line that loops into the first.",
    "shares": "Build one moment worth sending: a jaw-dropping true detail, a relatable laugh or a tip someone would "
              "pass on, said in one short line people will quote. " + NO_ASK,
    "likes": "Earn the like at the payoff: answer the opening question with one satisfying reveal or 'no way' fact in "
             "the last seconds and hold it on screen for a beat. " + NO_ASK,
    "saves": "Give one thing worth keeping: a short list, a number to remember or a step-by-step the viewer will want "
             "to come back to; say it clearly on screen. " + NO_ASK,
    "comments": "Pose one specific question the viewer can answer in a word or by picking a side (A or B?) just "
                "before the reveal. Never 'comment below' or 'comment YES': Instagram does not recommend engagement "
                "bait.",
}


def _load() -> dict:
    import json
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save(state: dict) -> None:
    from .core.atomic import write_json
    write_json(STATE, state)


def measure(cid: str, since: float, db: Path | None = None) -> dict:
    """{"videos": n, "signals": {name: value or None}} for videos posted after `since` with >= MIN_VIEWS views."""
    db = db or DB
    if not db.exists():
        return {"videos": 0, "signals": {k: None for k in TARGETS}}
    try:
        with sqlite3.connect(db) as c:
            c.row_factory = sqlite3.Row
            cols = {r[1] for r in c.execute("PRAGMA table_info(video_metrics)")}
            likes = "likes" if "likes" in cols else "NULL AS likes"
            rows = [dict(r) for r in c.execute(
                "SELECT item_id, platform, hours_after, views, engaged_views, stayed_pct, avg_pct_viewed, shares, "
                f"saves, comments, {likes} FROM video_metrics WHERE channel = ? AND posted_at > ? "
                "ORDER BY item_id, platform, hours_after", (cid, since))]
    except sqlite3.Error as e:
        print(f"scorecard: metrics unreadable for {cid} ({e})")
        return {"videos": 0, "signals": {k: None for k in TARGETS}}
    latest: dict[tuple, dict] = {}
    for r in rows:
        latest[(r["item_id"], r["platform"])] = r
    vids = [r for r in latest.values() if float(r.get("views") or 0) >= MIN_VIEWS]
    views = sum(float(r["views"]) for r in vids)
    stayed = [float(r["stayed_pct"]) for r in vids if r.get("stayed_pct") is not None] or \
             [100.0 * float(r["engaged_views"]) / float(r["views"]) for r in vids if r.get("engaged_views") is not None]
    watched = [float(r["avg_pct_viewed"]) for r in vids if r.get("avg_pct_viewed")]

    def per_k(col: str):
        have = [r for r in vids if r.get(col) is not None]
        v = sum(float(r["views"]) for r in have)
        return round(1000.0 * sum(float(r[col]) for r in have) / v, 2) if have and v else None
    return {"videos": len(vids), "views": views, "signals": {
        "hook": round(statistics.median(stayed), 1) if stayed else None,
        "watch": round(statistics.median(watched), 1) if watched else None,
        "shares": per_k("shares"), "likes": per_k("likes"), "saves": per_k("saves"),
        "comments": per_k("comments")}}


def posted_since(cid: str, since: float, db: Path | None = None) -> int:
    """How many videos (any views) were posted after `since`: 0 means no video has been made under an experiment."""
    db = db or DB
    if not db.exists():
        return 0
    try:
        with sqlite3.connect(db) as c:
            return int(c.execute("SELECT COUNT(DISTINCT item_id || '|' || platform) FROM video_metrics "
                                 "WHERE channel = ? AND posted_at > ?", (cid, since)).fetchone()[0])
    except sqlite3.Error as e:
        print(f"scorecard: metrics unreadable for {cid} ({e})")
        return 0


def weakest(signals: dict) -> tuple[str, float] | None:
    """The signal furthest below its target (relative shortfall), or None when every measured one is on target.
    Shortfalls within TIE of the largest count as a tie, won by the earlier signal in PRIORITY."""
    gaps = {k: 1 - float(v) / TARGETS[k] for k, v in signals.items()
            if k in TARGETS and v is not None and float(v) < TARGETS[k]}
    if not gaps:
        return None
    top = max(gaps.values())
    near = [k for k in PRIORITY if k in gaps and gaps[k] >= top - TIE - 1e-9]
    k = near[0] if near else max(gaps, key=gaps.get)
    return k, round(gaps[k], 3)


def _reaim(cid: str, act: dict, now: float, day: str, db: Path | None, st: dict) -> dict | None:
    """Before the first video is posted under an experiment, nothing has been tested yet: when today's numbers pick
    another signal (new data, e.g. YouTube's watch numbers after 3 days, or a changed rule), it follows that pick."""
    if posted_since(cid, act["start"], db):
        return None
    m = measure(cid, now - LOOKBACK_D * 86400, db)
    if m["videos"] < MIN_VIDEOS:
        return None
    w = weakest(m["signals"])
    if not w or w[0] == act["signal"]:
        return None
    sig, gap = w
    st["history"] = (st.get("history", []) + [{**act, "end": now, "value": None, "verdict": "re-aimed"}])[-30:]
    st["active"] = {"signal": sig, "rule": RULES[sig], "start": now, "baseline": m["signals"][sig], "gap": gap,
                    "from": act["signal"]}
    return {"day": day, "channel": cid, "change": True, "signal": sig,
            "why": f"re-aimed from {act['signal']} (no video posted under it yet) to {sig}: "
                   f"{m['signals'][sig]}{UNITS[sig]} vs target {TARGETS[sig]:g} -> {RUN_DAYS}-day experiment"}


def decide(cid: str, now: float | None = None, db: Path | None = None, state: dict | None = None) -> dict:
    """Today's one decision for a channel; updates `state` in place (experiments, kept rules, history)."""
    now = now or time.time()
    st = (state if state is not None else _load()).setdefault(cid, {"kept": [], "history": []})
    day = datetime.fromtimestamp(now).strftime("%Y-%m-%d")
    act = st.get("active")
    if act:
        age = (now - act["start"]) / 86400
        if age < RUN_DAYS:
            return _reaim(cid, act, now, day, db, st) or {
                "day": day, "channel": cid, "change": False,
                "why": f"the {act['signal']} experiment is on day {int(age) + 1} of {RUN_DAYS}"}
        after = measure(cid, act["start"], db)
        val = after["signals"].get(act["signal"])
        if (after["videos"] < MIN_VIDEOS or val is None) and age < MAX_DAYS:
            return {"day": day, "channel": cid, "change": False,
                    "why": f"the {act['signal']} experiment needs more videos ({after['videos']} so far)"}
        base = act.get("baseline")
        if val is None or base is None:
            verdict = "inconclusive"
        else:
            verdict = "keep" if val >= float(base) * (1 + KEEP_GAIN) or (base == 0 and val > 0) else "revert"
        if verdict == "keep" and act["rule"] not in st["kept"]:
            st["kept"] = (st["kept"] + [act["rule"]])[-5:]
        st["history"] = (st["history"] + [{**act, "end": now, "value": val, "verdict": verdict}])[-30:]
        st.pop("active", None)
        out = {"day": day, "channel": cid, "change": True, "verdict": verdict, "signal": act["signal"],
               "why": f"{act['signal']} experiment ended: {base} -> {val} ({verdict})"}
        return out
    m = measure(cid, now - LOOKBACK_D * 86400, db)
    if m["videos"] < MIN_VIDEOS:
        return {"day": day, "channel": cid, "change": False,
                "why": f"only {m['videos']} video(s) with {MIN_VIEWS}+ views in {LOOKBACK_D} days (need {MIN_VIDEOS})"}
    w = weakest(m["signals"])
    if not w:
        return {"day": day, "channel": cid, "change": False, "why": "every measured signal is on target"}
    sig, gap = w
    st["active"] = {"signal": sig, "rule": RULES[sig], "start": now, "baseline": m["signals"][sig], "gap": gap}
    return {"day": day, "channel": cid, "change": True, "signal": sig,
            "why": f"weakest signal {sig}: {m['signals'][sig]}{UNITS[sig]} vs target {TARGETS[sig]:g} -> "
                   f"{RUN_DAYS}-day experiment"}


def run_all(channel_ids: list[str], now: float | None = None, db: Path | None = None, log=print) -> list[dict]:
    """One decision per channel (S6), saved with the experiment state; returns the decisions."""
    state = _load()
    out = [decide(cid, now, db, state) for cid in channel_ids]
    day = out[0]["day"] if out else ""
    for d in out:
        st = state.setdefault(d["channel"], {"kept": [], "history": []})
        st["days"] = (st.get("days", []) + [{"day": day, "change": d["change"], "why": d["why"]}])[-30:]
    _save(state)
    log(f"scorecard: {sum(d['change'] for d in out)} change(s), {sum(not d['change'] for d in out)} reasoned no-change")
    return out


def writer_rule(cid: str, state: dict | None = None) -> str:
    """The channel's running experiment + the rules its own numbers proved (for the script writer)."""
    st = (state if state is not None else _load()).get(cid) or {}
    lines = []
    if st.get("active"):
        sig = st["active"].get("signal")       # the current wording of the signal's rule (22 Nov: no engagement asks)
        lines.append(f"THIS WEEK'S EXPERIMENT ({sig} is our weakest number): "
                     f"{RULES.get(sig) or st['active'].get('rule', '')}")
    lines += [f"PROVEN BY OUR NUMBERS: {r}" for r in st.get("kept", [])]
    return "\n".join(lines)


def summary(decisions: list[dict]) -> str:
    """Two lines for the owner's end-of-day message."""
    changed = [f"{d['channel']}: {d['signal']}" for d in decisions if d.get("change") and d.get("signal")]
    waiting = sum(1 for d in decisions if not d.get("change"))
    return (f"🧪 Today's changes from the numbers: {', '.join(changed) or 'none'}"
            + (f"\n   {waiting} channel(s) no change (experiment running or too little data yet)" if waiting else ""))
