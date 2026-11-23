"""24 Nov S6 for Brain Snack (from the 23 Nov 21:00 review and the held 24 Nov videos):
- the 'Read it if you can' fact Shorts open on the fact's own teaser (the judge called the fixed "READ IT IF YOU CAN"
  card a vague, templated opening; the review's best Instagram Shorts were the ones whose subject showed first);
- the character battles are retired behind settings `snack_retired_formats` (189 Instagram views = 0.09x median,
  0 likes, a viewer called the fight unfair; the review: stop them)."""
import numpy as np

from engine.snack import maker, readfast


def test_a_good_hook_is_kept_and_weak_ones_fall_back_to_the_dare():
    assert readfast.hook_of({"hook": "America reset every clock at once"}) == "America reset every clock at once"
    assert readfast.hook_of({"hook": '  "Why did Boston drown in molasses?" '}) == "Why did Boston drown in molasses?"
    for weak in ("", "Wow", "Did you know this about clocks?", "Guess what happened in 1883",
                 "Read it if you can", "a teaser that goes on far too long to fit on one card at all"):
        assert readfast.hook_of({"hook": weak}) == "", weak
    assert readfast.hook_of({}) == ""


def test_the_card_wraps_to_short_lines():
    card = readfast.wrap("AMERICA RESET EVERY CLOCK AT ONCE")
    assert card.split("\n") == ["AMERICA", "RESET EVERY", "CLOCK AT", "ONCE"]


def test_the_judge_and_the_upload_see_the_facts_own_hook():
    fact = {"fact": "On 18 November 1883 US railroads reset every clock to four time zones at noon.",
            "hook": "America reset every clock at once"}
    spec = {"format": "readfast", "fact": fact}
    assert maker.screen_hook(spec) == "America reset every clock at once"
    shown = maker.describe(spec, {"words": 15, "total": 9.0})
    assert shown.startswith('0:00 "America reset every clock at once" fills the screen')
    assert "read it if you can" in shown and "READ IT IF YOU CAN" not in shown
    old = {"format": "readfast", "fact": {"fact": "x y z"}}            # a saved spec without a hook: as before
    assert maker.screen_hook(old) == "READ IT IF YOU CAN"
    assert "READ IT IF YOU CAN" in maker.describe(old, {"words": 3, "total": 5.0})


class _Writer:
    def __init__(self):
        self.frames = []

    def write(self, f):
        self.frames.append(f.copy())


def test_the_render_opens_on_the_teaser_card():
    fact = {"fact": "On 18 November 1883 US railroads reset every clock to four time zones at noon sharp.",
            "hook": "America reset every clock at once"}
    spec = {"format": "readfast", "seed": 3, "melody": "twinkle", "instrument": "pluck"}
    w = _Writer()
    info = readfast.render(spec, fact, w, fps=10, log=lambda *a: None)
    assert info["bounces"][0][0] == 1.9                 # the first word comes after the teaser card
    assert info["cover_at"] < 1.9                       # the cover shows the teaser, not one flashing word
    plain = _Writer()
    readfast.render(spec, {"fact": fact["fact"]}, plain, fps=10, log=lambda *a: None)
    assert not np.array_equal(w.frames[0], plain.frames[0])     # a different opening card than the old dare


def test_retired_formats_are_never_picked(monkeypatch):
    monkeypatch.setattr("engine.config.settings", lambda: {"snack_retired_formats": ["versus"]})
    assert "versus" not in maker.ready_formats()
    picks = {maker.choose_format([], made=["spiral", "ladder"]) for _ in range(120)}
    assert picks and "versus" not in picks
    monkeypatch.setattr("engine.config.settings", lambda: {})                    # the switch: back again
    assert "versus" in maker.ready_formats()


def test_the_live_settings_retire_the_battles():
    from engine.config import settings
    assert "versus" in (settings().get("snack_retired_formats") or [])
