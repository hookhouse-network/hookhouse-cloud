"""The ledger: an append-only event log + a lease-based job queue (docs/ARCHITECTURE.md, phases 1-2).

Why: the system kept its truth in ~100 JSON files and weekly plans, rewritten in place by many modules, and every
failure was handled where it happened (361 broad `except Exception`, 111 of them silent). Nobody could answer "what
happened to this video?" or "what is stuck?", and a crash between "posted" and "saved" could post twice.

Event log: every important fact (status change, post, failure, quota hit) is one immutable row. History, metrics,
stuck detection and the daily report are queries over it.

Job queue (the standard pattern for at-least-once work with crash recovery):
- enqueue(kind, key, payload): the key is an idempotency key; enqueueing the same key twice is a no-op.
- claim(worker, kinds): atomically leases the next due jobs; a lease that is not renewed expires and the job
  goes back to the queue (a worker that crashed or was switched off never blocks work).
- complete / fail: failures are classified. transient -> capped exponential backoff with full jitter; quota ->
  waits until the given reset time without using up an attempt; permanent or out of attempts -> "dead" (the
  dead-letter list, reported to the heal queue).
Backend: SQLite here (data/ledger.db, inside the memory bundle). The same interface is meant to run on Cloudflare
D1 behind the Worker (phase 2), so the cloud, the PC and the Telegram bot share one live truth."""
from __future__ import annotations

import json
import os
import random
import sqlite3
import threading
import time
from pathlib import Path

from ..config import ROOT

DB = ROOT / "data" / "ledger.db"
BACKOFF_BASE_S = 60.0
BACKOFF_CAP_S = 6 * 3600.0
EVENT_KEEP_DAYS = 120
_LOCK = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, at REAL NOT NULL, type TEXT NOT NULL,
  item TEXT, channel TEXT, worker TEXT, data TEXT);
CREATE INDEX IF NOT EXISTS ev_item ON events(item);
CREATE INDEX IF NOT EXISTS ev_type_at ON events(type, at);
CREATE TABLE IF NOT EXISTS jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, key TEXT NOT NULL UNIQUE, payload TEXT,
  state TEXT NOT NULL DEFAULT 'queued', priority INTEGER NOT NULL DEFAULT 0,
  attempts INTEGER NOT NULL DEFAULT 0, max_attempts INTEGER NOT NULL DEFAULT 5,
  run_after REAL NOT NULL DEFAULT 0, lease_owner TEXT, lease_until REAL,
  created REAL NOT NULL, updated REAL NOT NULL, last_error TEXT, result TEXT);
CREATE INDEX IF NOT EXISTS jobs_due ON jobs(state, run_after);
CREATE TABLE IF NOT EXISTS checkpoints (
  item TEXT NOT NULL, stage TEXT NOT NULL, status TEXT NOT NULL, artifact TEXT, attempts INTEGER NOT NULL DEFAULT 0,
  error TEXT, updated REAL NOT NULL, PRIMARY KEY (item, stage));
