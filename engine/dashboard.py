"""HookHouse monitoring pad (output/dashboard.html): one self-contained page with a menu.

Pages:
- Overview: headline numbers, every channel as a card (status, views, monetization progress), what needs the owner.
- One page per channel: live numbers, monetization progress (YouTube Partner Program thresholds), earnings
  (received / pending / estimate), points to improve (from the latest videos vs research targets and from live
  analytics), latest videos with thumbnails, this week's plan, matching campaigns, the channel's style rules.
- Money, Campaigns, Plan & jobs, To-do & learnings.
Everything is read from local files and databases; nothing is sent anywhere. Works offline and on a phone
(the Telegram bot sends this same file).
"""
from __future__ import annotations

import base64
import hashlib
import html
import io
import json
import re
import shutil
import sqlite3
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from .config import ROOT

OUT = ROOT / "output" / "dashboard.html"

# YouTube Partner Program (research: reports/Channel growth and earnings plan.md). New applicants from 1 Feb 2027
# need 8,000 watch hours or 20M Shorts views; we will apply after that date, so those are the targets shown.
YPP = {"subs": 1000, "hours": 8000, "shorts_views": 20_000_000, "fan_subs": 500, "fan_hours": 3000,
       "fan_shorts": 3_000_000}
# Ad revenue per 1,000 views (USD), middle of the research ranges; only used for "if monetized" estimates.
RPM = {"unsolved_after_dark": (0.10, 6.0), "clutch_tales": (0.08, 5.0), "ending_decoded": (0.08, 4.0),
       "money_cheat_codes": (0.15, 15.0), "itihaas_ke_raaz": (0.02, 0.8), "cricket_ke_kisse": (0.02, 0.8),
       "picture_abhi_baaki_hai": (0.02, 0.8), "brain_snack": (0.05, 2.0), "bloop_and_friends": (0.02, 1.5),
       "cosmos_unboxed": (0.10, 7.0), "deep_blue_files": (0.10, 7.0), "wild_instinct": (0.10, 6.0)}
QLABEL = {"planned": "to be made", "making": "making now", "made": "waiting for you", "approved": "approved",
          "posted": "posted", "rejected": "rejected", "redo": "remaking with your change", "missed": "missed (not approved)",
          "failed": "failed, retrying", "needs_source": "needs source footage"}
QCLS = {"made": "warn", "approved": "good", "posted": "good", "rejected": "bad", "missed": "bad", "failed": "bad",
        "redo": "warn"}
CAMPAIGN_CPM = 1.5                     # typical campaign pay per 1,000 views (daily finder median)
INR = 84.0


def _e(x) -> str:
    return html.escape(str(x if x is not None else ""))


def _num(n) -> str:
    if n is None:
        return "-"
    n = float(n)
    for div, suf in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(n) >= div:
            return f"{n / div:.1f}{suf}".replace(".0", "")
    return f"{n:,.0f}"


# ---------------- data ----------------
def _channels() -> list[dict]:
    out = []
    for p in sorted((ROOT / "config" / "channels").glob("*.yaml")):
        try:
            out.append(yaml.safe_load(p.read_text(encoding="utf-8")))
        except Exception:  # noqa: BLE001
            continue
    return out


def _latest(ch_id: str, fmt: str) -> tuple[Path | None, dict]:
    folder = ROOT / "output" / ch_id
    if not folder.exists():
        return None, {}
    for d in sorted(folder.iterdir(), reverse=True):
        meta = d / "upload.json"
        if meta.exists():
            try:
                j = json.loads(meta.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
            if j.get("format") == fmt:
                return d, j
    return None, {}


def _range(text) -> list[int]:
    nums = [int(x) for x in re.findall(r"\d+", str(text or ""))[:2]]
    return nums if len(nums) == 2 else []


def _video_row(ch: dict, fmt: str) -> dict:
    d, j = _latest(ch["id"], fmt)
    if not d:
        return {}
    return video_checks(ch, d, j, fmt)


def _rel(p: Path | None) -> str | None:
    if not p:
        return None
    try:
        return p.resolve().relative_to(OUT.parent.resolve()).as_posix()
    except ValueError:
        return None


def video_checks(ch: dict, d: Path, j: dict | None = None, fmt: str | None = None) -> dict:
    """Research-target checks for one finished video folder (also shown in the phone approval message)."""
    if j is None:
        j = json.loads((d / "upload.json").read_text(encoding="utf-8")) if (d / "upload.json").exists() else {}
    fmt = fmt or j.get("format") or "short"
    words = sum(len(str(b.get("narration", "")).split()) for b in j.get("beats") or [])
    dur = float(j.get("duration_s") or 0)
    spec = ch.get("spec") or {}
    wpm = words / dur * 60 if dur else 0
    target = spec.get("short_wpm" if fmt == "short" else "long_wpm")
    rng = _range(spec.get("short_words" if fmt == "short" else "long_words"))
    fcd = j.get("fact_check") or {}
    story = ch.get("type") == "story"
    fc = fcd.get("ok") if fcd else (None if story else "n/a")      # kids songs / quizzes make no factual claims
    pace_ok = abs(wpm / target - 1) <= 0.06 if (target and words) else True
    words_ok = rng[0] <= words <= rng[1] * (1.0 if fmt == "short" else 1.15) if (rng and words) else True
    title_ok = 20 <= len(j.get("title") or "") <= 40 if (fmt == "short" and story) else True
    thumb = next((p for pat in ("thumbnail_v2*.jpg", "thumbnail_*.jpg", "cover_vertical.jpg") for p in sorted(d.glob(pat))),
                 None)
    return {"folder": d.name, "title": j.get("title", ""), "dur": dur, "words": words, "wpm": wpm, "target_wpm": target,
            "words_range": rng, "fact_ok": fc, "pace_ok": pace_ok, "words_ok": words_ok, "title_ok": title_ok,
            "ok": pace_ok and words_ok and title_ok and fc in (True, "n/a"), "thumbs": len(j.get("thumbnails") or []),
            "thumb": _rel(thumb)}


def _plan() -> tuple[str | None, list[dict]]:
    weeks = ROOT / "data" / "weeks"
    plans = sorted(weeks.glob("*/plan.json")) if weeks.exists() else []
    if not plans:
        return None, []
    p = json.loads(plans[-1].read_text(encoding="utf-8"))
    return p.get("start"), p.get("items") or []


def _lanes() -> list[dict]:
    """Render jobs from data/review/lane_*.log: what is running now and what finished last."""
    rows = []
    for log in sorted((ROOT / "data" / "review").glob("lane_*.log"), key=lambda p: p.stat().st_mtime, reverse=True)[:8]:
        lines = [ln.strip() for ln in log.read_text(encoding="utf-8", errors="replace").splitlines() if ln.strip()]
        if not lines:
            continue
        last = lines[-1]
        running = "DONE" not in last and (time.time() - log.stat().st_mtime) < 6 * 3600 and "start" in last
        rows.append({"lane": log.stem.replace("lane_", ""), "last": last[:160], "running": running,
                     "age_min": (time.time() - log.stat().st_mtime) / 60})
    return rows


def _db(sql: str, args=()) -> list:
    db = ROOT / "data" / "system.db"
    if not db.exists():
        return []
    try:
        with sqlite3.connect(db) as c:
            return c.execute(sql, args).fetchall()
    except sqlite3.Error:
        return []


def _metrics() -> dict[str, dict]:
    """Per-channel insights from data/analytics.db (written by `stats fetch`). Each video counts once, at its latest
    snapshot. Empty until accounts are connected and videos are live."""
    out: dict[str, dict] = {}
    db = ROOT / "data" / "analytics.db"
    now = datetime.now().timestamp()
    rows = []
    try:
        if db.exists():                            # (connect() would create an empty file)
            with sqlite3.connect(db) as c:
                rows = c.execute(
                    "SELECT m.channel, m.platform, m.item_id, m.hook, m.posted_at, m.views, m.stayed_pct, "
                    "m.avg_pct_viewed, m.subs_gained, m.likes, m.shares, m.skip_rate, m.format, m.avg_view_s FROM "
                    "video_metrics m JOIN (SELECT item_id, platform, MAX(hours_after) h FROM video_metrics GROUP BY "
                    "item_id, platform) last ON m.item_id = last.item_id AND m.platform = last.platform AND "
                    "m.hours_after = last.h").fetchall()
    except sqlite3.Error:
        rows = []
    rows = _with_live(rows)
    for ch, plat, item, hook, posted, views, stayed, pct, subs, likes, shares, skip, fmt, avg_s in rows:
        m = out.setdefault(str(ch), {"videos": 0, "views": 0, "views_7d": 0, "subs": 0, "likes": 0, "shares": 0,
                                     "yt": 0, "ig": 0, "stayed": [], "pct": [], "skip": [], "best": None, "worst": None,
                                     "shorts_views_90d": 0, "long_views": 0, "short_views": 0, "watch_hours_365d": 0.0,
                                     "posted_7d": 0})
        v = int(views or 0)
        age = now - (posted or now)
        yt = "youtube" in str(plat)
        m["videos"] += 1
        m["views"] += v
        m["views_7d"] += v if age <= 7 * 86400 else 0
        m["posted_7d"] += 1 if age <= 7 * 86400 else 0
        m["subs"] += int(subs or 0)
        m["likes"] += int(likes or 0)
        m["shares"] += int(shares or 0)
        m["yt" if yt else "ig"] += 1
        if fmt == "long":
            m["long_views"] += v
            if yt and age <= 365 * 86400:
                m["watch_hours_365d"] += v * float(avg_s or 0) / 3600
        else:
            m["short_views"] += v
            if yt and age <= 90 * 86400:
                m["shorts_views_90d"] += v
        for key, val in (("stayed", stayed), ("pct", pct), ("skip", skip)):
            if val is not None:
                m[key].append(float(val))
        if not m["best"] or v > m["best"][1]:
            m["best"] = (hook or item, v)
        if not m["worst"] or v < m["worst"][1]:
            m["worst"] = (hook or item, v)
    for m in out.values():
        for key in ("stayed", "pct", "skip"):
            m[key] = round(sum(m[key]) / len(m[key]), 1) if m[key] else None
    return out


def _with_live(rows: list) -> list:
    """Analytics snapshots lag 2-3 days; the live public counters (stats_fetch.live) are added on top: a video's views
    are the larger of the two, and videos with no snapshot yet still count (17 Nov: the pad showed almost nothing)."""
    from .stats_fetch import live_stats
    live = live_stats().get("videos") or {}
    by_item = {(str(r[1]), str(r[2])): list(r) for r in rows}
    for vid, v in live.items():
        k = ("youtube", str(v.get("item") or vid))
        if k in by_item:
            r = by_item[k]
            r[5] = max(int(r[5] or 0), int(v.get("views") or 0))
            r[9] = max(int(r[9] or 0), int(v.get("likes") or 0))
        else:
            by_item[k] = [v.get("channel"), "youtube", k[1], v.get("title"), v.get("posted_at"), v.get("views"),
                          None, None, None, v.get("likes"), None, None, v.get("format"), None]
    return [tuple(r) for r in by_item.values()]


def _insight(m: dict) -> str:
    """One plain-language tip from the numbers (benchmarks: analytics.BENCH)."""
    if not m:
        return "connect the account to see numbers"
    tips = []
    if m.get("stayed") is not None and m["stayed"] < 70:
        tips.append("many people swipe away in the first seconds: stronger hooks")
    if m.get("pct") is not None and m["pct"] < 60:
        tips.append("people leave midway: shorter, faster middle")
    if m.get("skip") is not None and m["skip"] > 50:
        tips.append("Reels skip rate high: change the first frame")
    if not tips:
        tips.append("on track: make more like the best video")
    return "; ".join(tips)


def _followers() -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for cid, plat, f in _db("SELECT channel_id, platform, followers FROM account_stats"):
        out.setdefault(cid, {})[plat] = int(f or 0)
    from .stats_fetch import live_stats
    for cid, rec in (live_stats().get("channels") or {}).items():     # live subscriber counts win
        out.setdefault(cid, {})["youtube"] = int(rec.get("subs") or 0)
    return out


def _connected(cid: str) -> dict[str, bool]:
    s = ROOT / "data" / "secrets"
    return {"youtube": (s / f"youtube_{cid}.json").exists(), "instagram": (s / f"meta_{cid}.json").exists()}


def _earnings() -> dict[str, dict]:
    """Campaign money per channel (ledger rows joined to the submission's account)."""
    out: dict[str, dict] = {}
    rows = _db("SELECT s.account, l.stage, SUM(l.amount_usd), SUM(l.amount_inr_received) FROM ledger l "
               "LEFT JOIN submissions s ON s.id = l.submission_id GROUP BY s.account, l.stage")
    for acct, stage, usd, inr in rows:
        e = out.setdefault(str(acct or "unassigned"), {"received_inr": 0.0, "pending_usd": 0.0})
        e["received_inr"] += inr or 0
        if stage not in ("bank_received", "reversed", "written_off"):
            e["pending_usd"] += usd or 0
    return out


def _avatar(cid: str) -> str:
    p = ROOT / "output" / "brand" / cid / "avatar.png"
    if not p.exists():
        return ""
    try:
        from PIL import Image
        im = Image.open(p).convert("RGB").resize((96, 96))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=82)
        return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception:  # noqa: BLE001
        return ""


def _table_rows(md: Path, last: int) -> list[list[str]]:
    if not md.exists():
        return []
    rows = []
    for ln in md.read_text(encoding="utf-8").splitlines():
        if ln.startswith("|") and not ln.startswith("|---") and not ln.startswith("| #") and not ln.startswith("| Item"):
            cells = [c.strip() for c in ln.strip().strip("|").split("|")]
            if len(cells) >= 2:
                rows.append(cells)
    return rows[-last:]


