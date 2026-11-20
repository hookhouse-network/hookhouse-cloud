"""20 Nov (owner: "generate more and more ... as per the analytics data and its limitations"): volume per channel
follows its views, every channel keeps a trial slot, the total grows only when making keeps up."""
import json
import sqlite3
import time
from datetime import datetime, timedelta

from engine import allocator as al, analytics, weekly


def _conn(rows):
    c = sqlite3.connect(":memory:")
    c.executescript(analytics.SCHEMA)
    now = time.time()
    for ch, item, plat, views in rows:
        c.execute("INSERT INTO video_metrics(item_id,channel,platform,posted_at,hours_after,views) VALUES (?,?,?,?,?,?)",
                  (item, ch, plat, now - 86400, 48, views))
    return c


def test_views_are_summed_over_platforms_per_video_and_long_videos_ignored():
    c = _conn([("a", "i1", "youtube", 100), ("a", "i1", "instagram", 50), ("a", "i2", "youtube", 10)])
    c.execute("INSERT INTO video_metrics(item_id,channel,platform,format,posted_at,hours_after,views) "
              "VALUES ('L','a','youtube','long',?,48,99999)", (time.time() - 3600,))
    assert sorted(al.channel_views(c)["a"]) == [10, 150]


def test_shrinkage_keeps_two_lucky_videos_from_taking_over():
    views = {"lucky": [5000, 5000], "steady": [800] * 20, "other": [100] * 20}
    s = al.shrunk_scores(views, ["lucky", "steady", "other", "new"])
    assert s["lucky"]["score"] < 5000 and s["steady"]["score"] > 100
    assert s["new"]["n"] == 0 and s["new"]["score"] > 0                  # a new channel still gets a fair trial


def test_allocate_keeps_one_each_and_gives_the_rest_to_the_best_within_caps():
    chans = [{"id": c} for c in ("a", "b", "c")]
    scores = {"a": {"score": 900}, "b": {"score": 90}, "c": {"score": 10}}
    got = al.allocate(chans, scores, total=9, caps={"a": 4, "b": 6, "c": 6})
    assert sum(got.values()) == 9 and got["c"] >= 1 and got["a"] == 4 and got["b"] >= got["c"]


def test_total_grows_only_when_last_week_was_made():
    now = datetime(2099, 1, 10, 12, tzinfo=weekly._zone())
    made = [{"kind": "short", "publish_at": (now - timedelta(days=d)).isoformat(), "made_at": 1.0} for d in range(1, 6)]
    assert al.made_ratio(made, now) == (5, 5)
    half = made + [{"kind": "short", "publish_at": (now - timedelta(days=2)).isoformat(), "status": "missed"}] * 5
    assert al.made_ratio(half, now) == (5, 10)


def test_build_plans_to_the_upload_budget_and_the_planner_uses_it(tmp_path, monkeypatch):
    monkeypatch.setattr(al, "FILE", tmp_path / "allocation.json")
    monkeypatch.setenv("YOUTUBE_UPLOAD_QUOTA", "1000")                 # 10 uploads x 0.8 = 8 a day
    chans = [{"id": "a", "type": "story", "schedule": {"shorts_per_day": 1, "long_per_week": 7}},
             {"id": "b", "type": "story", "schedule": {"shorts_per_day": 1, "long_per_week": 0}},
             {"id": "k", "type": "kids", "schedule": {"shorts_per_week": 7}},
             {"id": "s", "type": "story", "clips_first": True, "schedule": {"shorts_per_day": 3}}]
    monkeypatch.setattr("engine.config.channels", lambda: chans)
    monkeypatch.setattr(weekly, "_times", lambda ch: [(9, 0), (13, 0), (19, 0)])
    now = datetime.now(weekly._zone())
    c = _conn([("a", f"i{i}", "youtube", 2000) for i in range(10)] + [("b", f"j{i}", "youtube", 50) for i in range(10)])
    d = al.build(log=lambda m: None, conn=c, now=now, plan_items=[])
    assert d["total"] == 3                                    # 8 - long 1 - kids 1 - clip-first 3 = 3
    assert d["channels"]["a"]["shorts_per_day"] == 2 and d["channels"]["b"]["shorts_per_day"] == 1
    assert set(d["channels"]) == {"a", "b"}                    # kids + clip-first keep their own numbers
    assert al.shorts_per_day(chans[0]) == 2 and al.shorts_per_day(chans[3]) == 3
    assert "Volume plan: 3 Shorts a day" in al.text(d)


def test_more_shorts_than_peak_times_get_spread_slots(tmp_path, monkeypatch):
    monkeypatch.setattr(al, "FILE", tmp_path / "allocation.json")
    (tmp_path / "allocation.json").write_text(json.dumps({"at": time.time(), "channels": {"a": {"shorts_per_day": 6}}}))
    monkeypatch.setattr(weekly, "_times", lambda ch: [(9, 0), (19, 0)])
    ch = {"id": "a", "name": "A", "type": "story", "schedule": {"shorts_per_day": 1, "long_per_week": 1}}
    slots = weekly.slots_for(ch, datetime.now(weekly._zone()).date(), days=1)
    shorts = sorted(w for w, k in slots if k == "short")
    longs = [w for w, k in slots if k == "long"]
    assert len(shorts) == 6 and len(longs) == 1 and longs[0] not in shorts
    mins = sorted(w.hour * 60 + w.minute for w, _ in slots)
    assert all(b - a >= 60 for a, b in zip(mins, mins[1:]))   # never a burst on one account
    assert weekly.spread_times([(9, 0)], 3)[0] == (9, 0)      # the peak times stay first


def test_stale_allocation_is_ignored(tmp_path, monkeypatch):
    monkeypatch.setattr(al, "FILE", tmp_path / "allocation.json")
    (tmp_path / "allocation.json").write_text(json.dumps({"at": time.time() - 30 * 86400,
                                                          "channels": {"a": {"shorts_per_day": 5}}}))
    assert al.shorts_per_day({"id": "a", "type": "story", "schedule": {"shorts_per_day": 1}}) == 1
