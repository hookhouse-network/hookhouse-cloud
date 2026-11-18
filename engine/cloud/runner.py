"""What runs where (owner's choice, 13 Nov 2026: "Cloud now, PC as helper").

tick    (GitHub Actions, several times a day + when the Worker has messages): Telegram inbox -> merge videos the PC
        finished -> make sure due videos are on this machine -> the autopilot's light steps (missed, post, ask,
        daily, source notice, Shorts thumbnails, plan) -> status snapshot for the Worker -> save state.
render  (GitHub Actions, once a day, time budget): the soonest Shorts nobody has claimed, made in the cloud.
helper  (the PC, whenever it is on): claims the next videos, makes them (long ones too), uploads them; the next
        tick merges them. The PC never writes the shared state, so the cloud and the PC can't overwrite each other.
"""
from __future__ import annotations

import json
import os
import re
import time
import traceback
from datetime import timedelta
from pathlib import Path

from ..config import ROOT
from . import media, state
from .store import Store

CLAIM_H = 5                                      # a PC claim older than this is treated as abandoned
OVERDUE_D = 3                                    # a missed video is still made up to 3 days after its slot
CLOUD_KINDS = {"short", "clip"}                  # long videos are too heavy for the free 2-core cloud machine


_SECRETS = re.compile(r"((?:access_token|token|key|client_secret|code)=)[^&\s'\"]+|\b(?:EAA|IG)[A-Za-z0-9]{40,}\b"
                      r"|\bAIza[0-9A-Za-z_\-]{35}\b|\bgh[ps]_[A-Za-z0-9]{20,}\b")


def redact(msg: str) -> str:
    """Never a login in the logs (16 Nov: a Facebook error printed the page token inside the request URL)."""
    return _SECRETS.sub(lambda m: (m.group(1) or "") + "[hidden]", str(msg))


def _log(msg: str) -> None:
    print(time.strftime("%H:%M:%S"), redact(msg), flush=True)


def _kv():
    try:
        from .kv import KV
        return KV()
    except Exception as e:  # noqa: BLE001 - the inbox is optional until Cloudflare is set up
        _log(f"inbox off: {e}")
        return None


# ---------- pieces ----------
def process_inbox(kv, log=_log) -> int:
    """Telegram updates the Worker stored: handled by the same code the PC bot used."""
    if kv is None:
        return 0
    from .. import telegram_bot
    n = 0
    for key in kv.keys("upd:"):
        raw = kv.get(key)
        try:
            if raw:
                telegram_bot.handle(json.loads(raw))
                n += 1
        except Exception as e:  # noqa: BLE001 - one bad update must not block the rest
            log(f"update {key}: {type(e).__name__}: {e}")
        finally:
            kv.delete(key)
    if n:
        log(f"inbox: {n} message(s) handled")
    return n


def claims(store) -> dict[str, float]:
    """item id -> claim time, for PC claims that are still fresh."""
    out = {}
    for name, a in store.assets(media.TAG).items():
        if name.startswith("claim-") and name.endswith(".json"):
            age_h = (time.time() - _ts(a.get("created_at", ""))) / 3600
            if age_h < CLAIM_H:
                out[name[6:-5]] = age_h
    return out


def _ts(iso: str) -> float:
    from datetime import datetime
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def merge_helper(store, log=_log) -> int:
    """Videos the PC finished: mark them made in the shared plan (first one wins), tidy their claims."""
    from .. import autopilot
    n = 0
    assets = store.assets(media.TAG)
    for name in [x for x in assets if x.startswith("done-") and x.endswith(".json")]:
        info = json.loads(store.get(media.TAG, name) or b"{}")
        try:
            it = next((it for s, it in autopilot.items(14, 21) if it["id"] == info.get("id")), None)
            if it and it["status"] not in ("made", "approved", "posted", "scheduled"):
                autopilot.update_item(info["start"], info["id"], status="made", made_at=info.get("made_at"),
                                      out_dir=str(ROOT / info["out_rel"]), file=info.get("file"),
                                      cloud_asset=media.asset_name(info["id"]), topic=info.get("topic"),
                                      angle=info.get("angle"), error=None, attempts=0, retry_at=None, made_by="pc")
                n += 1
        finally:
            store.delete(media.TAG, name)
            store.delete(media.TAG, f"claim-{info.get('id')}.json")
    if n:
        log(f"merged {n} video(s) made on the PC")
    return n


