"""Phase 2 acceptance: cloud/worker/scheduler.js (the code the LedgerDO runs) passes its checks on Node's built-in
SQLite: re-lease after a PC sleeps + late completion refused by the epoch, P0 never waits behind P2, EDF, GitHub render
only as a fallback (never long videos), clean release, and zero double completions over 10,000 randomized runs."""
import shutil
import subprocess
from pathlib import Path

import pytest

from engine.cloud import sched

ROOT = Path(__file__).resolve().parents[1]


def _node_sqlite() -> bool:
    node = shutil.which("node")
    if not node:
        return False
    r = subprocess.run([node, "-e", "require('node:sqlite')"], capture_output=True, text=True, timeout=60)
    return r.returncode == 0


@pytest.mark.skipif(not _node_sqlite(), reason="needs Node 22.13+ (node:sqlite)")
def test_scheduler_js_acceptance_and_property():
    r = subprocess.run([shutil.which("node"), str(ROOT / "cloud" / "worker" / "scheduler.test.mjs")],
                       capture_output=True, text=True, timeout=900, encoding="utf-8", errors="replace")
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
    assert "all checks passed" in r.stdout and ", 0 doubles" in r.stdout


class Transport:
    def __init__(self, reply):
        self.reply, self.sent = reply, []

    def call(self, payload):
        self.sent.append(payload)
        return self.reply


def test_pc_heartbeat_builds_presence_and_releases(monkeypatch):
    import time as _t
    t = Transport({"ok": 1, "released": 0})
    hb = sched.Heartbeat(sched.SchedClient(client=t), "pc-test", "pc", ["ffmpeg", "pc"], every_s=0.05,
                         log=lambda *_: None).start()
    for _ in range(100):
        if hb.beats >= 2:
            break
        _t.sleep(0.02)
    hb.stop()
    hb.thread.join(timeout=2)
    ops = [p["op"] for p in t.sent]
    assert ops.count("s_register") >= 2 and ops[-1] == "s_release" and not hb.thread.is_alive()
    assert t.sent[0]["worker"] == {"id": "pc-test", "kind": "pc", "caps": ["ffmpeg", "pc"], "slots": {},
                                   "version": "", "load": 0.0}


def test_heartbeat_off_switch_and_unconfigured(monkeypatch):
    monkeypatch.setattr("engine.config.settings", lambda: {"scheduler": "off"})
    assert sched.mode() == "off" and sched.start_pc_heartbeat(log=lambda *_: None) is None
    monkeypatch.setattr("engine.config.settings", lambda: {"scheduler": "shadow"})
    assert sched.start_pc_heartbeat(log=lambda *_: None) is None          # tests: the signed API is never set up
    monkeypatch.setattr("engine.config.settings", lambda: {"scheduler": "sideways"})
    assert sched.mode() == "off"
    assert {"ffmpeg", "pc"} <= set(sched.pc_caps())


class QueueTwin:
    """In-memory stand-in for the LedgerDO queue (enqueue / list / cancel only)."""
    def __init__(self):
        self.jobs = {}

    def enqueue(self, **j):
        if j["key"] in self.jobs:
            return False
        self.jobs[j["key"]] = dict(j, state="queued")
        return True

    def list(self, state="queued", limit=500):
        return [j for j in self.jobs.values() if j["state"] == state]

    def cancel(self, key):
        if self.jobs.get(key, {}).get("state") == "queued":
            self.jobs[key]["state"] = "cancelled"
            return True
        return False


