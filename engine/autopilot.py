"""Autopilot: the whole daily loop, driven by the owner's approvals on the phone (owner, 12 Nov).

Every few minutes (inside `python cli.py bot run`):
1. Plan:    keeps a plan for the coming days (next week planned on Friday).
2. Make:    makes each video MAKE_AHEAD_H before its posting slot (one at a time; render lock for the cleanup).
3. Ask:     sends the finished video to Telegram ASK_AHEAD_H before its slot: preview, title, thumbnail, checks,
            buttons Approve / Change / Reject. "Change" takes the owner's words, the video is remade with them and
            sent again. Reminder REMIND_H before the slot.
4. Post:    only APPROVED videos. YouTube is uploaded right after approval with the slot time (YouTube publishes
            it on time even if this PC is off); Instagram and Facebook Reels go out at the slot time. Safety checks
            run again just before posting (file, fact-check, never-topics, kids rules, no double posting, limits).
5. Missed:  a video not approved by its slot is never posted; the owner can still approve it and it moves to
            the channel's next free peak slot.
6. Daily:   09:00 campaigns + stats + morning report; 03:30 disk cleanup.
Nothing is ever posted without the owner's tap.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import threading
import time
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from . import weekly
from .config import ROOT

STATE = ROOT / "data" / "state" / "autopilot.json"
PREVIEWS = ROOT / "data" / "telegram" / "previews"
LOCK = ROOT / "data" / "state" / "render.lock"
HEARTBEAT = ROOT / "data" / "state" / "heartbeat.txt"
MAKE_AHEAD_H = 40         # start making this long before the slot
MAKE_AHEAD_LONG_H = 96    # long videos (1.5-4.5 h each on this PC): start days ahead, in the PC's free time
ASK_AHEAD_H = 20          # ask for approval this long before the slot (or as soon as it's made, if later)
REMIND_H = 3
LATE_POST_MAX_H = 2       # IG/FB: if the PC was off at slot time, still post up to 2 h late; later -> re-slot
TG_MAX = 48 * 1024 * 1024
_STATE_LOCK = threading.Lock()
_MAKING = threading.Lock()
_ASKING = threading.Lock()


# ---------------- small helpers ----------------
def _load() -> dict:
    return json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}


def _save(s: dict) -> None:
    from .core.atomic import write_json                  # 20 Nov: crash-safe (tokens, decisions, daily jobs)
    write_json(STATE, s)


def _update_state(fn) -> dict:
    with _STATE_LOCK:
        s = _load()
        fn(s)
        _save(s)
        return s


def token(start: str, item_id: str, version: str = "") -> str:
    """Short id for Telegram buttons (callback data is limited to 64 bytes). The version (made_at) makes buttons on
    an old message stop working once a new version of the video exists."""
    t = hashlib.sha1(f"{start}|{item_id}|{version}".encode()).hexdigest()[:10]
    _update_state(lambda s: s.setdefault("tokens", {}).__setitem__(t, [start, item_id, version]))
    return t


def resolve(tok: str) -> tuple[str, str, str] | None:
    v = _load().get("tokens", {}).get(tok)
    if not v:
        return None
    return (v[0], v[1], v[2] if len(v) > 2 else "")


def _now() -> datetime:
    return datetime.now(weekly._zone())


def _when(it: dict) -> datetime:
    return datetime.fromisoformat(it["publish_at"])


def free_limit_wait(e: Exception) -> float | None:
    """17 Nov: three "free pictures used up" / "no AI model free" errors used up a video's 3 tries and the slot was
    skipped for good. These are daily limits, not faults: the video waits for the reset instead."""
    from . import storyboard
    if isinstance(e, storyboard.NoPictures):
        return max(storyboard.reset_at(), time.time() + 1800)
    if type(e).__name__ == "BrainError" and re.search(r"No AI model available|All models failed", str(e)):
        return time.time() + 3600
    return None


def update_item(start: str, item_id: str, **fields) -> dict:
    """Change one plan item safely (fresh load under the planner's lock, so no decision is overwritten)."""
    with weekly._LOCK:
        plan = weekly.load_plan(start)
        for it in plan["items"]:
            if it["id"] == item_id:
                it.update(fields)
                weekly.save_plan(plan)
                return it
    raise KeyError(item_id)


def items(days_back: int = 3, days_ahead: int = 9) -> list[tuple[str, dict]]:
    """(week start, item) for every item with a slot in the window, across all plans."""
    now, out = _now(), []
    for p in sorted(weekly.WEEKS_DIR.glob("*/plan.json")) if weekly.WEEKS_DIR.exists() else []:
        try:
            plan = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:              # 20 Nov: a broken plan hid a whole week without a word
            from .core import ledger
            ledger.event("plan.unreadable", data={"path": str(p), "error": f"{type(e).__name__}: {e}"})
            try:
                from . import heal
                heal.report("plan", f"weekly plan unreadable: {p.parent.name}: {type(e).__name__}")
            except Exception as e2:  # noqa: BLE001 - the other weeks still load
                print(f"plan report failed: {e2}")
            continue
        for it in plan.get("items") or []:
            try:
                w = _when(it)
            except (KeyError, ValueError):
                continue
            if now - timedelta(days=days_back) <= w <= now + timedelta(days=days_ahead):
                out.append((plan["start"], it))
    return sorted(out, key=lambda x: x[1]["publish_at"])


def _channel(cid: str) -> dict:
    from .config import channel
    return channel(cid)


def next_free_slot(start: str, it: dict) -> str:
    """The channel's next peak slot from now that no other item of the channel uses."""
    ch = _channel(it["channel"])
    taken = {x["publish_at"] for _, x in items(0, 30) if x["channel"] == it["channel"] and x["id"] != it["id"]}
    now = _now() + timedelta(minutes=45)
    if it.get("kind") != "long":
        # owner, 16 Nov ("I approved many things but it does not post"): every daily slot was held by a planned
        # Short that isn't even made yet, so a late approval waited a WEEK. A finished, approved Short goes out at
        # the channel's next spare peak time within 48 h instead (2 h away from the channel's other posts).
        busy = [datetime.fromisoformat(t) for t in taken if t]
        spare = []
        for d in range(0, 3):
            day = (now + timedelta(days=d)).date()
            for h, m in weekly._times(ch):                 # peak times, in priority order: take the soonest
                when = datetime(day.year, day.month, day.day, h, m, tzinfo=weekly._zone())
                if now < when < now + timedelta(hours=48) and \
                        all(abs((when - b).total_seconds()) >= 2 * 3600 for b in busy):
                    spare.append(when)
        if spare:
            return min(spare).isoformat()
    for d in range(0, 14):
        day = (now + timedelta(days=d)).date()
        for when, kind in weekly.slots_for(ch, day, days=1):
            if when > now and when.isoformat() not in taken and (kind == "long") == (it.get("kind") == "long"):
                return when.isoformat()
    return (now + timedelta(hours=2)).isoformat()


# ---------------- safety before posting ----------------
def _with_local_media(start: str, it: dict) -> dict:
    """The video folder on this machine: in the cloud each run starts empty, so download it from the video store."""
    out = Path(it.get("out_dir") or "")
    if (out / (it.get("file") or "video.mp4")).exists():
        return it
    try:
        from .cloud import media
        from .cloud.store import Store
        folder = media.ensure_local(Store(), it)
    except Exception:  # noqa: BLE001 - no store (PC without cloud): preflight reports the missing file
        return it
    if folder and str(folder) != it.get("out_dir"):
        it = update_item(start, it["id"], out_dir=str(folder))
    return it


def preflight(it: dict) -> list[str]:
    """Problems that block posting ([] = safe)."""
    probs = []
    out = Path(it.get("out_dir") or "")
    video = out / (it.get("file") or "video.mp4")
    if not video.exists():
        return ["the video file is missing"]
    meta = {}
    if (out / "upload.json").exists():
        meta = json.loads((out / "upload.json").read_text(encoding="utf-8"))
    if not meta and (out / "clips.json").exists():
        from .publish import item_meta
        meta = item_meta(it)
        if not (meta.get("permission") or {}).get("basis"):
            probs.append("clip has no permission record (campaign, public domain or written permission)")
        if meta.get("campaign"):                 # ONE campaign gate (owner, 17 Nov): every brief condition, fresh
            from .campaign_gate import gate_item
            gp = gate_item(it, brain_fn=lambda: default_brain()[0])
            if gp:
                probs.append("campaign conditions not met: " + "; ".join(gp)[:300])
    fc = meta.get("fact_check") or {}
    if fc.get("checked") and not fc.get("ok"):
        probs.append("fact-check failed")
    if meta.get("policy_flags"):
        probs.append("touches a never-topic: " + ", ".join(meta["policy_flags"]))
    try:
        from .media import ffmpeg
        dur = ffmpeg.duration(video)
        if it.get("kind") != "long" and dur > 180:
            probs.append(f"Short is {dur:.0f} s (YouTube Shorts max 180 s)")
    except Exception:  # noqa: BLE001
        pass
    from .publish import already_posted
    done = already_posted(it, ignore_youtube_id=it.get("youtube_id"))
    if done:
        probs.append(f"already posted once on {', '.join(done)} (no double posting)")
    return probs


def _connected(cid: str) -> dict:
    s = ROOT / "data" / "secrets"
    return {"youtube": (s / f"youtube_{cid}.json").exists(), "meta": (s / f"meta_{cid}.json").exists()}


# ---------------- Telegram approval messages ----------------
def preview_file(it: dict) -> Path | None:
    """The video itself if small enough for Telegram, else a lighter copy for watching on the phone."""
    from .media import ffmpeg
    video = Path(it["out_dir"]) / (it.get("file") or "video.mp4")
    if not video.exists():
        return None
    if video.stat().st_size <= TG_MAX:
        return video
    PREVIEWS.mkdir(parents=True, exist_ok=True)
    out = PREVIEWS / f"{hashlib.sha1(str(video).encode()).hexdigest()[:10]}.mp4"
    if out.exists():
        return out
    dur = max(1.0, ffmpeg.duration(video))
    kbps = max(150, int(TG_MAX * 8 / 1024 / dur * 0.9) - 64)
    vertical = it.get("kind") != "long"
    subprocess.run([ffmpeg.ffmpeg_bin(), "-y", "-v", "error", "-i", str(video), "-vf",
                    "scale=-2:854" if vertical else "scale=-2:360", "-c:v", "libx264", "-preset", "veryfast",
                    "-b:v", f"{kbps}k", "-maxrate", f"{int(kbps * 1.3)}k", "-bufsize", f"{kbps * 2}k",
                    "-c:a", "aac", "-b:a", "64k", str(out)], check=True, timeout=3600)
    return out


def approval_text(it: dict, reminder: bool = False) -> str:
    m = weekly._item_media(it)
    when = _when(it)
    us = when.astimezone(ZoneInfo("America/New_York"))
    us_txt = f" (US {us:%I:%M %p} ET)" if _channel(it["channel"]).get("market") == "US" else ""
    plats = ["YouTube " + ("long video" if it.get("kind") == "long" else "Short")]
    meta_p = Path(it["out_dir"]) / "upload.json"
    kids = json.loads(meta_p.read_text(encoding="utf-8")).get("made_for_kids") if meta_p.exists() else False
    if m.get("reel") and not kids:
        plats += ["Instagram Reel", "Facebook Reel"]
    checks = []
    fact = m.get("fact")
    checks.append("facts ✔" if not fact or fact.get("ok") else "facts ✘")
    checks.append("never-topics ✔" if not m.get("policy") else "never-topic ✘")
    why = weekly.attention_reasons(it, m)
    out = Path(it["out_dir"])
    if (out / "upload.json").exists():
        from .dashboard import video_checks
        v = video_checks(_channel(it["channel"]), out)
        length = f"{v['dur']:.0f} s" if it.get("kind") != "long" else f"{v['dur'] / 60:.1f} min"
        checks.append(f"length {length}")
        if v.get("words"):
            checks.append(f"pace {v['wpm']:.0f} wpm {'✔' if v['pace_ok'] else '✘'}")
            if not v["words_ok"]:
                why.append(f"{v['words']} words, research range {v['words_range'][0]}-{v['words_range'][1]}")
        if not v["title_ok"]:
            why.append(f"title is {len(v['title'])} characters (best 20-40)")
        if v.get("target_wpm") and v.get("words") and not v["pace_ok"]:
            why.append(f"pace off the research target ({v['target_wpm']} wpm)")
    same = title_pattern_repeats(it, m.get("title") or "")
    if same:
        why.append(f"title starts like {same} recent titles on this channel (YouTube judges whole channels for "
                   "templated, repetitive content): try another title (\"title 2\")")
    head = "⏰ Reminder: still waiting for you\n" if reminder else "🎬 New video for your approval\n"
    titles = "\n".join(f"  {i}. {t}" for i, t in enumerate((m.get("titles") or [])[:3], 1))
    hook = _opening_line(it)
    if hook:
        titles = (titles + "\n" if titles else "") + f"Opening line (the hook): “{hook[:160]}”"
    return (head + f"{it['channel_name']} · {when:%a %d %b, %H:%M} IST{us_txt}\n"
            f"Posts to: {', '.join(plats)}\n\n"
            f"Title: {m.get('title') or it.get('topic')}\n" + (f"Other titles:\n{titles}\n" if titles else "") +
            f"Checks: {' · '.join(checks)}" + (f"\n⚠️ Look closely: {'; '.join(why)}" if why else "") +
            "\n\nApprove to post it at that time, Change to tell me what to fix, or Reject.")


def _opening_line(it: dict) -> str:
    """The first spoken line (story script) or the clip's hook: what viewers hear in the first seconds."""
    out = Path(it.get("out_dir") or "")
    try:
        s = json.loads((out / "script.json").read_text(encoding="utf-8"))
        beats = s.get("beats") or []
        return str(s.get("hook_text") or (beats[0].get("narration") if beats else "") or "").strip()
    except (OSError, ValueError):
        pass
    try:
        for c in json.loads((out / "clips.json").read_text(encoding="utf-8")):
            if c.get("file") == it.get("file"):
                return str((c.get("hook_options") or [""])[0] or "").strip()
    except (OSError, ValueError):
        pass
    return ""


def title_pattern_repeats(it: dict, title: str, last: int = 6) -> int:
    """How many of the channel's last few titles open with the same 3 words (0 or 1 = fine)."""
    key = " ".join(re.sub(r"[^\w\s]", "", title.lower()).split()[:3])
    if len(key.split()) < 3:
        return 0
    titles = []
    for _, x in items(14, 0):
        if x["channel"] == it["channel"] and x["id"] != it["id"] and x.get("out_dir") and \
                x["status"] in ("made", "approved", "posted"):
            up = Path(x["out_dir"]) / "upload.json"
            try:
                titles.append(json.loads(up.read_text(encoding="utf-8")).get("title") or "")
            except (OSError, ValueError):
                continue
    hits = sum(1 for t in titles[-last:] if " ".join(re.sub(r"[^\w\s]", "", t.lower()).split()[:3]) == key)
    return hits if hits >= 2 else 0


def ask(start: str, it: dict, reminder: bool = False, mark: bool = True) -> None:
    from . import telegram_bot as tb
    if _campaign_held(start, it, log=print):          # every path to the owner goes through the campaign gate
        return
    reach = _reach_check(start, it)                    # ... and the reach gate (owner 17 Nov: algorithm-friendly only)
    if reach and reach.get("block"):
        return
    tok = token(start, it["id"], str(it.get("made_at") or ""))
    kb = {"inline_keyboard": [[{"text": "✅ Approve & post", "callback_data": f"ap:{tok}"},
                               {"text": "✏️ Change", "callback_data": f"ch:{tok}"},
                               {"text": "❌ Reject", "callback_data": f"rj:{tok}"}]]}
    thumb = next(iter(sorted(Path(it["out_dir"]).glob("thumbnail_v2*.jpg"))), None)
    if thumb and it.get("kind") == "long" and not reminder:
        try:
            with thumb.open("rb") as fh:
                tb.api("sendPhoto", files={"photo": (thumb.name, fh, "image/jpeg")}, chat_id=tb._chat(),
                       caption="Thumbnail (YouTube tests 3 versions)", http_timeout=120)
        except Exception:  # noqa: BLE001 - the video and buttons matter more
            pass
    text = approval_text(it, reminder)
    if reach and not reminder:
        from .reach_gate import summary as reach_summary
        text = text + "\n" + reach_summary(reach)
    prev, sent = None, False
    if not reminder:
        try:
            prev = preview_file(it)
        except Exception:  # noqa: BLE001 - a broken preview must not block the question
            prev = None
    msg = None
    if prev:
        try:
            with prev.open("rb") as fh:
                msg = tb.api("sendVideo", files={"video": (prev.name, fh, "video/mp4")}, chat_id=tb._chat(),
                             caption=text[:1024], reply_markup=kb, supports_streaming=True, http_timeout=600,
                             disable_notification=tb.quiet_hours())
            sent = True
            if len(text) > 1024:
                tb.send(text)
        except Exception:  # noqa: BLE001 - upload too slow or refused: send the question as text
            sent = False
    if not sent:
        note = "" if reminder else "\n\n(The video couldn't be sent to the phone: watch it on the PC dashboard.)"
        msg = tb.send(text + note, reply_markup=kb)
    remember_buttons(it["id"], msg)
    if not mark:                                   # morning list / queue: doesn't replace the 3-hour reminder
        return
    key = "reminded" if reminder else "asked"
    _update_state(lambda s: s.setdefault(key, {}).__setitem__(it["id"], time.time()))


# ---------------- buttons work once (owner 17 Nov: reminders repeat the buttons; taps on old copies confused) -------
def remember_buttons(item_id: str, msg) -> None:
    mid = (msg or {}).get("message_id") if isinstance(msg, dict) else None
    if mid:
        _update_state(lambda s: s.setdefault("button_msgs", {}).setdefault(item_id, []).append(mid))


def close_buttons(item_id: str, label: str) -> int:
    """After a decision: every message that showed this video's buttons gets one inert label instead
    ("✅ Approved · posts Tue 22:30"), so nothing can be tapped twice."""
    from . import telegram_bot as tb
    mids = list(_load().get("button_msgs", {}).get(item_id, []))
    n = 0
    for mid in mids:
        try:
            tb.api("editMessageReplyMarkup", chat_id=tb._chat(), message_id=mid,
                   reply_markup={"inline_keyboard": [[{"text": label[:60], "callback_data": "noop"}]]})
            n += 1
        except Exception:  # noqa: BLE001 - very old messages can't be edited
            pass
    _update_state(lambda s: s.get("button_msgs", {}).pop(item_id, None))
    return n


def item_of(tok: str) -> str | None:
    ref = resolve(tok)
    return ref[1] if ref else None


# ---------------- the owner's decisions (called by the Telegram bot) ----------------
def decide(tok: str, action: str, note: str = "") -> str:
    from . import telegram_bot as tb
    ref = resolve(tok)
    if not ref:
        return "That button has expired."
    start, item_id, version = ref
    plan_it = next((x for x in weekly.load_plan(start)["items"] if x["id"] == item_id), None)
    if not plan_it:
        return "I can't find that video any more."
    if plan_it["status"] in ("making", "redo"):
        return "⏳ A new version of this video is being made. I'll send it here; decide on that one."
    if version and str(plan_it.get("made_at") or "") != version:
        return "This message shows an older version. Please use the newest message for this video."
    st = plan_it["status"]
    if st == "posted":
        return "This video is already posted."
    if st in ("failed", "planned", "needs_source"):
        return ("⏳ The new version of this video couldn't be finished yet, so there's nothing to decide. I'll send it "
                "here when it's ready.")
    if action == "approve" and (st in ("approved", "scheduled") or plan_it.get("youtube_id")):   # never upload twice
        return f"✅ Already approved: {plan_it['channel_name']} posts {_when(plan_it):%a %d %b %H:%M} IST."
    if st == "missed" and action in ("change", "reject"):
        update_item(start, item_id, status="made")
    if action == "change" and not TITLE_ONLY.match(note or ""):
        need_h = 6 if plan_it.get("kind") == "long" else 1.5     # time a remake needs before the slot
        if _when(plan_it) < _now() + timedelta(hours=need_h):
            new = next_free_slot(start, plan_it)
            if datetime.fromisoformat(new) < _now() + timedelta(hours=need_h):
                new = _later_slot(start, plan_it, need_h)
            update_item(start, item_id, publish_at=new)
            plan_it["publish_at"] = new
    if action == "approve":
        if st in ("missed",) or _when(plan_it) < _now() + timedelta(minutes=20):
            new = next_free_slot(start, plan_it)
            update_item(start, item_id, publish_at=new, status="made")
            plan_it["publish_at"] = new
        weekly.decide(start, item_id, "approve")
        it = update_item(start, item_id, approved_at=time.time())
        it = _with_local_media(start, it)                      # cloud: fetch the video if this run doesn't have it yet
        probs = preflight(it)
        if probs:
            update_item(start, item_id, status="made")
            return "⚠️ Not approved, because: " + "; ".join(probs) + ". Tap Change to fix it."
        yt = _schedule_youtube(start, it)
        return (f"✅ Approved: {it['channel_name']} posts {_when(it):%a %d %b %H:%M} IST." +
                (f"\nYouTube: {yt}" if yt else ""))
    if action in ("reject", "change") and plan_it.get("youtube_id"):
        from .publish import youtube_delete
        ok = youtube_delete(plan_it["channel"], plan_it["youtube_id"])
        update_item(start, item_id, youtube_id=None)
        if not ok:
            tb.notify(f"⚠️ Couldn't remove the scheduled YouTube upload {plan_it['youtube_id']}: delete it in "
                      "YouTube Studio so the old version doesn't go live.")
    if action == "reject":
        weekly.decide(start, item_id, "reject")
        return f"❌ Rejected. {plan_it['channel_name']} skips that slot."
    if action == "change" and TITLE_ONLY.match(note or ""):
        return _change_title(start, plan_it, TITLE_ONLY.match(note).group(1).strip())
    if action == "change":
        weekly.decide(start, item_id, "redo", note)
        _update_state(lambda s: (s.get("asked", {}).pop(item_id, None), s.get("reminded", {}).pop(item_id, None)))
        clip = _channel(plan_it["channel"]).get("type") == "clips"
        tb.notify(f"✏️ Remaking {plan_it['channel_name']} with your change: “{note[:200]}”. " +
                  ("Clips can't be re-edited one by one, so I'll send the next best clip from the footage instead. "
                   if clip else "I'll send the new version. ") +
                  f"Posting time: {_when(plan_it):%a %d %b %H:%M} IST.")
        return ""
    return "Unknown action."


def _later_slot(start: str, it: dict, hours: float) -> str:
    """The channel's first free peak slot at least `hours` from now (so a remake can finish before it)."""
    ch = _channel(it["channel"])
    taken = {x["publish_at"] for _, x in items(0, 30) if x["channel"] == it["channel"] and x["id"] != it["id"]}
    after = _now() + timedelta(hours=hours)
    for d in range(0, 14):
        for when, kind in weekly.slots_for(ch, (after + timedelta(days=d)).date(), days=1):
            if when > after and when.isoformat() not in taken and (kind == "long") == (it.get("kind") == "long"):
                return when.isoformat()
    return (after + timedelta(hours=1)).isoformat()


TITLE_ONLY = re.compile(r"^\s*title\s*[:\-]?\s*(.+)$", re.I | re.S)


def _change_title(start: str, it: dict, value: str) -> str:
    """Owner typed "title 2" or "title: New words": swap the title, no remake; then ask again."""
    out = Path(it["out_dir"])
    m = weekly._item_media(it)
    opts = m.get("titles") or []
    if value.isdigit() and 1 <= int(value) <= len(opts):
        value = opts[int(value) - 1]
    value = value.strip().strip('"')[:100]
    if not value:
        return "Type the new title after the word title, for example: title: The Lake That Vanished"
    up = out / "upload.json"
    if up.exists():
        meta = json.loads(up.read_text(encoding="utf-8"))
        meta["title"] = value
        up.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    cj = out / "clips.json"
    if cj.exists():
        clips = json.loads(cj.read_text(encoding="utf-8"))
        for c in clips:
            if c.get("file") == it.get("file"):
                c["title"] = value
        cj.write_text(json.dumps(clips, indent=2, ensure_ascii=False), encoding="utf-8")
    fields = {"status": "made", "made_at": time.time()}
    if _when(it) < _now() + timedelta(minutes=30):                # slot gone or too close: next free peak slot
        fields["publish_at"] = next_free_slot(start, it)
    fresh = update_item(start, it["id"], **fields)
    try:
        ask(start, fresh)
    except Exception:  # noqa: BLE001
        pass
    return f"✏️ Title changed to: {value}. The updated version is above; approve it when you're happy."


def _schedule_youtube(start: str, it: dict) -> str:
    """Upload to YouTube right after approval with the slot time; YouTube publishes it then."""
    if not _connected(it["channel"])["youtube"]:
        return "channel not connected yet, so nothing was uploaded (connect it with python cli.py connect)."
    fresh = next((x for x in weekly.load_plan(start)["items"] if x["id"] == it["id"]), it)
    if fresh.get("youtube_id"):                                # 17 Nov: one video is uploaded once, whatever is tapped
        return f"already uploaded (https://youtu.be/{fresh['youtube_id']})"
    _unique_title(it)
    from .publish import upload_item
    acts = upload_item(it, dry_run=False, platforms=("youtube",))
    up = next((a for a in acts if a.platform == "youtube"), None)
    if up and up.what.startswith("SKIPPED"):                # 20 Nov: campaign brief without YouTube: not an error
        return "not for YouTube (the campaign's brief doesn't list it); it goes to the brief's platforms at its slot"
    vid = (up.result or {}).get("video_id") if up and up.done else None
    if vid:
        update_item(start, it["id"], youtube_id=vid)
        return f"uploaded and scheduled (https://youtu.be/{vid})"
    return "upload failed: " + str((up.result or {}).get("error") if up else "unknown")


def _unique_title(it: dict) -> None:
    """Last check before any upload: the title was never used on this channel (owner 17 Nov: "be careful about
    duplicates"). An unused option from title_options, else the title plus a short distinguishing detail."""
    from . import uniq
    folder = Path(it.get("out_dir") or "")
    for name in ("upload.json", "meta.json"):
        f = folder / name
        if not f.exists():
            continue
        try:
            meta = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        title = meta.get("title")
        if not title:
            continue
        if not _title_taken_elsewhere(it, title):
            return
        used = uniq.used_titles(it["channel"]) | {uniq._norm(title)}     # the taken title must not come back
        opts = [title] + [t for t in meta.get("title_options") or [] if t != title]
        meta["title"] = uniq.pick(it["channel"], opts, used=used)[0]
        f.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
        return


def _title_taken_elsewhere(it: dict, title: str) -> bool:
    """True when another video of this channel (uploaded, or made/approved in a plan) already has this title."""
    from . import uniq
    n = uniq._norm(title)
    if uniq.LOG.exists():
        for line in uniq.LOG.read_text(encoding="utf-8").splitlines():
            try:
                a = json.loads(line)
            except ValueError:
                continue
            if (a.get("channel") == it["channel"] and a.get("done") and a.get("item_id") != it["id"]
                    and uniq._norm((a.get("details") or {}).get("title") or "") == n):
                return True
    for _, x in items(30, 30):
        if x["channel"] == it["channel"] and x["id"] != it["id"] and x.get("youtube_id") and x.get("out_dir"):
            for name in ("upload.json", "meta.json"):
                f = Path(x["out_dir"]) / name
                try:
                    if f.exists() and uniq._norm(json.loads(f.read_text(encoding="utf-8")).get("title") or "") == n:
                        return True
                except (OSError, ValueError):
                    continue
    return False


# ---------------- the loop ----------------
_BRAIN: list = []


def default_brain():
    """The AI brain (writes scripts, picks topics and moments, checks facts) + our memory; created once."""
    if not _BRAIN:
        from .brain import Brain
        from .memory import open_memory
        _BRAIN.append((Brain(), open_memory()))
    return _BRAIN[0]


def _ensure_plan(brain_fn, log) -> None:
    """Plan next week on Friday (or whenever the plan runs out within 3 days)."""
    now = _now()
    future = [it for _, it in items(0, 14)]
    last = max((_when(it) for it in future), default=None)
    if last and last > now + timedelta(days=3):
        return
    nm = weekly.next_monday(now.date())
    if (weekly.week_dir(nm) / "plan.json").exists():
        return
    tried = _load().get("plan_tried") or {}
    if tried.get("week") == str(nm) and time.time() - tried.get("at", 0) < 3600:
        return                                              # failed recently: try again in an hour, not every tick
    n = (tried.get("n", 0) + 1) if tried.get("week") == str(nm) else 1
    _update_state(lambda s: s.__setitem__("plan_tried", {"week": str(nm), "at": time.time(), "n": n}))
    log(f"Planning the week of {nm}")
    brain, memory = brain_fn()
    try:                                     # 20 Nov: volume per channel follows its views + proven capacity
        from . import allocator
        allocator.build(log=log)
    except Exception as e:  # noqa: BLE001 - the plan uses the configured numbers instead
        log(f"allocation failed, using the configured numbers: {type(e).__name__}: {e}")
    try:
        weekly.plan_week(brain, nm, memory=memory, log=log)
    except Exception as e:
        if n == 3:
            from .telegram_bot import notify
            notify(f"⚠️ I couldn't plan the week of {nm} (3 tries): {type(e).__name__}: {str(e)[:150]}. "
                   "I keep trying every hour; videos stop when the current plan ends.")
        raise


def _make_due(brain_fn, log) -> None:
    if not _MAKING.acquire(blocking=False):
        return
    try:
        now = _now()
        due = [(s, it) for s, it in items(0, 5) if it["status"] in weekly.TO_MAKE and
               (it["status"] == "redo" or _when(it) <= now + timedelta(
                   hours=MAKE_AHEAD_LONG_H if it.get("kind") == "long" else MAKE_AHEAD_H)) and _when(it) > now
               and (it["status"] != "needs_source" or weekly.has_clip_material(it["channel"]))   # footage arrived
               and (it.get("retry_at") or 0) <= time.time()
               and (it.get("attempts") or 0) < 3]
        if not due:
            return
        import shutil
        due.sort(key=lambda x: (x[1]["status"] != "redo", x[1]["publish_at"]))     # owner's changes first
        start, it = due[0]
        need = 10 if it.get("kind") == "long" else 6         # GB free before starting (long renders use more)
        if shutil.disk_usage(ROOT).free / 1e9 < need:
            from .cleanup import run as cleanup_run
            cleanup_run(log=log)
            if shutil.disk_usage(ROOT).free / 1e9 < need:
                day = _now().date().isoformat()
                if _load().get("disk_warned") != day:
                    _update_state(lambda st: st.__setitem__("disk_warned", day))
                    from .telegram_bot import notify
                    notify(f"💾 Disk almost full (under {need} GB free on D:). I paused making videos until there is "
                           "space. Delete or move some of your own files from D:, please.")
                return
        brain, memory = brain_fn()
        plan = weekly.load_plan(start)
        item = next(x for x in plan["items"] if x["id"] == it["id"])
        LOCK.parent.mkdir(parents=True, exist_ok=True)
        LOCK.write_text(item["id"], encoding="utf-8")
        try:
            update_item(start, item["id"], status="making")
            log(f"Making {item['channel_name']} {item['kind']}: {item.get('topic') or 'clip'}")
            weekly.make_item(plan, item, brain, memory=memory, log=lambda m: log("   " + str(m)))
            update_item(start, item["id"], status="made", made_at=time.time(), out_dir=item.get("out_dir"),
                        file=item.get("file"), error=None, attempts=0, retry_at=None, topic=item.get("topic"),
                        angle=item.get("angle"), planned_topic=item.get("planned_topic"),
                        feeling=item.get("feeling"), now_hook=item.get("now_hook"))
            try:
                preview_file(item)                   # phone copy ready now, so the approval message is quick
            except Exception:  # noqa: BLE001
                pass
            work = Path(item.get("out_dir") or "") / "work"
            if item.get("out_dir") and work.is_dir():  # temporary render files: not needed once it's finished
                import shutil
                shutil.rmtree(work, ignore_errors=True)
        except weekly.NeedsSource as e:
            update_item(start, item["id"], status="needs_source", error=str(e))
        except Exception as e:  # noqa: BLE001
            wait = free_limit_wait(e)
            if wait:                                   # free daily limits: wait for the reset, never use up a try
                update_item(start, item["id"], status="redo" if it["status"] == "redo" else "failed",
                            error=f"{type(e).__name__}: {e}", retry_at=wait)
                log(f"{item['channel_name']}: free limit reached, waits until the reset")
                return                                 # (finally: the lock is still released)
            n = (it.get("attempts") or 0) + 1
            update_item(start, item["id"], status="redo" if it["status"] == "redo" else "failed",   # keep the note
                        error=f"{type(e).__name__}: {e}", attempts=n,
                        retry_at=time.time() + (1800 if n == 1 else 7200))
            log(traceback.format_exc())
            if n >= 3:
                from .telegram_bot import notify
                notify(f"⚠️ Couldn't make {item['channel_name']} ({item.get('topic') or item['kind']}) after 3 tries: "
                       f"{type(e).__name__}: {str(e)[:200]}. That slot will be skipped unless it's fixed.")
        finally:
            LOCK.unlink(missing_ok=True)
    finally:
        _MAKING.release()


def asked_current(s: dict, it: dict) -> bool:
    """Was the owner shown THIS version (asked after it was made)?"""
    t = s.get("asked", {}).get(it["id"])
    return bool(t) and t >= (it.get("made_at") or 0)


def _campaign_held(start, it: dict, log) -> bool:
    """A campaign clip reaches the owner if and only if the campaign gate passes (owner, 17 Nov). Held clips are
    re-checked every tick (a budget update or a fixed caption can free them); reasons show in 'Anything broken?'."""
    try:
        from .campaign_gate import gate_item
        probs = gate_item(it, brain_fn=lambda: default_brain()[0])
    except Exception as e:  # noqa: BLE001 - a gate that cannot run holds the clip
        probs = [f"the campaign gate could not run ({str(e)[:80]})"]
    if probs and (_load().get("gate_held") or {}).get(it["id"], {}).get("problems") != probs:
        log(f"Held by the campaign gate: {it['channel_name']} {it['id']}: {'; '.join(probs)[:200]}")

    def upd(s):
        held = {k: v for k, v in (s.get("gate_held") or {}).items() if time.time() - v.get("at", 0) < 3 * 86400}
        if probs:
            held[it["id"]] = {"problems": probs, "at": time.time(), "channel": it.get("channel_name")}
        else:
            held.pop(it["id"], None)
        s["gate_held"] = held
    _update_state(upd)
    return bool(probs)


def _reach_check(start, it: dict) -> dict | None:
    """Reach gate for one video (engine/reach_gate.py). A blocked video is held like a campaign clip (re-checked
    every tick, reasons in 'Anything broken?'); the gate never fails the ask because of its own error."""
    try:
        it = _with_local_media(start, it)
        from .reach_gate import gate_item
        res = gate_item(it)
    except Exception as e:  # noqa: BLE001
        print(f"reach gate skipped for {it.get('id')}: {e}")
        return None
    if not res:
        return None
    probs = [f"reach: {b}" for b in res.get("block") or []]

    def upd(s):
        held = dict(s.get("gate_held") or {})
        if probs:
            held[it["id"]] = {"problems": probs, "at": time.time(), "channel": it.get("channel_name")}
        elif held.get(it["id"], {}).get("problems", [""])[0].startswith("reach:"):
            held.pop(it["id"], None)
        s["gate_held"] = held
    _update_state(upd)
    return res


def gate_held() -> dict:
    """Campaign clips the gate is holding back right now: {item id: {problems, at, channel}}."""
    return dict(_load().get("gate_held") or {})


def _ask_due(log, allow=None) -> None:
    """allow(item) -> bool: the PC stand-in (pc_fallback) only asks about videos whose file it has."""
    from .telegram_bot import _chat
    if not _chat():
        return                                    # phone not paired yet: nothing to ask on
    now, s = _now(), _load()
    for start, it in items(0, 3):
        if it["status"] != "made" or (allow and not allow(it)):
            continue
        w = _when(it)
        if w <= now:
            continue
        hours = (w - now).total_seconds() / 3600
        if not asked_current(s, it) and hours <= ASK_AHEAD_H:
            log(f"Asking approval: {it['channel_name']} {it['publish_at']}")
            ask(start, it)
        elif asked_current(s, it) and it["id"] not in s.get("reminded", {}) and hours <= REMIND_H:
            ask(start, it, reminder=True)


def _post_due(log, allow=None) -> None:
    """At its slot an approved video is queued for every platform (engine/publish_queue.py: one job per platform,
    its own retries, the governor's budgets), then the queue posts what is due. allow(item) -> bool limits both
    steps to some videos (the Studio's "Upload now" on the PC)."""
    from . import publish_queue
    from .telegram_bot import notify
    now, s = _now(), _load()
    for start, it in items(3, 1):
        if it["status"] != "approved" or it["id"] in s.get("posted", {}):
            continue
        if allow and not allow(it):
            continue
        if publish_queue.queued(it["id"]):                 # the queue owns it now (retries, waits)
            continue
        if (it.get("post_retry_at") or 0) > time.time():
            continue
        w = _when(it)
        if w > now + timedelta(minutes=2):
            continue
        if now - w > timedelta(hours=LATE_POST_MAX_H):
            new = next_free_slot(start, it)
            update_item(start, it["id"], publish_at=new)
            notify(f"⏭ {it['channel_name']}: the PC was off at posting time, moved to {datetime.fromisoformat(new):%a %H:%M}.")
            continue
        probs = preflight(it)                    # its own scheduled YouTube upload doesn't count as a double post
        if probs:
            update_item(start, it["id"], status="made")
            notify(f"🛑 Not posted {it['channel_name']}: {'; '.join(probs)}. Fix with Change, then approve again.")
            continue
        plats = ["instagram", "threads", "facebook", "dailymotion", "telegram"] + ([] if it.get("youtube_id") else ["youtube"])
        publish_queue.enqueue(start, it, plats)
    publish_queue.drain(log, allow=allow)


def _missed(log) -> None:
    from .telegram_bot import notify
    now, s = _now(), _load()
    for start, it in items(2, 9):                  # approved Shorts parked a week out by the old slot search (16 Nov)
        if it["status"] != "approved" or it.get("kind") == "long" or _when(it) < now + timedelta(hours=48):
            continue
        try:                                       # the id starts with the original slot: MMDD_HHMM
            orig = datetime(now.year, int(it["id"][:2]), int(it["id"][2:4]), int(it["id"][5:7]), int(it["id"][7:9]),
                            tzinfo=now.tzinfo)
        except (ValueError, IndexError):
            continue
        if orig < now:
            new = next_free_slot(start, it)
            if datetime.fromisoformat(new) < _when(it):
                if it.get("youtube_id"):                  # already scheduled on YouTube: move it there too
                    from .publish import youtube_reschedule
                    if not youtube_reschedule(it["channel"], it["youtube_id"], new):
                        log(f"Couldn't move {it['id']} on YouTube; it stays at {it['publish_at']}")
                        continue
                update_item(start, it["id"], publish_at=new)
                log(f"Moved approved {it['id']} up to {new} (was parked a week out)")
    for start, it in items(0, 9):                  # approved before its channel existed (Brain Snack, 16 Nov): upload
        if it["status"] == "approved" and not it.get("youtube_id") and _when(it) > now + timedelta(minutes=20) \
                and _connected(it["channel"])["youtube"]:          # now, scheduled for its slot, like an approval
            try:
                it = _with_local_media(start, it)
                if not preflight(it):
                    log(f"{it['id']}: {_schedule_youtube(start, it)}")
            except Exception as e:  # noqa: BLE001 - the posting step still uploads it at its slot
                log(f"{it['id']}: late YouTube scheduling failed ({str(e)[:120]})")
    for start, it in items(2, 0):
        if it["status"] not in ("made", "redo") or _when(it) >= now - timedelta(minutes=5):
            continue
        from .telegram_bot import _chat
        if (it["status"] == "redo" or not asked_current(s, it)) and _chat() and (it.get("moves") or 0) < 3:
            # the owner never had a chance (remake still waiting, or finished too late to ask): new slot, no loss
            new = _later_slot(start, it, 6 if it.get("kind") == "long" else 1.5) if it["status"] == "redo" \
                else next_free_slot(start, it)
            update_item(start, it["id"], publish_at=new, moves=(it.get("moves") or 0) + 1)
            log(f"Moved {it['id']} to {new} (not shown to the owner in time)")
            continue
        update_item(start, it["id"], status="missed")
        notify(f"⌛ {it['channel_name']} wasn't approved in time, so I didn't post it. It's safe: approve it from "
               "the earlier message and it goes out in the next free peak slot.")


def _daily(log) -> None:
    now = _now()
    s = _load()
    today = now.date().isoformat()
    jobs = s.setdefault("daily", {})
    if now.hour >= 9 and jobs.get("morning") != today:
        _update_state(lambda st: st.setdefault("daily", {}).__setitem__("morning", today))
        from . import discover, stats_fetch, telegram_bot as tb
        for name, fn in (("campaigns", lambda: discover.discover(hours=30, log=log)),
                         ("stats", lambda: stats_fetch.fetch(log=log)), ("digest", tb.digest), ("report", tb.report),
                         ("logins", _check_logins), ("waiting", _morning_waiting), ("branding", _branding),
                         ("threads", _threads_refresh), ("retention", lambda: _retention(log)),
                         ("studio_button", tb.studio_button),                 # 19 Nov: Studio inside Telegram
                         ("milestones", lambda: __import__("engine.milestones", fromlist=["check"]).check(log=log)),
                         ("news_topics", lambda: __import__("engine.news_topics", fromlist=["refresh"]).refresh(log=log))):
            try:
                fn()
            except Exception as e:  # noqa: BLE001
                log(f"morning {name}: {e}")
    if now.hour >= 10 and jobs.get("outreach") != today:                 # creator outreach: Monday pitches,
        _update_state(lambda st: st.setdefault("daily", {}).__setitem__("outreach", today))   # daily follow-ups
        try:
            from . import outreach
            if now.weekday() == 0:
                outreach.weekly_queue(brain=default_brain()[0], log=log)
            outreach.followups(log=log)
        except Exception as e:  # noqa: BLE001
            log(f"outreach: {e}")
    if now.hour >= 18 and jobs.get("comments") != today:                 # evening: viewers' comments + reply drafts
        _update_state(lambda st: st.setdefault("daily", {}).__setitem__("comments", today))
        try:
            from . import comments
            comments.daily(brain=default_brain()[0], log=log)
        except Exception as e:  # noqa: BLE001
            log(f"comments: {e}")
    if now.hour >= 21 and jobs.get("review") != today:                   # end of day: review every channel and
        _update_state(lambda st: st.setdefault("daily", {}).__setitem__("review", today))   # platform (owner 18 Nov)
        try:
            from . import daily_review
            brain, memory = default_brain()
            daily_review.run(brain=brain, memory=memory, log=log)
        except Exception as e:  # noqa: BLE001
            log(f"daily review: {e}")
        try:
            from . import timing
            timing.learn(log=log)
        except Exception as e:  # noqa: BLE001
            log(f"timing: {e}")
    if now.hour >= 19 and jobs.get("share_packs") != today:              # evening: winners go to more platforms
        _update_state(lambda st: st.setdefault("daily", {}).__setitem__("share_packs", today))
        try:
            from . import share_packs
            share_packs.send(log)
        except Exception as e:  # noqa: BLE001
            log(f"share packs: {e}")
    week = f"{now.isocalendar()[0]}-W{now.isocalendar()[1]}"
    if now.weekday() >= 2 and now.hour >= 8 and jobs.get("winners") != week:   # Wednesday: learn from top creators
        _update_state(lambda st: st.setdefault("daily", {}).__setitem__("winners", week))
        try:
            _niche_winners(default_brain, log)
        except Exception as e:  # noqa: BLE001
            log(f"niche winners: {e}")
        try:                                                     # real music per mood, commercial licences only
            from .media import music_library
            music_library.refresh(log=log)
        except Exception as e:  # noqa: BLE001
            log(f"music catalogue: {e}")
        try:                                                     # the searches that bring viewers + drift alert
            from . import stats_fetch
            st = stats_fetch.search_terms(log=log)
            if st["alerts"]:
                from .telegram_bot import notify
                notify("📉 YouTube search traffic dropped:\n• " + "\n• ".join(st["alerts"]) +
                       "\nCheck the titles and thumbnails of the last videos on those channels.")
        except Exception as e:  # noqa: BLE001
            log(f"search terms: {e}")
        try:                                                     # every channel measured the same way, weekly
            from . import quality
            rep = quality.run(log=lambda m: None)
            weak = [(c["name"], c["score"], c["videos"]) for c in rep["channels"].values()
                    if c["score"] is not None and c["score"] < 100]
            from .telegram_bot import notify
            notify("🎯 Weekly quality check, all channels: " +
                   (f"{len(rep['channels']) - len(weak)} perfect." if weak else "every channel on target.") +
                   "".join(f"\n• {n} {s}: " + "; ".join(t for v in vids for _, t in v.get("issues", []))[:150]
                           for n, s, vids in weak[:8]))
        except Exception as e:  # noqa: BLE001
            log(f"quality: {e}")
    if now.weekday() >= 1 and now.hour >= 11 and jobs.get("products") != week:   # Tuesday: product research first
        _update_state(lambda st: st.setdefault("daily", {}).__setitem__("products", week))   # (owner, 16 Nov)
        try:
            from . import product_research
            product_research.weekly(log=log)
        except Exception as e:  # noqa: BLE001
            log(f"product research: {e}")
    if now.weekday() >= 3 and now.hour >= 8 and jobs.get("learn") != week:   # Thursday, before next week is planned
        _update_state(lambda st: st.setdefault("daily", {}).__setitem__("learn", week))
        try:
            _learn(default_brain, log)
        except Exception as e:  # noqa: BLE001
            log(f"learning loop: {e}")
    if time.time() - (jobs.get("stats_at") or 0) > 3 * 3600:   # 2 h / 24 h / 48 h snapshots
        _update_state(lambda st: st.setdefault("daily", {}).__setitem__("stats_at", time.time()))
        from . import stats_fetch
        try:
            stats_fetch.fetch(log=lambda m: None)
        except Exception as e:  # noqa: BLE001
            log(f"stats: {e}")
    if now.hour >= 3 and (now.hour, now.minute) >= (3, 30) and jobs.get("cleanup") != today:
        from .cleanup import rendering, run as cleanup_run
        if not rendering():
            _update_state(lambda st: st.setdefault("daily", {}).__setitem__("cleanup", today))
            res = cleanup_run(log=log)
            if res.get("free_gb") is not None and res["free_gb"] < 10:
                from .telegram_bot import notify
                notify(f"💾 Only {res['free_gb']} GB free on D: after cleanup.")


def _niche_winners(brain_fn, log) -> int:
    """Weekly: the most-viewed recent videos in each niche (official YouTube search) go into memory as examples
    for the topic picker and the writer; the owner gets a short "what's winning" message."""
    from . import niche_winners
    from .config import channels
    report = niche_winners.refresh(brain_fn()[1], log=log)
    if report:
        from .telegram_bot import notify
        notify(niche_winners.message(report, {c["id"]: c["name"] for c in channels()}))
    return sum(len(v) for v in report.values())


def _learn(brain_fn, log) -> int:
    """Weekly learning loop: each channel's top 20% (48-hour numbers vs its own median) go into our memory as
    'what worked', so next week's writer copies those hooks; the owner gets the learning report."""
    from . import analytics
    from .config import channels
    conn = analytics.connect()
    ids = [c["id"] for c in channels()]
    fed = set(_load().get("fed", []))
    new, memory = [], None
    for cid in ids:
        summ = analytics.channel_summary(conn, cid)
        if (summ.get("videos") or 0) < 5:                    # too little data to call anything a winner
            continue
        for r in summ["winners"]:
            key = f"{r['item_id']}|{r['platform']}"
            text = r.get("hook") or r.get("topic")
            if key in fed or not text:
                continue
            if memory is None:
                memory = brain_fn()[1]
            memory.add("hook", text, channel=cid, performance=r["views"],
                       meta={"platform": r["platform"], "format": r.get("format"), "source": "our_winner"})
            new.append(key)
    if new:
        _update_state(lambda s: s.__setitem__("fed", sorted(set(s.get("fed", [])) | set(new))))
    report = analytics.weekly_report(conn, ids)
    if "videos, median" in report:                           # at least one channel has numbers
        from .telegram_bot import notify
        notify("📈 " + report[:3800] + (f"\n\n{len(new)} winning hooks added to the writer's memory." if new else ""))
    log(f"Learning loop: {len(new)} winners added")
    return len(new)


def shown_waiting() -> list[tuple[str, dict]]:
    """Videos the owner has seen (this version was sent with its preview) that still wait for a tap."""
    s = _load()
    return [(st, it) for st, it in items(0, 3) if it["status"] == "made" and asked_current(s, it)
            and _when(it) > _now()]


def approve_all_shown() -> str:
    """One tap instead of one per video (owner, 12 Nov: fewer manual steps). Only videos already shown to the owner;
    each still passes the same checks as a single approval. Videos not shown yet are never approved."""
    waiting = shown_waiting()
    if not waiting:
        return "Nothing is waiting for your tap right now."
    replies = []
    for st, it in waiting:
        try:
            r = decide(token(st, it["id"], str(it.get("made_at") or "")), "approve")
            replies.append(r)
            if r.startswith("✅"):
                close_buttons(it["id"], r.split("\n")[0])
        except Exception as e:  # noqa: BLE001 - one failure must not stop the others
            replies.append(f"⚠️ {it['channel_name']}: {str(e)[:100]}")
    ok = [r for r in replies if r.startswith("✅")]
    rest = [r for r in replies if not r.startswith("✅")]
    return (f"✅ Approved {len(ok)} of {len(replies)} video(s); each posts at its time." +
            ("\n" + "\n".join(rest[:8]) if rest else ""))


def _morning_waiting() -> None:
    """09:00: everything shown overnight and still waiting for the owner's tap, with the buttons again."""
    waiting = [(st, it) for st, it in shown_waiting() if (_when(it) - _now()).total_seconds() < 86400]
    if not waiting:
        return
    from .telegram_bot import notify, send
    notify(f"☀️ {len(waiting)} video(s) still wait for your tap: " +
           ", ".join(f"{it['channel_name']} {_when(it):%H:%M}" for _, it in waiting[:12]) + ". Buttons below.")
    if len(waiting) > 1:
        try:
            send(f"Watched them all? One tap approves every video you were shown ({len(shown_waiting())}).",
                 reply_markup={"inline_keyboard": [[{"text": "✅ Approve all I've seen", "callback_data": "aa:all"}]]})
        except Exception:  # noqa: BLE001 - single buttons below still work
            pass
    for st, it in waiting[:12]:
        ask(st, it, reminder=True, mark=False)


def _branding() -> None:
    """Connected YouTube channels get their About text, keywords, banner, country and language by the API."""
    from . import branding
    try:                                       # 18 Nov: the cloud has no output/brand: fetch the v2 banners first
        from .brand_art import pull
        pull()
    except Exception:  # noqa: BLE001 - the texts are still written
        pass
    done = [r for r in branding.apply_all() if r.endswith("written")]
    if done:
        from .telegram_bot import notify
        notify("🎨 YouTube channel pages updated by the system:\n• " + "\n• ".join(done)
               + "\n(Only the profile picture is yours to upload: output/brand/<channel>/avatar.png)")


def _threads_refresh() -> None:
    """Threads 60-day logins renew themselves before they run out."""
    from . import threads
    threads.refresh_all()


def _retention(log=print) -> None:
    """Where viewers left each video (4-30 days old): lessons into memory for the next scripts."""
    from . import retention
    from .memory.store import open_memory
    try:
        memory = open_memory(allow_download=False)
    except Exception:  # noqa: BLE001 - the curves are still saved for the weekly report
        memory = None
    n = retention.run(log=log, memory=memory)
    if n:
        log(f"retention: {n} curve(s) read")


def _check_logins() -> None:
    from .connect import token_health
    probs = token_health()
    if probs:
        from .telegram_bot import notify
        notify("🔑 Account logins need you (posting stops without them):\n• " + "\n• ".join(probs))


def tick(brain_fn, log=print, make: bool = True) -> None:
    for name, fn in (("missed", lambda: _missed(log)), ("post", lambda: _post_due(log)),
                     ("ask", lambda: threading.Thread(target=_ask_thread, args=(log,), daemon=True).start()),
                     ("daily", lambda: _daily(log)),
                     ("sources", lambda: _needs_source_notice(log) if _now().hour >= 9 else None),
                     ("thumbs", lambda: _shorts_thumbnails(log)),
                     ("plan", lambda: _ensure_plan(brain_fn, log))):
        try:
            fn()
        except Exception as e:  # noqa: BLE001 - one failing step must not stop the others
            log(f"autopilot {name}: {type(e).__name__}: {e}")
    if make:
        threading.Thread(target=_make_due, args=(brain_fn, log), daemon=True).start()


def _shorts_thumbnails(log) -> None:
    """Every 15 minutes: Shorts whose processing finished get their custom cover as thumbnail (YouTube, Nov 2026)."""
    if time.time() - (_load().get("thumbs_at") or 0) < 900:
        return
    _update_state(lambda s: s.__setitem__("thumbs_at", time.time()))
    from .publish import process_pending_thumbnails
    n = process_pending_thumbnails()
    if n:
        log(f"Shorts thumbnails set: {n}")


def _ask_thread(log) -> None:
    """Approval messages upload videos (up to 48 MB): in their own thread, so posting is never held up."""
    if not _ASKING.acquire(blocking=False):
        return
    try:
        _ask_due(log)
    except Exception as e:  # noqa: BLE001
        log(f"autopilot ask: {type(e).__name__}: {e}")
    finally:
        _ASKING.release()


def keep_awake() -> bool:
    """Ask Windows not to sleep while this process runs (SetThreadExecutionState; undone when it exits)."""
    try:
        import ctypes
        ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001
        return bool(ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED))
    except Exception:  # noqa: BLE001 - not Windows
        return False