def ensure_media(store, log=_log) -> int:
    """Videos that need their files here soon (preview or posting): download them, point the plan at this copy."""
    from .. import autopilot
    n = 0
    soon = autopilot._now() + timedelta(hours=30)
    for start, it in autopilot.items(1, 9):
        if it["status"] not in ("made", "approved", "scheduled") or not it.get("out_dir"):
            continue
        if autopilot._when(it) > soon and it["status"] != "made":
            continue
        try:
            folder = media.ensure_local(store, it)
        except Exception as e:  # noqa: BLE001
            log(f"download {it['id']}: {e}")
            continue
        if folder and str(folder) != it["out_dir"]:
            autopilot.update_item(start, it["id"], out_dir=str(folder))
            n += 1
    return n


def snapshot(kv, log=_log) -> None:
    """Texts the Worker answers with at once (no run needed for /status)."""
    if kv is None:
        return
    from .. import telegram_bot
    # 18 Nov (owner: "telegram is not working"): every button except Today waited minutes for a cloud run. Now the
    # texts of all info buttons are kept here and the Worker answers them at once.
    texts: dict[str, str] = {}
    makers = {"tasks": telegram_bot.tasks_text, "health": telegram_bot.health_text,
              "channels": telegram_bot.channels_text,
              "heal": lambda: __import__("engine.heal", fromlist=["brief"]).brief(),
              "review": lambda: __import__("engine.daily_review", fromlist=["x"]).telegram_text(None),
              "books": lambda: __import__("engine.books", fromlist=["text"]).text()}
    for key, fn in makers.items():
        try:
            texts[key] = str(fn())[:3900]
        except Exception as e:  # noqa: BLE001 - one text missing: the Worker starts a run for that button
            log(f"snapshot {key}: {type(e).__name__}: {e}")
    try:
        from .. import autopilot
        waiting = sum(1 for _s, it in autopilot.items(2, 9) if it["status"] == "made")
    except Exception:  # noqa: BLE001
        waiting = None
    try:
        kv.put("snapshot", {"status": telegram_bot.status_text(), "texts": texts, "waiting": waiting,
                            "at": time.time()})
    except Exception as e:  # noqa: BLE001
        log(f"snapshot: {e}")


def _due_to_make(kinds: set | None, skip: set, connected_only: bool = False) -> list[tuple[str, dict]]:
    from .. import autopilot, weekly, storyboard
    now = autopilot._now()
    due = []
    pictures_out = storyboard.images_blocked()
    window = autopilot.items(OVERDUE_D, 5)
    # 18 Nov (owner: "where are the other channel's videos"): 6 channels never got a video because the soonest slots
    # always went to the same few, and a slot that passed unmade was dropped for ever. Now a missed video (up to
    # OVERDUE_D days) is still made (the missed-slot step gives it the next free slot), and the channels with the
    # fewest recent videos go first.
    recent = {}
    for _s, x in window:
        if x["status"] in ("making", "made", "approved", "posted") and x.get("kind") != "long":
            recent[x["channel"]] = recent.get(x["channel"], 0) + 1
    for s, it in window:
        if it["id"] in skip or it["status"] not in weekly.TO_MAKE or (kinds and it.get("kind") not in kinds
                                                                       and not _cloud_long(it, kinds)):
            continue
        ahead = autopilot.MAKE_AHEAD_LONG_H if it.get("kind") == "long" else autopilot.MAKE_AHEAD_H
        if not (it["status"] == "redo" or autopilot._when(it) <= now + timedelta(hours=ahead)):
            continue
        if autopilot._when(it) < now - timedelta(days=OVERDUE_D):
            continue                                       # too old: its topic has moved on
        if autopilot._when(it) <= now and any(x["channel"] == it["channel"] and x["status"] in weekly.TO_MAKE
                                               and now < autopilot._when(x) <= now + timedelta(hours=ahead)
                                               for _s2, x in window):
            continue                                       # missed, but a newer one for this channel is coming: make that
        if it["status"] == "needs_source" and not weekly.has_clip_material(it["channel"]):
            continue
        if (it.get("retry_at") or 0) > time.time() or (it.get("attempts") or 0) >= 3:
            continue
        if pictures_out and it.get("kind") in ("short", "long", "story") and _storyboarded(it["channel"]):
            continue                                       # no free pictures left today: wait, never word cards
        due.append((s, it))
    def live(it: dict) -> bool:                           # a connected account can actually post it
        c = autopilot._connected(it["channel"])
        return c["youtube"] or c["meta"]
    # owner, 14 Nov: 3 of 14 channels connected; the free cloud makes ~1-2 a day, so connected channels go first
    due.sort(key=lambda x: (x[1]["status"] != "redo", not live(x[1]), recent.get(x[1]["channel"], 0),
                            x[1]["publish_at"]))
    seen, fair = set(), []                                 # one per channel first, then the rest
    for d in due:
        if d[1]["channel"] not in seen:
            seen.add(d[1]["channel"])
            fair.append(d)
    due = fair + [d for d in due if d not in fair]
    if connected_only:
        due = [d for d in due if live(d[1])]
    return due


