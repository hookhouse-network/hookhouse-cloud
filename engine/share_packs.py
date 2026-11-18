"""Winners go everywhere: platforms we can't post to by ourselves (Snapchat Spotlight, X, and Threads / Pinterest
until each is connected: platforms.yaml needs:) get our proven winners only. Every evening the bot sends the top videos of the last 2 days (by real views) with a ready
caption per platform; the owner saves the video and posts it from the phone in under a minute, then taps "Posted".
Rules from config/platforms.yaml (kids never, campaign clips only where the brief allows)."""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from .config import ROOT

STATE = ROOT / "data" / "state" / "share_packs.json"
LIMITS = {"snapchat": 160, "threads": 480, "pinterest": 480, "x": 270}
MAX_S = {"snapchat": 60, "threads": 300, "pinterest": 900, "x": 140}   # longest video each accepts from the phone (s)
LABEL = {"snapchat": "Snapchat Spotlight", "threads": "Threads", "pinterest": "Pinterest", "x": "X"}


def _load() -> dict:
    return json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}


def _save(s: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(s, indent=1), encoding="utf-8")


def winners(hours: float = 48, top: int = 3) -> list[tuple[str, float]]:
    """(item_id, views) of the best videos posted in the last `hours`, by their latest snapshot."""
    db = ROOT / "data" / "analytics.db"
    if not db.exists():
        return []
    try:
        with sqlite3.connect(db) as c:
            rows = c.execute(
                "SELECT m.item_id, SUM(m.views) FROM video_metrics m JOIN (SELECT item_id, platform, MAX(hours_after) h "
                "FROM video_metrics GROUP BY item_id, platform) last ON m.item_id = last.item_id AND "
                "m.platform = last.platform AND m.hours_after = last.h WHERE m.posted_at > ? GROUP BY m.item_id "
                "ORDER BY SUM(m.views) DESC LIMIT ?", (time.time() - hours * 3600, top * 3)).fetchall()
    except sqlite3.Error:
        return []
    return [(str(i), float(v or 0)) for i, v in rows if v]


def captions(meta: dict, it: dict, links: dict) -> dict[str, str]:
    """A caption per platform: Snapchat short with up to 3 hashtags, Threads conversational with the YouTube link,
    Pinterest keyword-first with the link."""
    title = str(meta.get("title") or it.get("topic") or "").strip()
    desc = str(meta.get("description") or "").split("\n")[0].strip()
    tags = [t if t.startswith("#") else "#" + t for t in (meta.get("hashtags") or [])][:3]
    yt = links.get("youtube", "")
    if meta.get("clip"):                         # campaign clip: keep its required caption (credit + campaign tags)
        cap = str(meta.get("description") or title).strip()
        return {k: cap[:LIMITS[k]] for k in LIMITS}
    out = {
        "x": f"{title} {' '.join(tags)}".strip(),
        "snapchat": f"{title} {' '.join(tags)}".strip(),
        "threads": (f"{title}\n\n{desc}" + (f"\n\nFull video: {yt}" if yt else "")).strip(),
        "pinterest": (f"{title}. {desc}" + (f" Watch: {yt}" if yt else "")).strip(),
    }
    return {k: v[:LIMITS[k]] for k, v in out.items()}


def build(item: dict, views: float) -> dict | None:
    """Everything the bot needs for one winner, or None if it may go nowhere else."""
    from . import platforms
    from .config import channel
    from .publish import item_meta
    out = Path(item.get("out_dir") or "")
    if not item.get("out_dir") or not out.exists():
        return None
    meta = item_meta(item)
    ch = channel(item["channel"])
    reel = out / "reel.mp4"
    clip_reel = out / str(item.get("file") or "").replace(".mp4", "_reel.mp4")
    video = reel if reel.exists() else clip_reel if clip_reel.exists() else out / (item.get("file") or "video.mp4")
    if not video.exists():
        return None
    try:
        from .media import ffmpeg
        dur = ffmpeg.duration(video)
    except Exception:  # noqa: BLE001
        dur = 0.0
    plats = [p for p in platforms.by_mode(ch, "winners", meta) if not dur or dur <= MAX_S.get(p, 60)]
    if not plats:
        return None
    links = {"youtube": f"https://youtu.be/{item['youtube_id']}"} if item.get("youtube_id") else {}
    caps = captions(meta, item, links)
    return {"item": item["id"], "channel": ch.get("name", item["channel"]), "video": video, "views": views,
            "platforms": plats, "captions": {p: caps[p] for p in plats}}


