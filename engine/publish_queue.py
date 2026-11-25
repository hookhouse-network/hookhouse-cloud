"""The publish queue (docs/ARCHITECTURE.md, phase 3: outbox publishing).

Owner, 20 Nov: "prepare a queue that keeps uploading, so we can earn from everywhere".

Before: at its slot a video went to every platform in one go. If ANY platform worked, the whole video counted as
posted, so a platform that failed (an Instagram blip, a Facebook timeout) was never tried again: that earning was
lost. Limits (Facebook's 30 a day, the YouTube quota) failed the post instead of delaying it.

Now every (video, platform) is its own job in the ledger, key `post:<item>:<platform>` (idempotent: enqueueing twice
is a no-op, so a crash or a second tick never double-posts):
- Before posting, the publish log is asked whether this version is already on that platform (reconciliation after a
  crash between the API answer and the save): yes -> the job completes without posting again.
- The governor (core/governor.py) checks the account's budget: over a limit or too soon after the last post -> the
  job waits for the reset (no attempt used).
- Transient errors retry with capped exponential backoff + jitter; rule skips (kids never on Instagram, a campaign
  brief without that platform, a Reel too long) complete as skipped; after MAX_ATTEMPTS the job is dead: the owner
  gets one message and the heal queue gets the error.
One upload_item call per video per run (all of its due platforms together), so Threads still gets the Instagram
Reel's id when both go out together."""
from __future__ import annotations

import re
import time

from .core import ledger
from .core.governor import Governor

KIND = "post"
MAX_ATTEMPTS = 5
LEASE_S = 1800.0
PLATFORMS = ("youtube", "instagram", "threads", "facebook", "dailymotion", "telegram")
_QUOTA = re.compile(r"limit|quota|rate.?limit|too many|429|spam|try again later", re.I)
_PERMANENT = re.compile(r"not connected|no credentials|no login|longer than|must be \d|unsupported|no permission record"
                        r"|fact-check|never-topic", re.I)


def _ver(it: dict) -> str:
    return str(int(float(it.get("made_at") or 0)))


def key(item_id: str, platform: str, version: str = "0") -> str:
    """One job per video VERSION and platform: a remade video (after Change or a gate redo) gets fresh jobs."""
    return f"post:{item_id}:{version}:{platform}"


def enqueue(start: str, it: dict, platforms, run_after: float = 0.0, led=None) -> int:
    """Queue one job per platform; returns how many were new."""
    led = led or ledger.default()
    n = 0
    for p in platforms:
        if led.enqueue(KIND, key(it["id"], p, _ver(it)), {"start": start, "item": it["id"], "platform": p,
                                                          "channel": it.get("channel"), "version": _ver(it)},
                       run_after=run_after, max_attempts=MAX_ATTEMPTS):
            n += 1
    if n:
        ledger.event("post.queued", item=it["id"], channel=it.get("channel") or "", data={"platforms": list(platforms)})
    return n


def queued(item_id: str, led=None, version: str | None = None) -> list[dict]:
    """This video's post jobs (any state); only one version's when given."""
    led = led or ledger.default()
    pre = f"post:{item_id}:" + (f"{version}:" if version is not None else "")
    return [j for j in led.jobs(kind=KIND) if j["key"].startswith(pre)]


def _main_action(acts, platform: str):
    """The platform's own post (not captions, playlist, thumbnail or the Story teaser)."""
    return next((a for a in acts if a.platform == platform and a.item_id and "Story" not in a.what), None)


def classify(act) -> tuple[str, str]:
    """('done'|'skipped'|'quota'|'permanent'|'transient', reason)."""
    if act is None:
        return "skipped", "nothing to post on this platform (no file for it or not set up)"
    if act.done:
        return "done", ""
    err = str((act.result or {}).get("error") or "")
    if act.what.startswith("BLOCKED"):                     # the content gate (engine/content_gate.py)
        probs = [str(x) for x in (act.details or {}).get("problems") or []] or [err]
        if all(re.search(r"not allowed on|never go to|lists no platforms", x) for x in probs):
            return "skipped", err                          # the rules never allow this platform
        if any(re.search(r"could not|not checked yet|budget is left|campaign is |payer on hold|unreadable", x)
               for x in probs):
            return "transient", err                        # may clear by itself: check again later
        return "permanent", err                            # needs a fix or a remake: owner + heal queue
    if act.what.startswith("SKIPPED"):
        return ("quota", act.what) if _QUOTA.search(act.what) else ("skipped", act.what)
    if (act.details or {}).get("dry_run") and not err:
        return "skipped", act.what
    if _QUOTA.search(err):
        return "quota", err
    if _PERMANENT.search(err):
        return "permanent", err
    return "transient", err or "no answer"


