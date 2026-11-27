"""27 Nov (P8 bandits): Thompson sampling picks the proven option most, still tries untested ones, rarely a loser;
Brain Snack formats learn from their own views."""
import random

from engine import bandit


def test_thompson_prefers_the_winner_and_keeps_testing():
    scores = {"spiral": [90, 80, 85, 95], "race": [10, 20, 15, 5]}
    picks = [bandit.pick(["spiral", "race", "ladder"], scores, rng=random.Random(s))[0] for s in range(200)]
    assert picks.count("spiral") > 100                      # the winner most of the time
    assert picks.count("ladder") > 5                        # untested still tried
    assert picks.count("race") < picks.count("ladder")      # the loser least
    assert bandit.record(scores) == {"spiral": (4, 0), "race": (0, 4)}


def test_why_says_what_it_did():
    o, why = bandit.pick(["a"], {}, rng=random.Random(1))
    assert o == "a" and "testing" in why
    o, why = bandit.pick(["a", "b"], {"a": [9, 9, 9], "b": [1]}, rng=random.Random(1))
    assert "Thompson pick" in why


def test_brain_snack_formats_follow_their_views(monkeypatch, tmp_path):
    from engine import content_tuning as ct
    from engine.snack import maker
    for i in range(4):
        ct.record_format(f"s{i}", "spiral")
        ct.record_format(f"r{i}", "race")
    monkeypatch.setattr(ct, "label_scores", lambda cid, labels, db=None: {
        "spiral": [90.0] * 4, "race": [10.0] * 4} if labels else {})
    assert set(ct.format_scores()) == {"spiral", "race"}
    monkeypatch.setattr(maker, "ready_formats", lambda: {"spiral", "race"})
    monkeypatch.setattr(maker, "FORMATS", ["spiral", "race"])
    random.seed(3)
    got = [maker.choose_format([], made=[]) for _ in range(60)]
    assert got.count("spiral") > got.count("race")
