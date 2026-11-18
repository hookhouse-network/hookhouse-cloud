"""Retainer pitch kit: the most realistic road to ₹5 lakh/month is 3-4 creators paying $500-2,000/month for clips
(research: campaigns_5_lakh_plan.md §3; 2026 agency pricing guides).

- Prospects: creators who already pay clippers (their clipping campaigns, from daily discovery) plus any the owner adds.
  Warm leads: they already budget for clips.
- Media kit: one honest page (output/media_kit.html) with our services, packages, process, samples and rules. No fake
  numbers: until we have real views it leads with a free trial.
- Pitches: personalised email + short DM + two follow-ups per prospect (data/pitches/<id>.md), written by the brain
  under strict honesty rules.
- Pipeline: new -> pitched -> replied -> trial -> client / lost, with follow-up dates (shown on the dashboard).
Nothing is ever sent automatically: the owner sends from their own account.
"""
from __future__ import annotations

import html
import json
import re
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path

from .config import ROOT

DB = ROOT / "data" / "system.db"
PITCHES = ROOT / "data" / "pitches"
KIT = ROOT / "output" / "media_kit.html"
STATUSES = ("new", "pitched", "replied", "trial", "client", "lost")
PACKAGES = [
    ("Free trial", "$0", "5 clips in 7 days, posted on our pages or delivered to you", "Proof before any money"),
    ("Starter", "$500 / month", "12 clips a month for YouTube Shorts + Instagram Reels, captions, hooks, titles", "Small shows"),
    ("Growth", "$1,000 / month", "24 clips a month, posted on our clip pages + delivered files, monthly report",
     "Most popular"),
    ("Pro", "$2,000 / month", "40 clips a month, multi-part series from long episodes, thumbnails, weekly report",
     "Big shows"),
    ("Performance add-on", "+ agreed $ per 1,000 views above the target", "Pay more only when clips perform",
     "Aligns incentives"),
]

PITCH_PROMPT = """Write outreach for a short-form clipping service to a creator. Be honest and specific.
Creator: {name}
What we know: {notes}
Our proof right now: {proof}
Offer: a free 7-day trial (5 clips), then a monthly plan ($500 / $1,000 / $2,000) with an optional performance bonus.
Rules: no invented numbers, clients or results; never claim to be a big agency; no pressure or fake urgency; mention that
clips keep their meaning (no misleading cuts), credit them and follow ad-disclosure rules; plain friendly English;
sign as "the HookHouse clips team". Do not include any email address or phone number.
Return ONLY JSON: {{"subject": "under 60 characters", "email": "under 130 words", "dm": "under 60 words",
"follow_up_1": "day 3, under 60 words", "follow_up_2": "day 7, under 50 words", "clip_ideas": ["3 clip angles that suit this creator"]}}"""


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB)
    conn.execute("""CREATE TABLE IF NOT EXISTS prospects (
        id TEXT PRIMARY KEY, name TEXT, kind TEXT, source TEXT, niche TEXT, url TEXT, notes TEXT,
        status TEXT DEFAULT 'new', next_followup REAL, created REAL, updated REAL)""")
    return conn


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (s or "x").lower()).strip("-")[:40]


def add(conn, name: str, kind: str = "podcast", source: str = "owner", niche: str = "", url: str = "",
        notes: str = "") -> str:
    pid = _slug(name)
    conn.execute("INSERT OR IGNORE INTO prospects(id, name, kind, source, niche, url, notes, status, created, updated) "
                 "VALUES (?,?,?,?,?,?,?,?,?,?)", (pid, name, kind, source, niche, url, notes, "new", time.time(), time.time()))
    conn.commit()
    return pid


def import_from_campaigns(conn) -> int:
    """Creators/podcasts that run their own clipping campaigns already pay clippers: warm retainer leads."""
    from . import db
    n = 0
    for c in db.list_campaigns(db.connect()):
        name = str(c.get("brand") or "").strip()
        text = f"{c.get('name', '')} {c.get('niche', '')} {c.get('content_type', '')}".lower()
        if not name or c.get("fit") == "NO":
            continue
        if re.search(r"podcast|clips|show|stream|creator|interview", text) and \
                not re.search(r"movie|film|trailer|album|single|game|haircare|beauty|drone|tea shop", text):
            before = conn.total_changes
            add(conn, name, "podcast" if "podcast" in text else "creator", "runs a clipping campaign",
                c.get("niche") or "", c.get("url") or "", f"Campaign: {c.get('name')} (${c.get('cpm_usd')}/1K on "
                f"{c.get('board') or 'a clipping board'})")
            n += conn.total_changes - before
    return n


