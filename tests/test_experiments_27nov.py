"""27 Nov (P8 experiment log): each automatic change is logged with its baseline and, 7 days later, its measured
effect, shown in the brief."""
import sqlite3

from engine import experiments as ex
from engine.core.ledger import Ledger

DAY = 86400.0
NOW = 1_800_000_000.0


def _db(path, rows):
    c = sqlite3.connect(str(path))
    c.execute("CREATE TABLE video_metrics (item_id TEXT, channel TEXT, platform TEXT, posted_at REAL, hours_after REAL,"
              " views REAL, engaged_views REAL, stayed_pct REAL, avg_pct_viewed REAL, shares REAL, saves REAL,"
              " comments REAL, likes REAL)")
    c.executemany("INSERT INTO video_metrics (item_id, channel, platform, posted_at, hours_after, views) "
                  "VALUES (?,?,?,?,?,?)", rows)
    c.commit()
    c.close()


def test_a_change_is_measured_after_seven_days(tmp_path):
    db = tmp_path / "a.db"
    change_at = NOW - 8 * DAY
    before = [(f"b{i}", "snack", "youtube", change_at - (i + 1) * DAY, 72, 100) for i in range(4)]
    after = [(f"a{i}", "snack", "youtube", change_at + (i + 1) * DAY, 72, 300) for i in range(4)]
    _db(db, before)
    led = Ledger(tmp_path / "l.db")
    ex.record("volume", "snack", "2 -> 3 Shorts a day", led=led, now=change_at, db=db)   # baseline at change time
    c = sqlite3.connect(str(db))
    c.executemany("INSERT INTO video_metrics (item_id, channel, platform, posted_at, hours_after, views) "
                  "VALUES (?,?,?,?,?,?)", after)
    c.commit()
    c.close()
    rows = ex.effects(led=led, now=NOW, db=db)
    assert rows[0]["baseline"]["views_per_video"] == 100.0 and rows[0]["after"]["views_per_video"] == 300.0
    assert rows[0]["verdict"] == "helped"
    text = ex.brief_text(led=led, now=NOW, db=db)
    assert "snack volume: 2 -> 3 Shorts a day -> helped (views/video 100 -> 300)" in text


def test_young_changes_and_thin_data(tmp_path):
    db = tmp_path / "a.db"
    _db(db, [("a0", "snack", "youtube", NOW - DAY, 72, 300)])
    led = Ledger(tmp_path / "l.db")
    ex.record("slots", "snack", "09:00, 18:00", led=led, now=NOW - 2 * DAY, db=db)
    ex.record("rule", "snack", "hook: open on the payoff", led=led, now=NOW - 9 * DAY, db=db)
    rows = {r["kind"]: r for r in ex.effects(led=led, now=NOW, db=db)}
    assert rows["slots"]["verdict"] == "measuring" and rows["rule"]["verdict"] == "too few videos"
    assert "measuring (1): snack slots day 3" in ex.brief_text(led=led, now=NOW, db=db)
    assert ex.verdict({"views_per_video": 100}, {"videos": 5, "views_per_video": 95}) == "no clear change"
    assert ex.verdict({"views_per_video": 100}, {"videos": 5, "views_per_video": 80}) == "hurt"


def test_record_never_raises_and_empty_brief(tmp_path):
    class Broken:
        def event(self, *a, **k):
            raise RuntimeError("down")
    ex.record("rule", "snack", "x", led=Broken(), db=tmp_path / "none.db")
    assert "no automatic change" in ex.brief_text(led=Ledger(tmp_path / "l.db"), db=tmp_path / "none.db")
