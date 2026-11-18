"""Analytics + weekly learning loop.

Research basis (reports/Channel growth and earnings plan.md, deep pass):
- Shorts: "viewed vs swiped away" (hook), engaged views (monetisation), average % viewed, loops, subs gained.
- Reels: skip rate (swipe in first 3 s), watch time, shares/sends, saves.
- Long-form: CTR, average view duration, returning viewers.
- YouTube publishes no benchmarks: compare against each channel's OWN medians (after ~4 weeks).
Loop: winners (top 20%) -> memory "what worked" -> topic picking; weak formats (below the channel median
3 weeks running) -> flagged for change; best posting hour per channel -> slot suggestion; weekly report.
Fetching uses the official APIs once accounts are connected (Week 3); until then metrics can be added by hand.
"""
from __future__ import annotations

import sqlite3
import statistics
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import ROOT

SCHEMA = """
CREATE TABLE IF NOT EXISTS video_metrics (
    item_id TEXT, channel TEXT, platform TEXT, video_id TEXT, format TEXT, topic TEXT, hook TEXT,
    posted_at REAL, hours_after REAL, views REAL, engaged_views REAL, stayed_pct REAL, avg_pct_viewed REAL,
    avg_view_s REAL, ctr REAL, likes REAL, comments REAL, shares REAL, saves REAL, subs_gained REAL,
    skip_rate REAL, fetched_at REAL, PRIMARY KEY (item_id, platform, hours_after));
"""
BENCH = {"stayed_pct": 70.0, "avg_pct_viewed_short": 80.0, "avg_pct_viewed_long": 40.0, "skip_rate_max": 50.0}


