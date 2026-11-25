"""Autopilot: ask -> approve -> post only approved; change notes; missed slots never post; cleanup keeps live videos."""
import json
from datetime import timedelta

import pytest

from engine import autopilot, cleanup, weekly


@pytest.fixture
def env(tmp_path, monkeypatch):
    weeks = tmp_path / "weeks"
    monkeypatch.setattr(weekly, "WEEKS_DIR", weeks)
    monkeypatch.setattr(autopilot, "STATE", tmp_path / "autopilot.json")
    sent = []
    from engine import telegram_bot as tb
    monkeypatch.setattr(tb, "notify", lambda t: sent.append(t) or True)
    monkeypatch.setattr(tb, "send", lambda t, **k: sent.append(t))
    out = tmp_path / "out" / "v1"
    out.mkdir(parents=True)
    (out / "video.mp4").write_bytes(b"x" * 100)
    (out / "upload.json").write_text(json.dumps({"title": "T", "fact_check": {"checked": True, "ok": True}}))
    now = autopilot._now()
    plan = {"start": "2099-01-05", "items": [
        {"id": "a", "channel": "unsolved_after_dark", "channel_name": "Unsolved After Dark", "kind": "short",
         "publish_at": (now + timedelta(hours=10)).isoformat(), "status": "made", "out_dir": str(out),
         "file": "video.mp4", "topic": "Lake"}]}
    (weeks / "2099-01-05").mkdir(parents=True)
    (weeks / "2099-01-05" / "plan.json").write_text(json.dumps(plan))
    monkeypatch.setattr(autopilot, "preflight", lambda it: [])
    return {"sent": sent, "out": out, "now": now}


def _item():
    return weekly.load_plan("2099-01-05")["items"][0]


def test_ask_then_approve_then_post(env, monkeypatch):
    asked = []
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")                 # phone paired
    monkeypatch.setattr(autopilot, "ask", lambda start, it, reminder=False: asked.append((it["id"], reminder)) or
                        autopilot._update_state(lambda s: s.setdefault("asked", {}).__setitem__(it["id"], 1)))
    autopilot._ask_due(print)
    assert asked == [("a", False)]
    autopilot._ask_due(print)                                  # asked only once
    assert len(asked) == 1
    posted = []
    import engine.publish as pub
    monkeypatch.setattr(pub, "upload_item", lambda it, **k: posted.append(it["id"]) or [])
    autopilot._post_due(print)
    assert posted == []                                        # not approved -> never posted
    tok = autopilot.token("2099-01-05", "a")
    monkeypatch.setattr(autopilot, "_schedule_youtube", lambda s, it: "scheduled")
    reply = autopilot.decide(tok, "approve")
    assert "Approved" in reply and _item()["status"] == "approved"
    autopilot.update_item("2099-01-05", "a", publish_at=(env["now"] - timedelta(minutes=1)).isoformat())
    autopilot._post_due(print)
    assert posted == ["a"]


def test_change_note_sets_redo(env):
    tok = autopilot.token("2099-01-05", "a")
    autopilot.decide(tok, "change", "make the hook scarier")
    it = _item()
    assert it["status"] == "redo" and it["note"] == "make the hook scarier"


def test_missed_slot_is_not_posted(env):
    autopilot.update_item("2099-01-05", "a", publish_at=(env["now"] - timedelta(hours=1)).isoformat())
    autopilot._missed(print)
    assert _item()["status"] == "missed"
    assert any("wasn't approved in time" in t for t in env["sent"])


def test_cleanup_keeps_waiting_videos(env, monkeypatch):
    out_root = env["out"].parent.parent
    monkeypatch.setattr(cleanup, "OUT", out_root)
    monkeypatch.setattr(cleanup, "WEEKS", weekly.WEEKS_DIR)
    (env["out"] / "work").mkdir()
    old = out_root / "out" / "old_failed"
    old.mkdir()
    import os
    import time
    os.utime(old, (time.time() - 3 * 86400, time.time() - 3 * 86400))
    paths = {p for p, _ in cleanup.plan()}
    assert env["out"] / "work" in paths                     # temporary files of a finished video go
    assert env["out"] not in paths and env["out"] / "video.mp4" not in paths   # the waiting video stays
    assert old in paths


def test_campaign_clip_is_asked_as_soon_as_made(env, monkeypatch):
    """20 Nov (owner: "send it to me for approval when done"): clips don't wait for the 20 h window."""
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    plan = weekly.load_plan("2099-01-05")
    far = (env["now"] + timedelta(hours=30)).isoformat()
    plan["items"] = [dict(plan["items"][0], id="story", publish_at=far),
                     dict(plan["items"][0], id="clip", publish_at=far, made_as="clip")]
    (weekly.WEEKS_DIR / "2099-01-05" / "plan.json").write_text(json.dumps(plan))
    asked = []
    monkeypatch.setattr(autopilot, "ask", lambda start, it, reminder=False: asked.append(it["id"]))
    autopilot._ask_due(print)
    assert asked == ["clip"]


def test_a_parked_campaign_clip_moves_up_and_is_asked(env, monkeypatch):
    """25 Nov: the first GTA clip passed every gate but its slot had been parked on 30 Nov (4.6 days out), outside the
    3-day ask window: never asked, approved or submitted. It now takes the channel's next spare slot and is asked."""
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    plan = weekly.load_plan("2099-01-05")
    parked = (env["now"] + timedelta(days=5)).isoformat()
    plan["items"] = [dict(plan["items"][0], id="story", publish_at=parked),
                     dict(plan["items"][0], id="clip", publish_at=parked, made_as="clip")]
    (weekly.WEEKS_DIR / "2099-01-05" / "plan.json").write_text(json.dumps(plan))
    soon = (env["now"] + timedelta(hours=6)).isoformat()
    monkeypatch.setattr(autopilot, "next_free_slot", lambda start, it: soon)
    asked = []
    monkeypatch.setattr(autopilot, "ask", lambda start, it, reminder=False: asked.append((it["id"], it["publish_at"])))
    autopilot._ask_due(print)
    assert asked == [("clip", soon)]
    got = {x["id"]: x["publish_at"] for x in weekly.load_plan("2099-01-05")["items"]}
    assert got == {"story": parked, "clip": soon}            # an ordinary video keeps its slot
