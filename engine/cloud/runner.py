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

import threading

# 20 Nov (owner: "our system must not crash or fail by any means"): GitHub kills a tick at timeout-minutes (30, see
# .github/workflows/tick.yml) WITHOUT running the final save, so everything the run did (posts in the publish log,
# decisions, queue jobs) would be lost and the next run could post again. The guard saves first, then ends the run
# cleanly. 22 min leaves room for the job's setup steps and the save's own retries.
TICK_DEADLINE_S = float(os.environ.get("TICK_DEADLINE_S", str(22 * 60)))
SLOW_STEP_S = 300.0
_SAVE_LOCK = threading.Lock()
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


def _dash_buttons(kv, log=_log) -> int:
    """Taps on the live dashboard (Approve / Upload now / Change / Reject / Make now), same code as the PC stand-in;
    the cloud then also republishes the page so the owner sees the new state."""
    if kv is None or not kv.keys("cmd:"):
        return 0
    from .. import pc_fallback
    n = pc_fallback.process_commands(kv, log)
    try:
        pc_fallback.publish_dashboard(kv, log)
    except Exception as e:  # noqa: BLE001
        log(f"dashboard: {type(e).__name__}: {e}")
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
                                      angle=info.get("angle"), error=None, attempts=0, retry_at=None, made_by="pc",
                                      feeling=info.get("feeling"), now_hook=info.get("now_hook"),
                                      planned_topic=info.get("planned_topic"), made_as=info.get("made_as"),
                                      clip_source=info.get("clip_source"))
                n += 1
                done_with = [x for x in [info.get("clip_source"), *(info.get("clip_skipped") or [])] if x]
                if done_with:                              # 20 Nov: footage the PC cut or found unusable: never again
                    from .. import weekly
                    cs = weekly.clip_state()
                    new = [x for x in done_with if x not in cs["used"]]
                    if new:
                        cs["used"].extend(new)
                        weekly.save_clip_state(cs)
                rec = info.get("training")                 # 19 Nov: PC-made videos join the cloud's learning loops
                if rec:
                    from ..training_data import DIR, SCRIPTS
                    DIR.mkdir(parents=True, exist_ok=True)
                    with SCRIPTS.open("a", encoding="utf-8") as fh:
                        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    if rec.get("hook_type"):
                        from ..content_tuning import record_hook
                        record_hook(info["id"], it["channel"], rec["hook_type"])
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


def run_replans(log=_log) -> int:
    """config/replan.yaml requests, each run ONCE (state replans): the listed channels' slots in this and next week's
    plans are planned again (19 Nov: Stream Clips switched from clips to GTA facts and still had clip slots)."""
    import yaml
    from datetime import date
    from .. import autopilot, weekly
    from ..config import CONFIG_DIR
    p = CONFIG_DIR / "replan.yaml"
    if not p.exists():
        return 0
    reqs = (yaml.safe_load(p.read_text(encoding="utf-8")) or {}).get("requests") or []
    done = autopilot._load().get("replans", {})
    today = autopilot._now().date()
    monday = today - timedelta(days=today.weekday())
    n = 0
    for r in reqs:
        rid, chans = str(r.get("id") or ""), list(r.get("channels") or [])
        redo = [str(x) for x in r.get("redo") or []]
        if not rid or not (chans or redo) or rid in done:
            continue
        autopilot._update_state(lambda st, k=rid: st.setdefault("replans", {}).__setitem__(k, time.time()))  # once
        if redo:          # 20 Nov: made videos that no longer meet the brief are made again (never posted ones only)
            for s, it in autopilot.items(7, 14):
                if it["id"] in redo and it["status"] in ("made", "missed", "failed") and not it.get("youtube_id"):
                    autopilot.update_item(s, it["id"], status="redo", note=str(r.get("note") or "remake"),
                                          attempts=0, retry_at=None)
                    log(f"re-make {rid}: {it['id']}")
            n += 1
        if not chans:
            continue
        brain, memory = autopilot.default_brain()
        weeks = [w for w in (p2.name for p2 in weekly.WEEKS_DIR.glob("*") if (p2 / "plan.json").exists())
                 if monday <= date.fromisoformat(w) <= monday + timedelta(days=7)] if weekly.WEEKS_DIR.exists() else []
        for w in sorted(weeks):
            weekly.plan_week(brain, date.fromisoformat(w), only=chans, memory=memory, log=log)
        log(f"re-plan {rid}: {', '.join(chans)} in week(s) {', '.join(weeks) or 'none'}")
        n += 1
    return n


