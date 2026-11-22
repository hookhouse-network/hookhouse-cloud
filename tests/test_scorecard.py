"""P3r execution workstream (S6 + S8 A19): the 5-signal scorecard and one measured change per channel per day,
run as 7-day experiments that are kept or reverted on the channel's own numbers."""
import sqlite3

import pytest

from engine import scorecard as sc

DAY = 86400.0
NOW = 1_800_000_000.0


def _db(path, rows):
    with sqlite3.connect(path) as c:
        c.execute("CREATE TABLE video_metrics (item_id TEXT, channel TEXT, platform TEXT, posted_at REAL, "
                  "hours_after REAL, views REAL, engaged_views REAL, stayed_pct REAL, avg_pct_viewed REAL, "
                  "shares REAL, saves REAL, comments REAL)")
        c.executemany("INSERT INTO video_metrics VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    return path


def _video(i, posted, views=1000, stayed=70, watch=80, shares=8, saves=8, comments=3, ch="brain_snack"):
    return (f"v{i}", ch, "youtube", posted, 48, views, None, stayed, watch, shares, saves, comments)


def test_measure_uses_the_newest_snapshot_and_skips_tiny_videos(tmp_path):
    rows = [_video(1, NOW - DAY, shares=0), _video(2, NOW - DAY, shares=10), _video(3, NOW - DAY, views=20)]
    rows.append(("v1", "brain_snack", "youtube", NOW - DAY, 2, 100, None, 40, 30, 0, 0, 0))   # older snapshot
    m = sc.measure("brain_snack", NOW - 14 * DAY, _db(tmp_path / "a.db", rows))
    assert m["videos"] == 2 and m["signals"]["shares"] == 5.0 and m["signals"]["hook"] == 70.0


def test_weakest_signal_is_the_biggest_shortfall():
    assert sc.weakest({"hook": 70, "watch": 80, "shares": 1.0, "saves": 6, "comments": 1.5}) == ("shares", 0.8)
    assert sc.weakest({"hook": 70, "watch": None, "shares": 9, "saves": 6, "comments": 3}) is None


def test_one_decision_per_day_and_the_experiment_verdict(tmp_path):
    db = tmp_path / "b.db"
    _db(db, [_video(i, NOW - 3 * DAY, shares=1) for i in range(4)])
    state = {}
    d = sc.decide("brain_snack", NOW, db, state)
    assert d["change"] and d["signal"] == "shares" and state["brain_snack"]["active"]["baseline"] == 1.0
    assert "shares" in sc.writer_rule("brain_snack", state) and "worth sending" in sc.writer_rule("brain_snack", state)
    d2 = sc.decide("brain_snack", NOW + 2 * DAY, db, state)
    assert not d2["change"] and "day 3 of 7" in d2["why"]                     # a reasoned no-change
    d3 = sc.decide("brain_snack", NOW + 8 * DAY, db, state)
    assert not d3["change"] and "needs more videos" in d3["why"]              # nothing made since the start yet
    with sqlite3.connect(db) as c:                                            # new videos share much more
        c.executemany("INSERT INTO video_metrics VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                      [_video(10 + i, NOW + 1 * DAY, shares=4) for i in range(3)])
    d4 = sc.decide("brain_snack", NOW + 9 * DAY, db, state)
    assert d4["verdict"] == "keep" and "active" not in state["brain_snack"]
    assert "PROVEN BY OUR NUMBERS" in sc.writer_rule("brain_snack", state)


def test_too_little_data_and_revert(tmp_path):
    db = _db(tmp_path / "c.db", [_video(1, NOW - DAY)])
    d = sc.decide("clutch_tales", NOW, db, {})
    assert not d["change"] and "only 0 video" in d["why"] or "only 1 video" in d["why"]
    state = {"clutch_tales": {"kept": [], "history": [], "active": {
        "signal": "watch", "rule": sc.RULES["watch"], "start": NOW - 8 * DAY, "baseline": 60.0}}}
    with sqlite3.connect(db) as c:
        c.executemany("INSERT INTO video_metrics VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                      [_video(20 + i, NOW - 5 * DAY, watch=58, ch="clutch_tales") for i in range(3)])
    d = sc.decide("clutch_tales", NOW, db, state)
    assert d["verdict"] == "revert" and state["clutch_tales"]["kept"] == []


def test_run_all_saves_and_summarises(tmp_path):
    sc.DB.parent.mkdir(parents=True, exist_ok=True)
    _db(sc.DB, [_video(i, NOW - DAY, comments=0.1) for i in range(3)])
    out = sc.run_all(["brain_snack", "clutch_tales"], now=NOW, log=lambda *_: None)
    assert [d["change"] for d in out] == [True, False]
    saved = sc._load()
    assert saved["brain_snack"]["active"]["signal"] == "comments" and saved["clutch_tales"]["days"][-1]["why"]
    text = sc.summary(out)
    assert "brain_snack: comments" in text and "1 channel(s) no change" in text


def test_writer_rules_carry_the_experiment(monkeypatch):
    from engine import content_tuning
    monkeypatch.setattr(sc, "_load", lambda: {"brain_snack": {"active": {"signal": "hook", "rule": sc.RULES["hook"]},
                                                              "kept": []}})
    assert "THIS WEEK'S EXPERIMENT (hook" in content_tuning.writer_rules("brain_snack")
