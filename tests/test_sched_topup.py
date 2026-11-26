"""23 Nov shadow check (P2): the queue held nothing at 05:16 while the PC had due work.
- the cloud tick, with its own free pictures used up, dropped every story item from its due list and cancelled all
  their jobs (44 cancelled), and a cancelled key could never be queued again (fixed in scheduler.js, see
  cloud/worker/scheduler.test.mjs 6c);
- only the tick filled the queue, hours apart: the PC now adds what it sees as due;
- one job the PC can't make at the head of the queue cost a whole 5-minute round;
- shadow mode now writes what the queue would hand out next vs what the PC really makes (the evidence for 'on')."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from engine import autopilot
from engine.cloud import runner, sched

NOW = datetime(2026, 11, 23, 0, 0, tzinfo=timezone.utc)


class Queue:
    """In-memory queue with the LedgerDO's enqueue rules (a cancelled key opens again; leased/done stay)."""
    def __init__(self, jobs=()):
        self.jobs = {j["key"]: dict(j) for j in jobs}
        self.calls = []

    def enqueue(self, **j):
        self.calls.append(("enqueue", j["key"]))
        old = self.jobs.get(j["key"])
        if old and old["state"] != "cancelled":
            return False
        self.jobs[j["key"]] = dict(j, state="queued")
        return True

    def list(self, state="queued", limit=500):
        self.calls.append(("list", state))
        return [dict(j) for j in self.jobs.values() if j["state"] == state]


@pytest.fixture
def when(monkeypatch):
    monkeypatch.setattr(autopilot, "_when", lambda it: NOW + timedelta(hours=it["h"]))


def _it(iid, h, status="planned", redos=None, kind="short"):
    return {"id": iid, "h": h, "status": status, "gate_redos": redos, "kind": kind, "channel": iid.split("_", 2)[-1]}


def test_the_pc_adds_due_items_the_queue_does_not_have(when):
    q = Queue([{"key": "make:1123_1230_itihaas_ke_raaz_short:1:redo", "kind": "make", "cls": 1, "deadline": 1,
                "state": "cancelled"},
               {"key": "make:1124_0500_brain_snack_short:0:planned", "kind": "make", "cls": 2, "deadline": 2,
                "state": "queued"},
               {"key": "make:1124_0630_bloop_and_friends_long:2:redo", "kind": "make", "cls": 1, "deadline": 3,
                "state": "leased"}])
    due = [("s", _it("1123_1230_itihaas_ke_raaz_short", 7, "redo", 2)),      # remake 2: not queued at all
           ("s", _it("1124_0500_brain_snack_short", 29)),                     # queued already
           ("s", _it("1124_0630_bloop_and_friends_long", 30, "redo", 2, "long"))]   # someone is making it
    logs = []
    seen = sched.top_up(q, due, now=NOW.timestamp(), log=logs.append)
    assert seen["added"] == 1 and q.jobs["make:1123_1230_itihaas_ke_raaz_short:2:redo"]["state"] == "queued"
    assert [c for c in q.calls if c[0] == "enqueue"] == [("enqueue", "make:1123_1230_itihaas_ke_raaz_short:2:redo")]
    assert {sched.item_of(j["key"]) for j in seen["queued"]} == {"1124_0500_brain_snack_short",
                                                                "1123_1230_itihaas_ke_raaz_short"}
    assert "added 1" in logs[-1]
    assert sched.top_up(q, due, now=NOW.timestamp(), log=logs.append)["added"] == 0          # nothing twice


def test_a_cancelled_key_comes_back_when_its_item_is_due_again(when):
    key = "make:1123_0500_deep_blue_files_short:0:planned:late"
    q = Queue([{"key": key, "kind": "make", "cls": 2, "deadline": 1, "state": "cancelled"}])
    seen = sched.top_up(q, [("s", _it("1123_0500_deep_blue_files_short", -5))], now=NOW.timestamp(), log=lambda m: None)
    assert seen["added"] == 1 and q.jobs[key]["state"] == "queued"


def test_item_of_reads_the_plan_item_from_a_key():
    assert sched.item_of("make:1123_1230_itihaas_ke_raaz_short:2:redo") == "1123_1230_itihaas_ke_raaz_short"
    assert sched.item_of("make:1120_0500_cosmos_unboxed_short:0:planned:late") == "1120_0500_cosmos_unboxed_short"
    assert sched.item_of("tap") == "" and sched.item_of(None) == "" and sched.item_of("post:x:1") == ""


def test_the_queue_pick_follows_class_then_slack():
    now = NOW.timestamp()
    jobs = [{"key": "make:b_short:0:planned", "cls": 2, "deadline": now + 600},
            {"key": "make:a_long:0:planned", "cls": 1, "deadline": now + 5 * 3600},                 # slack 4h15
            {"key": "make:c_short:0:planned", "cls": 1, "deadline": now + 4 * 3600 + 30 * 60}]       # slack 4h18
    assert sched.queue_pick(jobs, now) == "a_long"       # the long one's 45 minutes count
    assert sched.queue_pick([], now) == ""
    assert sched.queue_pick([{"key": "make:x_short:0:planned", "cls": 1, "deadline": None}] + jobs[:1], now) == "x_short"


