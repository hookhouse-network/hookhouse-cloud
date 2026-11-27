"""27 Nov (P3 checkpoints): a stopped kids episode resumes from its kept plan (the AI planning call is not repeated,
same seed); a fresh plan is handed to on_plan before the slow render starts."""
import pytest

from engine import kids


class Stop(Exception):
    pass


def _stop_after_plan(monkeypatch):
    monkeypatch.setattr(kids, "use_layout", lambda *a, **k: None)
    monkeypatch.setattr(kids, "puppets_on", lambda: False)
    monkeypatch.setattr(kids, "qa", lambda *a, **k: (_ for _ in ()).throw(Stop()))      # stop before the render


def test_a_fresh_plan_is_kept_before_the_render(monkeypatch):
    _stop_after_plan(monkeypatch)
    monkeypatch.setattr(kids, "plan_episode", lambda brain, seed, topic, max_n=10: {"lines": [{"t": "one"}],
                                                                                    "count_to": 3, "object": "apple"})
    kept = []
    with pytest.raises(Stop):
        kids.make(None, {"id": "bloop_and_friends"}, seed=42, on_plan=kept.append)
    assert kept and kept[0]["seed"] == 42 and kept[0]["lines"] == [{"t": "one"}]


def test_a_kept_plan_skips_the_ai_call(monkeypatch):
    _stop_after_plan(monkeypatch)
    monkeypatch.setattr(kids, "plan_episode", lambda *a, **k: pytest.fail("the AI planning call must not repeat"))
    seen = {}
    monkeypatch.setattr(kids, "qa", lambda lines, n, rounds_needed=3: seen.update(lines=lines) or
                        (_ for _ in ()).throw(Stop()))
    with pytest.raises(Stop):
        kids.make(None, {"id": "bloop_and_friends"}, planned={"lines": [{"t": "kept"}], "count_to": 3,
                                                              "object": "apple", "seed": 7})
    assert seen["lines"] == [{"t": "kept"}]
