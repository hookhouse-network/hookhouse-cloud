"""22 Nov: Stream Clips GTA's story Shorts can never pass the content gate (every GTA topic, title and the #GTA6
hashtag name a protected franchise; policy checks never relax). At 05:34 the PC dropped two GTA topics, found no other
and failed the 06:30 slot. A channel with `story_pause` makes no story Shorts: its slots wait for campaign footage
(clips still go first), and make_item refuses them on any path."""
from datetime import timedelta

import pytest

from engine import autopilot, weekly
from engine.cloud import runner
from engine.config import channel


def _it(i, ch, hours, status="planned", kind="short"):
    return ("2026-11-23", {"id": i, "channel": ch, "kind": kind, "status": status,
                           "publish_at": (autopilot._now() + timedelta(hours=hours)).isoformat()})


def test_the_gta_channel_story_shorts_are_paused_by_config():
    assert weekly.story_paused(channel("stream_clips"))                  # the live config pauses them
    assert weekly.story_paused({"type": "story"}) is None
    assert weekly.story_paused({"type": "story", "story_pause": "  "}) is None
    assert all(weekly.story_paused(channel(c)) is None for c in ("brain_snack", "cosmos_unboxed", "clutch_tales"))


def test_paused_story_slots_wait_for_campaign_footage(monkeypatch):
    its = [_it("s1", "stream_clips", 2, "redo"), _it("s2", "stream_clips", 5), _it("c1", "cosmos_unboxed", 8)]
    monkeypatch.setattr(autopilot, "items", lambda *a, **k: its)
    monkeypatch.setattr(autopilot, "_connected", lambda cid: {"youtube": True, "meta": False})
    from engine import storyboard
    monkeypatch.setattr(storyboard, "images_blocked", lambda: False)
    monkeypatch.setattr(runner, "_clip_slot", lambda it: False)
    assert [it["id"] for _, it in runner._due_to_make(None, set())] == ["c1"]       # no footage: nothing to make
    monkeypatch.setattr(runner, "_clip_slot", lambda it: it["channel"] == "stream_clips")
    assert [it["id"] for _, it in runner._due_to_make(None, set())] == ["s1", "s2", "c1"]   # footage: clips first


def test_make_item_never_writes_a_paused_story_short(monkeypatch):
    monkeypatch.setattr(weekly, "clip_slot", lambda ch, it: False)
    item = {"id": "s1", "channel": "stream_clips", "kind": "short", "status": "redo", "topic": None}
    with pytest.raises(RuntimeError, match="paused"):
        weekly.make_item({"items": [item]}, item, brain=object(), log=lambda *a: None)
