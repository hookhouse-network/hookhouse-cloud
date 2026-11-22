"""22 Nov: a make that failed on the PC kept its claim file (taken for CLAIM_H = 5 h): the Itihaas 12:30 video failed
at 05:46 for lack of free pictures and stayed locked until 10:40, although the PC could draw its pictures from 08:05.
The PC never counted its own failures either. Now a failed make frees its claim and the PC keeps a small retry list."""
import json
import time

import pytest

from engine import storyboard
from engine.cloud import media, runner


class Store:
    def __init__(self):
        self.files = {}

    def assets(self, tag):
        return {n: {"name": n, "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
                for (t, n) in self.files if t == tag}

    def put(self, tag, name, data, content_type=""):
        self.files[(tag, name)] = data
        return {"name": name}

    def delete(self, tag, name):
        return self.files.pop((tag, name), None) is not None


IT = {"id": "1122_1230_itihaas_ke_raaz_short", "channel_name": "Itihaas Ke Raaz", "kind": "short"}


@pytest.fixture
def pc(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "PC_FAILS", tmp_path / "make_fails.json")
    errors = []

    def make_one(start, it, log):
        if errors:
            raise errors.pop(0)
        out = tmp_path / "out"
        out.mkdir(exist_ok=True)
        return {"id": it["id"], "out_dir": str(out), "file": "v.mp4"}
    monkeypatch.setattr(runner, "make_one", make_one)
    from engine.cloud import pc_outbox
    monkeypatch.setattr(pc_outbox, "add", lambda *a, **k: None)
    monkeypatch.setattr(pc_outbox, "flush", lambda *a, **k: False)
    return Store(), errors


def test_no_pictures_frees_the_claim_and_waits_for_the_reset(pc, monkeypatch):
    store, errors = pc
    monkeypatch.setattr(storyboard, "reset_at", lambda: time.time() + 3000)
    errors.append(storyboard.NoPictures("5/8 scenes had no picture"))
    with pytest.raises(storyboard.NoPictures):
        runner._make_and_hand_over(store, "2026-11-16", IT, log=lambda *a: None)
    assert IT["id"] not in runner.claims(store)                   # free again for the next make
    rec = json.loads(runner.PC_FAILS.read_text())[IT["id"]]
    assert rec["n"] == 0 and rec["until"] == pytest.approx(time.time() + 3000, abs=5)   # a free limit keeps the tries
    assert runner._pc_waiting(IT["id"])
    rec["until"] = time.time() - 1
    runner.PC_FAILS.write_text(json.dumps({IT["id"]: rec}))
    assert not runner._pc_waiting(IT["id"])                       # the reset came: make it


def test_other_failures_wait_an_hour_and_stop_after_three(pc):
    store, errors = pc
    for n in (1, 2, 3):
        errors.append(RuntimeError("No topic was planned for this slot"))
        with pytest.raises(RuntimeError):
            runner._make_and_hand_over(store, "2026-11-16", IT, log=lambda *a: None)
        rec = json.loads(runner.PC_FAILS.read_text())[IT["id"]]
        assert rec["n"] == n and rec["until"] == pytest.approx(time.time() + 3600, abs=5)
        rec["until"] = time.time() - 1                             # the hour passed
        runner.PC_FAILS.write_text(json.dumps({IT["id"]: rec}))
    assert runner._pc_waiting(IT["id"])                           # 3 failures today: the PC leaves it alone


def test_a_made_video_clears_its_record_and_keeps_its_claim(pc):
    store, errors = pc
    errors.append(RuntimeError("blip"))
    with pytest.raises(RuntimeError):
        runner._make_and_hand_over(store, "2026-11-16", IT, log=lambda *a: None)
    runner._make_and_hand_over(store, "2026-11-16", IT, log=lambda *a: None)
    assert json.loads(runner.PC_FAILS.read_text()) == {} and not runner._pc_waiting(IT["id"])
    assert IT["id"] in runner.claims(store)                       # the cloud tidies it when it merges the video


def test_yesterdays_failures_are_forgotten(pc):
    runner.PC_FAILS.write_text(json.dumps({IT["id"]: {"n": 3, "until": time.time() + 999, "day": "2026-11-01"}}))
    assert not runner._pc_waiting(IT["id"])


def test_the_helper_skips_videos_on_the_pc_retry_list():
    import inspect
    assert "_pc_waiting(it[\"id\"])" in inspect.getsource(runner.helper)
