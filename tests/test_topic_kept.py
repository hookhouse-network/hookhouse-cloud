"""24 Nov: Clutch Tales' slot had a news topic from the morning pick ("Victor Wembanyama goes off for 50 points and
19 boards"); the make-time trend refresh replaced it with "Tom Jackson's Legendary NFL Journey", and on the PC (a
read-only plan copy) every retry re-picked again: Agüero's 2012 goal, then the 2017 Super Bowl. A topic the cloud
already chose from current news or trends is kept at make time."""
from datetime import date, timedelta

from engine import story, weekly

TODAY = date.today().isoformat()


def test_what_counts_as_already_fresh():
    assert weekly.cloud_freshened({"news": "Wembanyama goes off for 50 points"})
    for days in (0, 1, 2):
        assert weekly.cloud_freshened({"fresh_day": (date.today() - timedelta(days=days)).isoformat()}), days
    assert not weekly.cloud_freshened({"fresh_day": (date.today() - timedelta(days=3)).isoformat()})
    assert not weekly.cloud_freshened({"fresh_day": "soon"}) and not weekly.cloud_freshened({})


def _make(monkeypatch, item):
    called, logs, made = [], [], {}
    monkeypatch.setattr(weekly, "_refresh_topic", lambda *a, **k: called.append(1))
    monkeypatch.setattr("engine.config.channel", lambda cid: {"id": cid, "name": "Clutch Tales", "type": "story"})
    monkeypatch.setattr(weekly, "clip_slot", lambda ch, it: False)

    def fake_make(brain, ch, topic, fmt, memory, log, **k):
        made["topic"] = topic
        raise StopIteration                                     # stop before rendering
    monkeypatch.setattr(story, "make", fake_make)
    try:
        weekly.make_item({"items": [item]}, item, brain=object(), log=logs.append)
    except StopIteration:
        pass
    return called, logs, made


def test_a_news_topic_is_kept_at_make_time(monkeypatch):
    item = {"id": "i1", "channel": "clutch_tales", "kind": "short", "status": "planned",
            "topic": "Victor Wembanyama's 50-point night", "news": "Victor Wembanyama goes off for 50 points"}
    called, logs, made = _make(monkeypatch, item)
    assert not called and made["topic"].startswith("Victor Wembanyama's 50-point night")
    assert any("kept (news: Victor Wembanyama" in m for m in logs)


def test_a_topic_checked_against_todays_trends_is_kept(monkeypatch):
    item = {"id": "i1", "channel": "clutch_tales", "kind": "short", "status": "planned", "topic": "The 28-3 comeback",
            "fresh_day": TODAY}
    called, logs, made = _make(monkeypatch, item)
    assert not called and any(f"checked against the trends on {TODAY}" in m for m in logs)


def test_an_old_plan_topic_is_still_refreshed(monkeypatch):
    item = {"id": "i1", "channel": "clutch_tales", "kind": "short", "status": "planned", "topic": "Tom Jackson"}
    called, _logs, _made = _make(monkeypatch, item)
    assert called == [1]
