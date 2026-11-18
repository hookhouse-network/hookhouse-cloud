"""Safety rules: old buttons, approvals during a remake, undoing a scheduled YouTube upload, clip metadata, Facebook
duration guard, shared clip folders in the cleanup, failure back-off."""
import json
import time
from datetime import timedelta

import pytest

from engine import autopilot, cleanup, publish, weekly


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(weekly, "WEEKS_DIR", tmp_path / "weeks")
    monkeypatch.setattr(autopilot, "STATE", tmp_path / "autopilot.json")
    sent = []
    from engine import telegram_bot as tb
    monkeypatch.setattr(tb, "notify", lambda t: sent.append(t) or True)
    out = tmp_path / "out" / "v1"
    out.mkdir(parents=True)
    (out / "video.mp4").write_bytes(b"x")
    (out / "upload.json").write_text(json.dumps({"title": "T"}))
    now = autopilot._now()
    plan = {"start": "2099-01-05", "items": [
        {"id": "a", "channel": "unsolved_after_dark", "channel_name": "Unsolved", "kind": "short",
         "publish_at": (now + timedelta(hours=10)).isoformat(), "status": "made", "made_at": 111.0,
         "out_dir": str(out), "file": "video.mp4"}]}
    (tmp_path / "weeks" / "2099-01-05").mkdir(parents=True)
    (tmp_path / "weeks" / "2099-01-05" / "plan.json").write_text(json.dumps(plan))
    monkeypatch.setattr(autopilot, "preflight", lambda it: [])
    monkeypatch.setattr(autopilot, "_schedule_youtube", lambda s, it: "scheduled")
    return {"sent": sent, "tmp": tmp_path, "out": out}


def _it():
    return weekly.load_plan("2099-01-05")["items"][0]


def test_old_message_cannot_approve_new_version(env):
    old = autopilot.token("2099-01-05", "a", "111.0")
    autopilot.update_item("2099-01-05", "a", made_at=222.0)          # a remade version exists now
    assert "older version" in autopilot.decide(old, "approve")
    assert _it()["status"] == "made"
    new = autopilot.token("2099-01-05", "a", "222.0")
    assert "Approved" in autopilot.decide(new, "approve")


def test_no_approval_while_remaking(env):
    tok = autopilot.token("2099-01-05", "a", "111.0")
    autopilot.update_item("2099-01-05", "a", status="redo")
    assert "being made" in autopilot.decide(tok, "approve")


def test_change_after_approval_removes_scheduled_youtube(env, monkeypatch):
    deleted = []
    monkeypatch.setattr(publish, "youtube_delete", lambda ch, vid, session=None: deleted.append(vid) or True)
    autopilot.update_item("2099-01-05", "a", status="approved", youtube_id="YT1")
    tok = autopilot.token("2099-01-05", "a", "111.0")
    autopilot.decide(tok, "change", "new hook")
    assert deleted == ["YT1"] and _it()["youtube_id"] is None and _it()["status"] == "redo"


def test_clip_metadata_comes_from_clips_json(tmp_path):
    out = tmp_path / "c"
    out.mkdir()
    (out / "clips.json").write_text(json.dumps([{"file": "clip_02.mp4", "title": "Big moment",
                                                 "caption": "Wow. Source: X #podcast", "hook_options": ["H1"],
                                                 "permission": {"basis": "campaign"}, "campaign": "Brand A"}]))
    m = publish.item_meta({"out_dir": str(out), "file": "clip_02.mp4", "channel_name": "Hot Take HQ"})
    assert m["title"] == "Big moment" and "Source: X" in m["description"] and m["campaign"] == "Brand A"
    assert m["clip"] and m["permission"]["basis"] == "campaign"


def test_clip_without_permission_is_never_uploaded(tmp_path):
    out = tmp_path / "c"
    out.mkdir()
    (out / "clip_01.mp4").write_bytes(b"x")
    (out / "clips.json").write_text(json.dumps([{"file": "clip_01.mp4", "title": "T", "caption": "c"}]))
    acts = publish.upload_item({"id": "i", "channel": "hot_take_hq", "channel_name": "Hot Take HQ",
                                "out_dir": str(out), "file": "clip_01.mp4", "publish_at": ""}, dry_run=True)
    assert len(acts) == 1 and "permission" in acts[0].result["error"]


def test_facebook_duration_guard(tmp_path, monkeypatch):
    out = tmp_path / "s"
    out.mkdir()
    for f in ("video.mp4", "reel.mp4"):
        (out / f).write_bytes(b"x")
    (out / "upload.json").write_text(json.dumps({"title": "T"}))
    monkeypatch.setattr(publish, "_duration", lambda v: 120.0)
    acts = publish.upload_item({"id": "i", "channel": "clutch_tales", "channel_name": "C", "out_dir": str(out),
                                "file": "video.mp4", "publish_at": ""}, dry_run=True)
    fb = [a for a in acts if a.platform == "facebook"][0]
    assert "3-90" in fb.what


def test_cleanup_keeps_shared_clip_folder_while_any_item_waits(tmp_path, monkeypatch):
    weeks = tmp_path / "weeks" / "2099-01-05"
    weeks.mkdir(parents=True)
    out = tmp_path / "output" / "hot_take_hq" / "20990101_clips"
    out.mkdir(parents=True)
    (out / "clip_01.mp4").write_bytes(b"x")
    old = time.time() - 10 * 86400
    plan = {"start": "2099-01-05", "items": [
        {"id": "p", "status": "posted", "posted_at": old, "out_dir": str(out), "file": "clip_01.mp4"},
        {"id": "q", "status": "made", "out_dir": str(out), "file": "clip_02.mp4"}]}
    (weeks / "plan.json").write_text(json.dumps(plan))
    monkeypatch.setattr(cleanup, "OUT", tmp_path / "output")
    monkeypatch.setattr(cleanup, "WEEKS", tmp_path / "weeks")
    paths = {p for p, _ in cleanup.plan()}
    assert out / "clip_01.mp4" not in paths and out not in paths


def test_title_only_change_needs_no_remake(env, monkeypatch):
    monkeypatch.setattr(autopilot, "ask", lambda *a, **k: None)
    (env["out"] / "upload.json").write_text(json.dumps({"title": "Old", "title_options": ["A one", "B two"]}))
    monkeypatch.setattr(weekly, "_item_media", lambda it: {"titles": ["A one", "B two"]})
    tok = autopilot.token("2099-01-05", "a", "111.0")
    reply = autopilot.decide(tok, "change", "title 2")
    assert "B two" in reply and _it()["status"] == "made"
    assert json.loads((env["out"] / "upload.json").read_text())["title"] == "B two"