CATCH_UP_DAYS = 7
CATCH_UP_PLATFORMS = ("instagram", "facebook", "threads", "dailymotion")


def posted_platforms(item_id: str) -> set[str]:
    """Platforms the publish log shows this video already went to (real posts only)."""
    from ..publish import LOG
    done = set()
    try:
        for ln in LOG.read_text(encoding="utf-8").splitlines():
            try:
                a = json.loads(ln)
            except ValueError:
                continue
            if a.get("item_id") == item_id and a.get("done") and not (a.get("details") or {}).get("dry_run") \
                    and not str(a.get("what", "")).startswith(("delete", "captions", "thumbnail", "add ")):
                done.add(a.get("platform"))
    except OSError:
        pass
    return done


def catch_up_platforms(store, log=_log, max_per_run: int = 4) -> int:
    """Owner 19 Nov: "the already approved videos should also be uploaded on the platforms that did not get them, do
    not upload the same thing again and again". Posted videos of the last CATCH_UP_DAYS go once to each platform the
    publish log shows they never reached (an account connected later). Each video x platform is tried ONCE (state
    catch_up), so a platform that isn't connected can't make it repeat or double post."""
    from .. import autopilot
    from ..publish import upload_item
    s = autopilot._load()
    tried = s.get("catch_up", {})
    cutoff, n = time.time() - CATCH_UP_DAYS * 86400, 0
    for start, it in autopilot.items(CATCH_UP_DAYS + 1, 0):
        if n >= max_per_run:
            break
        if it.get("status") != "posted" or (it.get("posted_at") or 0) < cutoff:
            continue
        missing = [p for p in CATCH_UP_PLATFORMS
                   if p not in posted_platforms(it["id"]) and f"{it['id']}|{p}" not in tried]
        if not missing:
            continue
        for p in missing:                                  # record first: never twice, even if the upload crashes
            autopilot._update_state(lambda st, k=f"{it['id']}|{p}": st.setdefault("catch_up", {}).__setitem__(k, time.time()))
        try:
            folder = media.ensure_local(store, it)
        except Exception as e:  # noqa: BLE001
            log(f"catch-up {it['id']}: no video file ({e})")
            continue
        if not folder:
            continue
        acts = upload_item(dict(it, out_dir=str(folder)), dry_run=False, platforms=tuple(missing), publish_at=None)
        got = [a.platform for a in acts if a.done and a.item_id and not a.what.startswith("SKIPPED")]
        if got:
            n += 1
            log(f"catch-up {it['id']}: now also on {', '.join(got)}")
    return n


