"""Platform numbers -> content changes (owner 19 Nov: swipes, no watch time, outdated, not trending)."""
import sqlite3

from engine import analytics, content_tuning as ct, trends, weekly


def _db(tmp_path, rows):
    db = tmp_path / "a.db"
    conn = analytics.connect(db)
    for r in rows:
        analytics.record(conn, **r)
    conn.commit()
    conn.close()
    return db


def test_plateau_low_likes_and_swipe_baseline(tmp_path):
    base = {"channel": "bs", "platform": "youtube", "format": "short", "posted_at": 1.0}
    db = _db(tmp_path, [
        {**base, "item_id": "a", "video_id": "A", "hours_after": 24, "views": 1056, "likes": 5},
        {**base, "item_id": "a", "video_id": "A", "hours_after": 48, "views": 1062, "likes": 5},
        {**base, "item_id": "b", "video_id": "B", "hours_after": 24, "views": 791, "likes": 8},
    ])
    s = ct.signals("bs", db)
    assert s["videos"] == 2 and s["plateaued"] == 1 and s["stayed"] is None
    assert round(s["like_rate"], 2) == round(100 * 13 / 1853, 2)
    rules = ct.writer_rules("bs", db)
    assert "FIRST SECOND" in rules and "stopped growing" in rules and "likes per 100 views" in rules
    assert "FEELING" in rules and "NEVER DATED" in rules
    notes = ct.channel_notes("bs", db)
    assert any("swipe away" in n for n in notes)


def test_measured_stayed_share_is_used(tmp_path):
    base = {"channel": "c", "platform": "youtube", "format": "short", "posted_at": 1.0, "hours_after": 96}
    db = _db(tmp_path, [{**base, "item_id": "x", "video_id": "X", "views": 1000, "engaged_views": 820, "likes": 40,
                         "avg_pct_viewed": 92}])
    s = ct.signals("c", db)
    assert round(s["stayed"]) == 82
    rules = ct.writer_rules("c", db)
    assert "FIRST SECOND" not in rules and "OUR NUMBERS" not in rules      # healthy: only the base rules


def test_no_data_channel_still_gets_baseline(tmp_path):
    hints = ct.topic_hints("none", tmp_path / "missing.db")
    assert hints and "swipe away" in hints[0]


def test_weak_topics_dropped():
    assert weekly._weak({"topic": "x", "scroll_stop": 5})
    assert not weekly._weak({"topic": "x", "scroll_stop": 9})
    assert not weekly._weak({"topic": "x"})
    assert not weekly._weak({"topic": "x", "scroll_stop": "high"})


def test_topic_prompt_asks_for_feeling_and_now():
    assert "scroll_stop" in weekly.TOPIC_PROMPT and "feeling" in weekly.TOPIC_PROMPT
    assert "CURRENT" in weekly.TOPIC_PROMPT


def test_youtube_trending_hint_and_market():
    it = {"source": "youtube:US", "title": "GTA 6 first look", "score": 1200000}
    assert trends._eligible(it, "US") and not trends._eligible(it, "IN")
    assert "Trending on YouTube in the US" in trends.hint_text(it)


def test_refresh_topic_swaps_in_stronger_topic(monkeypatch):
    monkeypatch.setattr("engine.trends.trend_hints", lambda brain, log=print: {"c1": ["Trending now: X"]})
    seen = {}

    def fake_pick(brain, ch, n, memory=None, hints=None, taken=None, log=print, cluster_out=None):
        seen["hints"] = hints
        return [{"topic": "GTA 6 map secrets", "angle": "a", "feeling": "awe", "now_hook": "GTA 6 launch"}]
    monkeypatch.setattr(weekly, "pick_topics", fake_pick)
    item = {"id": "i", "topic": "Old topic", "angle": "old"}
    weekly._refresh_topic({"items": [item]}, item, {"id": "c1", "name": "C"}, object(), log=lambda m: None)
    assert item["topic"] == "GTA 6 map secrets" and item["planned_topic"] == "Old topic"
    assert item["feeling"] == "awe" and item["refreshed"]
    assert any("PLANNED EARLIER" in h for h in seen["hints"]) and "Trending now: X" in seen["hints"]


def test_hook_loop_tests_then_exploits(tmp_path, monkeypatch):
    import random
    monkeypatch.setattr(ct, "HOOKS_FILE", tmp_path / "hooks.json")
    h, why = ct.next_hook("c", tmp_path / "none.db", rng=random.Random(1))
    assert h in ct.HOOK_TYPES and "testing" in why                 # nothing measured: test a hook type
    base = {"channel": "c", "platform": "youtube", "format": "short", "posted_at": 1.0, "hours_after": 96}
    rows, i = [], 0
    for hook, stayed in (("outcome_first", 80), ("contrarian", 40)):
        for _ in range(ct.MIN_TESTS):
            i += 1
            ct.record_hook(f"v{i}", "c", hook)
            rows.append({**base, "item_id": f"v{i}", "video_id": f"V{i}", "views": 100, "stayed_pct": stayed})
    db = _db(tmp_path, rows)
    sc = ct.hook_scores("c", db)
    assert len(sc["outcome_first"]) == ct.MIN_TESTS and sc["outcome_first"][0] == 80
    picks = [ct.next_hook("c", db, rng=random.Random(s))[0] for s in range(40)]
    assert picks.count("outcome_first") > picks.count("contrarian")  # the winner is used most
    assert any(p not in ("outcome_first", "contrarian") for p in picks)   # untested types still get tried
    rules = ct.writer_rules("c", db, hook="outcome_first")
    assert "HOOK TYPE for this video: outcome_first" in rules and "YOUTUBE POLICY" in rules


def test_record_hook_ignores_unknown(tmp_path, monkeypatch):
    monkeypatch.setattr(ct, "HOOKS_FILE", tmp_path / "hooks.json")
    ct.record_hook("x", "c", "made_up")
    assert not (tmp_path / "hooks.json").exists()