# ---------------- per-channel logic ----------------
def improvements(ch: dict, short: dict, long: dict, m: dict, conn: dict) -> list[tuple[str, str]]:
    """(level, text) points to improve the channel, most important first. level: bad / warn / good."""
    pts: list[tuple[str, str]] = []
    story = ch.get("type") == "story"
    if not conn["youtube"]:
        pts.append(("bad", "Create and connect the YouTube channel (setup guide, Phase 2 + 4). Nothing earns before that."))
    if ch.get("id") != "bloop_and_friends" and not conn["instagram"]:
        pts.append(("warn", "Connect the Instagram account (setup guide, Phase 3) so every video also goes out as a Reel."))
    for fmt, v in (("Short", short), ("Long video", long)):
        if not v:
            if fmt == "Long video" and story:
                pts.append(("warn", "No long video yet. Long videos earn 10-30x more per view than Shorts."))
            continue
        if v.get("target_wpm") and not v["pace_ok"]:
            pts.append(("warn", f"{fmt} pace {v['wpm']:.0f} words/min, research target {v['target_wpm']}: "
                                "re-voice at the target speed."))
        if v.get("words_range") and not v["words_ok"]:
            lo, hi = v["words_range"]
            pts.append(("warn", f"{fmt} has {v['words']} words; research range {lo}-{hi}."))
        if not v["title_ok"]:
            pts.append(("warn", f"{fmt} title is {len(v['title'])} characters; Shorts titles work best at 20-40."))
        if v.get("fact_ok") is False:
            pts.append(("bad", f"{fmt} failed the fact-check: fix the script before it can be uploaded."))
        if fmt == "Short" and v.get("thumbs", 3) < 3 and story:
            pts.append(("warn", "Fewer than 3 thumbnails: YouTube's A/B test needs 3."))
    if m:
        if m.get("stayed") is not None and m["stayed"] < 70:
            pts.append(("bad", f"Only {m['stayed']:.0f}% stay past the first seconds (aim 70%+): sharper first line, "
                               "faster first cut, name the subject in the first shot."))
        if m.get("pct") is not None and m["pct"] < 60:
            pts.append(("warn", f"Viewers watch {m['pct']:.0f}% on average (aim 80%+ for Shorts): cut slow beats, "
                                "add a twist in the middle."))
        if m.get("skip") is not None and m["skip"] > 50:
            pts.append(("warn", f"Reels skip rate {m['skip']:.0f}%: change the first frame and the hook text."))
        planned = (ch.get("schedule") or {}).get("shorts_per_day", 1) * 7
        if m.get("posted_7d", 0) < planned:
            pts.append(("warn", f"{m.get('posted_7d', 0)} videos posted this week, plan is {planned}: approve the "
                                "week's videos to keep the channel active."))
        if m.get("best"):
            pts.append(("good", f"Best so far: \"{m['best'][0][:70]}\" ({_num(m['best'][1])} views). Make more on "
                                "that angle."))
    if not any(lv != "good" for lv, _ in pts):
        pts.append(("good", "Everything checked is on target."))
    order = {"bad": 0, "warn": 1, "good": 2}
    return sorted(pts, key=lambda p: order[p[0]])


def _bar(label: str, have: float, need: float, fmt=_num) -> str:
    pct = max(0.0, min(100.0, 100 * (have or 0) / need)) if need else 0
    return (f"<div class=bar><div class=barhead><span>{_e(label)}</span><b>{fmt(have)} / {fmt(need)}</b></div>"
            f"<div class=track><div class=fill style='width:{pct:.1f}%'></div></div></div>")


def _ypp_pct(m: dict, subs: int) -> float:
    """Overall progress to ad revenue: subscribers AND (watch hours OR Shorts views), 0-100."""
    s = min(1.0, subs / YPP["subs"])
    other = max(min(1.0, m.get("watch_hours_365d", 0) / YPP["hours"]),
                min(1.0, m.get("shorts_views_90d", 0) / YPP["shorts_views"]))
    return 100 * min(s, other) if subs else 0.0


# ---------------- small visual helpers ----------------
IST = ZoneInfo("Asia/Kolkata")
POSTERS = ROOT / "data" / "cache" / "posters"
SLABEL = {"made": "waiting for you", "approved": "approved", "posted": "posted", "redo": "remaking", "sample": "sample",
          "missed": "missed", "rejected": "rejected", "making": "making now"}
SCLS = {"made": "warn", "approved": "good", "posted": "good", "redo": "warn", "missed": "bad", "rejected": "bad",
        "making": "info"}
_POSTER_CACHE: dict = {}


def _spark(vals: list[float], w: int = 120, h: int = 30) -> str:
    """Tiny trend line (inline SVG): one point per day, oldest on the left."""
    if len(vals) < 2 or max(vals) <= 0:
        return (f"<svg class=spark viewBox='0 0 {w} {h}' preserveAspectRatio=none>"
                f"<line x1=0 y1={h - 2} x2={w} y2={h - 2} /></svg>")
    mx = max(vals)
    pts = " ".join(f"{i * w / (len(vals) - 1):.1f},{h - 2 - v / mx * (h - 5):.1f}" for i, v in enumerate(vals))
    return f"<svg class=spark viewBox='0 0 {w} {h}' preserveAspectRatio=none><polyline points='{pts}' /></svg>"


def _delta(now_v: float, prev_v: float) -> str:
    if not prev_v:
        return ""
    d = (now_v - prev_v) / prev_v * 100
    return f"<span class={'up' if d >= 0 else 'down'}>{'▲' if d >= 0 else '▼'} {abs(d):.0f}%</span> vs the week before"


def _when(it: dict) -> datetime | None:
    try:
        return datetime.fromisoformat(it["publish_at"]).astimezone(IST)
    except (KeyError, TypeError, ValueError):
        return None


def _daily_views(days: int = 28) -> dict[str, list[float]]:
    """Views per posting day (latest snapshot of each video, or its live counter when higher) per channel, plus '*'
    for all; newest day last."""
    out: dict[str, list[float]] = {}
    db = ROOT / "data" / "analytics.db"
    rows = []
    try:
        if db.exists():
            with sqlite3.connect(db) as c:
                rows = c.execute(
                    "SELECT m.channel, m.platform, m.item_id, m.hook, m.posted_at, m.views, NULL, NULL, NULL, m.likes, "
                    "NULL, NULL, m.format, NULL FROM video_metrics m JOIN (SELECT item_id, platform, MAX(hours_after) h "
                    "FROM video_metrics GROUP BY item_id, platform) last ON m.item_id = last.item_id AND m.platform = "
                    "last.platform AND m.hours_after = last.h").fetchall()
    except sqlite3.Error:
        rows = []
    today = datetime.now(IST).date()
    for r in _with_live(rows):
        ch, posted, views = r[0], r[4], r[5]
        if not posted:
            continue
        age = (today - datetime.fromtimestamp(posted, IST).date()).days
        if 0 <= age < days:
            for key in (str(ch), "*"):
                out.setdefault(key, [0.0] * days)[days - 1 - age] += float(views or 0)
    return out


# ---------------- videos you can play from the page ----------------
def _poster(folder: Path, file: str | None) -> str:
    """Small JPEG poster as a data URI. The page is a single file, so pictures also show on the phone, where the
    PC's video files can't load."""
    key = (str(folder), file)
    if key in _POSTER_CACHE:
        return _POSTER_CACHE[key]
    uri = ""
    try:
        from PIL import Image
        src = None
        if not str(file or "").startswith("clip_"):
            for pat in ("cover_vertical.jpg", "cover.jpg", "reel_cover.jpg", "thumbnail_v2*.jpg", "thumbnail_*.jpg"):
                hit = sorted(folder.glob(pat))
                if hit:
                    src = hit[0]
                    break
        if src is None:                                   # clips have no cover: one frame of the video
            video = folder / (file or "video.mp4")
            if video.exists():
                POSTERS.mkdir(parents=True, exist_ok=True)
                tag = hashlib.sha1(f"{video}|{video.stat().st_mtime}".encode()).hexdigest()[:12]
                src = POSTERS / f"{tag}.jpg"
                if not src.exists():
                    from .media import ffmpeg
                    subprocess.run([ffmpeg.ffmpeg_bin(), "-y", "-v", "error", "-ss", "1.5", "-i", str(video),
                                    "-frames:v", "1", "-vf", "scale=360:-2", str(src)], timeout=60, check=False)
        if src is not None and src.exists():
            im = Image.open(src).convert("RGB")
            im.thumbnail((320, 320))
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=62)
            uri = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception:  # noqa: BLE001 - a missing poster must not break the page
        uri = ""
    _POSTER_CACHE[key] = uri
    return uri


def _video(ch_id: str, folder: Path, file: str | None, status: str = "sample", when: str | None = None,
           youtube_id: str | None = None) -> dict | None:
    file = file or "video.mp4"
    if not (folder / file).exists():
        return None
    meta: dict = {}
    try:
        if (folder / "upload.json").exists():
            meta = json.loads((folder / "upload.json").read_text(encoding="utf-8"))
        else:
            for name in ("clips.json", "manifest.json"):          # clip folders (manifest: pitch samples)
                if (folder / name).exists():
                    meta = next((c for c in json.loads((folder / name).read_text(encoding="utf-8"))
                                 if isinstance(c, dict) and c.get("file") == file), {})
                    if meta:
                        break
    except Exception:  # noqa: BLE001
        meta = {}
    title = (meta.get("title") or ((meta.get("hook_options") or [""])[0]) or meta.get("hook")
             or ("Sample clip" if file.startswith("clip_") else "Video"))
    return {"ch": ch_id, "title": title, "src": _rel(folder / file), "poster": _poster(folder, file),
            "dur": meta.get("duration_s"), "fmt": meta.get("format") or "short", "status": status, "when": when,
            "yt": youtube_id}


def _gallery(items: list[dict], chans: list[dict], only: str | None = None, limit: int = 16) -> list[dict]:
    """Videos to watch: waiting for your tap first, then approved, then recently posted; filled up with each
    channel's newest finished videos so there is always something to play."""
    order = {"made": 0, "redo": 1, "approved": 2, "posted": 3, "missed": 4}
    out, seen = [], set()
    for it in sorted(items, key=lambda x: (order.get(x.get("status"), 9), x.get("publish_at") or "")):
        if it.get("status") not in order or not it.get("out_dir") or (only and it.get("channel") != only):
            continue
        key = (str(Path(it["out_dir"]).resolve()), it.get("file") or "video.mp4")
        if key in seen:
            continue
        v = _video(it["channel"], Path(it["out_dir"]), it.get("file"), it["status"], it.get("publish_at"),
                   it.get("youtube_id"))
        if v:
            seen.add(key)
            out.append(v)
    for ch in chans:
        if only and ch["id"] != only:
            continue
        want, n = (6 if only else 1), 0
        folder = ROOT / "output" / ch["id"]
        for d in sorted((x for x in folder.iterdir() if x.is_dir()), reverse=True) if folder.exists() else []:
            for f in (sorted(d.glob("video.mp4")) or sorted(d.glob("clip_0[1-3].mp4")))[: want - n]:
                key = (str(d.resolve()), f.name)
                if key in seen:
                    continue
                v = _video(ch["id"], d, f.name)
                if v:
                    seen.add(key)
                    out.append(v)
                    n += 1
            if n >= want:
                break
    return out[:limit]


def _vcard(v: dict, ctx: dict) -> str:
    ch = ctx["chmap"].get(v["ch"], {})
    when = ""
    if v.get("when"):
        w = _when({"publish_at": v["when"]})
        when = f"{w:%a %d %b %H:%M}" if w else ""
    dur = ""
    if v.get("dur"):
        dur = f"{float(v['dur']) / 60:.0f} min" if v["fmt"] == "long" else f"{float(v['dur']):.0f} s"
    yt = f" <a href='https://youtu.be/{_e(v['yt'])}' target=_blank>▶ YouTube</a>" if v.get("yt") else ""
    src = f" src='{_e(v['src'])}'" if v.get("src") else ""
    msg = "Plays on the PC. On the phone, watch it in Telegram" + (" or on YouTube." if v.get("yt") else ".")
    return (f"<figure class='vc {'hor' if v['fmt'] == 'long' else 'ver'}'><div class=player>"
            f"<video controls preload=none playsinline{src} poster='{v['poster']}' "
            f"onerror=\"this.parentNode.classList.add('nofile')\"></video><div class=nofile-msg>{_e(msg)}</div></div>"
            f"<figcaption><div class=vtop><img src='{ctx['avatars'].get(v['ch'], '')}' alt=''>"
            f"<span>{_e(ch.get('name', v['ch']))}</span><span class='pill {SCLS.get(v['status'], '')}'>"
            f"{_e(SLABEL.get(v['status'], v['status']))}</span></div><b>{_e(str(v['title'])[:90])}</b>"
            f"<div class=muted>{_e(' · '.join(x for x in (dur, when) if x))}{yt}</div></figcaption></figure>")


