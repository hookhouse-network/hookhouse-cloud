"""Phase 1 of docs/ARCHITECTURE.md: lifecycle state machine, ledger (events + lease-based job queue), atomic writes,
no silent plan loss, and a ratchet so silently swallowed errors can only go down."""
import json
import re
from pathlib import Path

import pytest

from engine.core import atomic, ledger, lifecycle


# ---------------------------------------------------------------- lifecycle
def test_every_state_has_rules_and_terminal_states_stay_put():
    for s in lifecycle.STATES:
        assert s in lifecycle.TRANSITIONS, s
    assert lifecycle.allowed("planned", "making") and lifecycle.allowed("making", "made")
    assert lifecycle.allowed("made", "approved") and lifecycle.allowed("approved", "posted")
    assert not lifecycle.allowed("posted", "making")          # a posted video is never made again
    assert not lifecycle.allowed("posted", "planned")
    assert not lifecycle.allowed("rejected", "posted")        # nothing the owner rejected goes live


def test_audit_logs_changes_and_reports_illegal_ones(monkeypatch):
    before = {"items": [{"id": "a", "status": "posted", "channel": "c"}, {"id": "b", "status": "planned"}]}
    after = {"items": [{"id": "a", "status": "making", "channel": "c"}, {"id": "b", "status": "making"},
                       {"id": "n", "status": "planned"}]}
    events, reports = [], []
    changes = lifecycle.audit(before, after, log_event=lambda t, **k: events.append((t, k)),
                              report=lambda a, e, channel="": reports.append(e))
    assert {(c["item"], c["ok"]) for c in changes} == {("a", False), ("b", True), ("n", True)}
    assert len(events) == 3 and reports == ["illegal status change posted -> making"]
    monkeypatch.setenv("LIFECYCLE_MODE", "enforce")
    with pytest.raises(lifecycle.IllegalTransition):
        lifecycle.audit(before, after)


def test_save_plan_records_every_status_change(tmp_path, monkeypatch):
    from engine import weekly
    monkeypatch.setattr(weekly, "WEEKS_DIR", tmp_path / "weeks")
    monkeypatch.setattr(weekly, "week_dir", lambda s: tmp_path / "weeks" / str(s))
    plan = {"start": "2026-11-23", "items": [{"id": "x", "status": "planned", "channel": "c"}]}
    weekly.save_plan(plan)
    plan["items"][0]["status"] = "making"
    weekly.save_plan(plan)
    plan["items"][0]["status"] = "made"
    weekly.save_plan(plan)
    hist = [(e["data"]["old"], e["data"]["new"]) for e in ledger.default().history("x")]
    assert hist == [(None, "planned"), ("planned", "making"), ("making", "made")]


# ---------------------------------------------------------------- ledger: job queue
class Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


def _ledger(tmp_path, clock):
    return ledger.Ledger(tmp_path / "l.db", clock=clock, rng=lambda: 1.0)


def test_enqueue_is_idempotent(tmp_path):
    led = _ledger(tmp_path, Clock())
    assert led.enqueue("publish", "post:item1:instagram", {"item": "item1"})
    assert not led.enqueue("publish", "post:item1:instagram", {"item": "item1"})   # same key: no second post
    assert len(led.jobs()) == 1


def test_one_job_goes_to_one_worker_and_a_dead_worker_releases_it(tmp_path):
    clk = Clock()
    led = _ledger(tmp_path, clk)
    led.enqueue("render", "r1")
    a = led.claim("pc", ["render"], lease_s=60)
    assert len(a) == 1 and led.claim("cloud", ["render"]) == []      # leased: nobody else gets it
    clk.t += 61                                                       # the PC was switched off mid-render
    b = led.claim("cloud", ["render"], lease_s=60)
    assert len(b) == 1 and b[0]["attempts"] == 2
    assert not led.complete(a[0]["id"], "pc")                         # the old worker lost its lease
    assert led.complete(b[0]["id"], "cloud", {"file": "v.mp4"})
    assert led.stats() == {"render": {"done": 1}}


def test_heartbeat_keeps_a_long_job(tmp_path):
    clk = Clock()
    led = _ledger(tmp_path, clk)
    led.enqueue("render", "r1")
    j = led.claim("pc", lease_s=60)[0]
    for _ in range(5):
        clk.t += 50
        assert led.heartbeat(j["id"], "pc", lease_s=60)
    assert led.claim("cloud") == []


def test_transient_failures_back_off_then_go_dead(tmp_path):
    clk = Clock()
    led = _ledger(tmp_path, clk)
    led.enqueue("render", "r1", max_attempts=3)
    waits = []
    for n in range(3):
        j = led.claim("pc")[0]
        state = led.fail(j["id"], "pc", "ffmpeg crashed")
        row = led.jobs()[0]
        waits.append(row["run_after"] - clk.t)
        clk.t = row["run_after"]
    assert state == "dead" and waits[0] == 60 and waits[1] == 120      # capped exponential backoff (jitter = 1.0)
    assert [e["data"]["job"] for e in led.events("job.dead")] == [1]
    assert led.retry_dead(1) and led.jobs()[0]["state"] == "queued"


