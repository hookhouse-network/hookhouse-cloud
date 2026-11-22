"""23 Nov 01:15: the first cloud run under the owner's "B" (the potential rubric only coaches until 28 Nov) posted the
owner's Itihaas approval, but the 22 Nov Brain Snack and Wild Instinct Shorts stayed silent: every platform had blocked
them for the rubric ALONE at 22:34 (before B), so they were settled at their redo limit and never tried again. Each
such version now gets one fresh gate check at its channel's next free slot; anything else that held it still holds it."""
import json
from datetime import datetime

import pytest

from engine import autopilot, content_gate, publish, publish_queue
from engine.core import ledger

ITEM = "1122_0500_wild_instinct_short"
SLOT = "2026-11-23T08:00:00+05:30"
RUBRIC = ("potential: below 8/10 on hook 5, retention 6, emotion 6, packaging 6. Fix: Start with a punchy, visual hook; "
          "Trim filler words.")
AI_MADE = "potential: looks/sounds obviously AI-made (human_feel 5, needs 6). Fix: use real footage"


@pytest.fixture()
def world(monkeypatch, tmp_path):
    clock = [1000.0]
    led = ledger.Ledger(tmp_path / "l.db", clock=lambda: clock[0], rng=lambda: 1.0)
    monkeypatch.setattr(ledger, "default", lambda: led)
    it = {"id": ITEM, "channel": "wild_instinct", "status": "approved", "made_at": 100.0, "out_dir": str(tmp_path),
          "publish_at": "2026-11-22T22:30:00+05:30"}
    state = {"posted": {ITEM: 900.0}}
    updates = []

    def update_item(start, iid, **fields):
        updates.append(fields)
        it.update(fields)
        return it

    def update_state(fn):
        fn(state)
        return state
    monkeypatch.setattr(autopilot, "items", lambda *a: [("2026-11-16", it)])
    monkeypatch.setattr(autopilot, "_load", lambda: state)
    monkeypatch.setattr(autopilot, "update_item", update_item)
    monkeypatch.setattr(autopilot, "_update_state", update_state)
    monkeypatch.setattr(autopilot, "next_free_slot", lambda start, x: SLOT)
    monkeypatch.setattr(content_gate, "temporary_bar", lambda today=None: {"until": "2026-11-28", "potential": "coach"})
    monkeypatch.setattr(publish, "item_meta", lambda x: {"title": "How a falcon breathes at 300 km/h"})
    log = tmp_path / "publish_log.jsonl"
    monkeypatch.setattr(publish, "LOG", log)
    for p in ("youtube", "facebook", "instagram", "threads"):
        led.enqueue(publish_queue.KIND, publish_queue.key(ITEM, p, "100"), {"item": ITEM, "platform": p})
    jobs = {j["payload"]["platform"]: j for j in led.claim("cloud", kinds=[publish_queue.KIND], limit=10)}
    for p in ("youtube", "facebook"):
        led.fail(jobs[p]["id"], "cloud", "🛑 blocked: " + RUBRIC, kind="permanent")
    led.fail(jobs["instagram"]["id"], "cloud", "temporarily restricted", kind="permanent")    # not the gate
    led.complete(jobs["threads"]["id"], "cloud", {"skipped": "not set up"})

    def blocked(problems, platforms=("youtube", "facebook"), at=950.0):
        log.write_text("".join(json.dumps({"item_id": ITEM, "platform": p, "what": "BLOCKED by the content gate",
                                           "at": at, "result": {"error": "🛑 blocked: " + "; ".join(problems)},
                                           "details": {"problems": problems}}) + "\n" for p in platforms),
                       encoding="utf-8")
    return {"it": it, "state": state, "updates": updates, "led": led, "clock": clock, "blocked": blocked}


def _states(led):
    return {j["key"].rsplit(":", 1)[-1]: (j["state"], j["run_after"], j["attempts"])
            for j in led.jobs(kind=publish_queue.KIND)}