def drain(log=print, worker: str = "cloud", limit: int = 60, now: float | None = None, led=None,
          governor: Governor | None = None, allow=None) -> dict:
    """Post every due job (within the governor's budgets). allow(item) -> bool: only these videos (others are
    handed back untouched). Returns counts for the run log."""
    from . import autopilot, publish
    led = led or ledger.default()
    gov = governor or Governor(publish.LOG, now=now)
    counts = {"done": 0, "skipped": 0, "waiting": 0, "retry": 0, "dead": 0}
    jobs = led.claim(worker, kinds=[KIND], lease_s=LEASE_S, limit=limit)
    by_item: dict[str, list[dict]] = {}
    for j in jobs:
        by_item.setdefault(j["payload"]["item"], []).append(j)
    plans = {it["id"]: (start, it) for start, it in autopilot.items(14, 14)}
    for item_id, js in by_item.items():
        if allow and not (item_id in plans and allow(plans[item_id][1])):
            for j in js:                                  # not ours to post: back to the queue, no attempt used
                led.fail(j["id"], worker, "left for the cloud", kind="quota", retry_at=j["run_after"] or 1.0)
            continue
        try:
            _post_one(item_id, js, plans.get(item_id), led, gov, worker, counts, log)
        except Exception as e:  # noqa: BLE001 - one video's crash must not stop the others; its jobs retry
            log(f"publish queue: {item_id}: {type(e).__name__}: {e}")
            for j in js:
                led.fail(j["id"], worker, f"{type(e).__name__}: {e}")
            counts["retry"] += len(js)
    if jobs:
        log(f"publish queue: {counts}")
    return counts


def _post_one(item_id, js, found, led, gov, worker, counts, log) -> None:
    from . import autopilot, publish
    from .telegram_bot import notify
    if not found:
        for j in js:
            led.complete(j["id"], worker, {"skipped": "the video is no longer in a plan"})
        counts["skipped"] += len(js)
        return
    start, it = found
    if it.get("status") in ("rejected", "redo", "missed", "planned", "failed"):
        for j in js:
            led.complete(j["id"], worker, {"skipped": f"status is {it.get('status')}"})
        counts["skipped"] += len(js)
        return
    already = set(publish.already_posted(it))
    try_now, jobs_for = [], {}
    for j in js:
        p = j["payload"]["platform"]
        if p in already or (p == "youtube" and it.get("youtube_id")):
            led.complete(j["id"], worker, {"reconciled": "already on the platform"})
            counts["skipped"] += 1
            continue
        from .links import hold_note
        held = hold_note(it["channel"], p)
        if held:                                  # 25 Nov: an account under a platform check is never posted to
            led.complete(j["id"], worker, {"skipped": f"account on hold: {held}"})
            counts["skipped"] += 1
            continue
        ok, retry_at, why = gov.check(p, it["channel"])
        if not ok:
            led.fail(j["id"], worker, why, kind="quota", retry_at=retry_at)
            counts["waiting"] += 1
            continue
        try_now.append(p)
        jobs_for[p] = j
    if not try_now:
        return
    it = autopilot._with_local_media(start, it)
    # the content gate (incl. the strict clip gate) runs inside upload_item for every platform
    acts = publish.upload_item(it, dry_run=False, platforms=tuple(try_now), publish_at=None)
    new_done, dead, waits = [], [], []
    for p in try_now:
        j, act = jobs_for[p], _main_action(acts, p)
        verdict, why = classify(act)
        if verdict == "done":
            gov.record(p, it["channel"])
            res = act.result or {}
            led.complete(j["id"], worker, {"id": res.get("video_id") or res.get("media_id") or res.get("id")})
            new_done.append((p, res))
            counts["done"] += 1
        elif verdict == "skipped":
            led.complete(j["id"], worker, {"skipped": why[:300]})
            counts["skipped"] += 1
        else:
            retry_at = time.time() + 3600 if verdict == "quota" else None
            state = led.fail(j["id"], worker, why, kind=verdict, retry_at=retry_at)
            if state == "dead":
                dead.append((p, why))
                counts["dead"] += 1
            else:
                waits.append((p, why))
                counts["retry" if verdict != "quota" else "waiting"] += 1
    yt = next((r.get("video_id") for p, r in new_done if p == "youtube" and r.get("video_id")), None)
    if yt:
        it = autopilot.update_item(start, item_id, youtube_id=yt)
    _settle(start, it, acts, new_done, dead, waits, led, log, notify)


