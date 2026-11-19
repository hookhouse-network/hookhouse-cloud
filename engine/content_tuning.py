"""Platform numbers -> content changes (owner 19 Nov: "videos are not getting viral, reach is down, more than 50% of
users just swipe our content, no real watch time, not in search or promotions because of poor SEO and thumbnails, the
content looks outdated: not trending, funny, emotional, nostalgic, interesting").

Every channel's own numbers (data/analytics.db: views over time, likes, engaged views = "viewed" vs "swiped away",
average % viewed) turn into plain rules that go into the next topic choice (weekly.pick_topics) and script
(story.write_script), and onto the dashboard ("What the numbers taught us"). The owner's Studio reading (more than half
swipe away) is the baseline until a channel's own measured stayed-to-watch share is healthy.

Benchmarks (research_notes/content_tuning_2026-11-19.md): Shorts "viewed" (stayed) share 70%+ is healthy, below 60%
the feed stops testing the Short; average viewed 80-100%+ (loops) for Shorts under 40 s; like rate 3-5% (below 1.5% =
nothing made people feel something); a Short whose views stop growing after the first day was tested and swiped.
"""
from __future__ import annotations

import sqlite3
import statistics
from pathlib import Path

from .config import ROOT

DB = ROOT / "data" / "analytics.db"
STAYED_OK = 65.0           # % of viewers who did not swipe away (YouTube Studio "Viewed")
AVG_PCT_OK = 75.0          # average % of a Short watched
LIKE_RATE_OK = 2.0         # likes per 100 views
PLATEAU_GROWTH = 0.05      # under 5% more views from day 1 to day 2 = the feed stopped pushing it

FIRST_SECOND = (
    "FIRST SECOND (owner's Studio: more than half of viewers swipe away, they decide in 1-2 seconds): beat 1 is the most "
    "striking moment or claim of the whole video, 8 words or fewer, spoken from the very first frame (no scene-setting, "
    "no date first, no name first, no 'In 1963'); the picture already moves and shows the subject; the hook text is "
    "on screen from frame one. Open a question the viewer needs answered and answer it only at the very end.")
FEELING = (
    "FEELING: every video must make the viewer FEEL one thing strongly (funny, emotional, nostalgic, shocking, "
    "satisfying, relatable or awe). Pick it before writing and serve it in every beat; a neutral documentary tone "
    "is what gets swiped. Tie the story to the viewer's life today (phones, money, school, work, games, films, cricket, "
    "memes) so it never feels like a history lesson.")
DATED = (
    "NEVER DATED: no 'Did you know', no encyclopedia tone, no slow narrator intro, no stock 'mystery' cliches. Write the "
    "way a funny, sharp friend tells it today.")


def _rows(cid: str, db: Path | None = None) -> list[dict]:
    db = db or DB
    if not db.exists():
        return []
    try:
        with sqlite3.connect(db) as c:
            c.row_factory = sqlite3.Row
            rows = c.execute("SELECT item_id, platform, format, hours_after, views, likes, comments, engaged_views, "
                             "stayed_pct, avg_pct_viewed FROM video_metrics WHERE channel = ? ORDER BY item_id, "
                             "platform, hours_after", (cid,)).fetchall()
    except sqlite3.Error:
        return []
    return [dict(r) for r in rows]


