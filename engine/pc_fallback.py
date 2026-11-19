"""The PC stands in for the cloud while GitHub Actions is down (owner 18 Nov: "until the cloud is not up and running
we depend upon the alternative or PC").

One loop (`python cli.py pc run`):
- Telegram: the Worker keeps storing every message/tap in its KV (upd:*); the PC answers them with the same code
  the cloud uses (runner.process_inbox), about once a minute.
- Dashboard buttons (phone or PC): the Worker stores each tap as cmd:<id>; the PC does it (approve, upload now,
  change, reject, make now, refresh) and writes the outcome to res:<id>, which the page shows.
- The cloud's light jobs: missed slots, posting approved videos at their time, asking for approval, the daily jobs
  (stats, review), the weekly plan; and making videos one at a time (capped per day, kinds the cloud makes).
- The live dashboard: fresh platform numbers, rebuilt every 30 minutes and put in KV for the Worker to serve.

While it runs, KV meta:pc_primary carries a heartbeat and the Worker starts no cloud runs. When GitHub answers
again, the PC pushes its memory to the store FIRST, then clears the flag: the cloud continues from the PC's state,
so nothing is posted twice and no decision is lost.

Safety (the PC's memory copy is from 12:07 on 18 Nov; the cloud ran until about 15:15):
- videos whose slot was before the cutoff (last cloud start + 1 h) are never posted automatically;
- before any YouTube upload, the channel's real upload list (scheduled ones too) is checked: same title, or
  another video scheduled within 45 minutes of the slot, means the slot is taken;
- only videos whose file is on this PC are offered or posted.
"""
from __future__ import annotations

import json
import secrets
import threading
import time
import traceback
from datetime import datetime, timedelta
from pathlib import Path

import requests

from .config import ROOT, load_env

STATE = ROOT / "data" / "state"
CUTOFF_FILE = STATE / "pc_cutoff.txt"
HANDED_FILE = STATE / "pc_handed_over.txt"     # written once the cloud has the PC's memory: the stand-in stays off
MADE_FILE = STATE / "pc_made.json"
MAKE_PER_DAY = 4                    # the cloud managed ~3-4 a day after the suspension; the PC is shared with coding
EVERY_S = 60
JOBS_EVERY_S = 15 * 60
DAILY_EVERY_S = 3 * 3600
DASH_EVERY_S = 30 * 60
SLOT_WINDOW_S = 45 * 60
HEARTBEAT_S = 300                   # KV free plan: 1,000 writes/day (heartbeats 288, dashboard 96, snapshot 48)
OPS = ("approve", "upload", "change", "reject", "make", "refresh")


def _log(msg: str) -> None:
    from .cloud.runner import redact
    print(time.strftime("%H:%M:%S"), redact(str(msg)), flush=True)


