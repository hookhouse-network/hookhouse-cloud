"""S6 review of the scorecard's first day (22 Nov 2026).

The first run gave Brain Snack a 'saves' experiment: saves 0/1k (shortfall 1.00) against shares 0.09/1k (0.98), while
Instagram names watch time, likes per reach and sends per reach as its top ranking signals (sends most for reaching
non-followers) and the scorecard did not measure likes at all. Instagram also does not recommend posts that ask for
shares, comments or tags, so no rule, caption or end card may ask for them."""
import sqlite3

from engine import scorecard as sc

DAY = 86400.0
NOW = 1_800_000_000.0


def _db(path, rows):
    with sqlite3.connect(path) as c:
        c.execute("CREATE TABLE video_metrics (item_id TEXT, channel TEXT, platform TEXT, posted_at REAL, "
                  "hours_after REAL, views REAL, engaged_views REAL, stayed_pct REAL, avg_pct_viewed REAL, "
                  "shares REAL, saves REAL, comments REAL, likes REAL)")
        c.executemany("INSERT INTO video_metrics VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    return path


def _ig(i, posted, views=2000, shares=0, saves=0, comments=0, likes=10, ch="brain_snack"):
    """An Instagram snapshot as stats_fetch stores it: no watch % or stayed %, the rest measured."""
    return (f"v{i}", ch, "instagram", posted, 48, views, None, None, None, shares, saves, comments, likes)


def test_brain_snack_22_nov_numbers_pick_shares_not_saves(tmp_path):
    # the real 7-day Instagram numbers: 9,604 views, 1 share, 0 saves, 0 comments, 79 likes over 5 Shorts
    rows = [_ig(1, NOW - 4 * DAY, 2790, likes=44), _ig(2, NOW - 3 * DAY, 189, likes=0),
            _ig(3, NOW - 3 * DAY, 2050, likes=13), _ig(4, NOW - 2 * DAY, 2470, shares=1, likes=16),
            _ig(5, NOW - 2 * DAY, 2105, likes=6)]
    m = sc.measure("brain_snack", NOW - 14 * DAY, _db(tmp_path / "a.db", rows))
    assert m["signals"]["saves"] == 0.0 and m["signals"]["likes"] == round(1000 * 79 / 9604, 2)
    assert m["signals"]["hook"] is None and m["signals"]["watch"] is None        # Instagram gives neither
    # shortfalls: saves 1.00, comments 1.00, shares 0.98, likes 0.59 -> a tie, won by the platform's own signal
    assert sc.weakest(m["signals"]) == ("shares", 0.98)


def test_a_clear_gap_still_wins_over_priority():
    assert sc.weakest({"hook": 64.0, "shares": 4.9, "saves": 0.0})[0] == "saves"          # 1.00 vs 0.02 / 0.015
    assert sc.weakest({"hook": 30.0, "shares": 2.0, "saves": 0.0})[0] == "saves"          # 1.00 vs 0.60: clear
    assert sc.weakest({"hook": 6.5, "shares": 0.0, "saves": 0.0})[0] == "hook"            # 0.90 vs 1.00: a tie


def test_an_experiment_with_no_posted_video_follows_the_newest_pick(tmp_path):
    db = _db(tmp_path / "b.db", [_ig(i, NOW - 3 * DAY, likes=40) for i in range(4)])       # saves 0, shares 0
    state = {"brain_snack": {"kept": [], "history": [], "active": {
        "signal": "saves", "rule": "old wording", "start": NOW - 0.5 * DAY, "baseline": 0.0, "gap": 1.0}}}
    d = sc.decide("brain_snack", NOW, db, state)
    st = state["brain_snack"]
    assert d["change"] and d["signal"] == "shares" and "re-aimed from saves" in d["why"]
    assert st["active"]["signal"] == "shares" and st["active"]["start"] == NOW and st["active"]["from"] == "saves"
    assert st["history"][-1]["verdict"] == "re-aimed"
    again = sc.decide("brain_snack", NOW + DAY, db, state)                                 # same pick: it runs on
    assert not again["change"] and "day 2 of 7" in again["why"]


def test_once_a_video_is_posted_under_it_the_experiment_is_not_re_aimed(tmp_path):
    rows = [_ig(i, NOW - 3 * DAY, likes=40) for i in range(4)] + [_ig(9, NOW - 0.2 * DAY, 30, likes=0)]
    db = _db(tmp_path / "c.db", rows)
    state = {"brain_snack": {"kept": [], "history": [], "active": {
        "signal": "saves", "rule": sc.RULES["saves"], "start": NOW - 0.5 * DAY, "baseline": 0.0, "gap": 1.0}}}
    d = sc.decide("brain_snack", NOW, db, state)
    assert not d["change"] and "saves experiment is on day 1" in d["why"]
    assert state["brain_snack"]["active"]["signal"] == "saves"


def test_old_databases_without_likes_still_measure(tmp_path):
    p = tmp_path / "old.db"
    with sqlite3.connect(p) as c:
        c.execute("CREATE TABLE video_metrics (item_id TEXT, channel TEXT, platform TEXT, posted_at REAL, "
                  "hours_after REAL, views REAL, engaged_views REAL, stayed_pct REAL, avg_pct_viewed REAL, "
                  "shares REAL, saves REAL, comments REAL)")
        c.execute("INSERT INTO video_metrics VALUES ('a','brain_snack','youtube',?,48,500,NULL,70,80,1,1,1)",
                  (NOW - DAY,))
    m = sc.measure("brain_snack", NOW - 14 * DAY, p)
    assert m["videos"] == 1 and m["signals"]["likes"] is None and m["signals"]["shares"] == 2.0


def test_no_rule_asks_for_engagement_and_the_writer_gets_the_current_wording():
    for sig, rule in sc.RULES.items():
        low = rule.lower()
        assert "send challenge" not in low and "share with" not in low and "comment below" not in low.replace(
            "never 'comment below'", "")
    state = {"clutch_tales": {"kept": [], "active": {"signal": "shares", "rule": "end with a send challenge"}}}
    text = sc.writer_rule("clutch_tales", state)
    assert "worth sending" in text and "send challenge" not in text and "Never ask" in text


def test_review_and_snack_texts_never_ask_for_shares():
    import inspect

    from engine import daily_review
    from engine.snack import ladder, maker, readfast
    v = {"title": "1 bounce = 2 balls", "kind": "short", "slot": "00:36", "views": 2105, "hours": 48, "likes": 6,
         "shares": 0}
    weak = daily_review.judge([v])["weak"]
    assert any("nobody shared it" in w for w in weak)
    assert not any("send this to" in w.lower() for w in weak) and any("without asking" in w for w in weak)
    assert 'cta_text = "Comment your score' not in inspect.getsource(ladder)
    assert 'text_sprite("Send it to' not in inspect.getsource(readfast)
    for fmt in list(maker.FORMATS) + ["unknown"]:
        assert all("send it" not in line.lower() for line in maker.cta_for(fmt))