def snapshot(kv, log=_log) -> None:
    """Texts the Worker answers with at once (no run needed for /status)."""
    if kv is None:
        return
    from .. import telegram_bot
    # 18 Nov (owner: "telegram is not working"): every button except Today waited minutes for a cloud run. Now the
    # texts of all info buttons are kept here and the Worker answers them at once.
    texts: dict[str, str] = {}
    def _health():                                          # 20 Nov: + the posting queue and the volume plan
        parts = [telegram_bot.health_text()]
        for mod in ("publish_queue", "allocator"):
            try:
                parts.append(__import__(f"engine.{mod}", fromlist=["text"]).text())
            except Exception as e:  # noqa: BLE001 - health still answers without this part
                log(f"snapshot {mod}: {type(e).__name__}: {e}")
        try:                                                # 20 Nov: Cloudflare KV daily budget
            from .kv_budget import status as kv_status
            parts.append(kv_status())
        except Exception as e:  # noqa: BLE001
            log(f"snapshot kv budget: {type(e).__name__}: {e}")
        return "\n\n".join(parts)
    makers = {"tasks": telegram_bot.tasks_text, "health": _health,
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
    try:                                                   # 20 Nov: 📥 Waiting for me answers at once with cards
        queue = telegram_bot.queue_cards()
    except Exception as e:  # noqa: BLE001 - without it the Worker starts a run for the button
        log(f"snapshot queue: {type(e).__name__}: {e}")
        queue = None
    try:
        snap = {"status": telegram_bot.status_text(), "texts": texts, "waiting": waiting, "queue": queue,
                "at": time.time()}
        if hasattr(kv, "put_if_changed"):                  # 20 Nov: KV budget (1,000 writes/day on the free plan)
            kv.put_if_changed("snapshot", snap, refresh_s=3600, normalize=lambda t: re.sub(r'"at": [0-9.]+', "", t))
        else:
            kv.put("snapshot", snap)
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
        if pictures_out and it.get("kind") in ("short", "long", "story") and _storyboarded(it["channel"]) \
                and not _clip_slot(it):
            continue                                       # no free pictures left today: wait, never word cards
            # (a clip slot cuts campaign footage and needs no pictures, 20 Nov)
        due.append((s, it))
    def live(it: dict) -> bool:                           # a connected account can actually post it
        c = autopilot._connected(it["channel"])
        return c["youtube"] or c["meta"]
    # owner, 14 Nov: 3 of 14 channels connected; the free cloud makes ~1-2 a day, so connected channels go first
    # 20 Nov (owner: "clipping is our main agenda", "make the first GTA clips now"): a connected channel's campaign
    # clip slot goes first; campaigns pay only while they run and their footage goes stale in days
    clip_first = {d[1]["id"] for d in due if live(d[1]) and _clip_slot(d[1])}
    due.sort(key=lambda x: (x[1]["status"] != "redo", x[1]["id"] not in clip_first, not live(x[1]),
                            recent.get(x[1]["channel"], 0), x[1]["publish_at"]))
    clips = [d for d in due if d[1]["id"] in clip_first]
    seen, fair = set(), []                                 # one per channel first, then the rest
    for d in due:
        if d[1]["id"] not in clip_first and d[1]["channel"] not in seen:
            seen.add(d[1]["channel"])
            fair.append(d)
    due = clips + fair + [d for d in due if d not in fair and d not in clips]
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


def _clip_slot(it: dict) -> bool:
    from .. import weekly
    from ..config import channel
    try:
        return weekly.clip_slot(channel(it["channel"]), it)
    except Exception as e:  # noqa: BLE001 - a broken clip check never stops the queue
        _log(f"clip slot check {it.get('id')}: {type(e).__name__}: {e}")
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
    try:                                                   # 20 Nov: owner-picked campaigns (config) into the database
        cr_footage.ensure_config_campaigns(log=log)
    except Exception as e:  # noqa: BLE001
        log(f"picked campaigns: {e}")
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


def deadline_guard(store, log=_log, deadline_s: float | None = None, exit_fn=None, push=None):
    """Start the deadline timer; returns it (cancel() it before the normal save)."""
    secs = TICK_DEADLINE_S if deadline_s is None else deadline_s

    def fire():
        if not _SAVE_LOCK.acquire(timeout=5):          # the normal save is already running: let it finish
            return
        try:
            log(f"deadline: {secs:.0f}s reached; saving the state before GitHub stops this run")
            try:
                from ..core import ledger
                ledger.event("tick.deadline", data={"after_s": secs})
                from .. import heal
                heal.report("tick", f"a cloud run hit the {secs:.0f}s deadline (a step is too slow or hung)")
            except Exception as e:  # noqa: BLE001 - the save matters more than the report
                log(f"deadline report: {type(e).__name__}: {e}")
            kb = (push or state.push)(store) // 1024
            log(f"state saved at the deadline ({kb} KB)")
        except Exception as e:  # noqa: BLE001
            log(f"deadline save failed: {type(e).__name__}: {e}")
        finally:
            (exit_fn or os._exit)(0)
    t = threading.Timer(secs, fire)
    t.daemon = True
    t.start()
    return t


def _run_steps(steps, log, errors: dict | None = None) -> None:
    """Each step isolated (one failure never stops the others) and timed (slow steps show in the log/ledger)."""
    for name, fn in steps:
        t0 = time.time()
        try:
            fn()
        except Exception as e:  # noqa: BLE001 - one failing step must not stop the others
            log(f"{name}: {type(e).__name__}: {e}")
            if errors is not None:
                errors[name] = redact(f"{type(e).__name__}: {e}")
            traceback.print_exc()
        dur = time.time() - t0
        if dur > SLOW_STEP_S:
            log(f"{name}: slow step ({dur:.0f}s)")
            try:
                from ..core import ledger
                ledger.event("step.slow", data={"step": name, "seconds": round(dur)})
            except Exception as e:  # noqa: BLE001
                log(f"ledger: {type(e).__name__}: {e}")


def tick(log=_log, light: bool = False) -> None:
    """light=True (a run started by a Telegram message): only what the owner is waiting for: merge the PC's
    videos, fetch media, handle the inbox, post what is due, save. The scheduled ticks do everything."""
    from .. import autopilot
    store = Store()
    log(f"state: {state.pull(store)} files")
    guard = deadline_guard(store, log)
    try:                                                   # a login made on the PC in a coding session (18 Nov)
        state.merge_secrets(store, log=log)
    except Exception as e:  # noqa: BLE001
        log(f"secrets inbox: {type(e).__name__}: {e}")
    kv = _kv()
    from .. import books
    if light:
        steps = [("merge", lambda: merge_helper(store, log)), ("media", lambda: ensure_media(store, log)),
                 ("inbox", lambda: process_inbox(kv, log)),
                 ("buttons", lambda: _dash_buttons(kv, log)),     # dashboard taps (Worker /cmd)
                 ("campaigns", lambda: _campaign_footage(store, log)),
                 ("post", lambda: autopilot._post_due(log))]
        _run_steps(steps, log)
        guard.cancel()
        with _SAVE_LOCK:
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
             ("buttons", lambda: _dash_buttons(kv, log)),         # dashboard taps (Worker /cmd)
             # 18 Nov: logged-in jobs in the cloud (owner's session, encrypted): joined campaigns -> footage
             ("browser", lambda: __import__("engine.cloud.browser_session", fromlist=["x"]).cloud_jobs(store, log)),
             ("campaigns", lambda: _campaign_footage(store, log)),   # after the inbox: a fresh Confirm is "picked"
             ("missed", lambda: autopilot._missed(log)),
             ("preflight", lambda: __import__("engine.preflight", fromlist=["run"]).run(log=log)),   # logins
             ("post", lambda: autopilot._post_due(log)),
             ("catch_up", lambda: catch_up_platforms(store, log)),   # 19 Nov: platforms connected after posting
             ("ask", lambda: autopilot._ask_due(log)),
             ("daily", lambda: autopilot._daily(log)),
             ("sources", lambda: autopilot._needs_source_notice(log)),
             ("thumbs", lambda: autopilot._shorts_thumbnails(log)),
             ("live_stats", lambda: _live_due() and __import__("engine.stats_fetch", fromlist=["live"]).live(log=log)),
             ("plan", lambda: autopilot._ensure_plan(autopilot.default_brain, log)),
             ("replan", lambda: run_replans(log)),       # config/replan.yaml, each request once (19 Nov)
             # 19 Nov: book pages from leftover free picture quota at night (API calls only, a few per tick)
             ("book_pages", lambda: log("book pages: " + __import__("engine.cloud.book_farm", fromlist=["x"])
                                        .quota_pages(store, log=log))),
             # 19 Nov: the live dashboard (page + review-player previews) is the cloud's job again after the outage
             ("dashboard", lambda: __import__("engine.pc_fallback", fromlist=["x"]).publish_dashboard(kv, log))]
    errors: dict[str, str] = {}
    _run_steps(steps, log, errors)
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
    guard.cancel()
    try:                                                   # Phase 1 dual-write: the tick's last rows go out now
        from ..core.ledger import default as _ledger
        n = _ledger().flush_shadow(log)
        if n:
            log(f"shared truth: {n} ledger rows mirrored")
    except Exception as e:  # noqa: BLE001 - shadow copy only; rows stay queued in ledger.db
        log(f"shared truth: {type(e).__name__}: {e}")
    with _SAVE_LOCK:
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
                                  planned_topic=item.get("planned_topic"), feeling=item.get("feeling"),
                                  now_hook=item.get("now_hook"), made_by="cloud")
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