CLOUD_LONG_TYPES = {"kids"}                      # long videos the 4-core cloud machine makes quickly (2-2.5 min episodes)


def _cloud_long(it: dict, kinds: set | None) -> bool:
    """18 Nov (owner: no PC): kids long episodes are short and code-drawn, so the cloud makes them too. Long story
    documentaries still need the in-house picture pipeline first (handoff next step 2-3)."""
    if it.get("kind") != "long" or kinds is not CLOUD_KINDS:
        return False
    from ..config import channel
    try:
        return channel(it["channel"]).get("type") in CLOUD_LONG_TYPES
    except Exception:  # noqa: BLE001
        return False


def _storyboarded(channel_id: str) -> bool:
    from .. import storyboard
    from ..config import channel
    try:
        return storyboard.enabled(channel(channel_id))
    except Exception:  # noqa: BLE001
        return False


def _campaign_footage(store, log=_log) -> int:
    from .. import cr_footage
    n = cr_footage.merge(store, log)
    if n:
        log(f"campaigns: {n} joined, footage queued for clips")
    try:
        cr_footage.recover_sources(store, log)             # footage already in storage, back in the clip list
    except Exception as e:  # noqa: BLE001
        log(f"campaign footage recovery: {type(e).__name__}: {e}")
    return n


def make_one(start: str, it: dict, log=_log) -> dict:
    """Make one planned video here; returns the plan item with out_dir/file filled in."""
    from .. import autopilot, weekly
    brain, memory = autopilot.default_brain()
    plan = weekly.load_plan(start)
    item = next(x for x in plan["items"] if x["id"] == it["id"])
    weekly.make_item(plan, item, brain, memory=memory, log=lambda m: log("   " + str(m)))
    return item


# ---------- entry points ----------
LIVE_EVERY_H = 3                                  # public counters: often enough for the evening review


LIVE_AT = ROOT / "data" / "state" / "live_at.txt"     # inside the memory bundle (file times are not kept)