# ---------------- week grid, health, what needs the owner ----------------
def _timeline(items: list[dict], chans: list[dict], ctx: dict, days: int = 7) -> str:
    today = datetime.now(IST).date()
    cols = [today + timedelta(days=i) for i in range(days)]
    cells: dict = {}
    for it in items:
        w = _when(it)
        if w and w.date() in cols:
            cells.setdefault((it.get("channel"), w.date()), []).append((w, it))
    head = "<tr><th class=chcol>Channel</th>" + "".join(
        f"<th class='{'today' if d == today else ''}'>{'Today' if d == today else d.strftime('%a %d')}</th>"
        for d in cols) + "</tr>"
    rows = []
    for ch in chans:
        tds = []
        for d in cols:
            slots = sorted(cells.get((ch["id"], d), []), key=lambda x: x[0])
            tds.append(f"<td class='{'today' if d == today else ''}'>" + "".join(
                f"<span class='slot s-{_e(it.get('status'))}{' long' if it.get('kind') == 'long' else ''}' "
                f"title='{w:%H:%M} · {_e(it.get('kind'))} · {_e(QLABEL.get(it.get('status'), it.get('status')))}"
                f" · {_e((it.get('topic') or '')[:90])}'>{w:%H:%M}</span>" for w, it in slots) + "</td>")
        rows.append(f"<tr><td class=chcol><a href='#ch-{ch['id']}'><img src='{ctx['avatars'].get(ch['id'], '')}' "
                    f"alt=''>{_e(ch['name'])}</a></td>{''.join(tds)}</tr>")
    legend = "".join(f"<span class='slot s-{k}'>{_e(t)}</span>" for k, t in (
        ("planned", "to be made"), ("making", "making"), ("made", "waiting for you"), ("approved", "approved"),
        ("posted", "posted"), ("needs_source", "needs footage"), ("failed", "failed / missed")))
    return (f"<div class=tw><table class=tl>{head}{''.join(rows)}</table></div>"
            f"<div class=legend>{legend}<span class='slot long'>long video</span></div>")


def _health(items: list[dict]) -> list[tuple[str, str, str]]:
    """(level, label, value) checks for the side panel."""
    out = []
    hb = ROOT / "data" / "state" / "heartbeat.txt"
    age = time.time() - hb.stat().st_mtime if hb.exists() else None
    if age is not None and age < 600:
        out.append(("good", "Autopilot", "running"))
    else:
        out.append(("bad", "Autopilot", "not running (double-click scripts/telegram_bot.cmd)" if age is None
                    else f"stopped {age / 3600:.1f} h ago"))
    lock = ROOT / "data" / "state" / "render.lock"
    if lock.exists():
        iid = lock.read_text(encoding="utf-8", errors="replace").strip()
        it = next((x for x in items if x.get("id") == iid), {})
        out.append(("info", "Making now", f"{it.get('channel_name', iid)} · {(it.get('topic') or it.get('kind') or '')[:40]}"))
    else:
        out.append(("good", "Making now", "idle"))
    free = shutil.disk_usage(str(ROOT)).free / 1e9
    out.append(("good" if free >= 15 else "warn" if free >= 10 else "bad", "Disk free (D:)", f"{free:.0f} GB"))
    q = ROOT / "data" / "state" / "youtube_quota.json"
    if q.exists():
        try:
            s = json.loads(q.read_text(encoding="utf-8"))
            ins = 100 * s.get("insert_used", 0) / max(1, s.get("insert_limit", 10000))
            gen = 100 * s.get("used", 0) / max(1, s.get("limit", 10000))
            out.append(("good" if max(ins, gen) < 70 else "warn", "YouTube quota today",
                        f"uploads {min(ins, 100):.0f}% · other {min(gen, 100):.0f}%"))
        except Exception:  # noqa: BLE001
            pass
    sec = ROOT / "data" / "secrets"
    yt = len(list(sec.glob("youtube_*.json"))) if sec.exists() else 0
    ig = len(list(sec.glob("meta_*.json"))) if sec.exists() else 0
    out.append(("good" if yt else "bad", "Accounts connected", f"YouTube {yt} · Instagram {ig}"))
    try:
        from .weekly import _read_sources, clip_state
        cs = clip_state()
        ready = sum(len(v) for v in cs.get("pool", {}).values())
        left = sum(1 for s in _read_sources() if s["source"] not in cs.get("used", []))
        out.append(("good" if ready or left else "warn", "Clip footage", f"{ready} clips ready · {left} sources waiting"))
    except Exception:  # noqa: BLE001
        pass
    reps = sorted((ROOT / "data" / "campaigns").glob("daily_*.md"))
    if reps:
        h = (time.time() - reps[-1].stat().st_mtime) / 3600
        out.append(("good" if h < 30 else "warn", "Campaign search", f"{h:.0f} h ago"))
    return out


def _needs(items: list[dict], todos: list[dict]) -> list[tuple[str, str]]:
    now = datetime.now(IST)
    out = []
    waiting = sorted((it for it in items if it.get("status") == "made" and (_when(it) or now) > now),
                     key=lambda x: x["publish_at"])
    if waiting:
        w = _when(waiting[0])
        out.append(("warn", f"{len(waiting)} video(s) wait for your OK. First one posts {w:%a %H:%M} "
                            f"({waiting[0].get('channel_name')}). Approve them in 📥 Needs your OK at the top, or with "
                            "📥 Waiting for me in Telegram."))
    failed = [it for it in items if it.get("status") == "failed" and (it.get("attempts") or 0) >= 3]
    if failed:
        out.append(("bad", f"{len(failed)} video(s) failed 3 times: see Plan & jobs."))
    ns: dict[str, int] = {}
    for it in items:
        if it.get("status") == "needs_source" and (_when(it) or now) > now:
            ns[it.get("channel_name") or "?"] = ns.get(it.get("channel_name") or "?", 0) + 1
    if ns:
        out.append(("warn", "Clip slots need footage: " + ", ".join(f"{k} ({v})" for k, v in ns.items()) +
                    ". Pick a campaign, then send /source <link> in Telegram."))
    out += [("todo", t["task"]) for t in todos if not t.get("done")][:3]
    return out


def _chcard(ch: dict, ctx: dict) -> str:
    cid = ch["id"]
    m = ctx["metrics"].get(cid, {})
    conn = _connected(cid)
    subs = ctx["followers"].get(cid, {}).get("youtube", 0)
    clips_ch = ch.get("type") == "clips"
    prog = _ypp_pct(m, subs)
    now = datetime.now(IST)
    mine = [it for it in ctx["items"] if it.get("channel") == cid and _when(it)]
    nxt = min((_when(it) for it in mine if _when(it) > now and it.get("status") not in ("rejected", "posted", "missed")),
              default=None)
    week = [it for it in mine if now <= _when(it) <= now + timedelta(days=7)]
    ready = sum(1 for it in week if it.get("status") in ("made", "approved", "posted"))
    series = ctx["daily"].get(cid, [0.0] * 28)[-14:]
    status = ("<span class='pill good'>Live</span>" if any(conn.values()) else "<span class='pill bad'>Not connected</span>")
    money = (("$" + format(ctx["earnings"].get(cid, {}).get("pending_usd", 0), ",.0f")) if clips_ch else f"{prog:.0f}%")
    acc = (ch.get("style") or {}).get("highlight_color") or "#7c8cff"
    return (f"<a class=chcard href='#ch-{cid}' style='--acc:{acc}'><div class=r><img src='{ctx['avatars'].get(cid, '')}' "
            f"alt=''><div class=nm><div class=n>{_e(ch['name'])}</div><div class=muted>"
            f"{_e('Hindi' if ch.get('language') == 'hi' else 'English')} · {_e(str(ch.get('niche') or '')[:34])}</div></div>"
            f"{status}</div><div class=cstats><div><small>Subscribers</small><b data-live='subs:{cid}'>{_num(subs)}</b></div>"
            f"<div><small>Views 7 days</small><b>{_num(sum(series[-7:]))}</b></div>"
            f"<div><small>Next post</small><b>{nxt.strftime('%a %H:%M') if nxt else '-'}</b></div>"
            f"<div><small>Ready, 7 days</small><b>{ready}/{len(week)}</b></div></div>{_spark(series)}"
            f"<div class=bar style='margin:8px 0 0'><div class=barhead><span>{'Campaign money pending' if clips_ch else 'Progress to ad money'}"
            f"</span><b>{money}</b></div><div class=track><div class=fill style='width:{0 if clips_ch else prog:.1f}%'></div>"
            f"</div></div></a>")


def _quality() -> dict:
    try:
        from .quality import load
        return (load() or {}).get("channels", {})
    except Exception:  # noqa: BLE001
        return {}


def _winners(cid: str, n: int = 6) -> list[dict]:
    """This month's most-viewed videos in the channel's niche (weekly official YouTube search; kept 30 days)."""
    db = ROOT / "data" / "memory.db"
    if not db.exists():
        return []
    try:
        with sqlite3.connect(db) as c:
            rows = c.execute("SELECT text, meta, performance FROM items WHERE kind='viral_example' AND channel=? "
                             "AND meta LIKE '%youtube_search%' AND created > ? ORDER BY performance DESC LIMIT ?",
                             (cid, time.time() - 30 * 86400, n)).fetchall()
    except sqlite3.Error:
        return []
    out = []
    for text, meta, perf in rows:
        try:
            m = json.loads(meta or "{}")
        except ValueError:
            m = {}
        out.append({"title": text, "views": perf or 0, "id": m.get("video_id"), "format": m.get("format")})
    return out


def _learn_page(chans: list[dict], metrics: dict) -> str:
    """📈 Trends & learnings (owner 17 Nov: "learnings, latest trends and all the stuff that can help us improve").
    Our real results (live counters), what wins in each niche (weekly YouTube search), what is trending today
    (Wikipedia spikes + Google Trends), the searches that bring viewers, and product ideas with real demand."""
    from .stats_fetch import live_stats
    live = live_stats()
    names = {c["id"]: c["name"] for c in chans}
    vids = sorted((live.get("videos") or {}).values(), key=lambda v: -int(v.get("views") or 0))
    rows = "".join(f"<tr><td>{_e(names.get(v.get('channel'), v.get('channel')))}</td><td>{_e((v.get('title') or '')[:70])}</td>"
                   f"<td class=num>{_num(v.get('views'))}</td><td class=num>{_num(v.get('likes'))}</td>"
                   f"<td class=num>{_num(v.get('comments'))}</td></tr>" for v in vids[:15])
    lessons = []
    if vids:
        top = vids[0]
        lessons.append(f"Best so far: <b>{_e(top.get('title'))}</b> ({_num(top.get('views'))} views on "
                       f"{_e(names.get(top.get('channel'), ''))}). New videos copy its format and hook style.")
        flat = [v for v in vids if int(v.get("views") or 0) < 50 and time.time() - (v.get("posted_at") or 0) > 2 * 86400]
        if flat:
            lessons.append(f"{len(flat)} video(s) stayed under 50 views after 2 days: the first 2 seconds and the "
                           "title need a stronger promise on those channels.")
    for cid, m in metrics.items():
        tip = _insight(m)
        if m.get("videos") and "on track" not in tip:
            lessons.append(f"{_e(names.get(cid, cid))}: {_e(tip)}")
    chan_live = sorted((live.get("channels") or {}).items(), key=lambda kv: -int(kv[1].get("views") or 0))
    subs = "".join(f"<tr><td>{_e(names.get(cid, cid))}</td><td class=num>{_num(r.get('subs'))}</td>"
                   f"<td class=num>{_num(r.get('views'))}</td><td class=num>{_num(r.get('videos'))}</td></tr>"
                   for cid, r in chan_live)
    updated = max([float(r.get("at") or 0) for _, r in chan_live] or [0])
    niche = []
    for c in chans:
        w = _winners(c["id"], 3)
        if w:
            niche.append(f"<li><b>{_e(c['name'])}</b><br>" + "<br>".join(
                f"<span class=muted>{_num(x['views'])} views:</span> {_e(x['title'][:90])}" for x in w) + "</li>")
    tdir = ROOT / "data" / "state" / "trends"
    latest = sorted(tdir.glob("*_items.json"))[-1:] if tdir.exists() else []
    trend = []
    for f in latest:
        try:
            items = json.loads(f.read_text(encoding="utf-8")).get("items") or []
        except (OSError, ValueError):
            items = []
        items = sorted(items, key=lambda it: -float(it.get("spike") or 0))[:12]
        trend = [f"<li><b>{_e(it.get('title'))}</b> <span class=muted>{_e(str(it.get('source', '')).split(':')[0])}"
                 f"{' · ' + _e(it.get('desc')) if it.get('desc') else ''}</span></li>" for it in items]
    tday = latest[0].name[:10] if latest else "-"
    terms = []
    try:
        from .stats_fetch import top_terms
        for c in chans:
            t = top_terms(c["id"], 4)
            if t:
                terms.append(f"<li><b>{_e(c['name'])}</b>: " + ", ".join(f"{_e(k)} ({v})" for k, v in t) + "</li>")
    except Exception:  # noqa: BLE001
        pass
    prod = []
    try:
        pr = json.loads((ROOT / "data" / "state" / "product_research.json").read_text(encoding="utf-8"))
        ideas = pr.get("ranked") or pr.get("ideas") or [] if isinstance(pr, dict) else pr
        for it in ideas[:6]:
            prod.append(f"<li>{_e(it.get('title') or it.get('name') or it.get('id'))} "
                        f"<span class=muted>score {_e(it.get('score'))}</span></li>")
    except (OSError, ValueError, AttributeError, TypeError):
        pass
    when = datetime.fromtimestamp(updated, IST).strftime("%d %b %H:%M") if updated else "not yet"
    none_v = "<tr><td colspan=5 class=muted>none public yet</td></tr>"
    none_c = "<tr><td colspan=4 class=muted>none yet</td></tr>"
    return (f"<section id=learn class=page><div class=top><h1>📈 Trends & learnings</h1>"
            f"<div class=muted>Live YouTube counters, updated {when} IST (every cloud run)</div></div>"
            "<div class=card><h2>🧠 What we learned</h2><ul class=list>"
            + ("".join(f"<li>{x}</li>" for x in lessons) or "<li class=muted>Not enough views yet.</li>") + "</ul></div>"
            "<div class=card><h2>📺 Channels (live)</h2><table><tr><th>Channel</th><th>Subscribers</th><th>Views</th>"
            f"<th>Videos</th></tr>{subs or none_c}</table></div>"
            "<div class=card><h2>🎬 Our videos, best first</h2><table><tr><th>Channel</th><th>Title</th><th>Views</th>"
            f"<th>Likes</th><th>Comments</th></tr>{rows or none_v}</table></div>"
            f"<div class=card><h2>🔥 Trending today ({_e(tday)})</h2><ul class=list>"
            + ("".join(trend) or "<li class=muted>no trend data yet</li>") + "</ul></div>"
            "<div class=card><h2>🏆 What wins in our niches (this month)</h2><ul class=list>"
            + ("".join(niche) or "<li class=muted>collected every Wednesday</li>") + "</ul></div>"
            "<div class=card><h2>🔎 Searches that bring us viewers</h2><ul class=list>"
            + ("".join(terms) or "<li class=muted>appears once videos get search traffic</li>") + "</ul></div>"
            "<div class=card><h2>🛍️ Product ideas with real demand</h2><ul class=list>"
            + ("".join(prod) or "<li class=muted>researched every Tuesday</li>") + "</ul></div></section>")