"""
FAIL_KINDS = ("transient", "quota", "permanent")


def _connect(path: Path | None = None) -> sqlite3.Connection:
    p = Path(path or os.environ.get("LEDGER_DB") or DB)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(p, timeout=30, isolation_level=None)      # explicit transactions below
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=DELETE")   # not WAL: the memory bundle packs ledger.db alone (no -wal file)
    conn.execute("PRAGMA busy_timeout=30000")
    conn.executescript(SCHEMA)
    from . import d1                             # Phase 1: dual mode notes changed rows for the shared truth
    d1.install(conn)
    return conn


class Ledger:
    def __init__(self, path: Path | None = None, clock=time.time, rng=random.random):
        self.path, self.clock, self.rng = path, clock, rng

    def _tx(self, fn):
        """One IMMEDIATE transaction (takes the write lock up front, so two workers can't claim the same job)."""
        with _LOCK:
            conn = _connect(self.path)
            try:
                conn.execute("BEGIN IMMEDIATE")
                out = fn(conn)
                conn.execute("COMMIT")
            except BaseException:
                if conn.in_transaction:              # BEGIN itself can fail (locked): keep that error, not ROLLBACK's
                    conn.execute("ROLLBACK")
                conn.close()
                raise
            try:
                from . import d1
                d1.maybe_flush(conn)                 # dual mode only; never raises (SQLite already committed)
            finally:
                conn.close()
            return out

    def flush_shadow(self, log=print) -> int:
        """Send every queued row to the shared truth now (end of a cloud tick). Failures are logged, rows stay."""
        from . import d1
        if d1.backend() != "dual":
            return 0
        with _LOCK:
            conn = _connect(self.path)
            try:
                return d1.flush(conn, log=log)
            except Exception as e:  # noqa: BLE001 - shadow copy only
                log(f"ledger shadow: flush failed ({type(e).__name__}: {str(e)[:160]}); {d1.pending(conn)} queued")
                return 0
            finally:
                conn.close()

    # ------------------------------------------------------------------ events
    def event(self, type_: str, item: str = "", channel: str = "", worker: str = "", data: dict | None = None) -> None:
        now = self.clock()
        self._tx(lambda c: c.execute("INSERT INTO events(at,type,item,channel,worker,data) VALUES (?,?,?,?,?,?)",
                                     (now, type_, item, channel, worker,
                                      json.dumps(data or {}, ensure_ascii=False, default=str))))

    def history(self, item: str) -> list[dict]:
        return self._tx(lambda c: [dict(r, data=json.loads(r["data"] or "{}")) for r in
                                   c.execute("SELECT * FROM events WHERE item=? ORDER BY id", (item,))])

    def events(self, type_: str, since: float = 0.0) -> list[dict]:
        return self._tx(lambda c: [dict(r, data=json.loads(r["data"] or "{}")) for r in
                                   c.execute("SELECT * FROM events WHERE type=? AND at>=? ORDER BY id", (type_, since))])

    def prune(self, keep_days: int = EVENT_KEEP_DAYS) -> int:
        cut = self.clock() - keep_days * 86400
        return self._tx(lambda c: c.execute("DELETE FROM events WHERE at<?", (cut,)).rowcount)

    # ------------------------------------------------------------------ jobs
    def enqueue(self, kind: str, key: str, payload: dict | None = None, run_after: float = 0.0, priority: int = 0,
                max_attempts: int = 5) -> bool:
        """True if a new job was added; False if a job with this idempotency key already exists."""
        now = self.clock()

        def go(c):
            cur = c.execute("INSERT OR IGNORE INTO jobs(kind,key,payload,priority,max_attempts,run_after,created,updated)"
                            " VALUES (?,?,?,?,?,?,?,?)", (kind, key, json.dumps(payload or {}, ensure_ascii=False),
                                                          priority, max_attempts, run_after, now, now))
            return cur.rowcount == 1
        return self._tx(go)

    def claim(self, worker: str, kinds: list[str] | tuple[str, ...] | None = None, lease_s: float = 900.0,
              limit: int = 1) -> list[dict]:
        now = self.clock()

        def go(c):
            c.execute("UPDATE jobs SET state='queued', lease_owner=NULL, lease_until=NULL, updated=? "
                      "WHERE state='leased' AND lease_until<?", (now, now))          # crashed / switched-off workers
            where, args = "state='queued' AND run_after<=?", [now]
            if kinds:
                where += f" AND kind IN ({','.join('?' * len(kinds))})"
                args += list(kinds)
            ids = [r["id"] for r in c.execute(f"SELECT id FROM jobs WHERE {where} ORDER BY priority DESC, run_after, id "
                                              f"LIMIT ?", (*args, limit))]
            out = []
            for i in ids:
                c.execute("UPDATE jobs SET state='leased', lease_owner=?, lease_until=?, attempts=attempts+1, "
                          "updated=? WHERE id=?", (worker, now + lease_s, now, i))
                r = dict(c.execute("SELECT * FROM jobs WHERE id=?", (i,)).fetchone())
                r["payload"] = json.loads(r["payload"] or "{}")
                out.append(r)
            return out
        return self._tx(go)

    def heartbeat(self, job_id: int, worker: str, lease_s: float = 900.0) -> bool:
        """Extend a lease; False means the lease was lost (expired and taken by someone else): stop the work."""
        now = self.clock()
        return self._tx(lambda c: c.execute("UPDATE jobs SET lease_until=?, updated=? WHERE id=? AND state='leased' "
                                            "AND lease_owner=?", (now + lease_s, now, job_id, worker)).rowcount == 1)

    def complete(self, job_id: int, worker: str, result: dict | None = None) -> bool:
        now = self.clock()
        return self._tx(lambda c: c.execute("UPDATE jobs SET state='done', result=?, lease_owner=NULL, "
                                            "lease_until=NULL, updated=? WHERE id=? AND lease_owner=?",
                                            (json.dumps(result or {}, ensure_ascii=False, default=str), now,
                                             job_id, worker)).rowcount == 1)

    def backoff(self, attempts: int) -> float:
        """Capped exponential backoff with full jitter (AWS Builders' Library), never under 30 s."""
        return max(30.0, self.rng() * min(BACKOFF_CAP_S, BACKOFF_BASE_S * 2 ** max(0, attempts - 1)))

    def fail(self, job_id: int, worker: str, error: str, kind: str = "transient",
             retry_at: float | None = None) -> str:
        """Returns the job's new state: queued (retry later) or dead."""
        if kind not in FAIL_KINDS:
            raise ValueError(f"kind must be one of {FAIL_KINDS}")
        now = self.clock()

        def go(c):
            r = c.execute("SELECT * FROM jobs WHERE id=? AND lease_owner=?", (job_id, worker)).fetchone()
            if r is None:
                return "lost"
            attempts = r["attempts"] - (1 if kind == "quota" else 0)       # waiting for a quota is not a failure
            if kind == "permanent" or attempts >= r["max_attempts"]:
                state, run_after = "dead", r["run_after"]
            else:
                state = "queued"
                run_after = retry_at if (kind == "quota" and retry_at) else now + self.backoff(attempts)
            c.execute("UPDATE jobs SET state=?, attempts=?, run_after=?, last_error=?, lease_owner=NULL, "
                      "lease_until=NULL, updated=? WHERE id=?", (state, attempts, run_after, str(error)[:1000], now,
                                                                job_id))
            return state
        state = self._tx(go)
        if state == "dead":
            self.event("job.dead", worker=worker, data={"job": job_id, "error": str(error)[:300]})
        return state

    def retry_dead(self, job_id: int, run_after: float | None = None) -> bool:
        """Put a dead job back (after a fix): attempts start again, now or at run_after (e.g. the next posting slot)."""
        now = self.clock()
        when = now if run_after is None else float(run_after)
        return self._tx(lambda c: c.execute("UPDATE jobs SET state='queued', attempts=0, run_after=?, updated=? "
                                            "WHERE id=? AND state='dead'", (when, now, job_id)).rowcount == 1)

    def jobs(self, state: str | None = None, kind: str | None = None) -> list[dict]:
        q, args = "SELECT * FROM jobs WHERE 1=1", []
        if state:
            q, args = q + " AND state=?", args + [state]
        if kind:
            q, args = q + " AND kind=?", args + [kind]
        return self._tx(lambda c: [dict(r) for r in c.execute(q + " ORDER BY id", args)])

    # ------------------------------------------------------------------ stage checkpoints (resumable pipelines)
    def checkpoint(self, item: str, stage: str) -> dict | None:
        r = self._tx(lambda c: c.execute("SELECT * FROM checkpoints WHERE item=? AND stage=?", (item, stage)).fetchone())
        return dict(r, artifact=json.loads(r["artifact"] or "null")) if r else None

    def _save_checkpoint(self, item: str, stage: str, status: str, artifact=None, error: str = "",
                         attempt: bool = False) -> None:
        now = self.clock()
        self._tx(lambda c: c.execute(
            "INSERT INTO checkpoints(item,stage,status,artifact,attempts,error,updated) VALUES (?,?,?,?,?,?,?) "
            "ON CONFLICT(item,stage) DO UPDATE SET status=excluded.status, artifact=excluded.artifact, "
            "attempts=checkpoints.attempts+?, error=excluded.error, updated=excluded.updated",
            (item, stage, status, json.dumps(artifact, ensure_ascii=False, default=str), int(attempt), error[:1000],
             now, int(attempt))))

    def invalidate(self, item: str, stages: list[str] | tuple[str, ...]) -> int:
        """Drop these stages' checkpoints (e.g. everything after a stage that has to be redone)."""
        if not stages:
            return 0
        return self._tx(lambda c: c.execute(f"DELETE FROM checkpoints WHERE item=? AND stage IN "
                                            f"({','.join('?' * len(stages))})", (item, *stages)).rowcount)

    def run_stage(self, item: str, stage: str, producer, validate=lambda a: a is not None,
                  order: list[str] | tuple[str, ...] = ()):
        """Resumable pipeline step (idea from darkzOGx/youtube-automation-agent's generation recovery, MIT; rebuilt
        here). A completed stage whose saved artifact still validates is reused, so a crash, a timeout or a
        switched-off PC resumes where it stopped instead of re-spending AI quota. A completed stage whose artifact
        is gone or broken is redone and every later stage in `order` is invalidated. The producer's exceptions
        propagate (the job queue decides about retries); its artifact must pass `validate` to count."""
        cp = self.checkpoint(item, stage)
        if cp and cp["status"] == "completed":
            if validate(cp["artifact"]):
                self.event("stage.reused", item=item, data={"stage": stage})
                return cp["artifact"]
            later = list(order[order.index(stage) + 1:]) if stage in order else []
            self.invalidate(item, later)
            self.event("stage.invalid", item=item, data={"stage": stage, "dropped": later})
        self._save_checkpoint(item, stage, "running", attempt=True)
        try:
            artifact = producer()
            if not validate(artifact):
                raise ValueError(f"stage '{stage}' produced an incomplete or missing result")
        except BaseException as e:
            self._save_checkpoint(item, stage, "failed", error=f"{type(e).__name__}: {e}")
            self.event("stage.failed", item=item, data={"stage": stage, "error": f"{type(e).__name__}: {e}"[:300]})
            raise
        self._save_checkpoint(item, stage, "completed", artifact=artifact)
        self.event("stage.done", item=item, data={"stage": stage})
        return artifact

    def stats(self) -> dict[str, dict[str, int]]:
        out: dict[str, dict[str, int]] = {}
        for r in self._tx(lambda c: c.execute("SELECT kind, state, COUNT(*) n FROM jobs GROUP BY kind, state").fetchall()):
            out.setdefault(r["kind"], {})[r["state"]] = r["n"]
        return out


_DEFAULT: Ledger | None = None


def default() -> Ledger:
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = Ledger()
    return _DEFAULT


def event(type_: str, **kw) -> None:
    """Fire-and-forget event for callers that must never fail because of logging (the failure is printed)."""
    try:
        default().event(type_, **kw)
    except Exception as e:  # noqa: BLE001 - observability must not break the work it observes
        print(f"ledger: could not record {type_}: {type(e).__name__}: {e}")
