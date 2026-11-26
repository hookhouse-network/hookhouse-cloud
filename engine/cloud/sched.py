"""Python side of the Phase 2 scheduler (cloud/worker/scheduler.js inside the LedgerDO), over the signed /api/ledger.

One shared job queue for every worker: the PC makers, the GitHub tick and render runs, the Cloudflare Worker.
Jobs have a priority class (P0 owner taps/posting .. P4 maintenance), a deadline (earliest-deadline-first with slack),
capabilities, preferred worker kinds and fallback rules; every lease carries an epoch that complete/fail/heartbeat
must present (fencing: a worker that slept through its lease can never finish a job someone else took over)."""
from __future__ import annotations

from ..core import d1

WORKER_KINDS = ("pc", "gh_tick", "gh_render", "cf_worker")


class SchedError(RuntimeError):
    """The scheduler refused a call or could not be reached."""


class SchedClient:
    def __init__(self, client: d1.Client | None = None):
        self.c = client or d1.Client()

    def available(self) -> bool:
        return self.c.configured()

    def _call(self, op: str, **kw) -> dict:
        try:
            out = self.c.call({"op": op, **kw})
        except RuntimeError as e:
            raise SchedError(str(e)) from e
        if isinstance(out, dict) and out.get("error"):
            raise SchedError(out["error"])
        return out

    def register(self, wid: str, kind: str, caps: list[str], slots: dict | None = None, version: str = "",
                 load: float = 0.0, state: str | None = None) -> dict:
        if kind not in WORKER_KINDS:
            raise ValueError(f"kind must be one of {WORKER_KINDS}")
        return self._call("s_register", worker={"id": wid, "kind": kind, "caps": caps, "slots": slots or {},
                                                "version": version, "load": load, **({"state": state} if state else {})})

    def enqueue(self, kind: str, key: str, cls: int = 2, deadline: float | None = None, est_min: float = 10,
                requires: list[str] | None = None, prefer: list[str] | None = None,
                fallback: list[dict] | None = None, payload: dict | None = None, run_after: float = 0,
                max_attempts: int = 5) -> bool:
        return bool(self._call("s_enqueue", job={
            "kind": kind, "key": key, "cls": cls, "deadline": deadline, "est_min": est_min,
            "requires": requires or [], "prefer": prefer or [], "fallback": fallback or [], "payload": payload or {},
            "run_after": run_after, "max_attempts": max_attempts}).get("added"))

    def claim(self, wid: str, limit: int = 1, lease_s: float = 900) -> list[dict]:
        return list(self._call("s_claim", worker=wid, limit=limit, lease_s=lease_s).get("jobs") or [])

    def heartbeat(self, job_id: int, wid: str, epoch: int, lease_s: float = 900) -> bool:
        return bool(self._call("s_heartbeat", job=job_id, worker=wid, epoch=epoch, lease_s=lease_s).get("ok"))

    def complete(self, job_id: int, wid: str, epoch: int, result: dict | None = None) -> bool:
        return bool(self._call("s_complete", job=job_id, worker=wid, epoch=epoch, result=result or {}).get("ok"))

    def fail(self, job_id: int, wid: str, epoch: int, error: str, kind: str = "transient",
             retry_at: float | None = None) -> str:
        return str(self._call("s_fail", job=job_id, worker=wid, epoch=epoch, error=error[:1000], kind=kind,
                              retry_at=retry_at).get("state"))

    def release(self, wid: str) -> int:
        return int(self._call("s_release", worker=wid).get("released") or 0)

    def cancel(self, key: str) -> bool:
        return bool(self._call("s_cancel", key=key).get("ok"))

    def list(self, state: str = "queued", limit: int = 500) -> list[dict]:
        return list(self._call("s_list", state=state, limit=limit).get("jobs") or [])

    def stats(self) -> dict:
        return self._call("s_stats")