def _settle(start, it, acts, new_done, dead, waits, led, log, notify) -> None:
    """Item status + one owner message per video: when it first goes out, and when a platform gives up."""
    from . import autopilot, heal
    item_id = it["id"]
    pending = [j for j in queued(item_id, led, version=_ver(it)) if j["state"] in ("queued", "leased")]
    first_post = it.get("status") == "approved" and (new_done or it.get("youtube_id"))
    for p, why in dead:
        ledger.event("post.dead", item=item_id, channel=it["channel"], data={"platform": p, "error": why[:300]})
        try:
            heal.report("post", f"{p}: {why}", channel=it["channel"], platform=p)
        except Exception as e:  # noqa: BLE001 - the owner message below still goes out
            log(f"heal report: {e}")
    if first_post:
        autopilot._update_state(lambda st: st.setdefault("posted", {}).__setitem__(item_id, time.time()))
        it = autopilot.update_item(start, item_id, status="posted", posted_at=time.time(), post_retry_at=None)
        lines = [f"YouTube: https://youtu.be/{it['youtube_id']}"] if it.get("youtube_id") else []
        for p, r in new_done:
            if p != "youtube":
                lines.append(f"{p.title()}: posted")
        for p, why in waits:
            lines.append(f"{p.title()}: retrying by itself ({why[:80]})")
        for p, why in dead:
            lines.append(f"{p.title()}: {why[:120]}")
        from .publish import item_meta
        camp = item_meta(it).get("campaign")
        if camp:
            try:                                        # owner 21 Nov: submitting is the system's job, within 30 min
                from . import campaign_submit, db
                campaign = db.get_campaign(db.connect(), camp) or {"id": camp}
                links = {"youtube": f"https://www.youtube.com/shorts/{it['youtube_id']}"} if it.get("youtube_id") else {}
                for p, r in new_done:
                    url = (r or {}).get("url") or (r or {}).get("permalink") if isinstance(r, dict) else None
                    if p != "youtube" and url:
                        links[p] = url
                res = campaign_submit.after_post(it, links, campaign, log=log)
                if res.get("ok"):
                    it = autopilot.update_item(start, item_id, campaign_submitted_at=time.time(),
                                               campaign_post_url=res.get("post_url"))
                lines.append("💰 Campaign: " + ("submitted automatically" if res.get("ok")
                                                else f"not submitted ({res.get('message')})"))
            except Exception as e:  # noqa: BLE001 - the post itself succeeded; tell the owner
                log(f"campaign submit: {type(e).__name__}: {e}")
                lines.append(f"💰 Campaign clip: automatic submit failed ({type(e).__name__}); campaign {camp}")
            try:
                from . import share_packs
                share_packs.send_now(it, log)
            except Exception as e:  # noqa: BLE001
                log(f"share now: {e}")
        notify(f"📤 Posted {it['channel_name']}: {it.get('topic') or ''}\n" + "\n".join(lines))
        log(f"Posted {item_id}: {lines}")
        return
    if it.get("status") == "posted":                         # a later platform: quiet unless it gave up
        for p, r in new_done:
            log(f"{item_id}: also posted on {p}")
        if dead:
            notify(f"⚠️ {it['channel_name']}: {', '.join(p.title() for p, _ in dead)} gave up after "
                   f"{MAX_ATTEMPTS} tries ({dead[0][1][:120]}). It is in the heal list.")
        return
    if not pending:                                          # nothing went out anywhere and nothing is left to try
        # 21 Nov: a video every platform's gate blocked was settled here and never remade (stuck 'approved' for
        # ever). A block a remake can fix sends it back to 'redo' (the remake posts as a new version).
        blocked = [why for _p, why in dead if "🛑 blocked:" in str(why)]
        if blocked and not it.get("youtube_id") and autopilot._redo_if_blocked(start, it, blocked[0], log):
            return
        autopilot._update_state(lambda st: st.setdefault("posted", {}).__setitem__(item_id, time.time()))
        reasons = [f"{p.title()}: {why[:120]}" for p, why in dead]
        notify(f"ℹ️ Nothing posted for {it['channel_name']}: {it.get('topic') or ''}" +
               ("\n" + "\n".join(reasons) if reasons else ""))
        return
    soon = min(j["run_after"] for j in pending)               # mirrors for the Studio / old readers
    tries = max([j["attempts"] for j in pending] + [0])
    autopilot.update_item(start, item_id, post_attempts=tries, post_retry_at=soon)
    log(f"Post {item_id}: waiting/retrying {[p for p, _ in waits]}")


def summary(led=None) -> dict:
    """{state: count} of post jobs + the dead ones (for the dashboard and the daily report)."""
    led = led or ledger.default()
    st = led.stats().get(KIND, {})
    dead = [{"key": j["key"], "error": (j["last_error"] or "")[:160]} for j in led.jobs(state="dead", kind=KIND)][-10:]
    return {"states": st, "dead": dead}


def text(led=None) -> str:
    """Plain-words status for Telegram (🩺 Health) and the Studio."""
    d = summary(led)
    st = d["states"]
    line = (f"📤 Posting queue: {st.get('done', 0)} posted/settled · {st.get('queued', 0)} waiting for a slot or a "
            f"platform limit · {st.get('dead', 0)} gave up")
    if d["dead"]:
        line += "\n" + "\n".join(f"• {x['key'].split(':', 1)[1]}: {x['error'][:90]}" for x in d["dead"][-3:])
    return line
