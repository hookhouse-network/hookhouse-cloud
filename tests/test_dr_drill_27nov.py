"""27 Nov (P9 disaster-recovery drill): the cloud memory restores; one backup is overwritten on every save, so a
snapshot per weekday keeps 7 restore points (written once a day, the marker travels inside the bundle)."""
import json
import sqlite3
import time

from engine.cloud import dr_drill, state
from tests.test_cloud import FakeStore


def _tree(root):
    (root / "data" / "weeks" / "2026-11-23").mkdir(parents=True)
    (root / "data" / "weeks" / "2026-11-23" / "plan.json").write_text(json.dumps({"items": [{"id": "a"}]}),
                                                                       encoding="utf-8")
    c = sqlite3.connect(str(root / "data" / "ledger.db"))
    c.execute("CREATE TABLE events (id INTEGER)")
    c.execute("INSERT INTO events VALUES (1)")
    c.commit()
    c.close()
    (root / "data" / "publish_log.jsonl").write_text('{"a": 1}\n', encoding="utf-8")


def test_a_day_snapshot_is_written_once_and_the_bundle_restores(tmp_path, monkeypatch):
    monkeypatch.setenv("STATE_KEY", state.new_key())
    _tree(tmp_path)
    s = FakeStore()
    state.push(s, tmp_path)
    day = time.strftime("%a").lower()
    assert ("state", f"state.{day}.bin") in s.files
    snap = s.files[("state", f"state.{day}.bin")]
    state.push(s, tmp_path)
    assert s.files[("state", f"state.{day}.bin")] == snap                     # not again the same day
    restored = tmp_path / "restored"
    state.unpack(s.files[("state", state.NAME)], restored)
    assert (restored / "data" / "state" / f"snapshot_{day}.txt").exists()     # the marker travels in the bundle
    r = dr_drill.check_tree(restored)
    assert dr_drill.usable(r) and r["items"] == 1 and r["ledger_events"] == 1


def test_a_broken_plan_makes_the_bundle_unusable(tmp_path):
    _tree(tmp_path)
    (tmp_path / "data" / "weeks" / "2026-11-23" / "plan.json").write_text("{broken", encoding="utf-8")
    r = dr_drill.check_tree(tmp_path)
    assert not dr_drill.usable(r) and r["plan_errors"]
