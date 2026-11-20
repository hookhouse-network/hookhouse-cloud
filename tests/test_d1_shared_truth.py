"""Phase 1 contract tests: the Ledger in dual mode mirrors every committed row to the shared truth (LedgerDO),
exactly, idempotently, and without losing anything when the network fails mid-way."""
import json
import sqlite3

import pytest

from engine.core import d1
from engine.core.ledger import SCHEMA, Ledger


class FakeDO:
    """Python twin of cloud/worker/ledger_do.js: applies row images (INSERT OR REPLACE / DELETE by primary key)."""

    def __init__(self, fail_after: int | None = None):
        self.db = sqlite3.connect(":memory:")
        self.db.executescript(SCHEMA)
        self.calls, self.fail_after = 0, fail_after

    def __call__(self, body, headers):
        assert headers["x-hh-sig"] == d1.sign("k" * 32, int(headers["x-hh-ts"]), body)
        self.calls += 1
        if self.fail_after is not None and self.calls > self.fail_after:
            raise ConnectionError("network cut")
        b = json.loads(body)
        if b["op"] == "apply":
            with self.db:                                       # all or nothing, like transactionSync
                for ch in b["changes"]:
                    pk = d1.TABLES[ch["t"]]
                    if ch["op"] == "up":
                        cols = list(ch["row"])
                        self.db.execute(f"INSERT OR REPLACE INTO {ch['t']}({','.join(cols)}) VALUES "
                                        f"({','.join('?' * len(cols))})", [ch["row"][c] for c in cols])
                    else:
                        self.db.execute(f"DELETE FROM {ch['t']} WHERE " + " AND ".join(f"{k}=?" for k in pk),
                                        [ch["key"][k] for k in pk])
            return {"applied": len(b["changes"])}
        if b["op"] == "rows":
            cur = self.db.execute(f"SELECT * FROM {b['table']}")
            cols = [d[0] for d in cur.description]
            return {"rows": [dict(zip(cols, r)) for r in cur]}
        return {"error": "unknown op"}


@pytest.fixture
def dual(tmp_path, monkeypatch):
    monkeypatch.setenv("LEDGER_BACKEND", "dual")
    monkeypatch.setattr(d1, "FLUSH_EVERY_S", 10 ** 9)               # flush only when the test says so
    monkeypatch.setattr(d1, "_last_flush", 10 ** 12)
    return Ledger(tmp_path / "ledger.db"), tmp_path / "ledger.db"


def _workload(lg: Ledger):
    lg.event("item.status", item="v1", channel="c", data={"to": "made"})
    lg.enqueue("post", "v1:youtube", {"p": 1})
    lg.enqueue("post", "v1:instagram", {"p": 2})
    lg.enqueue("post", "v1:youtube", {"p": 9})                     # idempotent: no second job
    job = lg.claim("pc1", ["post"])[0]
    lg.heartbeat(job["id"], "pc1")
    lg.complete(job["id"], "pc1", {"url": "u"})
    j2 = lg.claim("pc1", ["post"])[0]
    lg.fail(j2["id"], "pc1", "boom", kind="transient")
    lg.run_stage("v1", "script", lambda: {"ok": True})
    lg.invalidate("v1", ["script"])
    lg.run_stage("v1", "render", lambda: {"file": "x.mp4"})


def test_dual_write_mirrors_every_table_exactly(dual):
    lg, path = dual
    _workload(lg)
    fake = FakeDO()
    client = d1.Client(url="https://x", key="k" * 32, transport=fake)
    conn = sqlite3.connect(path)
    assert d1.flush(conn, client) > 0 and d1.pending(conn) == 0
    rep = d1.diff(conn, client)
    assert rep["clean"], rep
    assert rep["jobs"]["local"] == 2 and rep["checkpoints"]["local"] >= 1


def test_network_cut_mid_flush_loses_nothing_and_retry_is_idempotent(dual, monkeypatch):
    lg, path = dual
    monkeypatch.setattr(d1, "BATCH", 2)                             # several calls per flush
    _workload(lg)
    conn = sqlite3.connect(path)
    queued = d1.pending(conn)
    broken = d1.Client(url="https://x", key="k" * 32, transport=FakeDO(fail_after=1))
    with pytest.raises(ConnectionError):
        d1.flush(conn, broken)
    assert d1.pending(conn) == queued                               # nothing dropped from the queue
    fake = FakeDO()
    good = d1.Client(url="https://x", key="k" * 32, transport=fake)
    d1.flush(conn, good)
    d1.flush(conn, good)                                            # nothing left: no-op
    for _ in range(2):                                              # replaying the same rows changes nothing
        lg.event("x", item="v2")
        d1.flush(conn, good)
    assert d1.diff(conn, good)["clean"]


def test_maybe_flush_never_raises_and_keeps_rows(dual, monkeypatch, capsys):
    lg, path = dual
    lg.event("x", item="v1")
    conn = sqlite3.connect(path)
    monkeypatch.setattr(d1, "_last_flush", 0.0)
    monkeypatch.setattr(d1, "FLUSH_EVERY_S", 0.0)
    bad = d1.Client(url="https://x", key="k" * 32, transport=FakeDO(fail_after=0))
    assert d1.maybe_flush(conn, client=bad, log=print) == 0
    assert d1.pending(conn) >= 1 and "rows queued" in capsys.readouterr().out


def test_sqlite_mode_has_no_triggers_so_the_queue_never_grows(tmp_path, monkeypatch):
    monkeypatch.setenv("LEDGER_BACKEND", "dual")
    lg = Ledger(tmp_path / "l.db")
    lg.event("x")
    monkeypatch.setenv("LEDGER_BACKEND", "sqlite")
    lg.event("y")                                                   # reconnect drops the triggers
    conn = sqlite3.connect(tmp_path / "l.db")
    n = d1.pending(conn)
    lg.event("z")
    assert d1.pending(conn) == n
    assert not conn.execute("SELECT name FROM sqlite_master WHERE type='trigger'").fetchall()


def test_signature_matches_the_worker_format():
    # worker: hmacHex(HH_API_KEY, `${ts}.${body}`) -> lowercase hex SHA-256 HMAC
    import hashlib
    import hmac
    assert d1.sign("secret-key-123456789012345", 1700000000, '{"op":"stats"}') == hmac.new(
        b"secret-key-123456789012345", b'1700000000.{"op":"stats"}', hashlib.sha256).hexdigest()


def test_unconfigured_client_sends_nothing(dual, monkeypatch):
    lg, path = dual
    lg.event("x")
    monkeypatch.delenv("HH_API_URL", raising=False)
    monkeypatch.delenv("HH_API_KEY", raising=False)
    conn = sqlite3.connect(path)
    assert d1.flush(conn, d1.Client()) == 0 and d1.pending(conn) >= 1
