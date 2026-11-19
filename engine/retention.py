"""Where viewers leave: the YouTube Analytics audience-retention report for our own videos (read-only).

Official report (developers.google.com/youtube/analytics/channel_reports, checked 13 Nov 2026): dimension
elapsedVideoTimeRatio (0.01-1.0, up to 100 points), metrics audienceWatchRatio + relativeRetentionPerformance,
filter video==<one id> (+ optional audienceType). It is empty for videos with few views and in the first 2-3 days.
Idea from youtube-automation-agent (MIT, "scene-aware retention"): turn the curve into plain lessons. Each video is
read once, 4-30 days after posting: how many stayed past the hook, where the biggest drop was and which caption line
was on screen then, which moment people rewound to. Lessons go into our memory ("playbook", per channel) so the next
scripts avoid what lost people, and into the weekly report. YouTube API data is kept 30 days at most."""
from __future__ import annotations

import json
import re
import sqlite3
import statistics
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from .config import ROOT
from engine.core.http import HTTP

URL = "https://youtubeanalytics.googleapis.com/v2/reports"
SCHEMA = """
CREATE TABLE IF NOT EXISTS retention (
    video_id TEXT PRIMARY KEY, item_id TEXT, channel TEXT, fmt TEXT, duration_s REAL, fetched_at REAL,
    curve TEXT, hook_hold REAL, end_hold REAL, rel_perf REAL, drops TEXT, spikes TEXT, lesson TEXT);
CREATE TABLE IF NOT EXISTS retention_tries (video_id TEXT PRIMARY KEY, tried_at REAL, tries INTEGER);
"""
MIN_AGE_DAYS, MAX_AGE_DAYS, PER_DAY, KEEP_DAYS = 4, 30, 40, 30
HOOK_S = {"short": 3.0, "long": 30.0}        # Shorts: the swipe decision; long videos: the first 30 seconds
DROP_MIN = 0.02                               # a drop worth naming: 2% of the audience between two points
SPIKE_MIN = 0.02                              # a rewatch bump of 2% or more