def test_quota_waits_do_not_use_up_attempts(tmp_path):
    clk = Clock()
    led = _ledger(tmp_path, clk)
    led.enqueue("render", "r1", max_attempts=2)
    for _ in range(5):                                                 # five daily-limit days in a row
        j = led.claim("pc")[0]
        assert led.fail(j["id"], "pc", "free pictures used up", kind="quota", retry_at=clk.t + 3600) == "queued"
        assert led.claim("pc") == []                                   # waits for the reset
        clk.t += 3600
    assert led.jobs()[0]["attempts"] == 0


def test_permanent_failure_is_dead_at_once(tmp_path):
    led = _ledger(tmp_path, Clock())
    led.enqueue("publish", "p1")
    j = led.claim("cloud")[0]
    assert led.fail(j["id"], "cloud", "video rejected: copyright", kind="permanent") == "dead"


def test_priority_and_due_time_order(tmp_path):
    clk = Clock()
    led = _ledger(tmp_path, clk)
    led.enqueue("render", "later", run_after=clk.t + 100)
    led.enqueue("render", "low")
    led.enqueue("render", "high", priority=5)
    assert [j["key"] for j in led.claim("pc", limit=5)] == ["high", "low"]


# ---------------------------------------------------------------- atomic writes / no silent loss
def test_atomic_write_never_leaves_half_a_file(tmp_path, monkeypatch):
    p = tmp_path / "state.json"
    atomic.write_json(p, {"tokens": {"a": 1}})

    def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(atomic.os, "replace", boom)
    with pytest.raises(OSError):
        atomic.write_json(p, {"tokens": {}})
    assert json.loads(p.read_text(encoding="utf-8")) == {"tokens": {"a": 1}}    # old version intact
    assert [f.name for f in tmp_path.iterdir()] == ["state.json"]               # no temp files left behind


def test_an_unreadable_plan_is_reported_not_hidden(tmp_path, monkeypatch):
    from engine import autopilot, heal, weekly
    monkeypatch.setattr(weekly, "WEEKS_DIR", tmp_path)
    (tmp_path / "2026-11-23").mkdir()
    (tmp_path / "2026-11-23" / "plan.json").write_text('{"start": "2026-11-23", "items": [', encoding="utf-8")
    assert autopilot.items() == []
    assert ledger.default().events("plan.unreadable")
    assert any(s.startswith("plan:") for s in heal._load()["items"])


# ---------------------------------------------------------------- ratchet
SILENT_BASELINE = 0        # 27 Nov (P9): was 110; every deliberate carry-on now calls engine.core.quiet.noted()


def test_silently_swallowed_errors_never_grow():
    rx = re.compile(r"except Exception[^\n]*:\s*(#[^\n]*)?\n\s+(pass|continue|return None|return \[\]|return \{\}|"
                    r"return False)\s*(#[^\n]*)?\n")
    n = sum(len(rx.findall(f.read_text(encoding="utf-8", errors="ignore")))
            for f in Path("engine").rglob("*.py"))
    assert n <= SILENT_BASELINE, (f"{n} silent excepts (baseline {SILENT_BASELINE}): handle or report the error "
                                  "instead of swallowing it")


# ---------------------------------------------------------------- resumable stages (checkpoints)
ORDER = ("script", "storyboard", "pictures", "render")


def test_a_finished_stage_is_reused_after_a_crash(tmp_path):
    led = _ledger(tmp_path, Clock())
    calls = []
    led.run_stage("v1", "script", lambda: calls.append(1) or {"title": "T"}, lambda a: bool(a and a.get("title")))
    with pytest.raises(RuntimeError):                       # the render crashed (PC switched off)
        led.run_stage("v1", "render", lambda: (_ for _ in ()).throw(RuntimeError("killed")))
    again = led.run_stage("v1", "script", lambda: calls.append(1) or {"title": "other"},
                          lambda a: bool(a and a.get("title")))
    assert again == {"title": "T"} and calls == [1]          # no second AI call for the script
    assert led.checkpoint("v1", "render")["status"] == "failed"


def test_a_broken_artifact_is_redone_and_later_stages_dropped(tmp_path):
    led = _ledger(tmp_path, Clock())
    f = tmp_path / "pics.json"
    f.write_text("[]")
    ok = lambda a: bool(a and Path(a["file"]).exists())     # noqa: E731
    led.run_stage("v1", "pictures", lambda: {"file": str(f)}, ok, ORDER)
    led.run_stage("v1", "render", lambda: {"file": "v.mp4"}, order=ORDER)
    f.unlink()                                               # the cache was cleaned
    out = led.run_stage("v1", "pictures", lambda: (f.write_text("[1]"), {"file": str(f)})[1], ok, ORDER)
    assert Path(out["file"]).exists()
    assert led.checkpoint("v1", "render") is None            # the old render no longer matches the pictures
    assert led.checkpoint("v1", "pictures")["attempts"] == 2


def test_an_incomplete_result_does_not_count_as_done(tmp_path):
    led = _ledger(tmp_path, Clock())
    with pytest.raises(ValueError):
        led.run_stage("v1", "script", lambda: {"title": ""}, lambda a: bool(a.get("title")))
    assert led.checkpoint("v1", "script")["status"] == "failed"
