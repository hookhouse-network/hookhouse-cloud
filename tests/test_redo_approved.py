"""21 Nov: approved videos blocked at upload by a remake-fixable finding go back to redo (not retried forever)."""
from engine import autopilot


def _setup(monkeypatch, redos=0):
    calls = {}
    monkeypatch.setattr(autopilot, "update_item", lambda start, iid, **kw: calls.update(kw) or kw)
    monkeypatch.setattr(autopilot, "_channel", lambda cid: {"id": cid, "type": "story"})
    monkeypatch.setattr("engine.core.ledger.event", lambda *a, **k: None)
    it = {"id": "1121_0500_ending_decoded_short", "channel": "ending_decoded", "gate_redos": redos}
    return it, calls


def test_franchise_block_on_an_approved_video_sends_it_back_to_redo(monkeypatch):
    it, calls = _setup(monkeypatch)
    res = "upload failed: 🛑 blocked: names a protected franchise/character: avengers, doctor doom, mcu"
    assert autopilot._redo_if_blocked("2026-11-16", it, res, log=lambda *a: None)
    assert calls["status"] == "redo" and "avengers" in calls["gate_note"] and calls["gate_redos"] == 1


def test_no_redo_for_other_failures_or_after_the_limit(monkeypatch):
    it, calls = _setup(monkeypatch)
    assert not autopilot._redo_if_blocked("s", it, "upload failed (HTTP 500): boom", log=lambda *a: None)
    assert not autopilot._redo_if_blocked("s", it, "upload failed: 🛑 blocked: no title", log=lambda *a: None)
    assert not calls
    # 26 Nov: past the limit it is no longer retried every tick (Hot Take ~45 blocks): it is set aside once
    it2, calls2 = _setup(monkeypatch, redos=2)
    monkeypatch.setattr("engine.telegram_bot.notify", lambda t: True)
    assert autopilot._redo_if_blocked("s", it2, "upload failed: 🛑 blocked: potential: hook 3", log=lambda *a: None)
    assert calls2["status"] == "missed" and "blocked at upload after" in calls2["gate_note"]