def test_a_rubric_only_hold_gets_one_fresh_check_at_the_next_slot(world):
    world["blocked"]([RUBRIC])
    assert autopilot._recheck_coached(log=lambda *_: None) == 1
    at = datetime.fromisoformat(SLOT).timestamp()
    st = _states(world["led"])
    assert st["youtube"] == ("queued", at, 0) and st["facebook"] == ("queued", at, 0)
    assert st["instagram"][0] == "dead" and st["threads"][0] == "done"        # other deaths and skips untouched
    assert world["updates"] == [{"publish_at": SLOT, "coach_recheck": "100"}]
    assert ITEM not in world["state"]["posted"]                                 # no longer settled
    assert [e["item"] for e in world["led"].events("potential.recheck")] == [ITEM]
    # the queue owns this version again: nothing is due before the slot, both platforms are due at it
    assert world["led"].claim("cloud", kinds=[publish_queue.KIND], limit=10) == []
    world["clock"][0] = at + 1
    assert sorted(j["payload"]["platform"] for j in world["led"].claim("cloud", kinds=[publish_queue.KIND],
                                                                         limit=10)) == ["facebook", "youtube"]


def test_only_once_per_version(world):
    world["blocked"]([RUBRIC])
    assert autopilot._recheck_coached(log=lambda *_: None) == 1
    world["clock"][0] = datetime.fromisoformat(SLOT).timestamp() + 1            # at the slot the gate says no again
    for j in world["led"].claim("cloud", kinds=[publish_queue.KIND], limit=10):
        world["led"].fail(j["id"], "cloud", "🛑 blocked: " + AI_MADE, kind="permanent")
    world["state"]["posted"][ITEM] = world["clock"][0]                          # settled again
    assert autopilot._recheck_coached(log=lambda *_: None) == 0
    assert {s for s, _r, _a in _states(world["led"]).values()} == {"dead", "done"}


@pytest.mark.parametrize("problems", [[RUBRIC, AI_MADE], [AI_MADE],
                                      ["potential: speech starts at 2.0s (the hook must land within 0.6s)"],
                                      ["quality: score 79/100 (needs 85.0): 6/17 pictures barely match"]])
def test_anything_besides_the_rubric_keeps_it_held(world, problems):
    world["blocked"](problems)
    assert autopilot._recheck_coached(log=lambda *_: None) == 0
    assert _states(world["led"])["youtube"][0] == "dead" and ITEM in world["state"]["posted"]


def test_one_platform_held_for_more_keeps_the_whole_video_held(world):
    world["blocked"]([RUBRIC], platforms=("youtube",))
    with open(publish.LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps({"item_id": ITEM, "platform": "facebook", "what": "BLOCKED by the content gate", "at": 960.0,
                            "result": {"error": "🛑 blocked: " + AI_MADE}, "details": {"problems": [AI_MADE]}}) + "\n")
    assert autopilot._recheck_coached(log=lambda *_: None) == 0


def test_campaign_clips_the_end_of_b_and_older_blocks_change_nothing(world, monkeypatch):
    world["blocked"]([RUBRIC], at=50.0)                          # a block of an OLDER version of the video
    assert autopilot._recheck_coached(log=lambda *_: None) == 0
    world["blocked"]([RUBRIC])
    monkeypatch.setattr(publish, "item_meta", lambda x: {"clip": True, "campaign": "c1"})
    assert autopilot._recheck_coached(log=lambda *_: None) == 0
    monkeypatch.setattr(publish, "item_meta", lambda x: {})
    monkeypatch.setattr(content_gate, "temporary_bar", lambda today=None: {})   # after 28 Nov: the rubric blocks
    assert autopilot._recheck_coached(log=lambda *_: None) == 0
    assert _states(world["led"])["youtube"][0] == "dead"


def test_posted_or_unsettled_videos_are_not_touched(world):
    world["blocked"]([RUBRIC])
    world["it"]["youtube_id"] = "abc"
    assert autopilot._recheck_coached(log=lambda *_: None) == 0
    world["it"].pop("youtube_id")
    world["state"]["posted"].pop(ITEM)
    assert autopilot._recheck_coached(log=lambda *_: None) == 0


def test_retry_dead_waits_for_the_given_time(tmp_path):
    led = ledger.Ledger(tmp_path / "l.db", clock=lambda: 10.0)
    led.enqueue("post", "k")
    (j,) = led.claim("w", kinds=["post"])
    led.fail(j["id"], "w", "no", kind="permanent")
    assert led.retry_dead(j["id"], run_after=500.0) and led.jobs()[0]["run_after"] == 500.0
    assert led.claim("w", kinds=["post"]) == []                   # not before the given time
    assert led.retry_dead(j["id"]) is False                       # only dead jobs come back
