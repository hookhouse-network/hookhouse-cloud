"""20 Nov (owner: "for approval, yes you can consider auto-approval"): only after a clean record of owner approvals,
only with time to stop it, never counting its own approvals."""
from datetime import datetime, timedelta

import pytest

from engine import auto_approve as aa, weekly


@pytest.fixture(autouse=True)
def trust_rule(request, monkeypatch):
    """These tests cover the earned-trust rule itself (10 clean approvals, 2 h to veto); the live config may differ."""
    if "live_config" not in request.keywords:
        monkeypatch.setattr(aa, "settings", lambda: dict(aa.DEFAULTS))


@pytest.mark.live_config
def test_owner_21_nov_config_approves_every_gate_passed_video():
    """Owner 21 Nov: approving is the system's job; any video that passed every gate is approved (Stop still works)."""
    s = aa.settings()
    assert s["min_clean"] == 0 and s["min_hours"] <= 0.5
    ok, why = aa.eligible(_it(hours=1), plan_items=[])
    assert ok, why
    assert not aa.eligible(dict(_it(hours=1), status="planned"), plan_items=[])[0]    # only made (gate-passed) videos


def _now():
    return datetime.now(weekly._zone())


def _hist(n_clean, extra=None):
    rows = [{"channel": "c", "kind": "short", "status": "posted", "approved_at": 1000 + i} for i in range(n_clean)]
    return rows + (extra or [])


def _it(hours=5):
    return {"id": "new", "channel": "c", "kind": "short", "status": "made",
            "publish_at": (_now() + timedelta(hours=hours)).isoformat()}


def test_approves_after_ten_clean_owner_approvals():
    ok, why = aa.eligible(_it(), plan_items=_hist(10))
    assert ok and "last 10" in why


def test_not_enough_history():
    ok, why = aa.eligible(_it(), plan_items=_hist(9))
    assert not ok and "9 of 10" in why


def test_a_recent_reject_or_change_turns_it_off():
    rej = [{"channel": "c", "kind": "short", "status": "rejected", "decided_at": 5000}]
    assert not aa.eligible(_it(), plan_items=_hist(12, rej))[0]
    chg = [{"channel": "c", "kind": "short", "status": "posted", "approved_at": 5000, "note": "scarier hook"}]
    assert not aa.eligible(_it(), plan_items=_hist(12, chg))[0]


def test_auto_approvals_never_count_as_trust():
    auto = [{"channel": "c", "kind": "short", "status": "posted", "approved_at": 9000 + i, "auto_approved": True}
            for i in range(20)]
    assert not aa.eligible(_it(), plan_items=_hist(5, auto))[0]


def test_needs_time_to_stop_it_and_respects_the_switch(monkeypatch):
    assert not aa.eligible(_it(hours=1), plan_items=_hist(10))[0]
    monkeypatch.setattr(aa, "settings", lambda: dict(aa.DEFAULTS, enabled=False))
    assert not aa.eligible(_it(), plan_items=_hist(10))[0]


def test_other_kinds_and_channels_are_separate():
    other = [{"channel": "c", "kind": "long", "status": "posted", "approved_at": 1 + i} for i in range(10)]
    assert not aa.eligible(_it(), plan_items=other)[0]
