"""Owner 23 Nov: "you are taking too old trending topics". Trends fed the weekly plan once, at the start of the week;
now every planned story slot made in the next 36 h is offered that day's on-brand trends once (keep or switch)."""
from datetime import datetime, timedelta, timezone

import pytest

from engine import autopilot, config, fresh_topics

NOW = datetime(2026, 11, 23, 10, 0, tzinfo=timezone(timedelta(hours=5, minutes=30)))


def _item(i, hours, status="planned", kind="short", **kw):
    return dict({"id": f"it{i}", "channel": "cosmos_unboxed", "kind": kind, "status": status, "topic": f"old {i}",
                 "angle": "a", "_when": NOW + timedelta(hours=hours)}, **kw)


@pytest.fixture
def plan(monkeypatch):
    items = [_item(1, 20), _item(2, 60), _item(3, 10, status="made"), _item(4, 8, kind="clip"),
             _item(5, 12, fresh_day="2026-11-23")]
    updates = []
    monkeypatch.setattr(autopilot, "items", lambda back=0, ahead=3: [("2026-11-23", it) for it in items])
    monkeypatch.setattr(autopilot, "_now", lambda: NOW)
    monkeypatch.setattr(autopilot, "_when", lambda it: it["_when"])
    monkeypatch.setattr(autopilot, "update_item", lambda s, iid, **f: updates.append((iid, f)) or {})
    monkeypatch.setattr(config, "channel", lambda cid: {"id": cid, "name": "Cosmos Unboxed", "niche": "space"})
    return items, updates


class Brain:
    def __init__(self, decision):
        self.decision, self.prompts = decision, []

    def ask_json(self, task, prompt, temperature=0.4):
        self.prompts.append(prompt)
        return {"decision": self.decision, "topic": "Artemis II crew named today", "angle": "a", "why": "today"}, None


def test_a_due_slot_switches_to_todays_trend_and_keeps_the_old_topic(plan):
    items, updates = plan
    b = Brain("switch")
    n = fresh_topics.freshen_due(b, hints={"cosmos_unboxed": ["Trending now: Artemis II crew"]}, now=NOW)
    assert n == 1 and len(b.prompts) == 1 and "old 1" in b.prompts[0] and "Artemis II crew" in b.prompts[0]
    iid, f = updates[0]
    assert iid == "it1" and f["topic"] == "Artemis II crew named today" and f["planned_topic"] == "old 1"
    assert f["fresh_day"] == "2026-11-23"


def test_keep_marks_the_slot_so_it_is_asked_once_a_day(plan):
    items, updates = plan
    assert fresh_topics.freshen_due(Brain("keep"), hints={"cosmos_unboxed": ["x"]}, now=NOW) == 0
    assert updates == [("it1", {"fresh_day": "2026-11-23"})]


def test_far_made_clip_and_already_asked_slots_are_left_alone(plan):
    items, updates = plan
    b = Brain("switch")
    fresh_topics.freshen_due(b, hints={"cosmos_unboxed": ["x"]}, now=NOW)
    assert [u[0] for u in updates] == ["it1"]                     # it2 too far, it3 made, it4 a clip, it5 asked today


def test_no_trend_for_the_channel_means_no_call(plan):
    b = Brain("switch")
    assert fresh_topics.freshen_due(b, hints={"other_channel": ["x"]}, now=NOW) == 0 and b.prompts == []


def test_the_switch_can_be_turned_off(plan, monkeypatch):
    monkeypatch.setattr(config, "settings", lambda: {"fresh_topics": {"enabled": False}})
    b = Brain("switch")
    assert fresh_topics.freshen_due(b, hints={"cosmos_unboxed": ["x"]}, now=NOW) == 0 and b.prompts == []
