"""Shared truth client (master plan Phase 1, 20 Nov 2026): the Worker's LedgerDO (Durable Object, SQLite storage).

The Cloudflare token gets 401 on D1, so the plan's option (a) is used: a Durable Object deployed with the existing
Worker token (free plan: 100,000 requests and 100,000 row writes a day). The module keeps the name d1.py from the
plan. LEDGER_BACKEND:
- sqlite (default): only data/ledger.db.
- dual: SQLite stays authoritative. Triggers note every changed row in _shadow (same transaction); after commits the
  current row images are sent to the DO as idempotent upserts/deletes keyed by primary key, so a retry or a replay
  can never double anything and ids always match. Rows that could not be sent stay in _shadow for the next flush.
  `diff()` compares both sides (the overnight check before reads move).
Requests: POST {HH_API_URL}/api/ledger, headers x-hh-ts + x-hh-sig = HMAC-SHA256(HH_API_KEY, f"{ts}.{body}")."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
import time

TABLES = {
    "events": ["id"],
    "jobs": ["id"],
    "checkpoints": ["item", "stage"],
}
BATCH = 400                    # the DO accepts up to 500 changes per call
FLUSH_EVERY_S = 30.0           # ledger writes flush at most this often; the tick flushes once more at its end

SHADOW_SQL = [
    "CREATE TABLE IF NOT EXISTS _shadow (n INTEGER PRIMARY KEY AUTOINCREMENT, tbl TEXT NOT NULL, k TEXT NOT NULL)",
    *[f"CREATE TRIGGER IF NOT EXISTS sh_ev_{op} AFTER {op} ON events BEGIN "
      f"INSERT INTO _shadow(tbl,k) VALUES ('events', json_object('id', {ref}.id)); END"
      for op, ref in (("INSERT", "NEW"), ("UPDATE", "NEW"), ("DELETE", "OLD"))],
    *[f"CREATE TRIGGER IF NOT EXISTS sh_jobs_{op} AFTER {op} ON jobs BEGIN "
      f"INSERT INTO _shadow(tbl,k) VALUES ('jobs', json_object('id', {ref}.id)); END"
      for op, ref in (("INSERT", "NEW"), ("UPDATE", "NEW"), ("DELETE", "OLD"))],
    *[f"CREATE TRIGGER IF NOT EXISTS sh_cp_{op} AFTER {op} ON checkpoints BEGIN "
      f"INSERT INTO _shadow(tbl,k) VALUES ('checkpoints', json_object('item', {ref}.item, 'stage', {ref}.stage)); END"
      for op, ref in (("INSERT", "NEW"), ("UPDATE", "NEW"), ("DELETE", "OLD"))],
]
DROP_SQL = [f"DROP TRIGGER IF EXISTS {name}" for name in
            [f"sh_{t}_{op}" for t in ("ev", "jobs", "cp") for op in ("INSERT", "UPDATE", "DELETE")]]
_last_flush = 0.0


def backend() -> str:
    """LEDGER_BACKEND env wins (tests, manual runs). Otherwise config/settings.yaml `ledger_backend`, applied ONLY in
    the cloud runner: the cloud's ledger.db is the authoritative one; the PC's copy is replaced on every pull and its
    row ids would collide with the cloud's in the shared truth. Setting it back to sqlite is the off-switch."""
    b = os.environ.get("LEDGER_BACKEND", "").strip().lower()
    if not b:
        from .where import in_runner
        if not in_runner():
            return "sqlite"
        try:
            from ..config import settings
            b = str((settings() or {}).get("ledger_backend") or "sqlite").strip().lower()
        except Exception as e:  # noqa: BLE001 - unreadable settings: stay on the safe default
            print(f"ledger backend: settings unreadable ({type(e).__name__}); using sqlite")
            b = "sqlite"
    return b if b in ("sqlite", "dual", "d1") else "sqlite"


def install(conn: sqlite3.Connection) -> None:
    """Dual mode: shadow table + triggers. Any other mode: no triggers (so _shadow can never grow unread)."""
    if backend() == "dual":
        for s in SHADOW_SQL:
            conn.execute(s)
    else:
        for s in DROP_SQL:
            conn.execute(s)


def sign(key: str, ts: int, body: str) -> str:
    return hmac.new(key.encode(), f"{ts}.{body}".encode(), hashlib.sha256).hexdigest()


class Client:
    """Talks to /api/ledger. transport(body: str, headers: dict) -> dict can be swapped in tests."""

    def __init__(self, url: str | None = None, key: str | None = None, transport=None, clock=time.time):
        self.url = (url or os.environ.get("HH_API_URL", "")).rstrip("/")
        self.key = key or os.environ.get("HH_API_KEY", "")
        self.transport, self.clock = transport, clock

    def configured(self) -> bool:
        return bool(self.transport or (self.url and len(self.key) >= 24))

    def call(self, payload: dict) -> dict:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        ts = int(self.clock())
        headers = {"content-type": "application/json", "x-hh-ts": str(ts), "x-hh-sig": sign(self.key, ts, body)}
        if self.transport:
            return self.transport(body, headers)
        import requests
        r = requests.post(f"{self.url}/api/ledger", data=body.encode(), headers=headers, timeout=20)
        if r.status_code != 200:
            raise RuntimeError(f"ledger API {r.status_code}: {r.text[:200]}")
        return r.json()


