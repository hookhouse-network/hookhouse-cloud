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
