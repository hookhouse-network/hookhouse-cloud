"""27 Nov (P8, owner "Keep coaching"): the relative bar only watches. It records each judged video's card, its
pointwise and pairwise predictions (both orders), and report() scores them against real views 48 h+ later."""
import sqlite3

from engine import relative_bar as rb
from engine.core.ledger import Ledger


def _db(path, rows):
    c = sqlite3.connect(str(path))
    c.execute("CREATE TABLE video_metrics (item_id TEXT, channel TEXT, platform TEXT, views REAL, hours_after REAL)")
    c.executemany("INSERT INTO video_metrics VALUES (?,?,?,?,?)", rows)
    c.commit()
    c.close()


class Brain:
    """Answers 'A' or 'B' from a script of answers."""

    def __init__(self, answers):
        self.answers, self.prompts = list(answers), []

    def ask_json(self, task, prompt, temperature=0.4):
        self.prompts.append(prompt)
        return {"more_views": self.answers.pop(0)}, None


def _past(led, ch="snack"):
    for i, mean in (("v1", 5.0), ("v2", 6.0), ("v3", 7.0)):
        led.event(rb.EVENT, item=i, channel=ch, data={"mean": mean, "card": f"Title: {i}"})


def test_observe_records_both_predictions_and_never_blocks(tmp_path, monkeypatch):
    led = Ledger(tmp_path / "l.db")
    db = tmp_path / "a.db"
    _db(db, [("v1", "snack", "youtube", 100, 72), ("v2", "snack", "youtube", 500, 72),
             ("v3", "snack", "youtube", 900, 72)])
    _past(led)
    monkeypatch.setattr(rb, "card", lambda it, meta: "Title: new one")
    brain = Brain(["A", "B"])                          # A first (new = A), B second (new = B): both say "new"
    rec = rb.observe({"id": "v4"}, {"id": "snack"}, {}, {"scores": {"hook": 8, "retention": 7, "human_feel": 2}},
                     brain, led=led, db=db)
    assert rec["mean"] == 7.5 and rec["median_score"] == 6.0 and rec["pointwise"] == "above"
    assert rec["ref"] == "v2" and rec["ref_views"] == 500 and rec["pairwise"] == "new"
    assert "Title: new one" in brain.prompts[0].split("VIDEO B")[0] and "Title: v2" in brain.prompts[1].split("VIDEO B")[0]
    assert led.events(rb.EVENT)[-1]["item"] == "v4"


def test_position_bias_is_recorded_as_split(tmp_path, monkeypatch):
    led = Ledger(tmp_path / "l.db")
    db = tmp_path / "a.db"
    _db(db, [("v1", "snack", "youtube", 100, 72), ("v2", "snack", "youtube", 500, 72),
             ("v3", "snack", "youtube", 900, 72)])
    _past(led)
    monkeypatch.setattr(rb, "card", lambda it, meta: "x")
    rec = rb.observe({"id": "v4"}, {"id": "snack"}, {}, {"scores": {"hook": 6}}, Brain(["A", "A"]), led=led, db=db)
    assert rec["pairwise"] == "split"


def test_young_videos_and_failures_do_not_count(tmp_path, monkeypatch):
    led = Ledger(tmp_path / "l.db")
    db = tmp_path / "a.db"
    _db(db, [("v1", "snack", "youtube", 100, 10)])     # 10 h old: not mature
    _past(led)
    monkeypatch.setattr(rb, "card", lambda it, meta: "x")
    rec = rb.observe({"id": "v4"}, {"id": "snack"}, {}, {"scores": {"hook": 6}}, Brain([]), led=led, db=db)
    assert rec["pointwise"] is None and rec["pairwise"] is None   # no posted reference yet: recorded only
    class Broken:
        def events(self, *a, **k):
            raise RuntimeError("ledger down")
    assert rb.observe({"id": "v5"}, {"id": "snack"}, {}, {"scores": {"hook": 6}}, None, led=Broken()) is None


def test_report_scores_predictions_against_views(tmp_path):
    led = Ledger(tmp_path / "l.db")
    db = tmp_path / "a.db"
    _db(db, [("a", "snack", "youtube", 100, 72), ("b", "snack", "youtube", 500, 72),
             ("c", "snack", "youtube", 900, 72), ("d", "snack", "youtube", 50, 72)])
    led.event(rb.EVENT, item="a", channel="snack", data={"pointwise": "below", "pairwise": "ref", "ref_views": 500})
    led.event(rb.EVENT, item="c", channel="snack", data={"pointwise": "above", "pairwise": "new", "ref_views": 500})
    led.event(rb.EVENT, item="d", channel="snack", data={"pointwise": "above", "pairwise": "split", "ref_views": 500})
    led.event(rb.EVENT, item="b", channel="snack", data={"pointwise": None, "pairwise": None})
    r = rb.report(led=led, db=db)
    assert r["pointwise"] == {"right": 2, "n": 3, "pct": 67}
    assert r["pairwise"]["right"] == 2 and r["pairwise"]["n"] == 2 and r["pairwise"]["split"] == 1
    assert r["proven"] == [] and "never blocks" in r["line"] and "none yet" in r["line"]