def _row(conn: sqlite3.Connection, tbl: str, key: dict) -> dict | None:
    pk = TABLES[tbl]
    r = conn.execute(f"SELECT * FROM {tbl} WHERE " + " AND ".join(f"{k}=?" for k in pk),
                     [key[k] for k in pk]).fetchone()
    if r is None:
        return None
    cols = [d[0] for d in conn.execute(f"SELECT * FROM {tbl} LIMIT 0").description]
    return dict(zip(cols, r))


def pending(conn: sqlite3.Connection) -> int:
    try:
        return conn.execute("SELECT count(*) FROM _shadow").fetchone()[0]
    except sqlite3.OperationalError:
        return 0


def flush(conn: sqlite3.Connection, client: Client | None = None, log=print) -> int:
    """Send the changed rows to the DO. Returns how many changes were applied; unsent rows stay queued."""
    client = client or Client()
    if not client.configured():
        return 0
    try:
        marks = conn.execute("SELECT n, tbl, k FROM _shadow ORDER BY n LIMIT 5000").fetchall()
    except sqlite3.OperationalError:
        return 0
    if not marks:
        return 0
    latest: dict[tuple, int] = {}
    for n, tbl, k in marks:                         # one change per row: its CURRENT image (or a delete)
        if tbl in TABLES:
            latest[(tbl, k)] = n
    changes = []
    for (tbl, k), _n in sorted(latest.items(), key=lambda x: x[1]):
        key = json.loads(k)
        row = _row(conn, tbl, key)
        changes.append({"t": tbl, "op": "up", "row": row} if row is not None else {"t": tbl, "op": "del", "key": key})
    sent = 0
    top = marks[-1][0]
    for i in range(0, len(changes), BATCH):
        res = client.call({"op": "apply", "changes": changes[i:i + BATCH]})
        if res.get("error"):
            raise RuntimeError(f"ledger API refused the batch: {res['error']}")
        sent += int(res.get("applied") or 0)
    conn.execute("DELETE FROM _shadow WHERE n<=?", (top,))
    if conn.in_transaction:                         # a caller's connection without autocommit: never hold the lock
        conn.commit()
    return sent


def maybe_flush(conn: sqlite3.Connection, now: float | None = None, client: Client | None = None, log=print) -> int:
    """After a committed ledger write in dual mode: flush at most every FLUSH_EVERY_S. Never raises (the write
    already succeeded in SQLite); a failure is logged and the rows stay queued."""
    global _last_flush
    now = now or time.time()
    if backend() != "dual" or now - _last_flush < FLUSH_EVERY_S:
        return 0
    _last_flush = now
    try:
        return flush(conn, client, log)
    except Exception as e:  # noqa: BLE001 - shadow copy only; SQLite already has the truth
        log(f"ledger shadow: not sent this time ({type(e).__name__}: {str(e)[:160]}); {pending(conn)} rows queued")
        return 0


def _local_rows(conn: sqlite3.Connection, tbl: str) -> dict:
    pk = TABLES[tbl]
    cols = [d[0] for d in conn.execute(f"SELECT * FROM {tbl} LIMIT 0").description]
    out = {}
    for r in conn.execute(f"SELECT * FROM {tbl}"):
        d = dict(zip(cols, r))
        out[tuple(d[k] for k in pk)] = d
    return out


def _remote_rows(client: Client, tbl: str) -> dict:
    pk, out, after = TABLES[tbl], {}, (["", ""] if tbl == "checkpoints" else 0)
    while True:
        rows = client.call({"op": "rows", "table": tbl, "after": after, "limit": 2000}).get("rows") or []
        for d in rows:
            out[tuple(d[k] for k in pk)] = d
        if len(rows) < 2000:
            return out
        last = rows[-1]
        after = [last["item"], last["stage"]] if tbl == "checkpoints" else last["id"]


def diff(conn: sqlite3.Connection, client: Client | None = None) -> dict:
    """Overnight check: rows missing on either side and rows whose values differ, per table."""
    client = client or Client()
    report = {}
    for tbl in TABLES:
        mine, theirs = _local_rows(conn, tbl), _remote_rows(client, tbl)
        changed = [k for k in mine.keys() & theirs.keys()
                   if any(mine[k].get(c) != theirs[k].get(c) for c in mine[k])]
        report[tbl] = {"local": len(mine), "remote": len(theirs), "missing_remote": len(mine.keys() - theirs.keys()),
                       "extra_remote": len(theirs.keys() - mine.keys()), "changed": len(changed)}
    report["clean"] = all(v["missing_remote"] == 0 and v["extra_remote"] == 0 and v["changed"] == 0
                          for v in report.values() if isinstance(v, dict))
    report["queued"] = pending(conn)
    return report