class _SkipClaim(Exception):
    """This helper loop takes no new work (for example the disk is low); it waits and tries again."""


def _code_version(root: Path | None = None) -> str:
    """The commit this PC's code is on, read straight from .git ("" when unknown). 21 Nov: the helper is one long
    process, so pushed fixes (e.g. the S10 humanize pass) never reached the PC maker until someone restarted it."""
    git = (root or ROOT) / ".git"
    try:
        head = (git / "HEAD").read_text(encoding="utf-8").strip()
        if not head.startswith("ref: "):
            return head                                    # detached HEAD: the hash itself
        ref = head[5:]
        if (git / ref).exists():
            return (git / ref).read_text(encoding="utf-8").strip()
        for line in (git / "packed-refs").read_text(encoding="utf-8").splitlines():
            if line.endswith(" " + ref):
                return line.split()[0]
    except OSError:
        pass
    return ""


def _new_code(started: str, root: Path | None = None) -> bool:
    """True when the code on disk moved to another commit since the helper started (checked between videos only)."""
    now = _code_version(root)
    return bool(started and now and now != started)


def helper(once: bool = False, every_s: int = 300, log=_log, videos_only: bool = False) -> None:
    """The PC as helper: whenever it is on, make the next unclaimed videos (any length) and hand them to the cloud.
    videos_only (owner 19 Nov, option A: "start making videos now"): the PC only makes videos; posting, Telegram,
    the dashboard and every other job stay in the cloud (GitHub Actions stays light: one render a day there)."""
    if not _one_helper():
        log("Another PC helper is already running on this PC; this copy stops (two would make videos twice).")
        return
    log("PC helper: making videos for the cloud (Ctrl+C to stop; the cloud keeps running without the PC)"
        + (" [videos only]" if videos_only else ""))
    started = _code_version()
    while True:
        if not once and _new_code(started):           # between videos only: never cuts a video short
            log("helper: new code on this PC; stopping so the wrapper starts it again with the new code")
            return                                    # scripts/pc_maker.cmd restarts it after a minute
        if videos_only:
            _ensure_chrome(log)
        try:
            if not videos_only:
                _daily_pins(log)                           # Pinterest needs the signed-in PC browser
        except Exception as e:  # noqa: BLE001 - marketing never stops video making
            log(f"pins: {e}")
        if not videos_only:
            try:
                _books_job(log)                            # KDP needs the signed-in PC browser too
            except Exception as e:  # noqa: BLE001
                log(f"books: {e}")
            try:
                from .. import books_v2                    # owner 17 Nov: redesigned books from leftover night quota
                log("book art: " + books_v2.ensure_night_worker(log))     # cloud + night backup (owner 18 Nov)
            except Exception as e:  # noqa: BLE001
                log(f"book art: {e}")
            try:                                           # the logged-in session -> the cloud (18 Nov)
                from .browser_session import export
                export(Store(), log)
            except Exception as e:  # noqa: BLE001
                log(f"browser session: {e}")
            try:                                           # .env changed on the PC -> the cloud gets it (18 Nov)
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
                from . import pc_outbox
                watchdog.helper_heartbeat(store, cr_footage.chrome_up(), alerts=pc_outbox.alerts())
            except Exception as e:  # noqa: BLE001
                log(f"heartbeat: {e}")
            state.pull(store)                              # read-only copy of the cloud's plan
            try:                                           # joined campaigns: their footage links (signed-in browser)
                from .. import cr_footage
                if cr_footage.pc_job(store, log):
                    _wake_cloud(log)
            except Exception as e:  # noqa: BLE001
                log(f"campaign footage: {e}")
            try:                                           # 20 Nov: Kick clips of owner-picked campaigns (hourly)
                from .. import cr_footage
                cr_footage.ensure_config_campaigns(log=log)   # local copy, so the PC can cut them too
                if cr_footage.kick_job(store, log):
                    _wake_cloud(log)
                cr_footage.recover_sources(store, log)
            except Exception as e:  # noqa: BLE001
                log(f"kick footage: {e}")
            from . import pc_outbox                        # P0 4b: finished videos waiting for their upload
            if pc_outbox.flush(store, log):
                _wake_cloud(log)
            if not pc_outbox.disk_ok(log):                 # P0 4c: no new work on a full disk
                raise _SkipClaim("disk low")
            taken = set(claims(store)) | {r["id"] for r in pc_outbox.pending()}
            # clips stay in the cloud: their spare-clip pool lives in the cloud memory, which the PC only reads
            due = [(s, it) for s, it in _due_to_make(None, taken) if it["status"] != "making" and it.get("kind") != "clip"]
            if due:
                start, it = due[0]
                store.put(media.TAG, f"claim-{it['id']}.json", json.dumps({"id": it["id"], "at": time.time()}).encode())
                log(f"making {it.get('channel_name')} {it.get('kind')}")
                item = make_one(start, it, log)
                folder = Path(item["out_dir"])
                try:
                    from ..training_data import _scripts
                    training = _scripts().get(item["id"])
                except Exception as e:  # noqa: BLE001 - the video still goes up without its training record
                    log(f"training record: {type(e).__name__}: {e}")
                    training = None
                pc_outbox.add(item["id"], folder, {    # saved before the upload: a failed upload never means a remake
                    "id": item["id"], "start": start, "out_rel": media.rel_out(folder), "file": item.get("file"),
                    "topic": item.get("topic"), "angle": item.get("angle"), "made_at": time.time(),
                    "feeling": item.get("feeling"), "now_hook": item.get("now_hook"),
                    "planned_topic": item.get("planned_topic"), "training": training,
                    "clip_source": item.get("clip_source"), "clip_skipped": item.get("clip_skipped"),
                    "made_as": item.get("made_as")})
                if pc_outbox.flush(store, log):
                    _wake_cloud(log)
                continue                                   # straight to the next one while the PC is on
        except _SkipClaim as e:
            log(f"helper: no new work this round ({e})")
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