def _live_due() -> bool:
    try:
        last = float(LIVE_AT.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        last = 0.0
    if time.time() - last < LIVE_EVERY_H * 3600:
        return False
    LIVE_AT.parent.mkdir(parents=True, exist_ok=True)
    LIVE_AT.write_text(str(time.time()), encoding="utf-8")
    return True


def tick(log=_log, light: bool = False) -> None:
    """light=True (a run started by a Telegram message): only what the owner is waiting for: merge the PC's
    videos, fetch media, handle the inbox, post what is due, save. The scheduled ticks do everything."""
    from .. import autopilot
    store = Store()
    log(f"state: {state.pull(store)} files")
    try:                                                   # a login made on the PC in a coding session (18 Nov)
        state.merge_secrets(store, log=log)
    except Exception as e:  # noqa: BLE001
        log(f"secrets inbox: {type(e).__name__}: {e}")
    kv = _kv()
    from .. import books
    if light:
        steps = [("merge", lambda: merge_helper(store, log)), ("media", lambda: ensure_media(store, log)),
                 ("inbox", lambda: process_inbox(kv, log)), ("campaigns", lambda: _campaign_footage(store, log)),
                 ("post", lambda: autopilot._post_due(log))]
        for name, fn in steps:
            try:
                fn()
            except Exception as e:  # noqa: BLE001
                log(f"{name}: {type(e).__name__}: {e}")
                traceback.print_exc()
        snapshot(kv, log)
        log(f"state saved ({state.push(store) // 1024} KB)")
        return
    steps = [("recover", lambda: autopilot.recover(log)),
             ("books", books.pull_cloud_copy),             # the PC's latest KDP statuses for /books + dashboard
             # owner 15 Nov: approvals failed with "video file missing": each run starts empty, so the videos must be
             # merged and downloaded BEFORE the owner's taps are handled (approve checks the file)
             ("merge", lambda: merge_helper(store, log)),
             ("media", lambda: ensure_media(store, log)),
             ("inbox", lambda: process_inbox(kv, log)),
             # 18 Nov: logged-in jobs in the cloud (owner's session, encrypted): joined campaigns -> footage
             ("browser", lambda: __import__("engine.cloud.browser_session", fromlist=["x"]).cloud_jobs(store, log)),
             ("campaigns", lambda: _campaign_footage(store, log)),   # after the inbox: a fresh Confirm is "picked"
             ("missed", lambda: autopilot._missed(log)),
             ("preflight", lambda: __import__("engine.preflight", fromlist=["run"]).run(log=log)),   # logins
             ("post", lambda: autopilot._post_due(log)),
             ("ask", lambda: autopilot._ask_due(log)),
             ("daily", lambda: autopilot._daily(log)),
             ("sources", lambda: autopilot._needs_source_notice(log)),
             ("thumbs", lambda: autopilot._shorts_thumbnails(log)),
             ("live_stats", lambda: _live_due() and __import__("engine.stats_fetch", fromlist=["live"]).live(log=log)),
             ("plan", lambda: autopilot._ensure_plan(autopilot.default_brain, log))]
    errors: dict[str, str] = {}
    for name, fn in steps:
        try:
            fn()
        except Exception as e:  # noqa: BLE001 - one failing step must not stop the others
            log(f"{name}: {type(e).__name__}: {e}")
            errors[name] = redact(f"{type(e).__name__}: {e}")
            traceback.print_exc()
    try:                                                   # 17 Nov: nothing may break silently again
        from .. import watchdog
        watchdog.record_steps(errors, [n for n, _ in steps])
        watchdog.run(store, log=log)
    except Exception as e:  # noqa: BLE001
        log(f"watchdog: {type(e).__name__}: {e}")
    try:                                                   # 18 Nov: code problems -> "Heal and Improve the system"
        from .. import heal
        heal.notify_due()
    except Exception as e:  # noqa: BLE001
        log(f"heal: {type(e).__name__}: {e}")
    snapshot(kv, log)
    log(f"state saved ({state.push(store) // 1024} KB)")


def _inbox_between(store, log=_log) -> int:
    """18 Nov (owner: "telegram is not working"): a render holds the shared-memory lock for up to 90 minutes, so the
    owner's taps waited behind it. The render now answers them between videos (same code as the tick's inbox step)."""
    kv = _kv()
    if kv is None or not kv.keys("upd:"):
        return 0
    try:
        ensure_media(store, log)                           # approvals check the video file
        return process_inbox(kv, log)
    except Exception as e:  # noqa: BLE001 - the render goes on either way
        log(f"inbox during render: {type(e).__name__}: {e}")
        return 0


def render(budget_min: float = 40, log=_log) -> int:
    """Make the soonest unclaimed Shorts within the time budget (the free minutes are shared with the ticks)."""
    from .. import autopilot
    store = Store()
    state.pull(store)
    try:
        merge_helper(store, log)
    except Exception as e:  # noqa: BLE001
        log(f"merge: {e}")
    _inbox_between(store, log)
    t0, made = time.time(), 0
    while (time.time() - t0) / 60 < budget_min * 0.6:      # don't start one we can't finish
        due = _due_to_make(CLOUD_KINDS, set(claims(store)), connected_only=True)   # scarce cloud minutes
        if not due:
            break
        start, it = due[0]
        autopilot.update_item(start, it["id"], status="making", making_by="cloud")
        state.push(store)                                  # the PC sees it's taken
        try:
            item = make_one(start, it, log)
            folder = Path(item["out_dir"])
            media.upload(store, item["id"], folder)
            autopilot.update_item(start, item["id"], status="made", made_at=time.time(), out_dir=item["out_dir"],
                                  file=item.get("file"), cloud_asset=media.asset_name(item["id"]), error=None,
                                  attempts=0, retry_at=None, topic=item.get("topic"), angle=item.get("angle"),
                                  made_by="cloud")
            made += 1
            log(f"made {item.get('channel_name')} in {(time.time() - t0) / 60:.0f} min")
        except Exception as e:  # noqa: BLE001
            wait = autopilot.free_limit_wait(e)
            if wait:                                       # a daily free limit: wait for the reset, keep the tries
                autopilot.update_item(start, it["id"], status="failed", error=f"{type(e).__name__}: {e}", retry_at=wait)
                log(f"{it.get('channel_name')}: free limit reached; waits until the reset")
                if type(e).__name__ == "NoPictures":
                    state.push(store)
                    continue                               # other kinds (Brain Snack, kids, clips) need no pictures
            else:
                n = (it.get("attempts") or 0) + 1
                autopilot.update_item(start, it["id"], status="failed", error=f"{type(e).__name__}: {e}", attempts=n,
                                      retry_at=time.time() + 3600)
            traceback.print_exc()
        _inbox_between(store, log)
        state.push(store)
    try:
        autopilot._ask_due(log)                            # previews for what was just made
    except Exception as e:  # noqa: BLE001
        log(f"ask: {e}")
    snapshot(_kv(), log)                                   # the Worker's instant answers see the new videos
    state.push(store)
    return made


PIN_STATE = ROOT / "data" / "state" / "pins_day.txt"


def _daily_pins(log=_log, per_day: int = 2) -> int:
    """Once a day (owner, 14 Nov: Pinterest marketing, automatically): post the next pins while the co-pilot
    Chrome is open. Research: a steady few pins a day beat bursts."""
    import urllib.request
    today = time.strftime("%Y-%m-%d")
    if PIN_STATE.exists() and PIN_STATE.read_text(encoding="utf-8").strip() == today:
        return 0
    try:
        urllib.request.urlopen("http://127.0.0.1:9333/json/version", timeout=3).read()
    except OSError:
        return 0                                           # co-pilot Chrome not open: try again later
    from .. import pinterest_post
    out = pinterest_post.post(per_day, log=log)
    PIN_STATE.parent.mkdir(parents=True, exist_ok=True)
    PIN_STATE.write_text(today, encoding="utf-8")
    return sum(1 for x in out if x.startswith("pinned"))


BOOKS_STATE = ROOT / "data" / "state" / "books_job.txt"


def _books_job(log=_log, every_h: float = 3) -> int:
    """Every few hours while the co-pilot Chrome is open (owner, 15 Nov: books automated, verified in Telegram):
    publish books the owner approved with ✅, refresh KDP statuses, message changes, ask about ready books."""
    import urllib.request
    last = float(BOOKS_STATE.read_text(encoding="utf-8")) if BOOKS_STATE.exists() else 0
    if time.time() - last < every_h * 3600:
        return 0
    try:
        urllib.request.urlopen("http://127.0.0.1:9333/json/version", timeout=3).read()
    except OSError:
        return 0                                           # co-pilot Chrome not open: try again later
    from .. import books
    BOOKS_STATE.parent.mkdir(parents=True, exist_ok=True)
    BOOKS_STATE.write_text(str(time.time()), encoding="utf-8")
    return len(books.pc_job(log=log))


_HELPER_LOCK: list = []


def _one_helper(port: int = 47614) -> bool:
    """17 Nov: the start-up helper and a manually started one ran together. A local port works as the lock and is
    freed automatically when the process ends (even after a crash)."""
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", port))
        sock.listen(1)
    except OSError:
        sock.close()
        return False
    _HELPER_LOCK.append(sock)
    return True


def helper(once: bool = False, every_s: int = 300, log=_log) -> None:
    """The PC as helper: whenever it is on, make the next unclaimed videos (any length) and hand them to the cloud."""
    from .. import autopilot
    if not _one_helper():
        log("Another PC helper is already running on this PC; this copy stops (two would make videos twice).")
        return
    log("PC helper: making videos for the cloud (Ctrl+C to stop; the cloud keeps running without the PC)")
    while True:
        try:
            _daily_pins(log)                               # Pinterest needs the signed-in PC browser
        except Exception as e:  # noqa: BLE001 - marketing never stops video making
            log(f"pins: {e}")
        try:
            _books_job(log)                                # KDP needs the signed-in PC browser too
        except Exception as e:  # noqa: BLE001
            log(f"books: {e}")
        try:
            from .. import books_v2                        # owner 17 Nov: redesigned books from leftover night quota
            log("book art: " + books_v2.ensure_night_worker(log))     # cloud + night backup (owner 18 Nov)
        except Exception as e:  # noqa: BLE001
            log(f"book art: {e}")
        try:                                               # the logged-in session -> the cloud (18 Nov)
            from .browser_session import export
            export(Store(), log)
        except Exception as e:  # noqa: BLE001
            log(f"browser session: {e}")
        try:                                               # .env changed on the PC -> the cloud gets it (18 Nov)
            from .setup import sync_env_secret
            sync_env_secret(log)
        except Exception as e:  # noqa: BLE001
            log(f"cloud keys: {e}")
        try:
            _ensure_chrome(log)
        except Exception as e:  # noqa: BLE001
            log(f"chrome: {e}")
        try:
            store = Store()
            try:
                from .. import cr_footage, watchdog
                watchdog.helper_heartbeat(store, cr_footage.chrome_up())
            except Exception as e:  # noqa: BLE001
                log(f"heartbeat: {e}")
            state.pull(store)                              # read-only copy of the cloud's plan
            try:                                           # joined campaigns: their footage links (signed-in browser)
                from .. import cr_footage
                if cr_footage.pc_job(store, log):
                    _wake_cloud(log)
            except Exception as e:  # noqa: BLE001
                log(f"campaign footage: {e}")
            taken = set(claims(store))
            # clips stay in the cloud: their spare-clip pool lives in the cloud memory, which the PC only reads
            due = [(s, it) for s, it in _due_to_make(None, taken) if it["status"] != "making" and it.get("kind") != "clip"]
            if due:
                start, it = due[0]
                store.put(media.TAG, f"claim-{it['id']}.json", json.dumps({"id": it["id"], "at": time.time()}).encode())
                log(f"making {it.get('channel_name')} {it.get('kind')}")
                item = make_one(start, it, log)
                folder = Path(item["out_dir"])
                media.upload(store, item["id"], folder)
                store.put(media.TAG, f"done-{item['id']}.json", json.dumps({
                    "id": item["id"], "start": start, "out_rel": media.rel_out(folder), "file": item.get("file"),
                    "topic": item.get("topic"), "angle": item.get("angle"), "made_at": time.time()}).encode())
                _wake_cloud(log)
                continue                                   # straight to the next one while the PC is on
        except KeyboardInterrupt:
            raise
        except Exception as e:  # noqa: BLE001 - the helper must keep going
            log(f"helper: {type(e).__name__}: {e}")
        if once:
            return
        time.sleep(every_s)


CHROME_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/157.0.0.0 "
             "Safari/537.36")