def connect(path: Path | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(path or ROOT / "data" / "analytics.db")
    conn.executescript(SCHEMA)
    return conn


def fetch_curve(channel_id: str, video_id: str, start: str, end: str, session=HTTP) -> list[tuple] | None:
    """[(ratio, watch, relative)] or None when the channel isn't connected."""
    from .publish import yt_access_token
    token = yt_access_token(channel_id, session)
    if not token:
        return None
    base = {"ids": "channel==MINE", "startDate": start, "endDate": end, "dimensions": "elapsedVideoTimeRatio",
            "metrics": "audienceWatchRatio,relativeRetentionPerformance", "sort": "elapsedVideoTimeRatio"}
    for filt in (f"video=={video_id};audienceType==ORGANIC", f"video=={video_id}"):
        r = session.get(URL, headers={"Authorization": f"Bearer {token}"}, params={**base, "filters": filt}, timeout=30)
        r.raise_for_status()
        rows = (r.json() or {}).get("rows") or []
        if rows:
            return [(float(a), float(b), float(c)) for a, b, c in rows]
    return []


def _at(curve: list[tuple], ratio: float) -> float:
    if not curve:
        return 0.0
    if ratio <= curve[0][0]:
        return curve[0][1]
    for (r0, w0, _), (r1, w1, _) in zip(curve, curve[1:]):
        if r0 <= ratio <= r1:
            return w0 + (w1 - w0) * (ratio - r0) / max(r1 - r0, 1e-9)
    return curve[-1][1]


def analyse(curve: list[tuple], duration: float, fmt: str = "short") -> dict:
    """hook_hold / end_hold (share of views still watching), rel_perf (0-1, 0.5 = typical for the length),
    drops and spikes as [(second, size)]: the two biggest falls after the hook, the biggest rewatch bump."""
    duration = max(float(duration or 0), 1.0)
    hook_r = min(HOOK_S.get(fmt, 3.0) / duration, 0.5)
    out = {"hook_hold": round(_at(curve, hook_r), 3), "end_hold": round(_at(curve, 0.95), 3),
           "rel_perf": round(statistics.mean(c[2] for c in curve), 3) if curve else None, "drops": [], "spikes": []}
    falls, bumps = [], []
    for i in range(1, len(curve)):
        (r0, w0, _), (r1, w1, _) = curve[i - 1], curve[i]
        if r1 <= hook_r or r1 >= 0.95:
            continue
        before = min(w0, curve[i - 2][1]) if i >= 2 else w0      # falling back after a rewatch bump isn't a loss
        if before - w1 >= DROP_MIN:
            falls.append((before - w1, r1))
        if w1 - w0 >= SPIKE_MIN and r1 > 0.03:
            bumps.append((w1 - w0, r1))
    chosen: list[float] = []
    for size, r in sorted(falls, reverse=True):              # two separate moments, not one drop counted twice
        if all(abs(r - c) > 0.03 for c in chosen):
            chosen.append(r)
            out["drops"].append((round(r * duration, 1), round(size, 3)))
        if len(chosen) == 2:
            break
    if bumps:
        size, r = max(bumps)
        out["spikes"].append((round(r * duration, 1), round(size, 3)))
    return out


def caption_at(out_dir: Path | None, t: float) -> str:
    """The caption line on screen at second t (captions.srt next to the video), or ''."""
    if not out_dir:
        return ""
    srt = Path(out_dir) / "captions.srt"
    if not srt.exists():
        return ""
    best, best_d = "", 2.01
    for block in re.split(r"\n\s*\n", srt.read_text(encoding="utf-8", errors="replace")):
        lines = [ln.strip() for ln in block.strip().splitlines()]
        idx = next((i for i, ln in enumerate(lines) if "-->" in ln), None)
        m = re.search(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)", lines[idx]) if idx is not None else None
        if not m:
            continue
        g = [int(x) for x in m.groups()]
        a = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000
        b = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000
        d = 0.0 if a <= t <= b else min(abs(t - a), abs(t - b))
        if d < best_d:
            best, best_d = " ".join(ln for ln in lines[idx + 1:] if ln), d
    return best[:90]


def _mmss(t: float) -> str:
    return f"{int(t // 60)}:{int(t % 60):02d}"


def lesson(title: str, fmt: str, a: dict, line_at=lambda t: "") -> str:
    hook = HOOK_S.get(fmt, 3.0)
    parts = [f"Retention ({fmt}, \"{title[:60]}\"): {a['hook_hold']:.0%} still watching at {hook:.0f} s"]
    for t, size in a["drops"]:
        line = line_at(t)
        parts.append(f"lost {size:.0%} at {_mmss(t)}" + (f" during \"{line}\"" if line else ""))
    for t, size in a["spikes"]:
        line = line_at(t)
        parts.append(f"rewatched at {_mmss(t)}" + (f" (\"{line}\")" if line else ""))
    if a.get("rel_perf") is not None:
        parts.append("better than typical for its length" if a["rel_perf"] > 0.55 else
                     "below typical for its length" if a["rel_perf"] < 0.45 else "typical for its length")
    return "; ".join(parts) + "."


def _items_by_id(days: int) -> dict:
    try:
        from . import autopilot
        return {it["id"]: it for _, it in autopilot.items(days, 0)}
    except Exception:  # noqa: BLE001
        return {}


def run(session=HTTP, log=print, conn=None, memory=None, now: float | None = None, videos=None,
        items: dict | None = None) -> int:
    """Reads the curves that are due (4-30 days old, not read yet), at most PER_DAY a day."""
    from .stats_fetch import posted_videos
    now = now or time.time()
    conn = conn or connect()
    conn.execute("DELETE FROM retention WHERE fetched_at < ?", (now - KEEP_DAYS * 86400,))   # API data: 30 days max
    done = {r[0] for r in conn.execute("SELECT video_id FROM retention")}
    tries = {r[0]: (r[1], r[2]) for r in conn.execute("SELECT video_id, tried_at, tries FROM retention_tries")}
    items = items if items is not None else _items_by_id(MAX_AGE_DAYS + 2)
    n = calls = 0
    for v in videos if videos is not None else posted_videos():
        if v.get("platform") != "youtube" or v["id"] in done:
            continue
        age = (now - float(v.get("posted_at") or now)) / 86400
        if not MIN_AGE_DAYS <= age <= MAX_AGE_DAYS:
            continue
        last, k = tries.get(v["id"], (0, 0))
        if now - last < 3 * 86400 or k >= 4:                     # empty curve: try again in 3 days, 4 times at most
            continue
        if calls >= PER_DAY:
            break
        start = datetime.fromtimestamp(float(v["posted_at"]), timezone.utc).date().isoformat()
        end = (datetime.fromtimestamp(now, timezone.utc).date() - timedelta(days=1)).isoformat()
        calls += 1
        try:
            curve = fetch_curve(v["channel"], v["id"], start, end, session=session)
        except Exception as e:  # noqa: BLE001
            log(f"retention {v['id']}: {str(e)[:120]}")
            continue
        if curve is None:
            continue
        if not curve:
            conn.execute("INSERT OR REPLACE INTO retention_tries VALUES (?,?,?)", (v["id"], now, k + 1))
            continue
        it = items.get(v.get("item")) or {}
        out_dir = Path(it["out_dir"]) if it.get("out_dir") else None
        meta = {}
        if out_dir and (out_dir / "upload.json").exists():
            try:
                meta = json.loads((out_dir / "upload.json").read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                meta = {}
        fmt = meta.get("format") or v.get("format") or it.get("kind") or "short"
        fmt = "long" if fmt == "long" else "short"
        duration = float(meta.get("duration_s") or it.get("duration_s") or (60 if fmt == "short" else 600))
        a = analyse(curve, duration, fmt)
        text = lesson(meta.get("title") or v.get("title") or v["id"], fmt, a, lambda t: caption_at(out_dir, t))
        conn.execute("INSERT OR REPLACE INTO retention VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (v["id"], v.get("item"), v["channel"], fmt, duration, now, json.dumps(curve), a["hook_hold"],
                      a["end_hold"], a["rel_perf"], json.dumps(a["drops"]), json.dumps(a["spikes"]), text))
        if memory is not None:
            try:
                memory.add("playbook", text, channel=v["channel"], meta={"source": "retention", "video": v["id"]})
            except Exception:  # noqa: BLE001
                pass
        n += 1
    conn.commit()
    return n


def summary(conn, channel: str) -> dict:
    rows = conn.execute("SELECT fmt, hook_hold, drops, duration_s FROM retention WHERE channel=?", (channel,)).fetchall()
    out = {}
    for fmt in ("short", "long"):
        rs = [r for r in rows if r[0] == fmt]
        if not rs:
            continue
        first = [json.loads(r[2])[0][0] / max(r[3], 1) for r in rs if json.loads(r[2] or "[]")]
        out[fmt] = {"videos": len(rs), "hook_hold": statistics.median(r[1] for r in rs),
                    "drop_at": statistics.median(first) if first else None}
    return out


def report_lines(conn, channels: list[str]) -> list[str]:
    lines = []
    for ch in channels:
        s = summary(conn, ch)
        for fmt, d in s.items():
            hook = HOOK_S[fmt]
            txt = f"  RETENTION {fmt}: {d['hook_hold']:.0%} still watching at {hook:.0f} s (median of {d['videos']})"
            if d.get("drop_at") is not None:
                txt += f", biggest drop usually {d['drop_at']:.0%} of the way in"
            lines.append(f"{ch}:{txt}")
    return lines