def proof_text() -> str:
    """Our real proof today (never invented): posted views from analytics, else samples only."""
    views = 0
    try:
        from .dashboard import _metrics
        views = sum(m["views"] for m in _metrics().values())
    except Exception:  # noqa: BLE001
        pass
    base = ROOT / "output" / "hot_take_hq"
    folders = sorted(base.glob("*_clips_pitch_samples")) or sorted(base.glob("*_clips*")) if base.exists() else []
    clips = len(list(folders[-1].glob("clip_*.mp4"))) if folders else 0     # current samples only (no old versions)
    if views:
        return f"{views:,} tracked views on our clip pages so far; {clips} sample clips"
    return (f"a new studio: {clips} sample clips (face-tracked framing, word-by-word captions, hooks), no public view "
            "record yet, so we lead with a free trial")


def make_pitch(conn, pid: str, brain=None) -> Path:
    row = conn.execute("SELECT name, notes, niche, kind FROM prospects WHERE id=?", (pid,)).fetchone()
    if not row:
        raise SystemExit(f"No prospect '{pid}'")
    name, notes, niche, kind = row
    if brain is None:
        from .brain import Brain
        brain = Brain()
    data, _ = brain.ask_json("writer", PITCH_PROMPT.format(name=name, notes=f"{kind}, {niche}. {notes}",
                                                           proof=proof_text()), temperature=0.5)
    PITCHES.mkdir(parents=True, exist_ok=True)
    out = PITCHES / f"{pid}.md"
    lines = [f"# Pitch: {name}", "", f"Prospect notes: {notes}", "", "Send from your own account; attach the media kit "
             "(output/media_kit.html as PDF) and 1-2 sample clips.", "",
             f"## Email\n**Subject:** {data.get('subject', '')}\n\n{data.get('email', '')}", "",
             f"## Short DM (Instagram / X)\n{data.get('dm', '')}", "",
             f"## Follow-up (day 3)\n{data.get('follow_up_1', '')}", "",
             f"## Follow-up (day 7)\n{data.get('follow_up_2', '')}", "",
             "## Clip ideas for them"] + [f"- {x}" for x in data.get("clip_ideas") or []]
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


def set_status(conn, pid: str, status: str) -> None:
    if status not in STATUSES:
        raise SystemExit(f"Status must be one of {', '.join(STATUSES)}")
    follow = {"pitched": 3, "replied": 2, "trial": 7}.get(status)
    nxt = time.time() + follow * 86400 if follow else None
    conn.execute("UPDATE prospects SET status=?, next_followup=?, updated=? WHERE id=?", (status, nxt, time.time(), pid))
    conn.commit()


def pipeline(conn) -> dict:
    counts = {s: 0 for s in STATUSES}
    for st, n in conn.execute("SELECT status, COUNT(*) FROM prospects GROUP BY status"):
        counts[st] = n
    due = conn.execute("SELECT id, name, status, next_followup FROM prospects WHERE next_followup IS NOT NULL AND "
                       "next_followup <= ? ORDER BY next_followup", (time.time() + 86400,)).fetchall()
    return {"counts": counts, "due": due}


def build_kit() -> Path:
    e = html.escape
    rows = "".join(f"<tr><td><b>{e(a)}</b></td><td>{e(b)}</td><td>{e(c)}</td><td>{e(d)}</td></tr>" for a, b, c, d in PACKAGES)
    page = f"""<!doctype html><html><head><meta charset=utf-8><title>Hot Take HQ Clips: media kit</title><style>
body{{font-family:Segoe UI,Arial,sans-serif;max-width:860px;margin:30px auto;color:#1b1f27;line-height:1.5}}
h1{{margin-bottom:0}}h2{{color:#3a55d4;margin-top:28px}}table{{width:100%;border-collapse:collapse}}
td,th{{border-bottom:1px solid #e3e7ef;padding:9px;text-align:left;vertical-align:top}}th{{background:#f3f5fa}}
.note{{background:#f6f8fd;border-left:4px solid #3a55d4;padding:10px 14px}}</style></head><body>
<h1>Hot Take HQ Clips</h1><p>Short-form clips that turn your long episodes into daily discovery on YouTube Shorts and
Instagram Reels.</p>
<h2>What you get</h2><ul>
<li>The strongest moments found from the full episode (hook in the first second, one complete idea per clip)</li>
<li>Vertical framing that follows the active speaker, clean word-by-word captions, a headline hook</li>
<li>Titles, captions and hashtags written for search; files delivered, or posted on our clip pages</li>
<li>A simple report: views, top clips and what to clip more of</li></ul>
<h2>Proof</h2><p>{e(proof_text())}.</p>
<h2>Plans</h2><table><tr><th>Plan</th><th>Price</th><th>Included</th><th>For</th></tr>{rows}</table>
<h2>How it works</h2><ol><li>You share your episodes (or we use your public uploads with your OK)</li>
<li>Free 7-day trial: 5 clips</li><li>Pick a plan; cancel any month</li></ol>
<h2>Our rules</h2><div class=note>Clips never change what you meant (no misleading cuts). Every clip credits you. Paid
posts carry the platforms' ad disclosure. We never repost other creators' content or buy views.</div>
<p style="color:#7a8291;margin-top:30px">Updated {datetime.now():%d %b %Y}</p></body></html>"""
    KIT.write_text(page, encoding="utf-8")
    return KIT
