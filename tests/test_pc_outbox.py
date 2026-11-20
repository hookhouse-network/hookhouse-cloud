"""Plan P0 4b/4c: a finished PC video is never remade because its upload failed; the PC claims nothing on a full disk."""
import json
import time
from collections import namedtuple

import pytest

from engine.cloud import pc_outbox


class FlakyStore:
    def __init__(self, fail_uploads=0):
        self.files, self.fail = {}, fail_uploads

    def put(self, tag, name, data, content_type="application/octet-stream"):
        if name.endswith(".zip") and self.fail > 0:
            self.fail -= 1
            raise ConnectionError("SSLError: uploads.github.com")
        self.files[name] = data
        return {}


@pytest.fixture
def outbox(tmp_path, monkeypatch):
    monkeypatch.setattr(pc_outbox, "PENDING", tmp_path / "pending")
    folder = tmp_path / "out" / "v1"
    folder.mkdir(parents=True)
    (folder / "video.mp4").write_bytes(b"mp4")
    return folder


def test_failed_upload_keeps_the_video_and_retries_with_backoff(outbox):
    store = FlakyStore(fail_uploads=2)
    pc_outbox.add("i1", outbox, {"id": "i1", "start": "2026-11-16"})
    t = time.time()
    assert pc_outbox.flush(store, log=lambda *a: None, now=t) == 0
    rec = pc_outbox.pending()[0]
    assert rec["attempts"] == 1 and rec["next_at"] > t and "SSLError" in rec["error"]
    assert store.files["claim-i1.json"]                        # the slot stays ours while we retry
    assert pc_outbox.flush(store, log=lambda *a: None, now=t + 1) == 0      # not due yet: no new try
    assert pc_outbox.pending()[0]["attempts"] == 1
    assert pc_outbox.flush(store, log=lambda *a: None, now=t + 10_000) == 0  # second failure
    assert pc_outbox.flush(store, log=lambda *a: None, now=t + 99_999) == 1  # third try works
    assert not pc_outbox.pending()
    assert json.loads(store.files["done-i1.json"])["id"] == "i1" and "i1.zip" in store.files


def test_backoff_is_capped_and_jittered():
    assert pc_outbox.backoff(1, rnd=0.5) == 60
    assert pc_outbox.backoff(3, rnd=0.5) == 240
    assert pc_outbox.backoff(30, rnd=0.5) == pc_outbox.MAX_WAIT_S
    assert pc_outbox.backoff(1, rnd=0.0) == 30 and pc_outbox.backoff(1, rnd=1.0) == 90


def test_report_after_five_failures(outbox):
    store = FlakyStore(fail_uploads=99)
    pc_outbox.add("i1", outbox, {"id": "i1"})
    t = time.time()
    for k in range(pc_outbox.REPORT_AFTER):
        assert not pc_outbox.alerts() or k == pc_outbox.REPORT_AFTER
        pc_outbox.flush(store, log=lambda *a: None, now=t + k * 10_000)
    a = pc_outbox.alerts()
    assert "upload:i1" in a and "nothing is lost" in a["upload:i1"]


def test_pending_record_survives_a_restart_and_a_lost_folder_is_dropped(outbox, tmp_path):
    pc_outbox.add("i1", outbox, {"id": "i1"})
    pc_outbox.add("i2", tmp_path / "gone", {"id": "i2"})
    assert {r["id"] for r in pc_outbox.pending()} == {"i1", "i2"}         # read back from disk (a new process)
    store = FlakyStore()
    assert pc_outbox.flush(store, log=lambda *a: None) == 1
    assert not pc_outbox.pending() and "done-i2.json" not in store.files


Usage = namedtuple("Usage", "total used free")


def test_disk_guard_cleans_up_then_stops_claiming(monkeypatch, tmp_path):
    frees = iter([2e9, 3e9])
    monkeypatch.setattr(pc_outbox.shutil, "disk_usage", lambda p: Usage(1, 1, next(frees)))
    cleaned = []
    assert not pc_outbox.disk_ok(log=lambda *a: None, path=tmp_path, cleanup=lambda log: cleaned.append(1))
    assert cleaned and "disk" in pc_outbox.alerts()
    frees2 = iter([2e9, 9e9])
    monkeypatch.setattr(pc_outbox.shutil, "disk_usage", lambda p: Usage(1, 1, next(frees2)))
    assert pc_outbox.disk_ok(log=lambda *a: None, path=tmp_path, cleanup=lambda log: None)
    assert "disk" not in pc_outbox.alerts()                    # cleared once there is room again


def test_watchdog_forwards_fresh_pc_alerts():
    from engine import watchdog

    class S:
        def __init__(self, hb):
            self.hb = hb

        def get(self, tag, name):
            return json.dumps(self.hb).encode()
    now = time.time()
    fresh = watchdog.problems(S({"at": now, "chrome": True, "alerts": {"disk": "low disk"}}), now=now)
    assert fresh.get("pc:disk") == "low disk"
    stale = watchdog.problems(S({"at": now - 99 * 3600, "chrome": True, "alerts": {"disk": "low disk"}}), now=now)
    assert "pc:disk" not in stale
