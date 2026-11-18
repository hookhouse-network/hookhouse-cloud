"""Fourth audit (12 Nov): long videos spread over the week, per-channel YouTube limit, Pacific quota day, a slot
without a topic gets one, long videos start early."""
import json
from collections import Counter
from datetime import date, timedelta

from engine import autopilot, publish, weekly
from engine.config import channels


def test_long_videos_are_spread_over_the_week():
    monday = date(2099, 1, 5)
    days = Counter()
    for ch in channels():
        for when, kind in weekly.slots_for(ch, monday):
            if kind == "long":
                days[when.date()] += 1
    assert days and max(days.values()) <= 2                  # never 10 long renders on one day


def test_respread_moves_only_unmade_long_videos(tmp_path, monkeypatch):
    monkeypatch.setattr(weekly, "WEEKS_DIR", tmp_path)
    tue = "2099-01-06T22:30:00+05:30"
    plan = {"start": "2099-01-05", "items": [
        {"id": "a", "channel": "clutch_tales", "kind": "long", "status": "planned", "publish_at": tue},
        {"id": "b", "channel": "ending_decoded", "kind": "long", "status": "made", "publish_at": tue}]}
    (tmp_path / "2099-01-05").mkdir()
    (tmp_path / "2099-01-05" / "plan.json").write_text(json.dumps(plan))
    weekly.respread_long("2099-01-05", log=lambda m: None)
    got = {it["id"]: it["publish_at"] for it in weekly.load_plan("2099-01-05")["items"]}
    assert got["b"] == tue and got["a"] != tue


def test_channel_upload_limit_blocks_only_that_channel(tmp_path, monkeypatch):
    monkeypatch.setattr(publish, "QUOTA_FILE", tmp_path / "q.json")
    monkeypatch.setattr(publish, "LOG", tmp_path / "log.jsonl")
    monkeypatch.setattr(publish, "yt_access_token", lambda c, s=None: "tok")
    v = tmp_path / "v.mp4"
    v.write_bytes(b"x")

    class Resp:
        status_code = 403

        def json(self):
            return {"error": {"errors": [{"reason": "uploadLimitExceeded"}]}}

    class S:
        def post(self, *a, **k):
            import requests
            raise requests.HTTPError(response=Resp())
    a = publish.youtube_upload("clutch_tales", v, {"title": "T"}, None, session=S(), dry_run=False)
    assert "verification" in a.result["error"]
    assert publish.quota_ok(100)                                   # other channels still upload
    b = publish.youtube_upload("clutch_tales", v, {"title": "T"}, None, session=S(), dry_run=False)
    assert "tries again tomorrow" in b.result["error"]


def test_quota_day_follows_pacific_time(tmp_path, monkeypatch):
    monkeypatch.setattr(publish, "QUOTA_FILE", tmp_path / "q.json")
    from datetime import datetime
    from zoneinfo import ZoneInfo
    assert publish._quota_state()["day"] == datetime.now(ZoneInfo("America/Los_Angeles")).strftime("%Y-%m-%d")


def test_slot_without_topic_gets_one(monkeypatch):
    picked = {}
    monkeypatch.setattr(weekly, "pick_topics", lambda brain, ch, n, **k: [{"topic": "The Lost Colony", "angle": "x"}])
    from engine import story

    def fake_make(brain, ch, topic, fmt, memory=None, log=print):
        picked["topic"] = topic
        raise RuntimeError("stop here")
    monkeypatch.setattr(story, "make", fake_make)
    item = {"id": "i", "channel": "unsolved_after_dark", "kind": "short", "topic": None}
    try:
        weekly.make_item({"items": []}, item, brain=object())
    except RuntimeError:
        pass
    assert item["topic"] == "The Lost Colony" and picked["topic"].startswith("The Lost Colony")


def test_long_videos_start_days_ahead(tmp_path, monkeypatch):
    monkeypatch.setattr(weekly, "WEEKS_DIR", tmp_path / "weeks")
    monkeypatch.setattr(autopilot, "STATE", tmp_path / "s.json")
    monkeypatch.setattr(autopilot, "LOCK", tmp_path / "render.lock")
    now = autopilot._now()
    plan = {"start": "2099-01-05", "items": [
        {"id": "L", "channel": "clutch_tales", "channel_name": "C", "kind": "long", "status": "planned",
         "publish_at": (now + timedelta(hours=70)).isoformat(), "topic": "t"}]}
    (tmp_path / "weeks" / "2099-01-05").mkdir(parents=True)
    (tmp_path / "weeks" / "2099-01-05" / "plan.json").write_text(json.dumps(plan))
    made = []
    monkeypatch.setattr(weekly, "make_item", lambda plan, item, brain, memory=None, log=print: made.append(item["id"]))
    monkeypatch.setattr(autopilot, "preview_file", lambda it: None)
    import collections                                          # the cloud test machine has little free disk
    import shutil
    monkeypatch.setattr(shutil, "disk_usage", lambda p: collections.namedtuple("D", "total used free")(
        500e9, 100e9, 400e9))
    autopilot._make_due(lambda: (None, None), lambda m: None)
    assert made == ["L"]
