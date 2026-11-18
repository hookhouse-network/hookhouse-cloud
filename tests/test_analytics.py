"""Learning-loop tests with synthetic metrics (no accounts needed)."""
import time

from engine import analytics as an


class FakeMemory:
    def __init__(self):
        self.items = []

    def add(self, kind, text, channel=None, performance=None):
        self.items.append((kind, text, channel, performance))


def _seed(conn, n=20, weak_fmt="multiply"):
    now = time.time()
    for i in range(n):
        fmt = weak_fmt if i % 2 else "spiral"
        views = 800 if fmt == weak_fmt else 4000 + i * 100
        an.record(conn, item_id=f"v{i}", channel="brain_snack", platform="youtube", format=fmt,
                  hook=f"hook {i}", topic=f"topic {i}", posted_at=now - (n - i) * 2 * 86400, hours_after=48,
                  views=views, stayed_pct=55 if fmt == weak_fmt else 78, avg_pct_viewed=70, shares=10)


def test_summary_finds_winners_and_weak_formats():
    conn = an.connect(":memory:")
    _seed(conn)
    s = an.channel_summary(conn, "brain_snack")
    assert s["videos"] == 20 and all(w["format"] == "spiral" for w in s["winners"])
    assert an.weak_formats(conn, "brain_snack") == ["multiply"]


def test_memory_gets_the_winning_hooks():
    conn = an.connect(":memory:")
    _seed(conn)
    mem = FakeMemory()
    assert an.feed_memory(conn, "brain_snack", mem) >= 1
    assert all(k == "hook" and ch == "brain_snack" for k, _, ch, _ in mem.items)


def test_report_text_has_actions_and_handles_empty_channels():
    conn = an.connect(":memory:")
    _seed(conn)
    rep = an.weekly_report(conn, ["brain_snack", "unsolved_after_dark"])
    assert "WIN" in rep and "multiply" in rep and "unsolved_after_dark: no data yet" in rep