def job_for(start: str, it: dict, now: float) -> dict:
    """The queue job for one plan item: P1 when its slot is under 24 h away, else P2 (the 72 h work-ahead buffer);
    long videos need the PC (never GitHub Actions); Shorts may fall back to GitHub render only when no PC is online
    and the slack is under twice the estimate (master plan 5.3)."""
    from .. import autopilot
    when = autopilot._when(it).timestamp()
    kind = str(it.get("kind") or "short")
    long_ = kind == "long"
    # 22 Nov shadow check: a video whose slot already passed (still made up to OVERDUE_D days late; it gets the next
    # free slot) kept class P1 and its old deadline, so earliest-deadline-first put the 20 and 21 Nov Itihaas videos
    # at the head of the queue, ahead of tonight's 19:00 Cricket long video that can still make its slot. A late
    # video gets its own key (the old job is cancelled by the sync), class P2 and a deadline a day out.
    late = when < now
    key = f"make:{it['id']}:{it.get('gate_redos') or 0}:{it.get('status')}" + (":late" if late else "")
    cls, deadline = (2 if late or when - now >= 24 * 3600 else 1), (now + 24 * 3600 if late else when)
    # 25 Nov shadow day (40 picks, 20 the same): the PC makes remakes first, then a connected channel's campaign clip
    # (campaigns pay only while they run), then channels that can post; the queue went by deadline alone and handed
    # out 1126_0500_stream_clips while the PC made the 1121 remake. The queue now carries the same order.
    h = order_hints(it)
    # 26 Nov shadow (15 of 26 the same): several remakes due at once came out in enqueue order (deadline "now - 1 h"
    # at each enqueue) while the PC takes them by slot time; remakes and clips now keep their slot order, shifted
    # 30 / 15 days earlier so they stay ahead of everything else (slots lie within days of now)
    if h["redo"]:
        cls, deadline = 1, when - 30 * 86400
    elif h["clip"] and h["live"]:
        cls, deadline, key = 1, when - 15 * 86400, key + ":clip"
    elif not h["live"]:
        cls = max(cls, 2)
    return {"kind": "make", "key": key,
            "cls": cls, "deadline": deadline,
            "est_min": 45 if long_ else 12,
            "requires": ["ffmpeg"] + (["pc"] if long_ else []), "prefer": ["pc"],
            "fallback": [] if long_ else [{"kind": "gh_render", "when": "no_pc_online&slack_lt_2x"}],
            "payload": {"item": it["id"], "start": start, "channel": it.get("channel"), "kind": kind}}


def order_hints(it: dict) -> dict:
    """The PC's own ordering facts for an item (runner._due_to_make): a remake, a campaign clip slot, a channel with a
    connected account. A failed check never stops the queue: not a clip, counted as live."""
    from .. import autopilot
    from . import runner
    live = True
    try:
        c = autopilot._connected(it["channel"])
        live = bool(c["youtube"] or c["meta"])
    except Exception as e:  # noqa: BLE001 - unknown channel: keep its deadline order
        runner._log(f"queue order: connection check {it.get('id')}: {type(e).__name__}: {e}")
    clip = bool(it.get("channel")) and runner._clip_slot(it)
    return {"redo": it.get("status") == "redo", "clip": clip, "live": live}


def sync_due(client: SchedClient, due: list[tuple[str, dict]], now: float | None = None, log=print) -> dict:
    """Keep the queue in step with what is due to make: enqueue every due item (idempotent key, a remake gets a new
    key) and cancel queued make-jobs whose item is no longer due (made through the claim files, slot dropped)."""
    import time
    now = now or time.time()
    want = {}
    for start, it in due:
        j = job_for(start, it, now)
        want[j["key"]] = j
    added = sum(1 for j in want.values() if client.enqueue(**j))
    stale = [j["key"] for j in client.list("queued") if j.get("kind") == "make" and j["key"] not in want]
    cancelled = sum(1 for k in stale if client.cancel(k))
    log(f"queue: {len(want)} due, {added} new job(s), {cancelled} cancelled")
    return {"due": len(want), "added": added, "cancelled": cancelled}


def item_of(key: str) -> str:
    """The plan item a make-job key belongs to (make:<item>:<redos>:<status>[:late])."""
    parts = str(key or "").split(":")
    return parts[1] if len(parts) > 2 and parts[0] == "make" else ""


def top_up(client: SchedClient, due: list[tuple[str, dict]], now: float | None = None, log=print) -> dict:
    """23 Nov shadow check: only the cloud tick filled the queue, a few hours apart. At 05:16 the queue was empty while
    the PC had due work (the Itihaas remake freed its claim at 03:48, after the tick), so with the scheduler on the PC
    would have idled until the next tick. The PC now adds every item IT sees as due that has no queued or leased job
    yet (enqueue is idempotent; a cancelled key opens again). Cancelling stays with the cloud, which has the fresh plan.
    Returns the queued jobs it saw (+ the ones it added) for the shadow comparison."""
    import time
    now = now or time.time()
    queued = [j for j in client.list("queued") if j.get("kind") == "make"]
    have = {item_of(j.get("key")) for j in queued} | {item_of(j.get("key")) for j in client.list("leased")}
    added = []
    for start, it in due:
        if it["id"] in have:
            continue
        j = job_for(start, it, now)
        if client.enqueue(**j):
            added.append(j)
            have.add(it["id"])
    if added:
        log(f"queue: this PC added {len(added)} due item(s) the queue did not have")
    return {"queued": queued + [{"key": j["key"], "cls": j["cls"], "deadline": j["deadline"]} for j in added],
            "added": len(added)}


