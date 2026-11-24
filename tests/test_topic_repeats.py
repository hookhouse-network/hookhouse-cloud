"""24 Nov: two Itihaas slots (24 Nov 12:30, 25 Nov 08:00) both switched to the day's trend "Jhalkari Bai - the fearless
Koli warrior of 1857": fresh_topics asks each slot alone, and the make step keeps a cloud-freshened topic, so the second
video would be made and held as a title repeat."""
from datetime import datetime, timedelta, timezone

import pytest

from engine import autopilot, config, fresh_topics, story, weekly

A = "Jhalkari Bai – The fearless Koli warrior of 1857"
B = "Jhalkari Bai: The fearless Koli warrior of 1857"


def test_what_counts_as_a_repeat():
    assert weekly.topic_repeats(B, ["The Dancing Plague of 1518", A]) == A
    assert weekly.topic_repeats("Jhalkari Bai's last stand at Jhansi in 1858", [A]) is None   # another story of hers
    assert weekly.topic_repeats("Rani Lakshmibai: The fearless queen of Jhansi in 1857", [A]) is None
    assert weekly.topic_repeats("The Dancing Plague of 1518", ["The Great Molasses Flood of 1919"]) is None
    assert weekly.topic_repeats("old 1", ["old 2"]) is None                        # too short to judge
    hi = ["सुनील गावस्कर और कपिल देव की लड़ाई", "ऋषभ पंत ने रचा इतिहास"]
    assert weekly.topic_repeats(hi[0], [hi[1]]) is None                           # Hindi topics are not all ''
    assert weekly.topic_repeats("सुनील गावस्कर और कपिल देव की लड़ाई की कहानी", [hi[0]]) == hi[0]


NOW = datetime(2026, 11, 24, 10, 0, tzinfo=timezone(timedelta(hours=5, minutes=30)))


class Brain:
    def __init__(self, answers):
        self.answers, self.prompts = list(answers), []

    def ask_json(self, task, prompt, temperature=0.4):
        self.prompts.append(prompt)
        return dict(self.answers.pop(0)), None


@pytest.fixture
def two_slots(monkeypatch):
    items = [{"id": "s1", "channel": "itihaas_ke_raaz", "kind": "short", "status": "planned", "topic": "Prithviraj Chauhan's last battle",
              "_when": NOW + timedelta(hours=2)},
             {"id": "s2", "channel": "itihaas_ke_raaz", "kind": "short", "status": "planned", "topic": "Ganesha's rarest temple form",
              "_when": NOW + timedelta(hours=22)}]
    updates = []
    monkeypatch.setattr(autopilot, "items", lambda back=0, ahead=3: [("2026-11-23", it) for it in items])
    monkeypatch.setattr(autopilot, "_when", lambda it: it["_when"])
    monkeypatch.setattr(autopilot, "update_item", lambda s, iid, **f: updates.append((iid, f)) or {})
    monkeypatch.setattr(config, "channel", lambda cid: {"id": cid, "name": "Itihaas Ke Raaz", "niche": "history"})
    return items, updates


def test_a_second_slot_never_switches_to_the_same_trend(two_slots):
    items, updates = two_slots
    sw = {"decision": "switch", "angle": "a", "why": "Jhalkari Bai is trending 23x", "feeling": "awe"}
    b = Brain([dict(sw, topic=A), dict(sw, topic=B)])
    assert fresh_topics.freshen_due(b, hints={"itihaas_ke_raaz": ["Jhalkari Bai (23x)"]}, now=NOW) == 1
    assert updates[0] == ("s1", updates[0][1]) and updates[0][1]["topic"] == A
    assert updates[1] == ("s2", {"fresh_day": "2026-11-24"})                    # kept: the switch repeated s1's
    assert A in b.prompts[1]                                                     # and s2's writer saw s1's new topic


def test_a_planned_topic_that_repeats_another_slot_is_told_to_switch(two_slots):
    items, updates = two_slots
    items[0]["topic"], items[1]["topic"] = A, B
    b = Brain([{"decision": "keep"}, {"decision": "keep"}])
    fresh_topics.freshen_due(b, hints={"itihaas_ke_raaz": ["x"]}, now=NOW)
    assert "repeats another video of this channel" in b.prompts[0]


def test_the_make_step_replaces_a_topic_another_slot_already_made(monkeypatch):
    called, logs = [], []
    monkeypatch.setattr(weekly, "_refresh_topic", lambda *a, **k: called.append(k.get("offer_planned")))
    monkeypatch.setattr("engine.config.channel", lambda cid: {"id": cid, "name": "Itihaas Ke Raaz", "type": "story"})
    monkeypatch.setattr(weekly, "clip_slot", lambda ch, it: False)
    monkeypatch.setattr(story, "make", lambda *a, **k: (_ for _ in ()).throw(StopIteration))
    made = {"id": "1124_1230", "channel": "itihaas_ke_raaz", "status": "posted", "topic": A}
    item = {"id": "test_topic_repeat_no_ck", "channel": "itihaas_ke_raaz", "kind": "short", "status": "planned",
            "topic": B, "fresh_day": datetime.now().date().isoformat()}
    with pytest.raises(StopIteration):
        weekly.make_item({"items": [made, item]}, item, brain=object(), log=logs.append)
    assert called == [False] and any("another slot already made" in m for m in logs)
