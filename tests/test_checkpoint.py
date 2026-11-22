"""22 Nov (P3 checkpointed stages; owner: "the content creation must become smoother"): a story Short that stopped
after its script was written started from nothing on the next try (the PC re-ran the topic refresh: Itihaas 12:30 was
"Tulsi Vivah" at 05:40 and "Raja Raghu" at 08:46), so pictures already drawn were never reused. The finished script +
shot plan + topic are kept until the video is made; a retry resumes them; a quality redo or owner change does not."""
import time

import pytest

from engine import weekly

ITEM = {"id": "1122_1230_itihaas_ke_raaz_short", "channel": "itihaas_ke_raaz", "kind": "short", "status": "planned",
        "topic": "Raja Raghu aur Rishi Kautsa", "angle": "14 crore", "feeling": "awe"}
SCRIPT = {"title": "14 करोड़ सोने के सिक्के", "beats": [{"narration": "a", "see": "x", "_prompt": "gold coins rain"}],
          "_fact_check": {"ok": True}}


def test_save_resume_and_clear():
    it = dict(ITEM)
    assert weekly.checkpoint(it) is None
    weekly.save_checkpoint(it, SCRIPT)
    ck = weekly.checkpoint(it)
    assert ck["script"]["beats"][0]["_prompt"] == "gold coins rain" and ck["item"]["topic"] == ITEM["topic"]
    weekly.clear_checkpoint(it)
    assert weekly.checkpoint(it) is None


def test_old_or_changed_checkpoints_are_not_resumed():
    it = dict(ITEM)
    weekly.save_checkpoint(it, SCRIPT)
    assert weekly.checkpoint(dict(it, note="make it shorter")) is None             # the owner asked for a change
    assert weekly.checkpoint(dict(it, gate_note="quality: 72/100")) is None         # the gate asked for a redo
    import json
    p = weekly._ck_path(it)
    rec = json.loads(p.read_text(encoding="utf-8"))
    rec["at"] = time.time() - 25 * 3600
    p.write_text(json.dumps(rec), encoding="utf-8")
    assert weekly.checkpoint(it) is None                                            # more than a day old


@pytest.fixture
def maker(monkeypatch):
    from engine import config, story
    monkeypatch.setattr(config, "channel", lambda cid: {"id": cid, "name": "Itihaas Ke Raaz", "type": "story"})
    monkeypatch.setattr(weekly, "clip_slot", lambda ch, it: False)
    monkeypatch.setattr(weekly, "story_paused", lambda ch: None)
    monkeypatch.setattr(weekly, "franchise_names", lambda it: [])
    refreshed = []
    monkeypatch.setattr(weekly, "_refresh_topic", lambda plan, it, ch, brain, memory=None, log=print:
                        refreshed.append(it["id"]) or it.update(topic="A fresher topic", refreshed=True))
    calls, fail = [], []

    def make(brain, ch, topic=None, fmt="short", script=None, memory=None, log=print, on_script=None, bank=None):
        calls.append({"topic": topic, "script": script, "bank": bank})
        if on_script:
            on_script(script or dict(SCRIPT, title=f"fresh about {topic.splitlines()[0]}"))
        if fail:
            raise RuntimeError(fail.pop(0))
        from pathlib import Path
        return Path("."), {}
    monkeypatch.setattr(story, "make", make)
    return calls, fail, refreshed


def test_a_stopped_try_is_resumed_with_its_topic_and_script(maker):
    calls, fail, refreshed = maker
    fail.append("NoPictures: 10/10 scenes had no picture")
    first = dict(ITEM)
    with pytest.raises(RuntimeError):
        weekly.make_item({"items": [first]}, first, brain=object(), log=lambda *a: None)
    assert refreshed == [ITEM["id"]] and calls[0]["script"] is None              # first try: topic refresh + fresh
    kept = weekly.checkpoint(ITEM)
    assert kept["item"]["topic"] == "A fresher topic"
    again = dict(ITEM)                                                            # the PC's fresh plan copy
    weekly.make_item({"items": [again]}, again, brain=object(), log=lambda *a: None)
    assert refreshed == [ITEM["id"]]                                              # no second refresh
    assert again["topic"] == "A fresher topic" and calls[1]["script"]["title"] == kept["script"]["title"]
    assert weekly.checkpoint(ITEM) is None                                        # made: cleared


def test_a_quality_redo_writes_a_fresh_script(maker):
    calls, fail, refreshed = maker
    fail.append("NoPictures")
    first = dict(ITEM)
    with pytest.raises(RuntimeError):
        weekly.make_item({"items": [first]}, first, brain=object(), log=lambda *a: None)
    redo = dict(ITEM, status="redo", gate_note="potential: below 8/10 on hook 5")
    weekly.make_item({"items": [redo]}, redo, brain=object(), log=lambda *a: None)
    assert calls[-1]["script"] is None and "hook 5" in calls[-1]["topic"]
