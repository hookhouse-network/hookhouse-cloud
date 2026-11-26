"""27 Nov (P9): silently swallowed errors 110 -> 0; noted() records them and never raises."""
from engine.core import quiet


def test_noted_records_and_never_raises(monkeypatch):
    events = []
    from engine.core import ledger
    monkeypatch.setattr(ledger, "event", lambda t, **k: events.append((t, k["data"]["where"])))
    monkeypatch.setattr(quiet, "_SEEN", {})
    for _ in range(5):
        quiet.noted("x.py:1", ValueError("boom"))
    assert events == [("swallowed", "x.py:1")] * quiet.PER_HOUR          # rate-limited per place
    monkeypatch.setattr(ledger, "event", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db gone")))
    quiet.noted("y.py:2", None)                                          # never raises into the caller