def due_packs(top: int = 3) -> list[dict]:
    """Today's winners not sent before."""
    from . import autopilot
    sent = _load().get("sent", {})
    by_id = {it["id"]: it for _, it in autopilot.items(3, 0)}
    packs = []
    for iid, views in winners():
        if iid in sent or iid not in by_id:
            continue
        p = build(by_id[iid], views)
        if p:
            packs.append(p)
        if len(packs) >= top:
            break
    return packs


def send(log=print) -> int:
    """Evening: send the winners' packs to the owner (one message each: video + captions + Posted buttons)."""
    from . import telegram_bot as tb
    packs = due_packs()
    s = _load()
    for p in packs:
        lines = [f"🏆 Winner: {p['channel']} · {p['views']:,.0f} views. Post it here too (save the video, then "
                 "upload it from the app):"]
        for plat in p["platforms"]:
            lines.append(f"\n{LABEL.get(plat, plat)}:\n{p['captions'][plat]}")
        kb = {"inline_keyboard": [[{"text": f"✅ {LABEL.get(pl, pl).split()[0]}", "callback_data": f"sp:{p['item'][:40]}:{pl[:5]}"}
                                   for pl in p["platforms"]]]}
        text = "\n".join(lines)
        try:
            with p["video"].open("rb") as fh:
                tb.api("sendVideo", files={"video": (p["video"].name, fh, "video/mp4")}, chat_id=tb._chat(),
                       caption=text[:1024], reply_markup=kb, supports_streaming=True, http_timeout=600,
                       disable_notification=tb.quiet_hours())
            if len(text) > 1024:
                tb.send(text)
        except Exception as e:  # noqa: BLE001
            log(f"share pack {p['item']}: {e}")
            continue
        s.setdefault("sent", {})[p["item"]] = time.time()
    _save(s)
    return len(packs)


def send_now(item: dict, log=print) -> int:
    """A campaign clip just went live: the platforms its campaign pays for that we post by hand (X, Snapchat) come
    to the phone right away, because campaigns only pay for links submitted within about 30 minutes."""
    from . import telegram_bot as tb
    p = build(item, 0)
    if not p:
        return 0
    lines = [f"⏱ Campaign clip live ({p['channel']}). Post it on {', '.join(LABEL.get(x, x) for x in p['platforms'])} "
             "now (the campaign pays for views there), then submit every link on the campaign page within 30 minutes."]
    for plat in p["platforms"]:
        lines.append(f"\n{LABEL.get(plat, plat)} caption:\n{p['captions'][plat]}")
    kb = {"inline_keyboard": [[{"text": f"✅ {LABEL.get(pl, pl).split()[0]}", "callback_data": f"sp:{p['item'][:40]}:{pl[:5]}"}
                               for pl in p["platforms"]]]}
    text = "\n".join(lines)
    try:
        with p["video"].open("rb") as fh:
            tb.api("sendVideo", files={"video": (p["video"].name, fh, "video/mp4")}, chat_id=tb._chat(),
                   caption=text[:1024], reply_markup=kb, supports_streaming=True, http_timeout=600)
    except Exception as e:  # noqa: BLE001
        log(f"share now {p['item']}: {e}")
        return 0
    s = _load()
    s.setdefault("sent", {})[p["item"]] = time.time()
    _save(s)
    return 1


def mark_posted(item_prefix: str, plat: str) -> str:
    s = _load()
    key = next((k for k in s.get("sent", {}) if k.startswith(item_prefix)), item_prefix)
    s.setdefault("posted", {}).setdefault(key, [])
    full = next((p for p in LABEL if p.startswith(plat)), plat)
    if full not in s["posted"][key]:
        s["posted"][key].append(full)
    _save(s)
    return f"Noted: posted on {LABEL.get(full, full)}. 👍"
