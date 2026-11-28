"""28 Nov (P3b): charts built from the narration's own numbers always pass the said-number check (the writer's broke
it 8-9 times a script)."""
from engine.media import html_scene as hs
from engine.media.auto_chart import auto_chart


def _ok(chart, said):
    out, why = hs.check_chart(chart, said)
    assert out, why
    return out


def test_two_years_make_a_timeline():
    said = "Ballard found the Titanic in 1985. By 2024 the wreck was nearly gone."
    c = auto_chart(said)
    assert c["type"] == "timeline" and [i["label"] for i in c["items"]] == ["1985", "2024"]
    _ok(c, said)


def test_same_unit_numbers_make_a_compare():
    said = "The asteroid was 6 miles wide. Mount Everest is 5.5 miles tall."
    c = auto_chart(said)
    assert c["type"] == "compare" and [i["value"] for i in c["items"]] == [6.0, 5.5]
    assert "asteroid" in c["items"][0]["label"].lower() and "Everest" in c["items"][1]["label"]
    _ok(c, said)


def test_one_depth_makes_a_depth_chart_only_when_allowed():
    said = "The wreck lies 12,500 feet below the waves."
    assert auto_chart(said) is None
    c = auto_chart(said, depth_ok=True)
    assert c["type"] == "depth"
    _ok(c, said)


def test_nothing_to_chart():
    assert auto_chart("It was a dark and stormy night.") is None
    assert auto_chart("It hit at 45,000 mph.") is None          # one number: no comparison to draw