def _needs_source_notice(log) -> None:
    """Once a day: which clip slots have no footage yet (pick a campaign or add a permitted source)."""
    today = _now().date().isoformat()
    if _load().get("daily", {}).get("needs_source") == today:
        return
    counts: dict[str, int] = {}
    for _, it in items(0, 3):
        if it["status"] == "needs_source":
            counts[it["channel_name"]] = counts.get(it["channel_name"], 0) + 1
    _update_state(lambda st: st.setdefault("daily", {}).__setitem__("needs_source", today))
    if counts:
        from .telegram_bot import notify
        notify("📥 Clip slots without footage in the next 3 days: " + ", ".join(f"{k} {v}" for k, v in counts.items()) +
               ". Pick campaigns (/campaigns), then send their footage link with /source <link>; otherwise those slots stay "
               "empty.")


def recover(log=print) -> int:
    """After a crash, restart or power cut: videos left 'making' go back in the queue (a remake keeps the owner's
    note), and a stale render lock is removed."""
    n = 0
    for start, it in items(3, 14):
        if it["status"] == "making":
            update_item(start, it["id"], status="redo" if it.get("note") and it.get("made_at") else "planned")
            n += 1
    LOCK.unlink(missing_ok=True)
    if n:
        log(f"Recovered {n} video(s) that were being made when the PC stopped.")
    return n


def loop(brain_fn, log=print, every_s: int = 120) -> None:
    keep_awake()
    try:
        recover(log)
    except Exception as e:  # noqa: BLE001
        log(f"recover: {e}")
    while True:
        tick(brain_fn, log)
        try:                                       # heartbeat: the dashboard shows whether the autopilot is alive
            HEARTBEAT.write_text(str(time.time()), encoding="utf-8")
        except OSError:
            pass
        time.sleep(every_s)