def _ensure_chrome(log=_log) -> bool:
    """17 Nov: the HookHouse Chrome window was closed and campaign joins went unseen. Reopen it (same signed-in
    profile, debugging port 9333) whenever it is closed; Windows only."""
    import os
    import subprocess
    import sys
    from .. import cr_footage
    if cr_footage.chrome_up() or not sys.platform.startswith("win"):
        return True
    exe = next((p for p in (r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                            os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"))
                if Path(p).exists()), None)
    if not exe:
        return False
    # 17 Nov (owner: "it pops up again and again"): no window at all. Headless with the same signed-in profile and a
    # normal Chrome user agent (YouTube Studio refuses "HeadlessChrome").
    subprocess.Popen([exe, "--headless=new", "--remote-debugging-port=9333",
                      f"--user-data-dir={ROOT / 'data' / 'browser_profile'}", "--no-first-run", "--window-size=1280,900",
                      "--disable-background-timer-throttling", "--disable-renderer-backgrounding",
                      f"--user-agent={CHROME_UA}", "about:blank"],
                     creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
    for _ in range(15):
        time.sleep(2)
        if cr_footage.chrome_up():
            log("HookHouse Chrome was closed: reopened it")
            return True
    return False


def _wake_cloud(log=_log) -> None:
    """Ask GitHub to run a tick now (so the preview reaches the phone quickly)."""
    import requests
    try:
        from .store import code_repo, token
        requests.post(f"https://api.github.com/repos/{code_repo()}/dispatches", timeout=20,
                      headers={"Authorization": f"Bearer {token()}", "Accept": "application/vnd.github+json"},
                      json={"event_type": "tick"})
    except Exception as e:  # noqa: BLE001
        log(f"wake: {e}")


def cloud_enabled() -> bool:
    return os.environ.get("HOOKHOUSE_CLOUD", "").strip() in ("1", "true", "yes")