def test_queue_mirrors_what_is_due(monkeypatch):
    from datetime import datetime, timedelta, timezone

    from engine import autopilot
    now = datetime(2026, 11, 21, 17, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(autopilot, "_when", lambda it: now + timedelta(hours=it["h"]))
    q = QueueTwin()
    due = [("s1", {"id": "a", "kind": "short", "status": "planned", "h": 5, "channel": "brain_snack"}),
           ("s2", {"id": "b", "kind": "long", "status": "planned", "h": 50, "channel": "bloop_and_friends"})]
    r = sched.sync_due(q, due, now=now.timestamp(), log=lambda *_: None)
    assert r == {"due": 2, "added": 2, "cancelled": 0}
    a, b = q.jobs["make:a:0:planned"], q.jobs["make:b:0:planned"]
    assert a["cls"] == 1 and a["fallback"] and "pc" not in a["requires"]
    assert b["cls"] == 2 and b["fallback"] == [] and "pc" in b["requires"] and b["est_min"] == 45
    # 'a' was made through the claim files and 'b' was remade: a's job is cancelled, b gets a new key
    due2 = [("s2", {"id": "b", "kind": "long", "status": "redo", "gate_redos": 1, "h": 50})]
    r2 = sched.sync_due(q, due2, now=now.timestamp(), log=lambda *_: None)
    assert r2 == {"due": 1, "added": 1, "cancelled": 2}
    assert q.jobs["make:a:0:planned"]["state"] == "cancelled" and "make:b:1:redo" in q.jobs
    assert sched.sync_due(q, due2, now=now.timestamp(), log=lambda *_: None)["added"] == 0   # idempotent


def test_a_late_video_never_jumps_ahead_of_a_slot_that_can_still_be_made(monkeypatch):
    """22 Nov shadow check: the 20 and 21 Nov Itihaas videos (slots passed, still made up to 3 days late) headed the
    queue with class P1 and their old deadlines, ahead of tonight's 19:00 Cricket long video."""
    from datetime import datetime, timedelta, timezone

    from engine import autopilot
    now = datetime(2026, 11, 22, 8, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(autopilot, "_when", lambda it: now + timedelta(hours=it["h"]))
    q = QueueTwin()
    on_time = {"id": "1117_1230_cricket_ke_kisse_long", "kind": "long", "status": "planned", "h": 5.5}
    late = {"id": "1120_1230_itihaas_ke_raaz_short", "kind": "short", "status": "planned", "h": -50}
    sched.sync_due(q, [("s1", late), ("s1", on_time)], now=now.timestamp(), log=lambda *_: None)
    lj, oj = q.jobs["make:1120_1230_itihaas_ke_raaz_short:0:planned:late"], \
        q.jobs["make:1117_1230_cricket_ke_kisse_long:0:planned"]
    assert oj["cls"] == 1 and lj["cls"] == 2                         # the slot that can still be saved goes first
    assert lj["deadline"] == now.timestamp() + 24 * 3600             # the late one is still made (next free slot)
    order = sorted(q.list(), key=lambda j: (j["cls"], j["deadline"]))
    assert order[0]["key"] == oj["key"]
    # a job queued before this rule (old key, class P1, old deadline) is cancelled by the next sync
    q.jobs["make:1121_1230_itihaas_ke_raaz_short:0:planned"] = {"key": "make:1121_1230_itihaas_ke_raaz_short:0:planned",
                                                                "kind": "make", "cls": 1, "state": "queued"}
    late2 = {"id": "1121_1230_itihaas_ke_raaz_short", "kind": "short", "status": "planned", "h": -26}
    r = sched.sync_due(q, [("s1", late), ("s1", on_time), ("s1", late2)], now=now.timestamp(), log=lambda *_: None)
    assert r["cancelled"] == 1 and "make:1121_1230_itihaas_ke_raaz_short:0:planned:late" in q.jobs


class JobsTwin(Transport):
    """A queue that hands out given jobs and records the reports."""
    def __init__(self, jobs):
        super().__init__({})
        self.queue = list(jobs)

    def call(self, payload):
        self.sent.append(payload)
        op = payload["op"]
        if op == "s_claim":
            return {"jobs": [self.queue.pop(0)] if self.queue else []}
        if op == "s_complete":
            return {"ok": 1}
        if op == "s_fail":
            return {"state": "queued"}
        return {"ok": 1}


def test_pc_takes_its_work_from_the_queue_in_on_mode(monkeypatch):
    monkeypatch.setattr("engine.config.settings", lambda: {"scheduler": "on"})
    job = {"id": 5, "epoch": 2, "key": "make:a:0:planned", "payload": {"item": "a"}}
    gone = {"id": 6, "epoch": 1, "key": "make:z:0:planned", "payload": {"item": "z"}}
    t = JobsTwin([gone, job])
    hb = sched.Heartbeat(sched.SchedClient(client=t), "pc-test", "pc", ["ffmpeg"], log=lambda *_: None)
    items = {"a": ("s1", {"id": "a"})}
    assert sched.next_job(hb, items, log=lambda *_: None) is None          # 'z' is not due here: put back
    assert t.sent[-1]["op"] == "s_fail" and t.sent[-1]["kind"] == "quota" and t.sent[-1]["retry_at"]
    start, it, j = sched.next_job(hb, items, log=lambda *_: None)
    assert (start, it["id"], j["id"]) == ("s1", "a", 5) and hb.jobs == {5: 2}   # its lease is kept alive
    assert sched.finish_job(hb, j, {"out_rel": "x"}, log=lambda *_: None) == "done" and hb.jobs == {}
    assert t.sent[-1] == {"op": "s_complete", "job": 5, "worker": "pc-test", "epoch": 2, "result": {"out_rel": "x"}}
    hb.track(j)
    assert sched.finish_job(hb, j, error=RuntimeError("render crashed"), log=lambda *_: None) == "queued"
    assert t.sent[-1]["kind"] == "transient"
    monkeypatch.setattr("engine.config.settings", lambda: {"scheduler": "shadow"})
    assert sched.next_job(hb, items) == "fallback"                         # shadow: the claim files still decide

    class Down(Transport):
        def call(self, payload):
            raise RuntimeError("ledger API 503")
    monkeypatch.setattr("engine.config.settings", lambda: {"scheduler": "on"})
    hb2 = sched.Heartbeat(sched.SchedClient(client=Down({})), "pc-test", "pc", [], log=lambda *_: None)
    assert sched.next_job(hb2, items, log=lambda *_: None) == "fallback"   # degraded mode: claim files


def test_github_render_joins_the_queue_only_in_on_mode(monkeypatch):
    from engine.cloud import runner
    monkeypatch.setattr("engine.config.settings", lambda: {"scheduler": "shadow"})
    assert runner._gh_worker(log=lambda *_: None) is None                   # shadow: the render run works as before
    t = JobsTwin([])

    class Client(sched.SchedClient):
        def __init__(self):
            super().__init__(client=t)

        def available(self):
            return True
    monkeypatch.setattr("engine.config.settings", lambda: {"scheduler": "on"})
    monkeypatch.setattr(sched, "SchedClient", Client)
    monkeypatch.setenv("GITHUB_RUN_ID", "4242")
    gh = runner._gh_worker(log=lambda *_: None)
    try:
        assert gh.kind == "gh_render" and gh.wid == "gh-render-4242"
        assert t.sent[0]["op"] == "s_register" and t.sent[0]["worker"]["kind"] == "gh_render"   # before any claim
        assert sched.next_job(gh, {}, log=lambda *_: None) is None          # nothing handed out: no Actions minutes
    finally:
        gh.stop()
    assert t.sent[-1]["op"] == "s_release"


def test_client_sends_the_scheduler_ops():
    t = Transport({"jobs": [{"id": 7, "epoch": 3, "key": "a"}], "ok": 1, "added": True, "state": "queued",
                   "released": 2})
    c = sched.SchedClient(client=t)
    c.register("pc-main", "pc", ["ffmpeg", "kokoro"], slots={"1": 1})
    assert t.sent[-1]["op"] == "s_register" and t.sent[-1]["worker"]["id"] == "pc-main"
    assert c.enqueue("make", "1124_0500_brain_snack_short", cls=1, deadline=1.0, prefer=["pc"]) is True
    assert t.sent[-1]["job"]["key"] == "1124_0500_brain_snack_short" and t.sent[-1]["job"]["cls"] == 1
    assert c.claim("pc-main")[0]["epoch"] == 3
    assert c.complete(7, "pc-main", 3, {"asset": "x.zip"}) and t.sent[-1] == {
        "op": "s_complete", "job": 7, "worker": "pc-main", "epoch": 3, "result": {"asset": "x.zip"}}
    assert c.fail(7, "pc-main", 3, "boom") == "queued" and c.release("pc-main") == 2
    with pytest.raises(ValueError):
        c.register("x", "laptop", [])
    with pytest.raises(sched.SchedError, match="nope"):
        sched.SchedClient(client=Transport({"error": "nope"})).stats()