def connect(path: Path | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(path or ROOT / "data" / "analytics.db")
    conn.executescript(SCHEMA)
    return conn


def record(conn, **m) -> None:
    cols = ["item_id", "channel", "platform", "video_id", "format", "topic", "hook", "posted_at", "hours_after",
            "views", "engaged_views", "stayed_pct", "avg_pct_viewed", "avg_view_s", "ctr", "likes", "comments",
            "shares", "saves", "subs_gained", "skip_rate"]
    vals = [m.get(c) for c in cols] + [time.time()]
    conn.execute(f"INSERT OR REPLACE INTO video_metrics({','.join(cols)},fetched_at) VALUES ({','.join('?' * (len(cols) + 1))})",
                 vals)
    conn.commit()


def _rows(conn, channel: str | None = None, hours_after: float = 48, since_days: float = 120) -> list[dict]:
    sql = ("SELECT item_id, channel, platform, format, topic, hook, posted_at, views, stayed_pct, avg_pct_viewed, "
           "shares, subs_gained, skip_rate, likes FROM video_metrics WHERE hours_after=? AND posted_at>?")
    args = [hours_after, time.time() - since_days * 86400]
    if channel:
        sql += " AND channel=?"
        args.append(channel)
    keys = ["item_id", "channel", "platform", "format", "topic", "hook", "posted_at", "views", "stayed_pct",
            "avg_pct_viewed", "shares", "subs_gained", "skip_rate", "likes"]
    return [dict(zip(keys, r)) for r in conn.execute(sql, args).fetchall()]


def score(r: dict, med_views: float) -> float:
    """One number per video: views vs the channel median, weighted by how well the hook and story held people."""
    v = (r.get("views") or 0) / max(med_views, 1.0)
    hold = ((r.get("stayed_pct") or 0) / 100.0) * 0.5 + ((r.get("avg_pct_viewed") or 0) / 100.0) * 0.5
    share = 1.0 + min(1.0, (r.get("shares") or 0) / max((r.get("views") or 1) * 0.01, 1.0)) * 0.2
    return v * (0.6 + hold) * share


def channel_summary(conn, channel: str) -> dict:
    rows = [r for r in _rows(conn, channel) if r["views"] is not None]
    if not rows:
        return {"channel": channel, "videos": 0}
    med_views = statistics.median(r["views"] for r in rows)
    for r in rows:
        r["score"] = score(r, med_views)
    ranked = sorted(rows, key=lambda r: r["score"], reverse=True)
    top_n = max(1, len(ranked) // 5)
    stayed = [r["stayed_pct"] for r in rows if r["stayed_pct"] is not None]
    return {"channel": channel, "videos": len(rows), "median_views": med_views, "winners": ranked[:top_n],
            "losers": ranked[-top_n:] if len(ranked) >= 5 else [],
            "median_stayed": statistics.median(stayed) if stayed else None}


FAN_VIEWS = 0.5       # under half the channel's median views ...
FAN_LIKES = 1.5       # ... with 1.5x its median like rate = it only reached existing fans
FAN_MIN = 6


def fan_only(conn, channel: str) -> list[dict]:
    """Videos that stayed inside the fan base (AutoClip research note #1, 9 Oct 2026: low-view clips often had the
    HIGHER like rate; the title relied on fan context and never reached strangers). Our own channels' data only."""
    rows = [r for r in _rows(conn, channel) if r.get("views") and r.get("likes") is not None]
    if len(rows) < FAN_MIN:
        return []
    med_v = statistics.median(r["views"] for r in rows)
    med_lr = statistics.median(r["likes"] / r["views"] for r in rows)
    if med_lr <= 0:
        return []
    return [r for r in rows if r["views"] < FAN_VIEWS * med_v and r["likes"] / r["views"] > FAN_LIKES * med_lr]


def weak_formats(conn, channel: str, weeks: int = 3) -> list[str]:
    """Formats whose weekly median score was below the channel median for `weeks` weeks in a row."""
    rows = [r for r in _rows(conn, channel) if r["views"] is not None and r.get("format")]
    if len(rows) < 6:
        return []
    med = statistics.median(r["views"] for r in rows)
    by_fmt_week: dict[str, dict[int, list[float]]] = {}
    for r in rows:
        wk = int((r["posted_at"] or 0) // (7 * 86400))
        by_fmt_week.setdefault(r["format"], {}).setdefault(wk, []).append(score(r, med))
    out = []
    for fmt, weeks_map in by_fmt_week.items():
        last = [statistics.median(v) for _, v in sorted(weeks_map.items())][-weeks:]
        if len(last) == weeks and all(x < 1.0 for x in last):
            out.append(fmt)
    return out


def best_hours(conn, channel: str, min_points: int = 8) -> list[int] | None:
    """Local (IST) posting hours ranked by median 48-hour views; None until there is enough data."""
    rows = [r for r in _rows(conn, channel) if r["views"] is not None and r["posted_at"]]
    if len(rows) < min_points:
        return None
    by_hour: dict[int, list[float]] = {}
    for r in rows:
        h = (datetime.fromtimestamp(r["posted_at"], timezone.utc) + timedelta(hours=5, minutes=30)).hour
        by_hour.setdefault(h, []).append(r["views"])
    ranked = sorted(by_hour, key=lambda h: statistics.median(by_hour[h]), reverse=True)
    return [h for h in ranked if len(by_hour[h]) >= 2] or None


def feed_memory(conn, channel: str, memory=None) -> int:
    """Winners' hooks/topics go into our own memory (RAG) as 'what worked', so the writer copies the style."""
    summ = channel_summary(conn, channel)
    if not summ.get("winners") or memory is None:
        return 0
    n = 0
    for r in summ["winners"]:
        text = r.get("hook") or r.get("topic")
        if text:
            memory.add("hook", text, channel=channel, performance=r["views"])
            n += 1
    return n


def weekly_report(conn, channels: list[str]) -> str:
    lines = [f"Weekly learning report — {datetime.now():%d %b %Y}"]
    for ch in channels:
        s = channel_summary(conn, ch)
        if not s.get("videos"):
            lines.append(f"\n{ch}: no data yet")
            continue
        lines.append(f"\n{ch}: {s['videos']} videos, median 48h views {s['median_views']:,.0f}"
                     + (f", median stayed-to-watch {s['median_stayed']:.0f}%" if s.get("median_stayed") else ""))
        for r in s["winners"][:3]:
            lines.append(f"  WIN  {r['views']:,.0f} views · {r.get('format') or ''} · {(r.get('hook') or r.get('topic') or '')[:70]}")
        fans = fan_only(conn, ch)
        if fans:
            lines.append(f"  FANS ONLY: {len(fans)} video(s) were liked but not shown to new viewers, e.g. "
                         f"\"{(fans[0].get('hook') or fans[0].get('topic') or '')[:60]}\". Name the person or thing "
                         f"plainly in the title so strangers get it.")
        if s.get("median_stayed") is not None and s["median_stayed"] < BENCH["stayed_pct"]:
            lines.append(f"  ACTION: hooks are losing people (stayed {s['median_stayed']:.0f}% < {BENCH['stayed_pct']:.0f}%). "
                         "Stronger first frame / first line.")
        weak = weak_formats(conn, ch)
        if weak:
            lines.append(f"  ACTION: change or pause these formats (below median 3 weeks): {', '.join(weak)}")
        hrs = best_hours(conn, ch)
        if hrs:
            lines.append(f"  Best posting hours (IST): {', '.join(f'{h:02d}:00' for h in hrs[:3])}")
    try:                                                  # where viewers left (YouTube retention curves)
        from .retention import SCHEMA as _RS, report_lines
        conn.executescript(_RS)
        extra = report_lines(conn, channels)
        if extra:
            lines += ["", "Where viewers leave (retention curves, last 30 days):"] + extra
    except Exception:  # noqa: BLE001
        pass
    return "\n".join(lines)