def signals(cid: str, db: Path | None = None) -> dict:
    """The channel's measured health: videos, median views, like rate, stayed %, average % viewed, plateaued videos."""
    per: dict[tuple, list[dict]] = {}
    for r in _rows(cid, db):
        per.setdefault((r["item_id"], r["platform"]), []).append(r)
    latest = [snaps[-1] for snaps in per.values()]
    views = [float(r["views"] or 0) for r in latest]
    likes = sum(float(r["likes"] or 0) for r in latest)
    stayed = [float(r["stayed_pct"]) for r in latest if r.get("stayed_pct") is not None]
    if not stayed:
        stayed = [100.0 * float(r["engaged_views"]) / float(r["views"]) for r in latest
                  if r.get("engaged_views") is not None and r.get("views")]
    avg_pct = [float(r["avg_pct_viewed"]) for r in latest if r.get("avg_pct_viewed")]
    plateaued = 0
    for snaps in per.values():
        d1 = next((s for s in snaps if 20 <= (s["hours_after"] or 0) <= 30), None)
        d2 = next((s for s in snaps if (s["hours_after"] or 0) >= 44), None)
        if d1 and d2 and (d1["views"] or 0) >= 100 and \
                (float(d2["views"] or 0) - float(d1["views"] or 0)) <= PLATEAU_GROWTH * float(d1["views"] or 1):
            plateaued += 1
    total = sum(views)
    return {"videos": len(latest), "views": total, "median_views": statistics.median(views) if views else 0,
            "like_rate": (100.0 * likes / total) if total else None,
            "stayed": statistics.median(stayed) if stayed else None,
            "avg_pct": statistics.median(avg_pct) if avg_pct else None,
            "plateaued": plateaued, "zero": sum(1 for v in views if v <= 2)}


def _findings(s: dict) -> list[tuple[str, str]]:
    """(what the numbers say, what changes) pairs."""
    out = []
    if s["stayed"] is None or s["stayed"] < STAYED_OK:
        said = (f"{100 - s['stayed']:.0f}% of viewers swipe away" if s["stayed"] is not None
                else "more than half of viewers swipe away (owner's Studio reading)")
        out.append((said, FIRST_SECOND))
    if s["plateaued"]:
        out.append((f"{s['plateaued']} video(s) stopped growing after the first day: YouTube tested them and viewers "
                    "left", "The topic itself must stop the scroll: something people are talking about this week, "
                    "or a feeling (funny, nostalgic, shocking) they get from the title alone."))
    if s["avg_pct"] is not None and s["avg_pct"] < AVG_PCT_OK:
        out.append((f"viewers watch only {s['avg_pct']:.0f}% on average",
                    "Cut every beat that doesn't raise the stakes; keep the reveal for the last 2 seconds; end so it "
                    "loops into the first line; aim at the short end of the length range."))
    if s["like_rate"] is not None and s["views"] >= 200 and s["like_rate"] < LIKE_RATE_OK:
        out.append((f"only {s['like_rate']:.1f} likes per 100 views (healthy: 3-5)",
                    "The payoff must hit emotionally: a twist people want to argue about, a laugh, or a lump in the "
                    "throat. Ask for one guess before the reveal so viewers answer in the comments."))
    if s["videos"] and s["zero"] == s["videos"]:
        out.append(("videos got no views at all: YouTube isn't showing them",
                    "Check the channel status; meanwhile trend-first topics with a searchable title (the words people "
                    "type this week) so search and suggested can find them."))
    return out


def writer_rules(cid: str, db: Path | None = None) -> str:
    """Extra rules for this channel's next script: always the feeling + not-dated rules, plus what its numbers say."""
    s = signals(cid, db)
    lines = [FEELING, DATED] + [f"OUR NUMBERS: {said}. SO: {do}" for said, do in _findings(s)]
    return "\n".join(lines)


def topic_hints(cid: str, db: Path | None = None) -> list[str]:
    s = signals(cid, db)
    hints = ["Our numbers: " + said for said, _ in _findings(s)]
    if s["videos"]:
        hints.append(f"So far {s['videos']} videos, median {s['median_views']:.0f} views: pick topics with a much "
                     "stronger pull than before (current, emotional, funny or nostalgic).")
    return hints


def channel_notes(cid: str, db: Path | None = None) -> list[str]:
    """For the dashboard: what the numbers said and what was changed in the next videos."""
    s = signals(cid, db)
    notes = [f"{said[0].upper()}{said[1:]} → {do.split(':', 1)[-1].strip()[:220]}" for said, do in _findings(s)]
    notes.append("Every topic now has to be current (trends of the day, YouTube's trending chart) and deliver one "
                 "feeling: funny, emotional, nostalgic, shocking, satisfying, relatable or awe.")
    return notes