def test_shadow_writes_what_the_queue_would_hand_out_vs_what_the_pc_makes(tmp_path, monkeypatch):
    monkeypatch.setattr(sched, "SHADOW_LOG", tmp_path / "shadow.jsonl")
    now = NOW.timestamp()
    queued = [{"key": "make:waiting_short:0:planned", "cls": 1, "deadline": now + 60},     # the PC can't make it now
              {"key": "make:soon_short:0:planned", "cls": 1, "deadline": now + 3600},
              {"key": "make:later_short:0:planned", "cls": 1, "deadline": now + 7200}]
    logs = []
    a = sched.shadow_compare(queued, ["later_short", "soon_short"], now=now, log=logs.append)
    b = sched.shadow_compare(queued, ["soon_short"], now=now, log=logs.append)
    assert (a["queue"], a["pc"], a["same"], a["not_here"]) == ("soon_short", "later_short", False, 1)
    assert b["same"] and "same video" in logs[-1] and "the PC makes later_short" in logs[0]
    rows = [json.loads(x) for x in (tmp_path / "shadow.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [r["same"] for r in rows] == [False, True] and rows[0]["queued"] == 3


def test_the_cloud_queue_sync_ignores_its_own_picture_supply(monkeypatch):
    got = {}

    def due(kinds, skip, connected_only=False, pictures=True):
        got["pictures"] = pictures
        return [("s", {"id": "a", "kind": "short"}), ("s", {"id": "c", "kind": "clip"})]
    monkeypatch.setattr(runner, "_due_to_make", due)
    monkeypatch.setattr(sched, "mode", lambda: "shadow")

    class Client:
        def available(self):
            return True
    monkeypatch.setattr(sched, "SchedClient", Client)
    monkeypatch.setattr(sched, "sync_due", lambda client, d, log=print: {"due": [it["id"] for _s, it in d]})
    assert runner._queue_sync(log=lambda m: None) == {"due": ["a"]} and got["pictures"] is False


def test_due_to_make_can_skip_the_picture_check(monkeypatch):
    from engine import storyboard, weekly
    monkeypatch.setattr(storyboard, "images_blocked", lambda: pytest.fail("the queue must not ask"))
    monkeypatch.setattr(autopilot, "items", lambda *a, **k: [])
    assert runner._due_to_make(None, set(), pictures=False) == []
    assert weekly.TO_MAKE                                 # (the real list the filter reads)


def test_next_job_moves_past_several_jobs_it_cannot_make(monkeypatch):
    monkeypatch.setattr("engine.config.settings", lambda: {"scheduler": "on"})
    sent = []

    class T:
        def __init__(self):
            self.queue = [{"id": i, "epoch": 1, "key": f"make:z{i}:0:planned", "payload": {"item": f"z{i}"}}
                          for i in range(3)] + [{"id": 9, "epoch": 4, "key": "make:a:0:planned", "payload": {"item": "a"}}]

        def call(self, p):
            sent.append(p)
            if p["op"] == "s_claim":
                return {"jobs": [self.queue.pop(0)] if self.queue else []}
            return {"state": "queued", "ok": 1}
    hb = sched.Heartbeat(sched.SchedClient(client=T()), "pc-t", "pc", [], log=lambda *_: None)
    start, it, job = sched.next_job(hb, {"a": ("s", {"id": "a"})}, log=lambda m: None)
    assert job["id"] == 9 and sum(1 for p in sent if p["op"] == "s_fail") == 3
    assert sched.next_job(hb, {"a": ("s", {"id": "a"})}, log=lambda m: None) is None     # empty queue: no loop


def test_next_job_stops_after_the_put_back_limit(monkeypatch):
    monkeypatch.setattr("engine.config.settings", lambda: {"scheduler": "on"})
    claims = []

    class Forever:
        def call(self, p):
            if p["op"] == "s_claim":
                claims.append(1)
                return {"jobs": [{"id": len(claims), "epoch": 1, "key": "make:z:0:planned", "payload": {"item": "z"}}]}
            return {"state": "queued"}
    hb = sched.Heartbeat(sched.SchedClient(client=Forever()), "pc-t", "pc", [], log=lambda *_: None)
    assert sched.next_job(hb, {}, log=lambda m: None) is None and len(claims) == sched.PUT_BACK_MAX


def test_a_job_handed_back_is_held_three_hours(monkeypatch):
    """26 Nov: 8 clip jobs the PC could not make were offered again every 30 min, eating each round's put-backs."""
    import time
    monkeypatch.setattr("engine.config.settings", lambda: {"scheduler": "on"})
    sent = []

    class T:
        def call(self, p):
            sent.append(p)
            if p["op"] == "s_claim":
                return {"jobs": [{"id": 1, "epoch": 1, "key": "make:z:0:planned:clip", "payload": {"item": "z"}}]
                        if not any(x["op"] == "s_fail" for x in sent) else []}
            return {"state": "queued", "ok": 1}
    hb = sched.Heartbeat(sched.SchedClient(client=T()), "pc-t", "pc", [], log=lambda *_: None)
    assert sched.next_job(hb, {"a": ("s", {"id": "a"})}, log=lambda m: None) is None
    fail = next(p for p in sent if p["op"] == "s_fail")
    assert fail["retry_at"] >= time.time() + 3 * 3600 - 60