def earning_accounts() -> list[tuple[str, str, str, str]]:
    """(account, status good/warn/bad, what we see, what is left) for every way HookHouse earns (owner 17 Nov: "is
    every earning account set up?"). Read from the real connections, campaigns, stores and books."""
    import os
    sec = ROOT / "data" / "secrets"
    rows: list[tuple[str, str, str, str]] = []
    from .stats_fetch import live_stats
    ch_live = live_stats().get("channels") or {}
    best = max(ch_live.items(), key=lambda kv: int(kv[1].get("subs") or 0), default=(None, {}))
    subs = int(best[1].get("subs") or 0)
    rows.append(("YouTube Partner Program (ads)", "warn", f"{len(ch_live)} channels live; most subscribers: {subs}",
                 "Automatic: apply when a channel reaches 1,000 subscribers + 10M Shorts views (90 days) or 4,000 "
                 "watch hours; usually months"))
    joined = len(_db("SELECT id FROM campaigns WHERE status='joined'"))
    rows.append(("Content Rewards (clipping campaigns)", "good" if joined else "warn",
                 f"{joined} campaign(s) joined, clips made automatically",
                 "Your ID check + Indian bank account at the first withdrawal"))
    rows.append(("Vyro (clipping campaigns)", "warn", "Account ready, Hot Take HQ linked",
                 "No campaign joined yet; payouts need a Whop account (being checked)"))
    dm = (sec / "dailymotion.json").exists()
    rows.append(("Dailymotion Partner (ads)", "good" if dm else "bad",
                 "Partner account, 8 English channels upload automatically" if dm else "not connected",
                 "Payment details (Tipalti) once the balance nears $100"))
    try:
        listed = json.loads((ROOT / "data" / "products" / "listed.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        listed = {}
    paid = sum(1 for k, v in listed.items() if (v or {}).get("payhip") and not k.startswith("free_"))
    rows.append(("Payhip store (digital products)", "bad", f"{paid} paid products + free samples listed",
                 "PayPal (name per PAN, DigiLocker + video check, bank): no sale can happen until it is connected"))
    rows.append(("Gumroad store", "bad", "Account and products ready", "Goes live after PayPal (India payouts are PayPal-only)"))
    try:
        books = json.loads((ROOT / "config" / "books.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        books = {}
    live_b = sum(1 for b in books.values() if b.get("status") == "live")
    review_b = sum(1 for b in books.values() if b.get("status") == "in review")
    rows.append(("Amazon KDP (books)", "good" if live_b or review_b else "warn",
                 f"{live_b} live, {review_b} in review, {len(books) - live_b - review_b} still to upload",
                 "Nothing from you; Claude uploads the rest (about 2 a week, each approved in Telegram)"))
    ig = len(list(sec.glob("meta_*.json"))) if sec.exists() else 0
    th = len(list(sec.glob("threads_*.json"))) if sec.exists() else 0
    rows.append(("Instagram + Threads (reach, later Reels bonuses)", "good" if ig else "bad",
                 f"Instagram {ig} of 13 channels, Threads {th}",
                 "Instagram for the other channels: 2-3 a day (your taps)"))
    rows.append(("Facebook Content Monetization", "bad", "No Facebook Pages for the channels",
                 "Later: Pages per channel, then request monetization monthly"))
    has_tags = bool(os.environ.get("AMAZON_COM_TAG") or os.environ.get("AMAZON_IN_TAG"))
    rows.append(("Amazon Associates (affiliate links)", "good" if has_tags else "bad",
                 "tags saved" if has_tags else "not signed up", "" if has_tags else "Optional: your sign-up (PAN/tax details)"))
    rows.append(("Music distribution (Bloop songs via RouteNote)", "bad", "Songs ready, not uploaded",
                 "Optional: RouteNote account (payouts via PayPal)"))
    rows.append(("Snapchat", "warn", "On hold", "Claude checks that Snapchat pays creators in India before any sign-up"))
    return rows


def _earning_card() -> str:
    icon = {"good": "✅", "warn": "⏳", "bad": "❌"}
    rows = "".join(f"<tr><td>{icon[st]} {_e(name)}</td><td>{_e(seen)}</td><td class=muted>{_e(left)}</td></tr>"
                   for name, st, seen, left in earning_accounts())
    return ("<div class=card><h2>💼 Earning accounts</h2><div class=tw><table><tr><th>Account</th><th>Now</th>"
            f"<th>Left</th></tr>{rows}</table></div></div>")


# ---------------- channel page ----------------
def _channel_page(ch: dict, ctx: dict) -> str:
    cid = ch["id"]
    m = ctx["metrics"].get(cid, {})
    fol = ctx["followers"].get(cid, {})
    conn = _connected(cid)
    short, long = _video_row(ch, "short"), _video_row(ch, "long")
    acc = (ch.get("style") or {}).get("highlight_color") or "#7c8cff"
    clips_ch = ch.get("type") == "clips" or "clipping_campaigns" in (ch.get("earns_from") or [])
    subs = fol.get("youtube", 0)
    live = conn["youtube"] or conn["instagram"]
    status = ("<span class='pill good'>Live</span>" if live and m else "<span class='pill warn'>Connected</span>" if live
              else "<span class='pill bad'>Not connected</span>")
    if ch.get("made_for_kids"):
        status += " <span class=pill>Made for Kids</span>"
    series = ctx["daily"].get(cid, [0.0] * 28)
    v7, p7 = sum(series[-7:]), sum(series[-14:-7])
    kpis = [("Subscribers", _num(subs) if conn["youtube"] else "-", "YouTube", ""),
            ("Instagram followers", _num(fol.get("instagram")) if conn["instagram"] else "-", "Instagram", ""),
            ("Views, last 7 days", _num(v7), _delta(v7, p7) or "all platforms", _spark(series[-14:])),
            ("Views, all time", _num(m.get("views", 0)), f"{_num(m.get('videos', 0))} videos posted", ""),
            ("Stayed to watch", f"{m['stayed']:.0f}%" if m.get("stayed") is not None else "-", "aim 70%+ (first seconds)", ""),
            ("Average % viewed", f"{m['pct']:.0f}%" if m.get("pct") is not None else "-", "aim 80%+ on Shorts", "")]
    live_key = {"Subscribers": f"subs:{cid}", "Instagram followers": f"ig:{cid}"}
    kpi_html = "".join(f"<div class=kpi><small>{_e(k)}</small><b"
                       + (f" data-live='{live_key[k]}'" if k in live_key else "")
                       + f">{_e(v)}</b><div class=ksub>{sub}</div>{sp}</div>" for k, v, sub, sp in kpis)

    if clips_ch:
        joined = [c for c in ctx["campaigns"] if c.get("account") == cid and c.get("status") in ("picked", "joined")]
        open_n = sum(1 for c in ctx["campaigns"] if c.get("account") == cid and c.get("status") in ("eligible", "review"))
        mon = (f"<p>Earns from <b>clipping campaigns</b>: brands and creators pay per 1,000 views (typically "
               f"${CAMPAIGN_CPM}). No YouTube thresholds needed.</p><div class=kpis3>"
               f"<div class=kpi><small>Picked / joined</small><b>{len(joined)}</b></div>"
               f"<div class=kpi><small>Matching, open</small><b>{open_n}</b></div>"
               f"<div class=kpi><small>Paid views</small><b>{_num(m.get('views', 0))}</b></div></div>")
    else:
        mon = "<p>Ad money starts when YouTube accepts the channel (we apply under the rules from 1 Feb 2027).</p>"
    mon += (_bar("Subscribers", subs, YPP["subs"]) +
            _bar("Long-video watch hours (12 months)", m.get("watch_hours_365d", 0), YPP["hours"]) +
            "<div class=or>or</div>" + _bar("Shorts views (90 days)", m.get("shorts_views_90d", 0), YPP["shorts_views"]) +
            f"<p class=muted>Fan funding opens earlier: {YPP['fan_subs']} subscribers + {_num(YPP['fan_hours'])} watch "
            f"hours or {_num(YPP['fan_shorts'])} Shorts views.</p>")
    if ch.get("made_for_kids"):
        mon += "<p class=muted>Made for Kids: lower ad rates (no personalised ads) and no comments.</p>"

    e = ctx["earnings"].get(cid, {})
    rs, rl = RPM.get(cid, (0.05, 2.0))
    est = (m.get("views", 0) / 1000 * CAMPAIGN_CPM) if clips_ch else \
        (m.get("short_views", 0) / 1000 * rs + m.get("long_views", 0) / 1000 * rl)
    earn = (f"<div class=kpis3><div class=kpi><small>Received</small><b>₹{e.get('received_inr', 0):,.0f}</b></div>"
            f"<div class=kpi><small>Pending</small><b>${e.get('pending_usd', 0):,.0f}</b></div>"
            f"<div class=kpi><small>{'Campaign value' if clips_ch else 'If monetized'}</small><b>${est:,.0f}</b></div></div>"
            + ("" if clips_ch else f"<p class=muted>Estimate: Shorts ${rs}/1K views, long videos ${rl}/1K views "
                                   "(research rates for this niche).</p>"))
    imp = "".join(f"<li class={lv}><span class=dot></span>{_e(t)}</li>" for lv, t in improvements(ch, short, long, m, conn))

    now = datetime.now(IST)
    mine = sorted([it for it in ctx["items"] if it.get("channel") == cid and (_when(it) or now) >= now - timedelta(days=1)],
                  key=lambda x: x.get("publish_at", ""))
    plan = "".join(f"<tr><td class=when>{_when(it):%a %d %b, %H:%M}</td><td>{_e(it.get('kind'))}</td>"
                   f"<td class=topic>{_e(it.get('topic') or 'picked when made')}</td><td><span class='pill {QCLS.get(it.get('status'), '')}'>"
                   f"{_e(QLABEL.get(it.get('status'), it.get('status')))}</span></td></tr>"
                   for it in mine[:12] if _when(it)) or "<tr><td class=muted colspan=4>Nothing planned yet</td></tr>"
    camps = [c for c in ctx["campaigns"] if c.get("account") == cid and c.get("status") not in ("rejected", "blocked_safety", "not_eligible")]
    camp = "".join(f"<tr><td><a href='{_e(c.get('url') or '#')}' target=_blank>{_e(str(c.get('name'))[:60])}</a>"
                   f"{' 🔥' if c.get('hot') else ''}</td><td>{_e(c.get('fit'))}</td><td>${_e(c.get('cpm_usd') or '-')}</td>"
                   f"<td><span class=pill>{_e(c.get('status'))}</span></td></tr>" for c in camps[:8])
    spec = ch.get("spec") or {}
    rules = [("Short length", spec.get("short_words")), ("Short pace", f"{spec['short_wpm']} words/min" if spec.get("short_wpm") else None),
             ("Long length", spec.get("long_words")), ("Long pace", f"{spec['long_wpm']} words/min" if spec.get("long_wpm") else None),
             ("Cut every", f"{spec['shot_s']} s" if spec.get("shot_s") else None),
             ("Posting", f"{(ch.get('schedule') or {}).get('shorts_per_day', 0)} Short/day, "
                         f"{(ch.get('schedule') or {}).get('long_per_week', 0)} long/week")]
    if clips_ch:
        rules = [("Clip length", "20-55 s, one complete moment"), ("Opening", "hook on screen in the first 2 s"),
                 ("Sources", "campaign footage, public domain or written permission only"),
                 ("Gaming clips", "no graphic violence in the first 7 s")] + rules[-1:]
    rules_html = "".join(f"<tr><td>{_e(k)}</td><td>{_e(v)}</td></tr>" for k, v in rules if v)
    qrow = ctx.get("quality", {}).get(cid) or {}
    q_items = "".join(
        f"<li class={lv}><span class=dot></span>{_e(v.get('format', ''))}: {_e(t)}</li>"
        for v in qrow.get("videos", []) for lv, t in v.get("issues", []))
    q_html = (f"<p>Score <b>{qrow['score']}</b>/100 · newest Short and long video measured: loudness, peaks, first and "
              "last frame, colour, length, pace, captions, thumbnails.</p>" +
              (f"<ul class=imp>{q_items}</ul>" if q_items else "<p class=muted>Everything measured is on target.</p>")) \
        if qrow.get("score") is not None else "<p class=muted>No finished video to measure yet.</p>"
    try:
        from .stats_fetch import top_terms
        terms = top_terms(cid)
    except Exception:  # noqa: BLE001
        terms = []
    terms_html = ("<ul class=imp>" + "".join(f"<li class=good><span class=dot></span><span>{_e(t)}"
                                             f"<span class=muted> · {_num(v)} views</span></span></li>" for t, v in terms)
                  + "</ul><p class=muted>YouTube search, last 28 days. The planner makes more videos on these.</p>") \
        if terms else "<p class=muted>Fills in weekly once the channel is connected and gets search views.</p>"
    win = _winners(cid)
    if win:
        win_html = ("<ul class=imp>" + "".join(
            f"<li class=good><span class=dot></span><span><a href='https://youtu.be/{_e(w['id'])}' target=_blank>"
            f"{_e(w['title'][:110])}</a><br><span class=muted>{_num(w['views'])} views · {_e(w.get('format') or '')}"
            "</span></span></li>" for w in win) + "</ul><p class=muted>From YouTube's own search each Wednesday "
            "(last 14 days). The writer learns the patterns, never copies the words. Kept 30 days.</p>")
    else:
        win_html = "<p class=muted>Fills in every Wednesday once a YouTube API key or a connected channel exists.</p>"
    vids = "".join(_vcard(v, ctx) for v in _gallery(ctx["items"], [ch], only=cid, limit=8)) or \
        "<p class=muted>No finished videos yet.</p>"
    try:                                       # owner 18 Nov: a YouTube-Studio-like menu per channel
        from . import dashboard_studio as _st
        studio = _st.content_card(ch, ctx, poster=_poster) + _st.insights_card(ch, ctx)
    except Exception as ex:  # noqa: BLE001 - the rest of the page still shows
        studio = f"<div class='card wide'><h2>🎬 Studio</h2><p class=muted>Couldn't build: {_e(ex)}</p></div>"
    return f"""<section id="ch-{cid}" class=page style="--acc:{acc}">
<div class=chead><img class=bigav src="{ctx['avatars'].get(cid, '')}" alt=""><div><h1>{_e(ch['name'])}</h1>
<div class=sub>{status} <span class=pill>{_e('Hindi' if ch.get('language') == 'hi' else 'English')} · {_e(ch.get('market'))}</span>
<span class=muted>{_e(ch.get('niche'))}</span></div><p class=bio>“{_e(ch.get('bio'))}”</p></div></div>
<div class=kpis6>{kpi_html}</div>
<div class=cgrid>
{studio}
<div class="card wide"><h2>🎬 Videos</h2><div class=gallery>{vids}</div></div>
<div class=card><h2>🛠 Points to improve</h2><ul class=imp>{imp}</ul></div>
<div class=card><h2>💰 Monetization</h2>{mon}</div>
<div class="card wide"><h2>🗓 Next posts</h2><div class=tw><table class=stack><tr><th>Posts at (IST)</th><th>Kind</th><th>Topic</th><th>Status</th></tr>{plan}</table></div></div>
<div class=card><h2>📈 Earnings</h2>{earn}</div>
<div class=card><h2>🎯 Research targets</h2><table>{rules_html}</table></div>
<div class=card><h2>🔥 Winning in this niche now</h2>{win_html}</div>
<div class=card><h2>🎯 Quality check</h2>{q_html}</div>
<div class=card><h2>🔎 Searches that bring viewers</h2>{terms_html}</div>
{f'<div class="card wide"><h2>📋 Campaigns for this channel</h2><div class=tw><table><tr><th>Campaign</th><th>Fit</th><th>$/1K</th><th>Status</th></tr>{camp}</table></div></div>' if camp else ''}
</div></section>"""


# ---------------- platform insights ----------------
PLAT_ICON = {"youtube": "▶️", "instagram": "📸", "facebook": "📘", "dailymotion": "🎞", "snapchat": "👻",
             "threads": "🧵", "pinterest": "📌", "x": "✖️"}
PLAT_TIPS = {
    "youtube": ["Shorts: the first second decides (cold open, no greeting); loop the last line into the first; 30-60 s",
                "Long videos: title + thumbnail first, chapters, a re-hook every 20-40 s",
                "Playlists per channel are filled automatically: they turn one view into several"],
    "instagram": ["Ranking = watch time, sends per reach (DM shares) and likes per reach: make it worth sending",
                  "Never ask for shares or tags (engagement bait is shown to fewer people)",
                  "Original renders only (our Reel copy differs from the Short); AI label set automatically"],
    "facebook": ["Reels must be 3-90 s via the API (longer ones are skipped automatically)",
                 "Request Content Monetization every month on each Page (invite-only)",
                 "Hindi audiences are large on Facebook: the Hindi channels matter most here"],
    "dailymotion": ["Search-led: keep the channel's search phrase at the start of every title",
                    "Long videos earn more than Shorts here; check the Partner dashboard monthly"],
    "snapchat": ["Spotlight: vertical, 60 s max, post the evening winners within a day",
                 "Up to 3 topic hashtags; India is eligible for creator payouts (view-time rules)"],
    "threads": ["A conversation-starting line + the video; link the full YouTube video in the post"],
    "pinterest": ["Evergreen explainers only (money, space, ocean, wildlife); keyword-first titles; link the long video"],
    "x": ["Only for campaigns that pay for X views: post within minutes and submit the link within 30 minutes"],
}


def _platform_stats(chans: list[dict]) -> dict:
    """Per platform: connected accounts, followers, posts (all / 7 days) per channel, views and quality signals."""
    out = {p: {"posts": 0, "posts_7d": 0, "by_channel": {}, "views": 0, "videos": 0, "stayed": [], "pct": [],
               "skip": [], "shares": 0, "saves": 0, "best": None, "followers": 0, "connected": 0, "hand_posted": 0}
           for p in PLAT_ICON}
    from .publish import LOG, dm_creds
    now = time.time()
    if LOG.exists():
        for ln in LOG.read_text(encoding="utf-8").splitlines():
            try:
                a = json.loads(ln)
            except ValueError:
                continue
            plat = a.get("platform")
            if plat not in out or not a.get("done") or not a.get("item_id") or (a.get("details") or {}).get("dry_run"):
                continue
            if str(a.get("what", "")).startswith(("delete", "captions", "thumbnail", "add ")):
                continue
            o = out[plat]
            o["posts"] += 1
            o["posts_7d"] += 1 if now - (a.get("at") or 0) < 7 * 86400 else 0
            o["by_channel"][a.get("channel")] = o["by_channel"].get(a.get("channel"), 0) + 1
    db = ROOT / "data" / "analytics.db"
    if db.exists():
        try:
            with sqlite3.connect(db) as c:
                rows = c.execute(
                    "SELECT m.platform, m.hook, m.views, m.stayed_pct, m.avg_pct_viewed, m.skip_rate, m.shares, m.saves "
                    "FROM video_metrics m JOIN (SELECT item_id, platform, MAX(hours_after) h FROM video_metrics GROUP BY "
                    "item_id, platform) last ON m.item_id = last.item_id AND m.platform = last.platform AND "
                    "m.hours_after = last.h").fetchall()
        except sqlite3.Error:
            rows = []
        for plat, hook, views, stayed, pct, skip, shares, saves in rows:
            o = out.get(str(plat))
            if not o:
                continue
            v = int(views or 0)
            o["views"] += v
            o["videos"] += 1
            o["shares"] += int(shares or 0)
            o["saves"] += int(saves or 0)
            for key, val in (("stayed", stayed), ("pct", pct), ("skip", skip)):
                if val is not None:
                    o[key].append(float(val))
            if not o["best"] or v > o["best"][1]:
                o["best"] = (hook or "", v)
    for p in out.values():
        for key in ("stayed", "pct", "skip"):
            p[key] = round(sum(p[key]) / len(p[key]), 1) if p[key] else None
    for cid, plat, f in _db("SELECT channel_id, platform, followers FROM account_stats"):
        if plat in out:
            out[plat]["followers"] += int(f or 0)
    sec = ROOT / "data" / "secrets"
    out["youtube"]["connected"] = len(list(sec.glob("youtube_*.json"))) if sec.exists() else 0
    metas = [json.loads(f.read_text(encoding="utf-8")) for f in sec.glob("meta_*.json")] if sec.exists() else []
    out["instagram"]["connected"] = len(metas)
    out["facebook"]["connected"] = sum(1 for m in metas if m.get("page_id"))
    out["threads"]["connected"] = len(list(sec.glob("threads_*.json"))) if sec.exists() else 0
    out["dailymotion"]["connected"] = sum(1 for ch in chans if dm_creds(ch["id"]))
    sp = ROOT / "data" / "state" / "share_packs.json"
    if sp.exists():
        try:
            for plats in (json.loads(sp.read_text(encoding="utf-8")).get("posted") or {}).values():
                for pl in plats:
                    if pl in out:
                        out[pl]["hand_posted"] += 1
        except ValueError:
            pass
    return out


def _platform_page(chans: list[dict], ctx: dict) -> str:
    from . import platforms as _pf
    st = _platform_stats(chans)
    reg = _pf.registry()
    possible = {p: sum(1 for ch in chans if _pf.allowed(ch, p)) for p in PLAT_ICON}
    cards = []
    for p, o in st.items():
        mode = (reg.get(p) or {}).get("post", "")
        warn = []
        if o["stayed"] is not None and o["stayed"] < 70:
            warn.append(f"Only {o['stayed']:.0f}% stay past the first seconds (aim 70%+): sharper first line and frame.")
        if o["pct"] is not None and o["pct"] < 60:
            warn.append(f"Viewers watch {o['pct']:.0f}% on average: cut slow parts, add a twist in the middle.")
        if o["skip"] is not None and o["skip"] > 50:
            warn.append(f"Skip rate {o['skip']:.0f}%: change the first frame and the hook text.")
        kpis = [("Accounts", f"{o['connected']}/{possible[p]}" if mode == "auto" or p in ("threads",) else
                 ("you post" if mode == "winners" else "later")),
                ("Followers", _num(o["followers"]) if o["followers"] else "-"),
                ("Posts (7 days)", f"{o['posts_7d'] or o['hand_posted'] or 0}"),
                ("Views", _num(o["views"]) if o["views"] else "-")]
        qual = [x for x in (f"stayed {o['stayed']:.0f}%" if o["stayed"] is not None else "",
                            f"watched {o['pct']:.0f}%" if o["pct"] is not None else "",
                            f"skip {o['skip']:.0f}%" if o["skip"] is not None else "",
                            f"{_num(o['shares'])} shares" if o["shares"] else "",
                            f"{_num(o['saves'])} saves" if o["saves"] else "") if x]
        cards.append(
            f"<div class=card><h2>{PLAT_ICON[p]} {_e(p.title())} <span class=muted>{_e({'auto': 'auto: posted by the system', 'winners': 'winners: you post our best videos', 'later': 'later'}.get(mode, ''))}</span></h2>"
            f"<div class=kpis3 style='grid-template-columns:repeat(4,1fr)'>" + "".join(
                f"<div class=kpi><small>{_e(k)}</small><b>{_e(v)}</b></div>" for k, v in kpis) + "</div>"
            + (f"<p class=muted>Quality: {_e(' · '.join(qual))}</p>" if qual else "")
            + (f"<p class=muted>Best: {_e(o['best'][0][:70])} ({_num(o['best'][1])} views)</p>" if o["best"] else "")
            + "<ul class=imp>" + "".join(f"<li class=bad><span class=dot></span>{_e(w)}</li>" for w in warn)
            + "".join(f"<li class=good><span class=dot></span>{_e(t)}</li>" for t in PLAT_TIPS.get(p, [])) + "</ul></div>")
    heads = "".join(f"<th>{PLAT_ICON[p]} {_e(p)}</th>" for p in PLAT_ICON)
    rows = "".join(
        f"<tr><td class=chcol><img src='{ctx['avatars'].get(ch['id'], '')}' alt=''>{_e(ch['name'])}</td>" + "".join(
            f"<td>{st[p]['by_channel'].get(ch['id'], 0) if _pf.allowed(ch, p) else '<span class=muted>-</span>'}</td>"
            for p in PLAT_ICON) + "</tr>" for ch in chans)
    return (f"<section id=platforms class=page><div class=top><h1>🌐 Platforms</h1><div class=muted>Numbers per platform, "
            "what each one rewards, and what to improve. They fill in as accounts get connected and videos go live."
            f"</div></div><div class=cgrid>{_accounts_card()}{''.join(cards)}<div class='card full'><h2>Posts per channel and platform</h2>"
            f"<div class=tw><table><tr><th>Channel</th>{heads}</tr>{rows}</table></div></div></div></section>")


# ---------------- page ----------------
CSS = """
:root{--bg:#0b0e14;--panel:#141922;--panel2:#1a2030;--line:#242c3a;--text:#e9edf4;--mut:#8d97a8;--acc:#7c8cff;
--good:#2ecc71;--warn:#f5a623;--bad:#ff5a5f;--info:#4da3ff}
*{box-sizing:border-box}html,body{margin:0}body{font-family:"Segoe UI",Inter,Roboto,Arial,sans-serif;background:var(--bg);color:var(--text)}
a{color:#9fb3ff;text-decoration:none}.muted{color:var(--mut);font-size:13px}
.layout{display:flex;min-height:100vh}
nav{width:232px;flex:none;background:#080b10;border-right:1px solid var(--line);padding:14px 10px;position:sticky;top:0;height:100vh;overflow-y:auto}
nav .brand{font-weight:800;font-size:19px;padding:4px 10px 12px}nav .brand span{color:#ffd400}
nav .grp{color:var(--mut);font-size:11px;letter-spacing:.08em;text-transform:uppercase;margin:14px 10px 6px}
nav a{display:flex;align-items:center;gap:10px;padding:6px 10px;border-radius:10px;color:var(--text);font-size:14px}
nav a:hover{background:var(--panel)}nav a.on{background:var(--panel2);box-shadow:inset 3px 0 0 var(--acc)}
nav img{width:24px;height:24px;border-radius:50%;flex:none}nav .ico{width:24px;text-align:center}
nav .st{margin-left:auto;width:8px;height:8px;border-radius:50%;background:#4a5263}nav .st.live{background:var(--good)}
main{flex:1;min-width:0;padding:22px 26px 50px}
.page{display:none;scroll-margin-top:90px}.page.on{display:block}
h1{margin:0;font-size:25px}h2{font-size:15px;margin:0 0 12px;color:#c9d3ff;letter-spacing:.01em}
.top{display:flex;justify-content:space-between;align-items:flex-end;flex-wrap:wrap;gap:8px;margin-bottom:6px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:16px;margin-bottom:16px;min-width:0}
.kpis6{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:12px;margin:14px 0 16px}
.kpis3{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin:8px 0}
.kpi{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:12px 14px;min-width:0}
.kpi small{color:var(--mut);font-size:12px}.kpi b{display:block;font-size:26px;margin-top:2px;font-variant-numeric:tabular-nums}
.kpi .ksub{color:var(--mut);font-size:12px;margin-top:2px}.kpi.warn{border-color:#6b4d12}.kpi.warn b{color:#ffd27a}
.kpi.bad{border-color:#5a2226}.card .kpi{background:var(--panel2)}.card .kpi b{font-size:19px}
.up{color:var(--good)}.down{color:var(--bad)}
.spark{width:100%;height:30px;display:block;margin-top:6px}.spark polyline{fill:none;stroke:var(--acc);stroke-width:2;vector-effect:non-scaling-stroke}
.spark line{stroke:#2a3242;stroke-width:2;vector-effect:non-scaling-stroke}
.ovgrid{display:grid;grid-template-columns:minmax(0,1fr) 370px;gap:16px;align-items:start}
.mainc,.side{min-width:0}
.cgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(360px,1fr));grid-auto-flow:dense;gap:16px;align-items:start}.cgrid>.card{margin-bottom:0}td.when{white-space:nowrap;font-variant-numeric:tabular-nums}@media(min-width:1300px){.cgrid>.wide{grid-column:span 2}}.cgrid>.full{grid-column:1/-1}
.pill{display:inline-block;padding:2px 9px;border-radius:999px;background:#2a3242;font-size:12px;margin-right:4px;white-space:nowrap}
.pill.good{background:#17432b;color:#7ff0a8}.pill.warn{background:#4d3810;color:#ffd27a}.pill.bad{background:#4a1c1f;color:#ff9da0}
.pill.info{background:#1d3a66;color:#9cc4ff}
.chead{display:flex;gap:18px;align-items:center}.bigav{width:80px;height:80px;border-radius:50%;border:3px solid var(--acc)}
.sub{margin-top:6px;display:flex;flex-wrap:wrap;gap:6px;align-items:center}.bio{margin:8px 0 0;color:#c0c8d6;font-style:italic}
.bar{margin:12px 0}.barhead{display:flex;justify-content:space-between;font-size:13px;margin-bottom:5px}.barhead span{color:var(--mut)}
.track{height:9px;background:#0c0f15;border-radius:99px;overflow:hidden}.fill{height:100%;background:var(--acc);border-radius:99px;min-width:2px}
.or{text-align:center;color:var(--mut);font-size:12px;margin:-4px 0}
ul.imp{list-style:none;padding:0;margin:0}ul.imp li{display:flex;gap:10px;padding:8px 0;border-bottom:1px solid var(--line);font-size:14px}
ul.imp li:last-child{border-bottom:0}
.dot{width:9px;height:9px;border-radius:50%;flex:none;margin-top:6px;background:var(--acc)}li.bad .dot{background:var(--bad)}
li.warn .dot{background:var(--warn)}li.good .dot{background:var(--good)}
.hl{list-style:none;padding:0;margin:0}.hl li{display:flex;align-items:center;gap:8px;padding:8px 0;border-bottom:1px solid var(--line);font-size:13.5px}
.hl li:last-child{border-bottom:0}.hl .v{margin-left:auto;text-align:right;color:#d5dbe6}
.lv{width:9px;height:9px;border-radius:50%;flex:none}.lv.good{background:var(--good)}.lv.warn{background:var(--warn)}
.lv.bad{background:var(--bad)}.lv.info{background:var(--info)}
table{width:100%;border-collapse:collapse}td,th{padding:7px 8px;border-bottom:1px solid var(--line);text-align:left;font-size:13.5px;vertical-align:top}
th{color:var(--mut);font-weight:600;font-size:12px}.tw{overflow-x:auto}
table.tl{min-width:900px}table.tl td,table.tl th{padding:6px;border-bottom:1px solid #1d2431}
table.tl .today{background:rgba(124,140,255,.07)}table.tl th.today{color:#c9d3ff}
.chcol{white-space:nowrap;width:190px}.chcol a{color:var(--text)}.chcol img{width:20px;height:20px;border-radius:50%;vertical-align:-5px;margin-right:7px}
.slot{display:inline-block;font-size:11.5px;padding:2px 6px;border-radius:6px;margin:2px 3px 2px 0;background:#2a3242;color:#c9d1de;
font-variant-numeric:tabular-nums;white-space:nowrap}
.slot.long{box-shadow:inset 0 -2px 0 #ffd400;font-weight:700}
.s-making{background:#1d3a66;color:#9cc4ff}.s-made,.s-redo{background:#4d3810;color:#ffd27a}
.s-approved{background:#17432b;color:#7ff0a8}.s-posted{background:#2ecc71;color:#06210f}
.s-failed,.s-missed,.s-rejected{background:#4a1c1f;color:#ff9da0}.s-needs_source{background:#3a2353;color:#d6b4ff}
.legend{margin-top:10px;display:flex;flex-wrap:wrap;gap:4px}
.gallery{display:grid;grid-template-columns:repeat(auto-fill,minmax(168px,1fr));grid-auto-flow:dense;gap:14px;align-items:start}
.vc{margin:0;background:var(--panel2);border:1px solid var(--line);border-radius:12px;overflow:hidden;min-width:0}
.vc.hor{grid-column:span 2}.player{position:relative;background:#000}
.vc video{width:100%;display:block;background:#000;object-fit:cover}.vc.ver video{aspect-ratio:9/16}.vc.hor video{aspect-ratio:16/9}
.nofile-msg{display:none;position:absolute;left:0;right:0;bottom:0;background:rgba(0,0,0,.8);font-size:12px;padding:8px;text-align:center}
.player.nofile .nofile-msg{display:block}
figcaption{padding:8px 10px 10px;font-size:13.5px}figcaption b{display:block;margin:2px 0;line-height:1.3}
.vtop{display:flex;align-items:center;gap:6px;font-size:12px;color:var(--mut);min-width:0}.vtop img{width:18px;height:18px;border-radius:50%;flex:none}.vtop span:not(.pill){min-width:0;flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.vtop .pill{margin-left:auto;margin-right:0}
.chgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(270px,1fr));gap:12px}
.chcard{background:var(--panel2);border:1px solid var(--line);border-radius:14px;padding:13px;color:var(--text);display:block;min-width:0}
.chcard:hover{border-color:var(--acc)}.chcard .r{display:flex;gap:10px;align-items:center}.chcard img{width:40px;height:40px;border-radius:50%}
.chcard .nm{min-width:0;flex:1}.chcard .n{font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.chcard .nm .muted{font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.cstats{display:grid;grid-template-columns:repeat(auto-fit,minmax(72px,1fr));gap:6px;margin-top:10px}.cstats small{color:var(--mut);font-size:11px;display:block}
.cstats b{font-size:15px;font-variant-numeric:tabular-nums}
ul.list{margin:0;padding-left:18px}ul.list li{margin:7px 0;font-size:14px}li.done{opacity:.45;text-decoration:line-through}
ul.tdl{list-style:none;padding:0;margin:0}ul.tdl li{padding:8px 0;border-bottom:1px solid var(--line);font-size:14px}
ul.tdl li:last-child{border-bottom:0}ul.tdl label{display:flex;gap:10px;align-items:flex-start;cursor:pointer}
ul.tdl input{width:20px;height:20px;margin-top:2px;accent-color:#2ecc71;flex:none}ul.tdl li.done b{text-decoration:line-through;opacity:.6}
@media(max-width:1500px){.kpis6{grid-template-columns:repeat(3,minmax(0,1fr))}}
@media(max-width:1200px){.ovgrid{grid-template-columns:minmax(0,1fr)}.mainc,.side{display:contents}
.ovgrid>*>.card{margin-bottom:0}.c-needs{order:1}.c-videos{order:2}.c-week{order:3}.c-channels{order:4}.c-health{order:5}.c-camps{order:6}}
@media(max-width:860px){.layout{display:block}
nav{width:auto;height:auto;position:sticky;top:0;z-index:5;display:flex;overflow-x:auto;gap:4px;padding:8px;border-right:0;border-bottom:1px solid var(--line)}
nav .brand,nav .grp{display:none}nav a{flex:none;padding:6px 10px;font-size:13px;white-space:nowrap}nav .st{display:none}
main{padding:12px}h1{font-size:21px}table.stack tr:first-child{display:none}table.stack tr{display:block;padding:9px 0;border-bottom:1px solid var(--line)}table.stack td{display:inline;border:0;padding:0 8px 0 0}table.stack td.topic{display:block;padding:4px 0}.kpis6{grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}.kpi{padding:10px 12px}.kpi b{font-size:21px}
.cgrid{grid-template-columns:minmax(0,1fr)}.kpis3{grid-template-columns:1fr 1fr 1fr}.kpis3 .kpi b{font-size:15px}
.gallery{grid-template-columns:none;grid-auto-flow:column;grid-auto-columns:44%;overflow-x:auto;scroll-snap-type:x mandatory;padding-bottom:6px}
.vc{scroll-snap-align:start}.chgrid{grid-template-columns:minmax(0,1fr)}.bigav{width:60px;height:60px}table.tl{min-width:720px}.chcol{width:150px}}
"""

JS = """
function show(id){document.querySelectorAll('video').forEach(function(v){v.pause()});
document.querySelectorAll('.page').forEach(p=>p.classList.toggle('on',p.id===id));
document.querySelectorAll('nav a').forEach(a=>a.classList.toggle('on',a.getAttribute('href')==='#'+id));
var a=document.querySelector('nav a.on'),n=document.querySelector('nav');if(a&&window.innerWidth<860)n.scrollLeft=a.offsetLeft-n.clientWidth/2+a.offsetWidth/2;
setTimeout(function(){window.scrollTo(0,0)},0);setTimeout(function(){window.scrollTo(0,0)},60)}
function route(){var id=(location.hash||'#overview').slice(1);if(!document.getElementById(id))id='overview';show(id)}
window.addEventListener('hashchange',route);route();
document.addEventListener('play',function(e){document.querySelectorAll('video').forEach(function(v){if(v!==e.target)v.pause()})},true);
document.querySelectorAll('ul.tdl input:not([disabled])').forEach(function(c){var k='todo_'+c.dataset.id;
if(localStorage.getItem(k)==='1'){c.checked=true;c.closest('li').classList.add('done')}
c.addEventListener('change',function(){localStorage.setItem(k,c.checked?'1':'0');c.closest('li').classList.toggle('done',c.checked)})});
"""


def _products_page() -> str:
    """Owner, 14 Nov: the digital products and their stores on the pad (what's live, draft, waiting for a payout)."""
    from PIL import Image
    from . import store_covers, store_publish
    from . import books as _books
    listed = store_publish.listed()
    kdp_state = _books.load()                         # committed config/books.json: same on the PC and in the cloud
    rows, n_live = [], 0
    for pid in store_covers.SPECS:
        folder = ROOT / "data" / "products" / pid
        if not (folder / "product.json").exists():
            continue
        thumb = ""
        t = folder / "store_thumb.jpg"
        if t.exists():
            im = Image.open(t).convert("RGB")
            im.thumbnail((64, 64))
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=70)
            thumb = f"<img src='data:image/jpeg;base64,{base64.b64encode(buf.getvalue()).decode()}' style='width:48px;border-radius:8px'>"
        lst = listed.get(pid) or {}
        pay = lst.get("payhip") or {}
        gum = lst.get("gumroad") or {}
        kd = kdp_state.get(pid) or {}
        pins = 0
        pj = folder / "pins" / "pins.json"
        if pj.exists():
            pins = sum(1 for p in json.loads(pj.read_text(encoding="utf-8"))["pins"] if p.get("posted"))
        n_live += bool(pay.get("public"))
        cell = lambda ok, txt: f"<span class='{'good' if ok else 'muted'}'>{_e(txt)}</span>"  # noqa: E731
        rows.append(
            f"<tr><td>{thumb}</td><td><b>{_e(store_publish.title_for(pid)[:70])}</b></td>"
            f"<td>${store_publish.price_usd(pid):.0f}</td>"
            f"<td>{cell(bool(pay.get('public')), 'live' if pay.get('public') else ('listed' if pay else '—'))}</td>"
            f"<td>{cell(bool(gum) and not gum.get('draft'), 'draft (needs bank)' if gum.get('draft') else ('live' if gum else '—'))}</td>"
            f"<td>{cell(kd.get('status') == 'live', kd.get('status', '—'))}</td>"
            f"<td>{pins}</td></tr>")
    return (f"<section id=products class=page><div class=top><h1>🛍️ Products & stores</h1>"
            f"<div class=muted>{n_live} live on Payhip · rebuild + list: python cli.py products all</div></div>"
            + _books_card(kdp_state) +
            "<div class='card full'><div class=tw><table class=stack><tr><th></th><th>Product</th><th>Price</th><th>Payhip</th>"
            f"<th>Gumroad</th><th>Amazon KDP</th><th>Pins</th></tr>{''.join(rows)}</table></div>"
            "<p class=muted>Payouts: Payhip needs PayPal, Gumroad needs a bank account, KDP needs the tax interview "
            "(owner steps). Pins post 2 a day from the PC helper.</p></div></section>")


def _books_card(books: dict) -> str:
    """Owner, 15 Nov: see every Amazon book any time: cover, status, price, ISBN and links (Telegram: /books)."""
    from . import books as _books
    if not books:
        return ""
    order = {"live": 0, "in review": 1, "publishing": 1, "ready": 2, "draft": 3, "not started": 4, "blocked": 5}
    cards = []
    for pid, b in sorted(books.items(), key=lambda kv: (order.get(kv[1].get("status", ""), 9), kv[1].get("title", ""))):
        st = b.get("status", "not started")
        img = (f"<img src='data:image/jpeg;base64,{b['thumb']}' style='width:84px;border-radius:6px;"
               "box-shadow:0 2px 8px #0005'>") if b.get("thumb") else ""
        links = []
        if st == "live" and _books.amazon_url(b):
            links.append(f"<a href='{_e(_books.amazon_url(b))}'>Amazon page</a>")
        if b.get("pdf_url"):
            links.append(f"<a href='{_e(b['pdf_url'])}'>PDF on Payhip</a>")
        links.append(f"<a href='{_books.BOOKSHELF}'>KDP bookshelf</a>")
        facts = " · ".join(x for x in (f"${b['price']}" if b.get("price") else "", f"{b['pages']} pages" if b.get("pages") else "",
                                       f"ISBN {b['isbn']}" if b.get("isbn") else "") if x)
        cards.append(
            f"<div style='display:flex;gap:12px;align-items:flex-start;padding:8px 0;border-bottom:1px solid #8883'>{img}"
            f"<div><b>{_e(b.get('title', pid))}</b><div class=muted>{_e(b.get('author', ''))}</div>"
            f"<div>{_books.ICON.get(st, '⚪')} <b>{_e(_books.label(st))}</b>{' · ' + _e(facts) if facts else ''}</div>"
            f"<div>{' · '.join(links)}</div>"
            f"<div class=muted>checked {_e(b.get('checked') or b.get('updated') or '—')}</div></div></div>")
    n_live = sum(1 for b in books.values() if b.get("status") == "live")
    return (f"<div class='card full'><h2>📚 Amazon books ({n_live} live of {len(books)})</h2>{''.join(cards)}"
            "<p class=muted>Status refreshes from the KDP bookshelf on the PC (python -m engine.books sync). "
            "Telegram: /books</p></div>")


def _studio_css() -> str:
    from .dashboard_accounts import CSS as acc
    from .dashboard_studio import CSS as c
    return c + acc


def _accounts_card() -> str:
    """19 Nov: every channel's accounts on every platform, linked (owner: "all the things should be inter-linked")."""
    try:
        from .dashboard_accounts import card, training_card
        return card() + training_card()
    except Exception as ex:  # noqa: BLE001 - the rest of the page still shows
        return f"<div class='card wide'><h2>🔗 Accounts &amp; links</h2><p class=muted>Couldn't build: {_e(ex)}</p></div>"


def _studio_js() -> str:
    from .dashboard_studio import JS as j
    return j


def build() -> Path:
    from . import autopilot
    chans = _channels()
    start, plan_items = _plan()
    try:
        items = [it for _, it in autopilot.items(7, 14)]       # every week's plan, not only the newest
    except Exception:  # noqa: BLE001
        items = plan_items
    lanes = _lanes()
    metrics = _metrics()
    followers = _followers()
    earnings = _earnings()
    daily = _daily_views()
    from . import todo as _todo
    todos = _todo.items()                                    # done = ticked by you, or seen done by the system
    campaigns = []
    for cid, st, score, data in _db("SELECT id, status, score, data FROM campaigns ORDER BY score DESC"):
        try:
            c = json.loads(data)
        except Exception:  # noqa: BLE001
            continue
        c["status"], c["score"] = st, score
        campaigns.append(c)
    ledger = _db("SELECT stage, COUNT(*), SUM(amount_usd), SUM(amount_inr_received) FROM ledger GROUP BY stage")
    now = datetime.now(IST)
    ctx = {"metrics": metrics, "followers": followers, "earnings": earnings, "items": items, "campaigns": campaigns,
           "daily": daily, "avatars": {ch["id"]: _avatar(ch["id"]) for ch in chans}, "chmap": {c["id"]: c for c in chans},
           "quality": _quality()}

    # ---- overview
    future = [it for it in items if (_when(it) or now) > now]
    waiting = sorted((it for it in future if it.get("status") == "made"), key=lambda x: x["publish_at"])
    next24 = [it for it in future if _when(it) <= now + timedelta(hours=24) and it.get("status") not in ("rejected", "missed")]
    appr24 = sum(1 for it in next24 if it.get("status") == "approved")
    allv = daily.get("*", [0.0] * 28)
    v7, p7 = sum(allv[-7:]), sum(allv[-14:-7])
    yt_f = sum(f.get("youtube", 0) for f in followers.values())
    ig_f = sum(f.get("instagram", 0) for f in followers.values())
    gained = sum(m.get("subs", 0) for m in metrics.values())
    received = sum(r[3] or 0 for r in ledger)
    pending = sum(r[2] or 0 for r in ledger if r[0] not in ("bank_received", "reversed", "written_off"))
    conns = {ch["id"]: _connected(ch["id"]) for ch in chans}
    live_n = sum(1 for c in conns.values() if any(c.values()))
    yt_n = sum(1 for c in conns.values() if c["youtube"])
    ig_n = sum(1 for c in conns.values() if c["instagram"])
    open_camps = [c for c in campaigns if c.get("status") in ("eligible", "review")]
    kpis = [("Waiting for your tap", str(len(waiting)),
             _e(f"first posts {_when(waiting[0]):%a %H:%M}") if waiting else "nothing waiting", "", "warn" if waiting else ""),
            ("Posting in the next 24 h", str(len(next24)), _e(f"{appr24} approved · {len(next24) - appr24} not yet"), "", ""),
            ("Views, last 7 days", _num(v7), _delta(v7, p7) or "all platforms", _spark(allv[-14:]), ""),
            ("Subscribers + followers", _num(yt_f + ig_f),
             _e(f"YouTube {_num(yt_f)} · Instagram {_num(ig_f)}") + (f" · <span class=up>+{_num(gained)}</span>" if gained else ""), "", ""),
            ("Money received", f"₹{received:,.0f}", _e(f"${pending:,.0f} pending"), "", ""),
            ("Channels connected", f"{live_n} / {len(chans)}", _e(f"YouTube {yt_n} · Instagram {ig_n}"), "",
             "bad" if not live_n else "")]
    kpi_html = "".join(f"<div class='kpi {cls}'" + (" onclick=\"location.hash='inbox'\" style='cursor:pointer'"
                                                     if k == "Waiting for your tap" else "")
                       + f"><small>{_e(k)}</small><b>{_e(v)}</b><div class=ksub>{sub}</div>{sp}</div>"
                       for k, v, sub, sp, cls in kpis)
    try:                                                     # 20 Nov: the decisions come first on the page
        from .dashboard_studio import inbox_card
        inbox_html = inbox_card(ctx, poster=_poster)
    except Exception as e:  # noqa: BLE001 - the rest of the page still builds; the error shows in the inbox
        inbox_html = f"<div class='card wide inbox' id=inbox><h2>📥 Needs your OK</h2><p>⚠️ {_e(str(e)[:200])}</p></div>"
    needs = "".join(f"<li class={lv}><span class=dot></span><span>{_e(t)}</span></li>" for lv, t in _needs(items, todos)) \
        or "<li class=good><span class=dot></span>Nothing needs you right now</li>"
    health = "".join(f"<li><span class='lv {lv}'></span>{_e(k)}<span class=v>{_e(v)}</span></li>" for lv, k, v in _health(items))
    qd = ctx["quality"]
    quality_html = "".join(
        f"<li><span class='lv {'good' if (qd.get(ch['id']) or {}).get('score') == 100 else 'warn' if (qd.get(ch['id']) or {}).get('score') is not None else 'info'}'></span>"
        f"<a href='#ch-{ch['id']}' style='color:var(--text)'>{_e(ch['name'])}</a><span class=v>"
        f"{(qd.get(ch['id']) or {}).get('score', '-') if (qd.get(ch['id']) or {}).get('score') is not None else 'no video yet'}</span></li>"
        for ch in chans) or "<li>Run: python cli.py quality</li>"
    gal = _gallery(items, chans, limit=18)
    gallery = "".join(_vcard(v, ctx) for v in gal) or "<p class=muted>No finished videos yet.</p>"
    gal_note = ("Waiting for your tap first, then approved and posted videos." if any(v["status"] != "sample" for v in gal)
                else "Nothing is waiting yet, so these are each channel's newest finished videos.")
    camps = "".join(f"<tr><td><a href='{_e(c.get('url') or '#')}' target=_blank>{_e(str(c.get('name'))[:44])}</a>"
                    f"{' 🔥' if c.get('hot') else ''}</td><td>${_e(c.get('cpm_usd') or '-')}</td>"
                    f"<td class=muted>{_e(c.get('account') or '-')}</td></tr>" for c in open_camps[:7]) \
        or "<tr><td class=muted colspan=3>none open</td></tr>"
    overview = f"""<section id=overview class=page>
<div class=top><div><h1>HookHouse Studio</h1><div class=muted>Updated {now:%d %b %Y, %H:%M} IST · decisions first, then numbers</div></div></div>
{inbox_html}
<div class=kpis6>{kpi_html}</div>
<div class=ovgrid><div class=mainc>
<div class="card c-week"><h2>🗓 Next 7 days</h2>{_timeline(items, chans, ctx)}</div>
<div class="card c-videos"><h2>🎬 Videos</h2><p class=muted style="margin-top:-6px">{_e(gal_note)} They play right here on the PC.</p><div class=gallery>{gallery}</div></div>
<div class="card c-channels"><h2>📺 Channels</h2><div class=chgrid>{''.join(_chcard(ch, ctx) for ch in chans)}</div></div>
</div><div class=side>
<div class="card c-needs"><h2>👉 Needs you</h2><ul class=imp>{needs}</ul><p class=muted><a href='#todo'>Full to-do list →</a></p></div>
<div class="card c-health"><h2>🩺 System health</h2><ul class=hl>{health}</ul></div>
<div class="card c-health"><h2>🎯 Quality per channel</h2><ul class=hl>{quality_html}</ul>
<p class=muted>Same checks for every channel, weekly (python cli.py quality).</p></div>
<div class="card c-camps"><h2>📋 Best campaigns now</h2><div class=tw><table><tr><th>Campaign</th><th>$/1K</th><th>For</th></tr>{camps}</table></div>
<p class=muted><a href='#campaigns'>All campaigns →</a> · pick on the phone with /campaigns</p></div>
</div></div></section>"""

    # ---- money
    per_ch = "".join(
        f"<tr><td>{_e(ch['name'])}</td><td>₹{earnings.get(ch['id'], {}).get('received_inr', 0):,.0f}</td>"
        f"<td>${earnings.get(ch['id'], {}).get('pending_usd', 0):,.0f}</td><td>{_num(metrics.get(ch['id'], {}).get('views', 0))}</td></tr>"
        for ch in chans)
    ledger_html = "".join(f"<tr><td>{_e(st)}</td><td>{n}</td><td>${(u or 0):,.2f}</td><td>₹{(r or 0):,.0f}</td></tr>"
                          for st, n, u, r in ledger) or "<tr><td colspan=4 class=muted>No earnings recorded yet</td></tr>"
    roadmap = [
        ("Campaign money", "Accounts connected + Content Rewards KYC", "Pays per 1,000 views from the first approved clip. Fastest money."),
        ("YouTube fan funding", "500 subs + 3 uploads (90 days) + 3,000 watch hours or 3M Shorts views", "Small, but the first YouTube money."),
        ("YouTube ads", "1,000 subs + 8,000 watch hours (12 months) or 20M Shorts views (90 days), rules from 1 Feb 2027",
         "The real money: US English long videos."),
        ("Facebook Content Monetization", "Invite-only; request it monthly on each Page", "Pays a little for Reels we already cross-post."),
        ("Retainers with creators", "A track record: accounts with real views (about 2-4 months)", "$1,000-2,000 per client per month."),
        ("Affiliate links", "Amazon Associates tags in .env", "Small extra per video from the first views."),
    ]
    try:
        from .pitch import connect as pconnect, pipeline
        pl = pipeline(pconnect())
        pitch_txt = " · ".join(f"{k}: {v}" for k, v in pl["counts"].items()) or "none"
    except Exception:  # noqa: BLE001
        pitch_txt = "none"
    try:
        from . import platforms as _pf
        reg = _pf.registry()
        glyph = {"auto": "<span class='pill good'>✅ auto</span>", "winners": "<span class='pill warn'>📲 winners</span>",
                 "later": "<span class=pill>⏳ later</span>"}
        heads = "".join(f"<th>{_e(pn)}</th>" for pn in reg)
        mrows = "".join(
            f"<tr><td class=chcol><img src='{ctx['avatars'].get(ch['id'], '')}' alt=''>{_e(ch['name'])}</td>" +
            "".join(f"<td>{glyph.get(spec.get('post'), '') if _pf.allowed(ch, pn) else '<span class=muted>-</span>'}</td>"
                    for pn, spec in reg.items()) + "</tr>" for ch in chans)
        matrix = (f"<div class='card full'><h2>🌐 Platforms per channel</h2><div class=tw><table><tr><th>Channel</th>{heads}</tr>"
                  f"{mrows}</table></div><ul class=imp style='margin-top:10px'>"
                  "<li class=good><span class=dot></span><span><b>✅ auto</b>: the system posts it by itself after your "
                  "approval. No work for you.</span></li>"
                  "<li class=warn><span class=dot></span><span><b>📲 winners</b>: the platform has no free posting API, so "
                  "you post by hand, but only our best videos: every evening the bot sends the top 3 of the last 2 days "
                  "with a ready caption (about a minute each). Paid campaign clips come right after posting.</span></li>"
                  "<li><span class=dot></span><span><b>⏳ later</b>: waits for something first (an audience, an invite, or "
                  "a product you upload once, like the Bloop songs and book).</span></li>"
                  "<li class=bad><span class=dot></span><span><b>-</b>: not allowed: Bloop is for children, so 13+ apps "
                  "are off by law (COPPA); campaign clips only go where the campaign's licence allows.</span></li></ul>"
                  "<p class=muted>Full detail: docs/money_map.md</p></div>")
    except Exception:  # noqa: BLE001
        matrix = ""
    prods = sorted((ROOT / "data" / "products").glob("*.pdf")) if (ROOT / "data" / "products").exists() else []
    products_html = ("<div class=card><h2>📚 Products</h2><ul class=imp>" + "".join(
        f"<li class=good><span class=dot></span><span>{_e(pp.stem.replace('_', ' '))}<br><span class=muted>"
        f"{pp.stat().st_size / 1e6:.1f} MB · listing: {_e(pp.stem)}_listing.md</span></span></li>" for pp in prods) +
        "</ul><p class=muted>Publish on Amazon KDP + Gumroad / Teachers Pay Teachers (setup guide, phase 8).</p></div>") \
        if prods else ""
    try:
        from . import outreach as _out
        out_html = f"<div class=card><h2>📨 Creator outreach</h2><p>{_e(_out.summary()).replace(chr(10), '<br>')}</p></div>"
    except Exception:  # noqa: BLE001
        out_html = ""
    money = f"""<section id=money class=page><div class=top><h1>💰 Money</h1></div>
<div class=kpis6><div class=kpi><small>Received</small><b>₹{received:,.0f}</b></div><div class=kpi><small>Pending</small><b>${pending:,.0f}</b></div>
<div class=kpi><small>Open campaigns</small><b>{len(open_camps)}</b></div><div class=kpi><small>Retainer pitches</small><b style="font-size:15px">{_e(pitch_txt)}</b></div></div>
{_earning_card()}
<div class=cgrid><div class=card><h2>Per channel</h2><div class=tw><table><tr><th>Channel</th><th>Received</th><th>Pending</th><th>Views</th></tr>{per_ch}</table></div></div>
<div class=card><h2>Payment stages</h2><table><tr><th>Stage</th><th>Entries</th><th>USD</th><th>INR received</th></tr>{ledger_html}</table></div>
<div class=card><h2>How the money comes (fastest first)</h2><div class=tw><table><tr><th>Source</th><th>What it needs</th><th>Why it matters</th></tr>
{''.join(f"<tr><td><b>{_e(a)}</b></td><td>{_e(b)}</td><td>{_e(c)}</td></tr>" for a, b, c in roadmap)}</table></div></div>
{matrix}{products_html}{out_html}</div></section>"""

    # ---- campaigns
    def crow(c):
        why = "; ".join(str(x) for x in (c.get("fit_reasons") or []) if x)[:150] or "fits our rules and tools"
        drain = ""
        if c.get("drain_at"):
            try:
                drain = datetime.fromisoformat(str(c["drain_at"]).replace("Z", "+00:00")).astimezone(IST).strftime("%d %b")
            except ValueError:
                drain = ""
        budget = f"{c['budget_left_pct']:.0f}% left" if c.get("budget_left_pct") is not None else "-"
        return (f"<tr><td><a href='{_e(c.get('url') or '#')}' target=_blank>{_e(str(c.get('name'))[:60])}</a>"
                f"{' 🔥 ' + _e(', '.join(c['hot'][:2])) if c.get('hot') else ''}<br><span class=muted>{_e(why)}</span></td>"
                f"<td>{_e(c.get('fit') or '-')}</td><td>${_e(c.get('cpm_usd') or '-')}</td>"
                f"<td>{_e(budget)}{(' · runs out ~' + _e(drain)) if drain else ''}</td>"
                f"<td>{_e(c.get('account') or '-')}</td><td><span class=pill>{_e(c.get('status'))}</span></td></tr>")
    shown = [c for c in campaigns if c.get("status") in ("eligible", "review", "picked", "joined")]
    reports = sorted((ROOT / "data" / "campaigns").glob("daily_*.md"))
    camp_page = f"""<section id=campaigns class=page><div class=top><h1>📋 Campaigns</h1>
<div class=muted>Daily finder at 09:00 · latest report: data/campaigns/{_e(reports[-1].name if reports else 'none')} · pick on your phone with /campaigns</div></div>
<div class=card><div class=tw><table><tr><th>Campaign</th><th>Fit</th><th>$/1K</th><th>Budget</th><th>Channel</th><th>Status</th></tr>
{''.join(crow(c) for c in shown[:60]) or '<tr><td colspan=6 class=muted>No campaigns yet</td></tr>'}</table></div></div></section>"""

    # ---- plan + jobs
    upcoming = sorted((it for it in items if it.get("status") != "posted" and (_when(it) or now) >= now - timedelta(hours=6)),
                      key=lambda x: x.get("publish_at", ""))[:60]
    up_html = "".join(f"<tr><td class=when>{_when(it):%a %d %b, %H:%M}</td><td>{_e(it.get('channel_name'))}</td>"
                      f"<td>{_e(it.get('kind'))}</td><td class=topic>{_e(it.get('topic') or 'picked when made')}</td>"
                      f"<td><span class='pill {QCLS.get(it.get('status'), '')}'>{_e(QLABEL.get(it.get('status'), it.get('status')))}</span>"
                      f"{('<br><span class=muted>' + _e(str(it.get('error'))[:120]) + '</span>') if it.get('error') else ''}</td></tr>"
                      for it in upcoming if _when(it)) or "<tr><td colspan=5 class=muted>No plan yet: python cli.py week plan</td></tr>"
    lane_html = "".join(f"<tr><td>{'<span class=\"pill good\">running</span>' if ln['running'] else '<span class=pill>done</span>'}</td>"
                        f"<td>{_e(ln['lane'])}</td><td class=muted>{_e(ln['last'])}</td><td>{ln['age_min']:.0f} min ago</td></tr>"
                        for ln in lanes) or "<tr><td colspan=4 class=muted>No render jobs</td></tr>"
    plan_page = f"""<section id=plan class=page><div class=top><h1>🗓 Plan & jobs</h1><div class=muted>Newest plan: week of {_e(start or '-')}</div></div>
<div class=card><h2>Next 7 days</h2>{_timeline(items, chans, ctx)}</div>
<div class=card><h2>Upcoming videos</h2><div class=tw><table class=stack><tr><th>Posts at (IST)</th><th>Channel</th><th>Kind</th><th>Topic</th><th>Status</th></tr>{up_html}</table></div></div>
<div class=card><h2>Render jobs</h2><div class=tw><table><tr><th></th><th>Job</th><th>Last step</th><th>When</th></tr>{lane_html}</table></div></div></section>"""

    # ---- to-do by platform, with checkboxes
    tdone = sum(1 for t in todos if t["done"])
    groups = []
    for plat, rows in _todo.grouped().items():
        n_done = sum(1 for r in rows if r["done"])
        lis = "".join(
            f"<li class='td{' done' if r['done'] else ''}'><label><input type=checkbox data-id='{_e(r.get('id'))}'"
            f"{' checked' if r['done'] else ''}{' disabled' if not r['manual'] or r['done'] else ''}>"
            f"<span><b>{_e(r['task'])}</b><br><span class=muted>{_e(r.get('why', ''))}"
            f"{(' · ' + _e(r['detail'])) if r.get('detail') else ''}{' · ticks itself' if not r['manual'] else ''}"
            f"</span></span></label></li>" for r in rows)
        groups.append(f"<div class=card><h2>{_todo.ICON.get(plat, '•')} {_e(plat)} <span class=muted>{n_done}/{len(rows)}"
                      f"</span></h2><ul class=tdl>{lis}</ul></div>")
    todo_html = (f"<div class='card full'><h2>✅ Setup progress: {tdone} of {len(todos)} done</h2>"
                 f"<div class=track><div class=fill style='width:{100 * tdone / max(1, len(todos)):.0f}%'></div></div>"
                 "<p class=muted>Tick a manual task here (saved in this browser) or in Telegram with /todo (saved for "
                 "the whole system). Tasks marked 'ticks itself' turn green when the system sees them done.</p></div>"
                 + "".join(groups))

    # ---- to-do + learnings
    audit = _table_rows(ROOT / "docs" / "research_audit_2026-11-12.md", 10)
    changes = _table_rows(ROOT / "docs" / "implementation_plan_v3.md", 8)
    notes = sorted((ROOT / "research_notes").rglob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)[:8]
    todo_page = f"""<section id=todo class=page><div class=top><h1>✅ To-do & learnings</h1><div class=muted>Step-by-step guide: docs/owner_setup_guide.md</div></div>
<div class=cgrid>{todo_html}
<div class=card><h2>Latest learnings</h2><ul class=list>{''.join(f"<li><b>{_e(r[1][:90])}</b><br><span class=muted>fix: {_e(r[-1][:160])}</span></li>" for r in reversed(audit)) or '<li class=muted>none</li>'}</ul></div>
<div class=card><h2>System changes</h2><ul class=list>{''.join(f"<li><b>{_e(r[0][:110])}</b><br><span class=muted>{_e(re.sub(r'[✅*]', '', r[1])[:220])}</span></li>" for r in reversed(changes))}</ul>
<h2 style="margin-top:16px">Newest research notes</h2><ul class=list>{''.join(f"<li>{_e(p.stem.replace('_', ' '))} <span class=muted>{datetime.fromtimestamp(p.stat().st_mtime):%d %b}</span></li>" for p in notes)}</ul></div></div></section>"""

    # ---- menu
    def nav_ch(ch):
        live = any(conns[ch["id"]].values())
        return (f"<a href='#ch-{ch['id']}' style='--acc:{(ch.get('style') or {}).get('highlight_color') or '#7c8cff'}'>"
                f"<img src='{ctx['avatars'].get(ch['id'], '')}' alt=''>{_e(ch['name'])}<span class='st{' live' if live else ''}'></span></a>")
    nav = (f"<nav><div class=brand>Hook<span>House</span></div>"
           "<a href='#overview'><span class=ico>🏠</span>Overview</a>"
           "<a href='#learn'><span class=ico>📈</span>Trends & learnings</a><a href='#money'><span class=ico>💰</span>Money</a>"
           "<a href='#platforms'><span class=ico>🌐</span>Platforms</a><a href='#products'><span class=ico>🛍️</span>Products</a>"
           "<a href='#campaigns'><span class=ico>📋</span>Campaigns</a><a href='#plan'><span class=ico>🗓</span>Plan & jobs</a>"
           f"<a href='#todo'><span class=ico>✅</span>To-do</a><div class=grp>Channels</div>{''.join(nav_ch(c) for c in chans)}</nav>")
    try:
        plat_page = _platform_page(chans, ctx)
    except Exception as e:  # noqa: BLE001 - the rest of the pad must still build
        plat_page = f"<section id=platforms class=page><h1>🌐 Platforms</h1><p class=muted>Not available: {_e(e)}</p></section>"
    try:
        prod_page = _products_page()
    except Exception as e:  # noqa: BLE001
        prod_page = f"<section id=products class=page><h1>🛍️ Products</h1><p class=muted>Not available: {_e(e)}</p></section>"
    try:
        learn_page = _learn_page(chans, _metrics())
    except Exception as e:  # noqa: BLE001
        learn_page = (f"<section id=learn class=page><h1>📈 Trends & learnings</h1><p class=muted>Not available: "
                      f"{_e(e)}</p></section>")
    pages = (overview + "".join(_channel_page(ch, ctx) for ch in chans) + money + learn_page + plat_page + prod_page
             + camp_page + plan_page + todo_page)
    page = (f"<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
            f"<title>HookHouse monitoring pad</title><style>{CSS}{_studio_css()}</style></head><body><div class=layout>{nav}<main>{pages}"
            f"<p class=muted style='margin-top:30px'>Rebuild: python cli.py dashboard · the Telegram bot sends a fresh copy every morning (/dashboard any time)</p>"
            f"</main></div><script>{JS}{_studio_js()}</script></body></html>")
    OUT.write_text(page, encoding="utf-8")
    return OUT
