"""27 Nov (P8 honest forgetting): a lesson loses weight unless new data confirms it, and drops out after weeks;
real examples never decay."""
import time

from engine.memory import store
from engine.memory.store import Memory

DAY = 86400.0


def test_freshness_halves_every_two_weeks():
    now = 1_800_000_000.0
    assert store.freshness("playbook", {}, now, now) == 1.0
    assert abs(store.freshness("playbook", {}, now - 14 * DAY, now) - 0.5) < 1e-9
    assert store.freshness("playbook", {"confirmed": now - DAY}, now - 60 * DAY, now) > 0.9   # confirmed lately
    assert store.freshness("hook", {}, now - 365 * DAY, now) == 1.0                        # examples never decay


def test_old_unconfirmed_lessons_are_forgotten_and_confirm_revives(tmp_path):
    m = Memory(tmp_path / "m.db")
    old = m.add("playbook", "KEEP: open on the payoff", channel="c")
    m.add("playbook", "KEEP: open on the payoff frame", channel="c")
    m.conn.execute("UPDATE items SET created=? WHERE id=?", (time.time() - 60 * DAY, old))
    m.conn.commit()
    ids = [h.id for h in m.search("open on the payoff", kind="playbook", channel="c")]
    assert old not in ids and len(ids) == 1                              # 60 days unconfirmed: forgotten
    m.confirm(old)
    hits = m.search("open on the payoff", kind="playbook", channel="c")
    assert old in [h.id for h in hits]
    assert next(h for h in hits if h.id == old).meta["confirms"] == 1
