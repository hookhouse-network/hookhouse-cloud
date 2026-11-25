"""26 Nov (P3, owner standard S1): hook in 1 s, open loops every 8-12 s, one story turn, payoff + loop ending were
never checked before voice and pictures. Plain-code findings feed the script judge's rewrite round."""
from engine import script_structure as ss


def _s(*lines):
    return {"beats": [{"narration": x} for x in lines]}


GOOD = _s("This falcon dives at 240 miles an hour and breathes fine.",
          "So how does it not burst its lungs?",
          "A tiny bone cone sits inside each nostril.",
          "But that alone would not save it.",
          "Its heart slows right before the strike.",
          "Turns out the dive is a controlled fall.",
          "Guess what it hunts at that speed?",
          "Other birds, in mid-air, and the falcon breathes fine at 240.")


def test_a_well_built_short_has_no_findings():
    assert ss.findings(GOOD) == []


def test_each_missing_part_is_named():
    bad = _s("So, today we look at falcons.", "Falcons are birds of prey.", "They live on every continent.",
             "They eat other birds.", "They nest on cliffs and buildings.", "Their eggs are reddish brown.",
             "Chicks fly after six weeks.", "Some live for fifteen years in the wild and many more in captivity.",
             "Many cities now host nesting pairs on tall towers and bridges near busy roads.",
             "Scientists ring the chicks every spring to follow them.", "That is a lot of data.")
    kinds = {f.split(":")[0] for f in ss.findings(bad)}
    assert kinds == {"hook", "open loops", "story turn", "loop ending"}


def test_short_or_foreign_scripts_are_left_alone():
    assert ss.findings(_s("a", "b", "c")) == []
    assert ss.findings(dict(_s(*["x y z"] * 6), language="hi")) == []
