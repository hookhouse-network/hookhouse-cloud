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

    def stats(self) -> dict:
        return self._call("s_stats")


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
        self.thread = threading.Thread(target=self._loop, name="sched-heartbeat", daemon=True)

    def _loop(self) -> None:
        warned = False
        while not self._stop.is_set():
            try:
                self.client.register(self.wid, self.kind, self.caps)
                self.beats += 1
                warned = False
            except Exception as e:  # noqa: BLE001 - the work goes on without the heartbeat (said once per outage)
                if not warned:
                    self.log(f"scheduler heartbeat: {type(e).__name__}: {str(e)[:120]}")
                    warned = True
            self._stop.wait(self.every_s)

    def start(self) -> "Heartbeat":
        self.thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        try:
            self.client.release(self.wid)
        except Exception as e:  # noqa: BLE001 - leases expire by themselves after 15 minutes
            self.log(f"scheduler release: {type(e).__name__}: {str(e)[:120]}")


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