def queue_pick(queued: list[dict], now: float) -> str:
    """The item the scheduler would hand a PC first: class, then slack (deadline minus the estimate), as claim() sorts
    (list() returns no estimate: long videos 45 min, the rest 12, as job_for sets them)."""
    def order(j):
        est = 45 if item_of(j.get("key")).endswith("_long") else 12
        dl = j.get("deadline")
        return (int(j.get("cls", 2)), float("inf") if dl is None else float(dl) - now - est * 60)
    best = min(queued, key=order, default=None)
    return item_of(best.get("key")) if best else ""


SHADOW_LOG = None                                     # set below (data/pc/shadow_picks.jsonl)


def shadow_compare(queued: list[dict], due_ids: list[str], now: float | None = None, log=print) -> dict:
    """Shadow mode: what the queue would hand this PC next vs what the PC really makes now (due_ids[0]), one line in
    the log and one row in data/pc/shadow_picks.jsonl (the 'a day of shadow' evidence before scheduler: on). Jobs for
    items this PC can't make now are skipped, as next_job puts them back."""
    import json
    import time
    now = now or time.time()
    mine = [j for j in queued if item_of(j.get("key")) in set(due_ids)]
    pick, pc_item = queue_pick(mine, now), (due_ids[0] if due_ids else "")
    row = {"at": round(now), "queue": pick, "pc": pc_item, "same": pick == pc_item, "queued": len(queued),
           "not_here": len(queued) - len(mine)}
    log("shadow: " + ("the queue would hand out the same video" if row["same"] else
                      f"the queue would hand out {pick or 'nothing'}; the PC makes {pc_item}"))
    try:
        path = SHADOW_LOG or _shadow_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
    except OSError as e:
        log(f"shadow log: {type(e).__name__}: {e}")
    return row


def _shadow_path():
    from ..config import ROOT
    return ROOT / "data" / "pc" / "shadow_picks.jsonl"


def mode() -> str:
    """settings.yaml scheduler: off | shadow (workers heartbeat, nothing claims from it yet) | on."""
    from ..config import settings
    m = str(settings().get("scheduler", "off"))
    return m if m in ("off", "shadow", "on") else "off"


def pc_caps() -> list[str]:
    """What this PC can do (the scheduler only hands it jobs whose requirements it meets)."""
    caps = ["ffmpeg", "pc", "browser"]
    try:
        import importlib.util
        if importlib.util.find_spec("kokoro"):
            caps.append("kokoro")
        from ..media import characters, hyperframes
        if hyperframes.available():
            caps.append("hyperframes")
        if characters.available():
            caps.append("puppets")
    except Exception as e:  # noqa: BLE001 - fewer capabilities = fewer jobs, never a crash (said, never silent)
        print(f"scheduler: capability probe incomplete ({type(e).__name__}: {e})")
    return caps