# ---------------- guards ----------------
def cutoff(kv=None) -> float:
    """Unix time before which the cloud may still have handled a slot (last cloud start + 1 h). Saved once."""
    try:
        return float(CUTOFF_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    last_ms = 0.0
    try:
        last_ms = float((kv.get("meta:last_dispatch") if kv else None) or 0)
    except Exception:  # noqa: BLE001
        last_ms = 0.0
    t = (last_ms / 1000 if last_ms else time.time()) + 3600
    STATE.mkdir(parents=True, exist_ok=True)
    CUTOFF_FILE.write_text(str(t), encoding="utf-8")
    return t


def has_file(it: dict) -> bool:
    try:
        out = Path(it.get("out_dir") or "")
        return bool(it.get("file")) and (out / it["file"]).exists()
    except (OSError, TypeError):
        return False


def slot_ts(it: dict) -> float:
    from . import autopilot
    try:
        return autopilot._when(it).timestamp()
    except Exception:  # noqa: BLE001
        return 0.0


_YT_CACHE: dict[str, tuple[float, list[dict]]] = {}


def yt_uploads(channel_id: str, session=requests) -> list[dict]:
    """The channel's latest uploads incl. private/scheduled ones: [{id, title, at}] (at = publishAt or publishedAt).
    About 3 quota units; cached 10 minutes."""
    hit = _YT_CACHE.get(channel_id)
    if hit and time.time() - hit[0] < 600:
        return hit[1]
    from .publish import YT_API, add_quota, yt_access_token
    tok = yt_access_token(channel_id, session)
    if not tok:
        return []
    h = {"Authorization": f"Bearer {tok}"}
    r = session.get(f"{YT_API}/channels", params={"part": "contentDetails", "mine": "true"}, headers=h, timeout=30)
    r.raise_for_status()
    ups = ((r.json().get("items") or [{}])[0].get("contentDetails") or {}).get("relatedPlaylists", {}).get("uploads")
    if not ups:
        return []
    r = session.get(f"{YT_API}/playlistItems", params={"part": "contentDetails", "playlistId": ups, "maxResults": 25},
                    headers=h, timeout=30)
    r.raise_for_status()
    ids = [x["contentDetails"]["videoId"] for x in r.json().get("items") or []]
    out = []
    if ids:
        r = session.get(f"{YT_API}/videos", params={"part": "snippet,status", "id": ",".join(ids)}, headers=h, timeout=30)
        r.raise_for_status()
        for v in r.json().get("items") or []:
            when = (v.get("status") or {}).get("publishAt") or (v.get("snippet") or {}).get("publishedAt") or ""
            try:
                at = datetime.fromisoformat(when.replace("Z", "+00:00")).timestamp()
            except ValueError:
                at = 0.0
            out.append({"id": v["id"], "title": (v.get("snippet") or {}).get("title", ""), "at": at})
    add_quota(3)
    _YT_CACHE[channel_id] = (time.time(), out)
    return out


def _norm(t: str) -> str:
    import re
    return re.sub(r"[^\w]+", " ", (t or "").lower()).strip()


def yt_taken(it: dict, uploads: list[dict] | None = None) -> str:
    """Why this item's YouTube slot is already taken ('' = free). Its own upload doesn't count."""
    try:
        ups = uploads if uploads is not None else yt_uploads(it["channel"])
    except Exception as e:  # noqa: BLE001 - can't check: treat as taken (never risk a double post)
        return f"couldn't check YouTube ({type(e).__name__})"
    own = it.get("youtube_id")
    title = _norm((it.get("meta") or {}).get("title") or it.get("title") or "")
    slot = slot_ts(it)
    for v in ups:
        if own and v["id"] == own:
            continue
        if title and _norm(v["title"]) == title:
            return f"already on YouTube: https://youtu.be/{v['id']}"
        if slot and v["at"] and abs(v["at"] - slot) <= SLOT_WINDOW_S:
            return f"another video is already scheduled/posted at that time: https://youtu.be/{v['id']}"
    return ""


def allow_post(it: dict, cut: float | None = None) -> bool:
    """Automatic posting/asking on the PC: own file, slot after the cutoff, YouTube slot free."""
    cut = cut if cut is not None else cutoff()
    if not has_file(it) or slot_ts(it) < cut:
        return False
    return bool(it.get("youtube_id")) or not yt_taken(it)


# ---------------- dashboard commands ----------------
def _find(item_id: str) -> tuple[str, dict] | tuple[None, None]:
    from . import autopilot
    for start, it in autopilot.items(14, 21):
        if it["id"] == item_id:
            return start, it
    return None, None


def do_command(cmd: dict, log=_log, maker=None) -> str:
    """One dashboard tap. Returns the text shown under the video."""
    from . import autopilot
    op, item_id = cmd.get("op"), str(cmd.get("item") or "")
    if op not in OPS:
        return "Unknown button."
    if op == "refresh":
        publish_dashboard(None, log, live=True)
        return "🔄 Dashboard refreshed with live numbers. Reload the page."
    start, it = _find(item_id)
    if not it:
        return "I can't find that video in the plan."
    tok = autopilot.token(start, it["id"], str(it.get("made_at") or ""))
    if op == "reject":
        return autopilot.decide(tok, "reject")
    if op == "change":
        note = str(cmd.get("note") or "").strip()
        if not note:
            return "Type what should change."
        reply = autopilot.decide(tok, "change", note)
        if maker is not None:
            maker.want(item_id, cmd.get("_id"))
        return reply
    if op == "make":
        if it["status"] in ("made", "approved", "posted", "scheduled"):
            return "This video is already made."
        autopilot.update_item(start, item_id, status="planned", retry_at=None, attempts=0, error=None)
        if maker is None:
            return "Queued: the PC loop makes it next."
        return maker.want(item_id, cmd.get("_id"))
    # approve / upload: the PC must have the file, and the YouTube slot must be free
    if not has_file(it):
        return ("⚠️ This video's file is in the cloud store (GitHub is down), not on this PC. "
                "It can be approved once GitHub is back, or tap Make now for a fresh PC version.")
    taken = "" if it.get("youtube_id") else yt_taken(it)
    if taken:
        return f"🛑 Not done: {taken}."
    if slot_ts(it) < cutoff() and not cmd.get("force"):
        return ("⚠️ Its time slot was before the outage, so the cloud may already have posted it on Instagram / "
                "Facebook. Tap again and confirm to post anyway.")
    if op == "approve":
        return autopilot.decide(tok, "approve")
    # upload now: approve (uploads to YouTube with its slot), then publish everywhere now
    if it["status"] in ("made", "missed"):
        reply = autopilot.decide(tok, "approve")
        if not reply.startswith("✅"):
            return reply
        start, it = _find(item_id)
    if it["status"] not in ("approved", "scheduled"):
        return f"Can't upload: the video is '{it['status']}'."
    now_iso = autopilot._now().replace(microsecond=0).isoformat()
    autopilot.update_item(start, item_id, publish_at=now_iso, post_retry_at=None)
    if it.get("youtube_id"):
        from .publish import youtube_reschedule
        soon = (datetime.utcnow() + timedelta(minutes=2)).replace(microsecond=0).isoformat() + "Z"
        youtube_reschedule(it["channel"], it["youtube_id"], soon)
    autopilot._post_due(log, allow=lambda x: x["id"] == item_id)
    return post_summary(item_id)


def post_summary(item_id: str) -> str:
    from .publish import LOG
    lines = []
    try:
        rows = [json.loads(ln) for ln in LOG.read_text(encoding="utf-8").splitlines()[-60:]]
    except (OSError, json.JSONDecodeError):
        rows = []
    for a in rows:
        if a.get("item_id") != item_id or (a.get("details") or {}).get("dry_run"):
            continue
        r = a.get("result") or {}
        if a.get("done"):
            vid = r.get("video_id")
            lines.append(f"{a['platform'].title()}: posted" + (f" https://youtu.be/{vid}" if a["platform"] == "youtube"
                                                               and vid else ""))
        elif r.get("error") and not str(a.get("what", "")).startswith("SKIPPED: not for"):
            lines.append(f"{a['platform'].title()}: {str(r['error'])[:120]}")
    return "🚀 " + (" · ".join(dict.fromkeys(lines)) if lines else "Posting started; results appear here and in Telegram.")


def process_commands(kv, log=_log, maker=None) -> int:
    n = 0
    for key in kv.keys("cmd:"):
        cid = key[4:]
        raw = kv.get(key)
        kv.delete(key)
        if not raw:
            continue
        try:
            cmd = json.loads(raw)
            cmd["_id"] = cid
            kv.put(f"res:{cid}", {"state": "working", "text": "⏳ Working on it…", "at": time.time()}, ttl=86400)
            text = do_command(cmd, log, maker)
            waiting = maker is not None and cid in sum(maker.res.values(), [])   # the maker reports the end
            kv.put(f"res:{cid}", {"state": "working" if waiting else "done", "text": text, "at": time.time()},
                   ttl=86400)
            log(f"dashboard {cmd.get('op')} {cmd.get('item')}: {text[:100]}")
        except Exception as e:  # noqa: BLE001 - the owner always gets an answer
            traceback.print_exc()
            kv.put(f"res:{cid}", {"state": "error", "text": f"⚠️ That didn't work: {type(e).__name__}: {str(e)[:150]}",
                                  "at": time.time()}, ttl=86400)
        n += 1
    return n


# ---------------- making videos ----------------
class Maker:
    """One video at a time in a background thread (same process: the plan lock is shared)."""

    def __init__(self, log=_log, per_day: int = MAKE_PER_DAY):
        self.log, self.per_day = log, per_day
        self.thread: threading.Thread | None = None
        self.wanted: list[str] = []
        self.res: dict[str, list[str]] = {}      # item id -> dashboard taps waiting for the outcome
        self.kv = None

    def busy(self) -> bool:
        return bool(self.thread and self.thread.is_alive())

    def made_today(self) -> int:
        try:
            d = json.loads(MADE_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            d = {}
        return int(d.get(time.strftime("%Y-%m-%d"), 0))

    def _count(self) -> None:
        try:
            d = json.loads(MADE_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            d = {}
        day = time.strftime("%Y-%m-%d")
        MADE_FILE.parent.mkdir(parents=True, exist_ok=True)
        MADE_FILE.write_text(json.dumps({day: int(d.get(day, 0)) + 1}), encoding="utf-8")

    def want(self, item_id: str, res_id: str | None = None) -> str:
        if res_id:
            self.res.setdefault(item_id, []).append(res_id)
        if item_id not in self.wanted:
            self.wanted.append(item_id)
        return ("🎬 Queued: " + ("making it right after the current video." if self.busy() else "making it now.")
                + " It appears here (and in Telegram) when ready.")

    def next_job(self) -> tuple[str, dict] | None:
        from .cloud import runner
        while self.wanted:
            start, it = _find(self.wanted.pop(0))
            if it and it["status"] not in ("made", "approved", "posted", "scheduled", "making"):
                return start, it
        if self.made_today() >= self.per_day:
            return None
        due = runner._due_to_make(runner.CLOUD_KINDS, set(), connected_only=True)
        due = [(s, it) for s, it in due if it.get("kind") != "clip" and it["status"] != "making"]
        return due[0] if due else None

    def poll(self) -> None:
        if self.busy():
            return
        job = self.next_job()
        if job:
            self.thread = threading.Thread(target=self._make, args=job, daemon=True)
            self.thread.start()

    def _make(self, start: str, it: dict) -> None:
        from . import autopilot
        from .cloud.runner import make_one
        log, t0 = self.log, time.time()
        autopilot.update_item(start, it["id"], status="making", making_by="pc")
        try:
            item = make_one(start, it, log)
            autopilot.update_item(start, item["id"], status="made", made_at=time.time(), out_dir=item["out_dir"],
                                  file=item.get("file"), error=None, attempts=0, retry_at=None,
                                  topic=item.get("topic"), angle=item.get("angle"), made_by="pc")
            self._count()
            log(f"made {item.get('channel_name')} {item.get('kind')} in {(time.time() - t0) / 60:.0f} min")
        except Exception as e:  # noqa: BLE001
            wait = autopilot.free_limit_wait(e)
            if wait:
                autopilot.update_item(start, it["id"], status="failed", error=f"{type(e).__name__}: {e}", retry_at=wait)
            else:
                autopilot.update_item(start, it["id"], status="failed", error=f"{type(e).__name__}: {e}",
                                      attempts=(it.get("attempts") or 0) + 1, retry_at=time.time() + 3600)
            log(f"making {it.get('channel_name')} failed: {type(e).__name__}: {e}")
            traceback.print_exc()
            self._tell(it["id"], "error", f"⚠️ Making failed: {type(e).__name__}: {str(e)[:160]}. "
                                          "It tries again in an hour (or tap Try again).")
            return
        self._tell(it["id"], "done", "✅ Made. Reload the page to watch it and approve, change or reject.")
        if self.kv is not None:
            try:
                publish_dashboard(self.kv, self.log)
            except Exception as e:  # noqa: BLE001
                self.log(f"dashboard: {type(e).__name__}: {e}")

    def _tell(self, item_id: str, state: str, text: str) -> None:
        for rid in self.res.pop(item_id, []):
            try:
                if self.kv is not None:
                    self.kv.put(f"res:{rid}", {"state": state, "text": text, "at": time.time()}, ttl=86400)
            except Exception:  # noqa: BLE001
                pass


# ---------------- video previews for the dashboard player ----------------
PREVIEW_FILE = STATE / "pc_previews.json"
PREVIEW_DIR = ROOT / "data" / "cache" / "dash_previews"
PREVIEW_TTL = 4 * 86400
PREVIEW_CHUNK = 20 * 1024 * 1024        # KV: max 25 MiB per value
PREVIEW_BUDGET = 600 * 1024 * 1024      # KV free plan: 1 GB in total (dashboard + Telegram inbox need some too)
REVIEW_STATES = ("made", "missed", "approved", "scheduled", "redo")


def previews() -> dict:
    """item id -> {sig, size, chunks, at} for previews in KV (what the page may play)."""
    try:
        d = json.loads(PREVIEW_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    now = time.time()
    return {k: v for k, v in d.items() if now - float(v.get("at") or 0) < PREVIEW_TTL - 3600}


def _preview_sig(it: dict) -> str:
    f = Path(it["out_dir"]) / it["file"]
    return f"{f.name}|{int(f.stat().st_mtime)}|{f.stat().st_size}"


def make_preview(it: dict) -> Path:
    """A light copy for the phone (480p, about 1 Mbit/s, starts playing before it has fully loaded)."""
    import hashlib
    import subprocess
    from .media import ffmpeg
    video = Path(it["out_dir"]) / it["file"]
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    out = PREVIEW_DIR / f"{hashlib.sha1(_preview_sig(it).encode()).hexdigest()[:12]}.mp4"
    if out.exists() and out.stat().st_size > 0:
        return out
    long = it.get("kind") == "long"
    subprocess.run([ffmpeg.ffmpeg_bin(), "-y", "-v", "error", "-i", str(video), "-vf",
                    "scale=-2:480" if long else "scale=-2:854", "-c:v", "libx264", "-preset", "veryfast",
                    "-crf", "28", "-maxrate", "700k" if long else "1000k", "-bufsize", "1600k",
                    "-c:a", "aac", "-b:a", "64k", "-movflags", "+faststart", str(out)], check=True, timeout=3600)
    return out


def push_previews(kv, log=_log, only: str | None = None) -> int:
    """Previews of the videos waiting for the owner go to KV (pv:<item>:meta + pv:<item>:<n>), so the dashboard can
    play them on the phone too. Previews of posted / rejected videos are removed. Returns how many were added."""
    from . import autopilot
    have = previews()
    items = {it["id"]: it for _, it in autopilot.items(14, 21)}
    for iid in [k for k in have if items.get(k, {}).get("status") not in REVIEW_STATES]:
        for n in range(int(have[iid].get("chunks") or 0)):
            kv.delete(f"pv:{iid}:{n}")
        kv.delete(f"pv:{iid}:meta")
        have.pop(iid)
    added = 0
    want = [it for it in items.values() if it.get("status") in REVIEW_STATES and has_file(it)
            and (only is None or it["id"] == only)]
    want.sort(key=lambda it: slot_ts(it))
    for it in want:
        sig = _preview_sig(it)
        if have.get(it["id"], {}).get("sig") == sig:
            continue
        if sum(int(v.get("size") or 0) for v in have.values()) > PREVIEW_BUDGET:
            log("previews: storage budget reached, the rest wait")
            break
        try:
            data = make_preview(it).read_bytes()
        except Exception as e:  # noqa: BLE001 - one broken video must not stop the rest
            log(f"preview {it['id']}: {type(e).__name__}: {e}")
            continue
        pieces = [data[i:i + PREVIEW_CHUNK] for i in range(0, len(data), PREVIEW_CHUNK)]
        for n, p in enumerate(pieces):
            kv.put_bytes(f"pv:{it['id']}:{n}", p, ttl=PREVIEW_TTL)
        kv.put(f"pv:{it['id']}:meta", {"size": len(data), "chunks": len(pieces), "chunk": PREVIEW_CHUNK},
               ttl=PREVIEW_TTL)
        have[it["id"]] = {"sig": sig, "size": len(data), "chunks": len(pieces), "at": time.time()}
        added += 1
        PREVIEW_FILE.parent.mkdir(parents=True, exist_ok=True)
        PREVIEW_FILE.write_text(json.dumps(have), encoding="utf-8")
    PREVIEW_FILE.parent.mkdir(parents=True, exist_ok=True)
    PREVIEW_FILE.write_text(json.dumps(have), encoding="utf-8")
    if added:
        log(f"previews: {added} video(s) playable on the dashboard")
    return added


# ---------------- dashboard ----------------
def publish_dashboard(kv, log=_log, live: bool = False) -> int:
    """Fresh platform numbers (live=True) -> rebuild -> put in KV for the Worker. Returns the page size."""
    if live:
        from . import stats_fetch
        for name, fn in (("live counters", lambda: stats_fetch.live(log=log)),
                         ("analytics", lambda: stats_fetch.fetch(log=log)),
                         ("followers", lambda: stats_fetch.channel_stats(log=log))):
            try:
                fn()
            except Exception as e:  # noqa: BLE001
                log(f"{name}: {type(e).__name__}: {e}")
    kv = kv if kv is not None else _kv_or_none()
    if kv is not None:
        try:
            push_previews(kv, log)
        except Exception as e:  # noqa: BLE001 - the page still goes out
            log(f"previews: {type(e).__name__}: {e}")
    from . import dashboard
    page = dashboard.build().read_text(encoding="utf-8")
    if kv is not None:
        kv.put("dash:html", page)
        kv.put("dash:ids", live_ids())          # what the Worker fetches live on every page load
    return len(page)


def live_ids() -> dict:
    """For the Worker's /live: YouTube channel ids per channel, posted YouTube video ids, and the PC-fetched
    Instagram/Facebook follower numbers (those need login tokens, which stay on the PC). No tokens in here."""
    from .stats_fetch import live_stats, posted_videos
    ls = live_stats()
    chans = {cid: c["yt_id"] for cid, c in (ls.get("channels") or {}).items() if c.get("yt_id")}
    vids = {}
    try:
        for v in posted_videos():
            if v.get("platform") == "youtube" and v.get("id"):
                vids[v["id"]] = v.get("channel")
    except Exception:  # noqa: BLE001
        pass
    for vid, v in (ls.get("videos") or {}).items():
        vids.setdefault(vid, v.get("channel"))
    try:
        from .dashboard import _followers
        meta = {cid: {p: n for p, n in f.items() if p != "youtube"} for cid, f in _followers().items()}
    except Exception:  # noqa: BLE001
        meta = {}
    return {"built": time.time(), "channels": chans, "videos": vids, "meta": meta}


def _kv_or_none():
    from .cloud.runner import _kv
    return _kv()


def dash_link() -> str:
    """The owner's private dashboard link (phone or PC). DASH_KEY lives in .env and as a Worker secret."""
    import os
    from .cloud.setup import cf_subdomain
    load_env()
    key = os.environ.get("DASH_KEY", "")
    sub = cf_subdomain(os.environ["CLOUDFLARE_ACCOUNT_ID"], os.environ["CLOUDFLARE_API_TOKEN"])
    return f"https://hookhouse-bot.{sub}.workers.dev/d?k={key}" if key else ""


def standin_running(port: int = 47615) -> bool:
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sk:
        sk.settimeout(1)
        return sk.connect_ex(("127.0.0.1", port)) == 0


def open_dashboard() -> str:
    """Desktop icon (owner 18 Nov: "a shortcut or icon that runs the system and I can see the dashboard"): starts
    the PC stand-in window if it isn't running (and the cloud hasn't taken over), then opens the live dashboard."""
    import subprocess
    import webbrowser
    started = ""
    if not HANDED_FILE.exists() and not standin_running():
        subprocess.Popen(["cmd", "/c", "start", "HookHouse PC stand-in", "/min",
                          str(ROOT / "scripts" / "pc_standin.cmd")], cwd=str(ROOT))
        started = "System started. "
    link = dash_link()
    if not link:
        return started + "No DASH_KEY in .env: ask Claude to set up the dashboard key."
    webbrowser.open(link)
    return started + "Dashboard opened in your browser."


def new_dash_key() -> str:
    return secrets.token_urlsafe(24)


# ---------------- handover ----------------
def github_back(session=requests) -> bool:
    from .cloud import store
    try:
        r = session.get(f"https://api.github.com/repos/{store.repo()}",
                        headers={"Authorization": f"Bearer {store.token()}", "User-Agent": "hookhouse"}, timeout=20)
        return r.status_code == 200
    except Exception:  # noqa: BLE001
        return False


def handover(kv, log=_log) -> bool:
    """GitHub is back: the cloud continues from the PC's memory (pushed first), then the Worker may start runs."""
    from .cloud import state
    from .cloud.store import Store
    try:
        n = state.push(Store())
    except Exception as e:  # noqa: BLE001 - keep standing in until the push works
        log(f"handover: push failed ({type(e).__name__}: {e}); the PC keeps standing in")
        return False
    HANDED_FILE.parent.mkdir(parents=True, exist_ok=True)
    HANDED_FILE.write_text(str(time.time()), encoding="utf-8")
    if kv is not None:
        kv.delete("meta:pc_primary")
    log(f"handover: memory pushed ({n // 1024} KB); the cloud takes over")
    try:
        from .telegram_bot import notify
        notify("☁️ GitHub is back. The PC handed everything to the cloud (its memory went up first, so nothing is "
               "posted twice). Claude: push the local code commits with _git_push().")
    except Exception:  # noqa: BLE001
        pass
    return True


# ---------------- the loop ----------------
def run(make: bool = True, once: bool = False, log=_log) -> int:
    """Returns 3 when the cloud has taken over (the launcher then stops for good), else 0."""
    from . import autopilot
    from .cloud.runner import _one_helper, process_inbox, snapshot
    load_env()
    if HANDED_FILE.exists():
        log("The cloud took over already (pc_handed_over.txt); the PC stand-in stays off.")
        return 3
    if not _one_helper(47615):
        log("Another PC stand-in is already running; this copy stops.")
        return 0
    kv = _kv_or_none()
    if kv is None:
        log("Cloudflare KV not reachable: the stand-in needs it (Telegram + dashboard).")
        return 0
    cut = cutoff(kv)
    log(f"PC stand-in on. Slots before {datetime.fromtimestamp(cut):%d %b %H:%M} are never auto-posted. "
        f"Making videos: {'on, ' + str(MAKE_PER_DAY) + '/day' if make else 'off'}.")
    maker = Maker(log) if make else None
    if maker is not None:
        maker.kv = kv
    last = {"jobs": 0.0, "daily": 0.0, "dash": 0.0, "gh": 0.0}
    allow = lambda it: allow_post(it, cut)                  # noqa: E731
    beat = 0.0
    while True:
        t = time.time()
        if t - beat >= HEARTBEAT_S:                         # free KV: 1,000 writes/day, so every 5 min
            try:
                kv.put("meta:pc_primary", {"at": t, "cutoff": cut})
                beat = t
            except Exception as e:  # noqa: BLE001
                log(f"heartbeat: {e}")
        if t - last["gh"] > 600:
            last["gh"] = t
            if github_back() and handover(kv, log):
                return 3
        for name, fn in (("inbox", lambda: process_inbox(kv, log)),
                         ("dashboard buttons", lambda: process_commands(kv, log, maker))):
            try:
                fn()
            except Exception as e:  # noqa: BLE001
                log(f"{name}: {type(e).__name__}: {e}")
        if t - last["jobs"] > JOBS_EVERY_S:
            last["jobs"] = t
            for name, fn in (("missed", lambda: autopilot._missed(log)),
                             ("post", lambda: autopilot._post_due(log, allow=allow)),
                             ("ask", lambda: autopilot._ask_due(log, allow=allow)),
                             ("snapshot", lambda: t - last.get("snap", 0) > DASH_EVERY_S
                              and (last.__setitem__("snap", t) or snapshot(kv, log)))):
                try:
                    fn()
                except Exception as e:  # noqa: BLE001
                    log(f"{name}: {type(e).__name__}: {e}")
        if t - last["daily"] > DAILY_EVERY_S:
            last["daily"] = t
            for name, fn in (("recover", lambda: autopilot.recover(log)),
                             ("preflight", lambda: __import__("engine.preflight", fromlist=["run"]).run(log=log)),
                             ("daily", lambda: autopilot._daily(log)),
                             ("thumbs", lambda: autopilot._shorts_thumbnails(log)),
                             ("plan", lambda: autopilot._ensure_plan(autopilot.default_brain, log))):
                try:
                    fn()
                except Exception as e:  # noqa: BLE001
                    log(f"{name}: {type(e).__name__}: {e}")
        if t - last["dash"] > DASH_EVERY_S:
            last["dash"] = t
            try:
                log(f"dashboard: {publish_dashboard(kv, log, live=True) // 1024} KB published")
            except Exception as e:  # noqa: BLE001
                log(f"dashboard: {type(e).__name__}: {e}")
                traceback.print_exc()
        if maker is not None:
            try:
                maker.poll()
            except Exception as e:  # noqa: BLE001
                log(f"maker: {type(e).__name__}: {e}")
        if once:
            return 0
        time.sleep(max(5, EVERY_S - (time.time() - t)))
