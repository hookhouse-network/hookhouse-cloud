"""Tests for the week-ahead batch and the approval page (fast, no internet or models)."""
import json
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from http.server import ThreadingHTTPServer

import pytest

from engine import weekly


@pytest.fixture()
def tmp_weeks(tmp_path, monkeypatch):
    monkeypatch.setattr(weekly, "WEEKS_DIR", tmp_path / "weeks")
    monkeypatch.setattr(weekly, "OUTPUT_DIR", tmp_path / "output")
    (tmp_path / "output").mkdir()
    return tmp_path


def test_next_monday_is_always_in_the_future():
    assert weekly.next_monday(date(2026, 11, 10)) == date(2026, 11, 16)   # Tuesday -> next Monday
    assert weekly.next_monday(date(2026, 11, 16)) == date(2026, 11, 23)   # Monday -> the Monday after


def test_slots_follow_each_channel_schedule():
    story = {"id": "s", "market": "US", "type": "story", "schedule": {"shorts_per_day": 1, "long_per_week": 1}}
    slots = weekly.slots_for(story, date(2026, 11, 16))
    assert len(slots) == 8 and sum(k == "long" for _, k in slots) == 1
    assert slots == sorted(slots)
    clips = {"id": "c", "market": "US", "type": "clips", "schedule": {"shorts_per_day": 2}}
    assert {k for _, k in weekly.slots_for(clips, date(2026, 11, 16))} == {"clip"}
    assert len(weekly.slots_for(clips, date(2026, 11, 16))) == 14


def test_plan_without_brain_marks_unbuilt_channels(tmp_weeks, monkeypatch):
    plan = weekly.plan_week(None, date(2026, 11, 16), only=["brain_snack", "bloop_and_friends"], log=lambda m: None)
    statuses = {it["channel"]: it["status"] for it in plan["items"]}
    assert statuses["brain_snack"] == "planned" and statuses["bloop_and_friends"] == "planned"   # kids maker exists
    monkeypatch.setattr(weekly, "BUILDABLE", {"story", "brainrot", "clips"})
    plan2 = weekly.plan_week(None, date(2026, 11, 23), only=["bloop_and_friends"], log=lambda m: None)
    assert {it["status"] for it in plan2["items"]} == {"not_built"}
    assert len({it["id"] for it in plan["items"]}) == len(plan["items"])        # ids are unique
    assert weekly.load_plan("2026-11-16")["items"] == plan["items"]


def test_only_finished_videos_can_be_decided(tmp_weeks):
    plan = weekly.plan_week(None, date(2026, 11, 16), only=["brain_snack"], log=lambda m: None)
    first = plan["items"][0]["id"]
    with pytest.raises(ValueError):
        weekly.decide("2026-11-16", first, "approve")                           # still only planned
    plan["items"][0]["status"] = "made"
    weekly.save_plan(plan)
    assert weekly.decide("2026-11-16", first, "approve")["status"] == "approved"
    assert [it["id"] for it in weekly.approved_items("2026-11-16")] == [first]
    assert weekly.decide("2026-11-16", first, "redo", "slower voice")["note"] == "slower voice"
    with pytest.raises(ValueError):
        weekly.decide("2026-11-16", first, "publish")


def test_files_outside_output_are_never_served(tmp_weeks):
    (tmp_weeks / "output" / "a.mp4").write_bytes(b"x")
    (tmp_weeks / "secret.env").write_text("KEY=1")
    assert weekly._safe_output_path("a.mp4") is not None
    assert weekly._safe_output_path("../secret.env") is None
    assert weekly._safe_output_path("..%2Fsecret.env") is None


def test_approval_page_needs_the_key_and_records_decisions(tmp_weeks):
    plan = weekly.plan_week(None, date(2026, 11, 16), only=["brain_snack"], log=lambda m: None)
    plan["items"][0]["status"] = "made"
    weekly.save_plan(plan)
    server = ThreadingHTTPServer(("127.0.0.1", 0), weekly.make_handler("2026-11-16", "key123"))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        with pytest.raises(urllib.error.HTTPError) as err:
            urllib.request.urlopen(base + "/")
        assert err.value.code == 403
        page = urllib.request.urlopen(base + "/?t=key123").read().decode("utf-8")
        assert "approve each video" in page and "Brain Snack" in page
        data = urllib.parse.urlencode({"id": plan["items"][0]["id"], "action": "reject", "note": "boring"}).encode()
        urllib.request.urlopen(urllib.request.Request(base + "/decide?t=key123", data=data))
        assert weekly.load_plan("2026-11-16")["items"][0]["status"] == "rejected"
        data = urllib.parse.urlencode({"id": plan["items"][0]["id"], "action": "redo", "note": ""}).encode()
        with pytest.raises(urllib.error.HTTPError) as err:                     # Change needs a note
            urllib.request.urlopen(urllib.request.Request(base + "/decide?t=key123", data=data))
        assert err.value.code == 400
    finally:
        server.shutdown()
        server.server_close()


def test_never_topics_are_dropped_and_replaced(tmp_path, monkeypatch):
    monkeypatch.setattr(weekly, "WEEKS_DIR", tmp_path)
    monkeypatch.setattr("engine.trends.trend_hints", lambda brain, log=print: {})     # offline
    calls = []

    class R:
        provider = "fake"

    class FakeBrain:
        def ask_json(self, task, prompt, **kw):
            calls.append(prompt)
            if len(calls) == 1:
                return ({"topics": [{"topic": "Best betting apps for IPL"}, {"topic": "How Nvidia makes money"}]}, R())
            return ({"topics": [{"topic": f"Replacement topic {k}"} for k in range(12)]}, R())

    plan = weekly.plan_week(FakeBrain(), date(2026, 12, 28), only=["money_cheat_codes"], log=lambda m: None)
    topics = [i["topic"] for i in plan["items"]]
    assert all(topics) and "Best betting apps for IPL" not in topics
    assert "Never make a video about" in calls[0] and "Best betting apps" in calls[1]