class Heartbeat:
    """Registers this worker every `every_s` seconds in a daemon thread (presence history for the availability
    forecast: master plan 5.3 asks for 7 days of data before trusting it); stop() releases its leases at once."""

    def __init__(self, client: SchedClient, wid: str, kind: str, caps: list[str], every_s: float = 60.0, log=print):
        import threading
        self.client, self.wid, self.kind, self.caps, self.every_s, self.log = client, wid, kind, caps, every_s, log
        self._stop = threading.Event()
        self.beats = 0
        self.jobs: dict[int, int] = {}                  # job id -> epoch: leases extended while the work runs
        self.lost: set[int] = set()                     # leases that ran out (someone else may have the job now)
        self.thread = threading.Thread(target=self._loop, name="sched-heartbeat", daemon=True)

    def track(self, job: dict) -> None:
        self.jobs[int(job["id"])] = int(job["epoch"])

    def untrack(self, job: dict) -> None:
        self.jobs.pop(int(job["id"]), None)

    def _loop(self) -> None:
        warned = False
        while not self._stop.is_set():
            try:
                self.client.register(self.wid, self.kind, self.caps)
                self.beats += 1
                for jid, epoch in list(self.jobs.items()):
                    if not self.client.heartbeat(jid, self.wid, epoch):
                        self.lost.add(jid)
                        self.log(f"scheduler: lease of job {jid} was lost (its result will be refused)")
                        self.jobs.pop(jid, None)
                warned = False
            except Exception as e:  # noqa: BLE001 - the work goes on without the heartbeat (said once per outage)
                if not warned:
                    self.log(f"scheduler heartbeat: {type(e).__name__}: {str(e)[:120]}")
                    warned = True
            self._stop.wait(self.every_s)

    def start(self) -> "Heartbeat":
        try:                                      # registered before the first claim (no "unknown worker" race)
            self.client.register(self.wid, self.kind, self.caps)
            self.beats += 1
        except Exception as e:  # noqa: BLE001 - the thread keeps trying (said, never silent)
            self.log(f"scheduler: first registration failed ({type(e).__name__}: {str(e)[:120]})")
        self.thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        try:
            self.client.release(self.wid)
        except Exception as e:  # noqa: BLE001 - leases expire by themselves after 15 minutes
            self.log(f"scheduler release: {type(e).__name__}: {str(e)[:120]}")


def next_job(hb: Heartbeat | None, items: dict[str, tuple[str, dict]], log=print):
    """Scheduler 'on' mode: (start, item, job) for this worker's next make job, None when the queue has nothing for
    it, or "fallback" when the queue cannot be reached (the caller uses the claim files this round). A job whose item
    is no longer due is closed at once (the queue moves on)."""
    if hb is None or mode() != "on":
        return "fallback"
    import time
    for _try in range(PUT_BACK_MAX):           # 23 Nov: one put-back used to end the round (5 idle minutes per job
        try:                                   # the PC couldn't make at the head of the queue)
            jobs = hb.client.claim(hb.wid, limit=1)
        except Exception as e:  # noqa: BLE001 - degraded mode: the old claim files (said, never silent)
            log(f"scheduler: queue unreachable ({type(e).__name__}: {str(e)[:100]}); claim files this round")
            return "fallback"
        if not jobs:
            return None
        for job in jobs:
            iid = str((job.get("payload") or {}).get("item") or "")
            if iid not in items:               # made or claimed elsewhere: back to the queue for 30 min (no attempt
                hb.client.fail(job["id"], hb.wid, job["epoch"], "not due on this PC now", "quota",   # counted); the
                               time.time() + 1800)                    # cloud's next sync cancels it if it is done
                log(f"scheduler: job {job['key']} put back: its item is not due here right now")
                continue
            hb.track(job)
            start, it = items[iid]
            return start, it, job
    return None


PUT_BACK_MAX = 6


def finish_job(hb: Heartbeat, job: dict, result: dict | None = None, error: Exception | None = None,
               log=print) -> str:
    """Complete (with the artifact) or fail the job with its epoch; returns done / queued / dead / lost / refused."""
    hb.untrack(job)
    try:
        if error is None:
            ok = hb.client.complete(job["id"], hb.wid, job["epoch"], result or {})
            if not ok:
                log(f"scheduler: completion of {job['key']} refused (lease lost: someone else has it)")
            return "done" if ok else "refused"
        kind = "permanent" if isinstance(error, (ValueError, KeyError)) else "transient"
        state = hb.client.fail(job["id"], hb.wid, job["epoch"], f"{type(error).__name__}: {error}", kind)
        log(f"scheduler: {job['key']} failed ({kind}) -> {state}")
        return state
    except Exception as e:  # noqa: BLE001 - the lease expires and the job returns by itself (said, never silent)
        log(f"scheduler: could not report {job['key']} ({type(e).__name__}: {e})")
        return "lost"


def start_pc_heartbeat(log=print) -> Heartbeat | None:
    """The PC helper's heartbeat (scheduler shadow/on mode and the signed API configured), else None."""
    import socket
    try:
        if mode() == "off":
            return None
        client = SchedClient()
        if not client.available():
            return None
        return Heartbeat(client, f"pc-{socket.gethostname().lower()}", "pc", pc_caps(), log=log).start()
    except Exception as e:  # noqa: BLE001 - never stops video making (said, never silent)
        log(f"scheduler heartbeat not started ({type(e).__name__}: {e})")
        return None
