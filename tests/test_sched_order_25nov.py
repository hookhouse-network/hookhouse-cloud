"""25 Nov shadow day (P2): 40 shadow picks, only 20 the same. The PC makes remakes first, then a connected channel's
campaign clip, then channels that can post; the queue went by deadline alone (it would hand out 1126_0500_stream_clips
while the PC made the 1121 remake). job_for now carries the PC's order."""
from datetime import datetime, timedelta, timezone

import pytest

from engine import autopilot
from engine.cloud import sched

NOW = datetime(2026, 11, 25, 10, 0, tzinfo=timezone.utc)


@pytest.fixture
def world(monkeypatch):
    monkeypatch.setattr(autopilot, "_when", lambda it: NOW + timedelta(hours=it["h"]))
    facts = {}
    monkeypatch.setattr(sched, "order_hints", lambda it: {"redo": it.get("status") == "redo",
                                                          "clip": facts.get(it["id"], {}).get("clip", False),
                                                          "live": facts.get(it["id"], {}).get("live", True)})
    return facts


def _it(iid, h, status="planned"):
    return {"id": iid, "h": h, "status": status, "kind": "short", "channel": "x"}


def test_the_queue_hands_out_what_the_pc_makes_first(world):
    now = NOW.timestamp()
    world.update({"1121_0100_stream_clips_short": {"clip": True}, "1126_0500_stream_clips_short": {"clip": True},
                  "1124_0500_unsolved_after_dark_short": {"live": False}})
    items = [_it("1124_0500_brain_snack_short", 2),                       # due soon, ordinary
             _it("1124_0500_unsolved_after_dark_short", 1),               # sooner, but its channel can't post
             _it("1126_0500_stream_clips_short", 30),                     # a campaign clip slot
             _it("1121_0500_clutch_tales_short", -90, "redo")]            # a remake
    jobs = [sched.job_for("s", it, now) for it in items]
    assert sched.queue_pick(jobs, now) == "1121_0500_clutch_tales_short"
    jobs = [j for j in jobs if "clutch" not in j["key"]]
    assert sched.queue_pick(jobs, now) == "1126_0500_stream_clips_short"
    jobs = [j for j in jobs if "stream" not in j["key"]]
    assert sched.queue_pick(jobs, now) == "1124_0500_brain_snack_short"   # a live channel before an earlier idle one


def test_a_slot_that_becomes_a_clip_gets_a_new_key(world):
    now = NOW.timestamp()
    plain = sched.job_for("s", _it("1126_0500_stream_clips_short", 30), now)
    world["1126_0500_stream_clips_short"] = {"clip": True}
    clip = sched.job_for("s", _it("1126_0500_stream_clips_short", 30), now)
    assert clip["key"] == plain["key"] + ":clip" and plain["cls"] == 2 and clip["cls"] == 1  # the sync swaps them


def test_order_hints_never_raise_on_an_unknown_channel():
    h = sched.order_hints({"id": "z", "status": "planned", "channel": "no_such_channel_zz"})
    assert h["redo"] is False and h["clip"] is False and isinstance(h["live"], bool)


def test_several_remakes_come_out_in_slot_order(world):
    """26 Nov shadow: three remakes due at once came out in enqueue order; the PC takes them by slot time."""
    now = NOW.timestamp()
    jobs = [sched.job_for("s", _it("1121_0630_stream_clips_short", -90, "redo"), now + 120),
            sched.job_for("s", _it("1121_0100_stream_clips_short", -95, "redo"), now + 60),
            sched.job_for("s", _it("1121_0500_stream_clips_short", -92, "redo"), now)]
    assert sched.queue_pick(jobs, now) == "1121_0100_stream_clips_short"


def test_a_same_slot_tie_goes_to_the_channel_with_fewer_recent_videos(monkeypatch):
    """26 Nov shadow: 1127_0500 Deep Blue vs Unsolved: the PC gave the turn to the channel with fewer recent videos."""
    monkeypatch.setattr(autopilot, "_when", lambda it: NOW + timedelta(hours=it["h"]))
    recent = {"busy": 3, "quiet": 0}
    monkeypatch.setattr(sched, "order_hints", lambda it: {"redo": False, "clip": False, "live": True,
                                                          "recent": recent[it["channel"]]})
    now = NOW.timestamp()
    a = dict(_it("1127_0500_busy_short", 20), channel="busy")
    b = dict(_it("1127_0500_quiet_short", 20), channel="quiet")
    assert sched.queue_pick([sched.job_for("s", a, now), sched.job_for("s", b, now)], now) == "1127_0500_quiet_short"
    c = dict(_it("1126_2300_busy_short", 5), channel="busy")              # a real deadline hours earlier still wins
    assert sched.queue_pick([sched.job_for("s", c, now), sched.job_for("s", b, now)], now) == "1126_2300_busy_short"


def test_recent_counts_are_cached(monkeypatch):
    calls = []
    monkeypatch.setattr(sched, "_RECENT", {"at": 0.0, "counts": {}})
    monkeypatch.setattr(autopilot, "items", lambda *a: calls.append(1) or [("s", {"channel": "x", "status": "posted"})])
    assert sched.recent_counts() == {"x": 1} and sched.recent_counts() == {"x": 1} and len(calls) == 1
