"""P8 daily operator brief + weekly earnings board (27 Nov; master plan 5.6). Evidence only, one Telegram message
(the 09:00 digest's 'Yesterday' part): posted in the last 24 h by platform, held and why, the making gap (slots that
passed unmade), quotas used up, earnings, and ONE recommended next action. On Mondays the earnings board adds each
channel's last 7 days: posts, views, campaign money."""
from __future__ import annotations

import json
import time
from collections import Counter
from datetime import timedelta
from pathlib import Path

DAY = 86400.0


def _log_rows(since: float, path: Path | None = None) -> list[dict]:
    from . import publish
    p = path or publish.LOG
    out = []
    try:
        with open(p, encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if float(r.get("at") or 0) >= since:
                    out.append(r)
    except OSError:
        return []
    return out


def _is_post(r: dict) -> bool:
    what = str(r.get("what") or "").lower()
    return bool(r.get("done")) and bool(r.get("item_id")) and not (r.get("details") or {}).get("dry_run") \
        and what.startswith(("upload", "publish", "cross-post", "post"))


def posted(rows: list[dict]) -> dict[str, int]:
    """{platform: distinct videos posted}."""
    per: dict[str, set] = {}
    for r in rows:
        if _is_post(r):
            per.setdefault(r.get("platform") or "?", set()).add(r["item_id"])
    return {p: len(v) for p, v in sorted(per.items(), key=lambda x: -len(x[1]))}


def held(rows: list[dict]) -> list[tuple[str, int]]:
    """[(reason, distinct videos)] for the content-gate holds, most common first."""
    per: dict[str, set] = {}
    for r in rows:
        if str(r.get("what") or "").startswith("BLOCKED"):
            probs = (r.get("details") or {}).get("problems") or ["unknown"]
            reason = str(probs[0]).split(":", 1)[0].strip()[:40] or "unknown"
            per.setdefault(reason, set()).add(r.get("item_id") or "")
    return sorted(((k, len(v)) for k, v in per.items()), key=lambda x: -x[1])


def making_gap() -> list[str]:
    """Videos whose slot passed in the last 24 h without a made video."""
    from . import autopilot, weekly
    now = autopilot._now()
    out = []
    for _s, it in autopilot.items(1, 0):
        if now - timedelta(days=1) <= autopilot._when(it) <= now and it.get("status") in weekly.TO_MAKE:
            out.append(it.get("channel_name") or it.get("channel") or it["id"])
    return out


def earnings() -> tuple[float, float]:
    """(received INR, pending USD) from the campaign money ledger."""
    try:
        from .dashboard import _earnings
        e = _earnings()
    except Exception as ex:  # noqa: BLE001 - the brief still goes out without it
        from .core.quiet import noted
        noted("operator_brief.earnings", ex)
        return 0.0, 0.0
    return sum(v["received_inr"] for v in e.values()), sum(v["pending_usd"] for v in e.values())


def next_action(high: int, holds: list[tuple[str, int]], gap: list[str], posts: int) -> str:
    if high:
        return f"{high} problem(s) need a code fix: tell Claude 'Heal and Improve the system'."
    if holds and holds[0][1] >= 3:
        return f"Most holds are '{holds[0][0]}' ({holds[0][1]} videos): the makers' templates get that fix first."
    if len(gap) >= 3:
        return (f"{len(gap)} slots passed unmade (pictures or PC time ran out): keep the PC on and plugged in "
                "tonight so it draws them.")
    if posts == 0:
        return "Nothing posted in 24 h: check the cloud runs."
    return "Nothing urgent: the system runs on its own today."


def brief(now: float | None = None, log_path: Path | None = None) -> str:
    now = now or time.time()
    rows = _log_rows(now - DAY, log_path)
    posts = posted(rows)
    holds = held(rows)
    try:
        gap = making_gap()
    except Exception as ex:  # noqa: BLE001
        from .core.quiet import noted
        noted("operator_brief.gap", ex)
        gap = []
    try:
        from .budgets import summary
        b = summary()
        out_pics = [p["source"] for p in b.get("pictures") or [] if not p.get("open")]
        ai_hits = [a["provider"] for a in b.get("ai") or [] if a.get("quota_hits")]
        loc = b.get("local") or {}
    except Exception as ex:  # noqa: BLE001
        from .core.quiet import noted
        noted("operator_brief.budgets", ex)
        out_pics, ai_hits, loc = [], [], {}
    try:
        from . import heal
        high = len(heal.open_items("high"))
    except Exception as ex:  # noqa: BLE001
        from .core.quiet import noted
        noted("operator_brief.heal", ex)
        high = 0
    inr, usd = earnings()
    lines = [f"Posted (24 h): {sum(posts.values())} - " + (", ".join(f"{p} {n}" for p, n in posts.items()) or "none"),
             "Held: " + (", ".join(f"{r} {n}" for r, n in holds[:4]) or "none"),
             "Slots passed unmade: " + (f"{len(gap)} ({', '.join(sorted(set(gap))[:5])})" if gap else "none"),
             "Quotas used up: " + (", ".join(out_pics + [f"AI {a}" for a in ai_hits]) or "none")
             + (f"; PC pictures {loc.get('used', 0)}/{loc.get('cap', 0)}" if loc.get("cap") else ""),
             f"Earnings: Rs {inr:,.0f} received, ${usd:,.2f} pending",
             "Next: " + next_action(high, holds, gap, sum(posts.values()))]
    if time.localtime(now).tm_wday == 0:                 # Mondays: the weekly earnings board
        lines.append(earnings_board(now))
    return "\n".join(lines)


def earnings_board(now: float | None = None, db: Path | None = None) -> str:
    """Each channel's last 7 days: posts, views (analytics), campaign money."""
    import sqlite3
    from .config import ROOT
    now = now or time.time()
    rows = _log_rows(now - 7 * DAY)
    posts = Counter()
    seen = set()
    for r in rows:
        if _is_post(r) and (r["item_id"], r.get("channel")) not in seen:
            seen.add((r["item_id"], r.get("channel")))
            posts[r.get("channel") or "?"] += 1
    views: dict[str, float] = {}
    try:
        c = sqlite3.connect(str(db or ROOT / "data" / "analytics.db"))
        for ch, v in c.execute("SELECT channel, SUM(mv) FROM (SELECT channel, item_id, platform, MAX(views) AS mv "
                               "FROM video_metrics WHERE posted_at >= ? GROUP BY channel, item_id, platform) "
                               "GROUP BY channel", (now - 7 * DAY,)):
            views[ch] = float(v or 0)
        c.close()
    except sqlite3.Error as ex:
        from .core.quiet import noted
        noted("operator_brief.board", ex)
    try:
        from .dashboard import _earnings
        money = _earnings()
    except Exception as ex:  # noqa: BLE001
        from .core.quiet import noted
        noted("operator_brief.board_money", ex)
        money = {}
    chans = sorted(set(posts) | set(views), key=lambda c: -views.get(c, 0))
    out = ["Weekly earnings board (7 days):"]
    for ch in chans[:14]:
        m = money.get(ch) or {}
        cash = f", Rs {m['received_inr']:,.0f} + ${m['pending_usd']:,.2f} pending" if m else ""
        out.append(f"• {ch}: {posts.get(ch, 0)} posts, {views.get(ch, 0):,.0f} views{cash}")
    return "\n".join(out) if len(out) > 1 else "Weekly earnings board: no posts in 7 days."
