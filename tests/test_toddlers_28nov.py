"""28 Nov (owner: "totally change the animations ... like CoComelon", bright cartoon): our own toddler cast replaces the
stiff DiceBear dolls. Always moving (never a frozen figure), blinks, waves; plugs in as the human friends; no credit
line needed (our own drawing)."""
import numpy as np

from engine import kids
from engine.media.toddler import TODDLERS, Toddler


def test_a_toddler_is_a_feet_aligned_bgra_sprite_that_never_freezes():
    t = Toddler("lulu", size=300, seed=1)
    a = t.draw(0.0)
    assert a.shape == (t.H, t.W, 4) and a[..., 3].max() == 255
    assert a[-int(t.H * 0.06):, ..., 3].max() > 0          # feet drawn at the bottom edge = the ground line
    b = t.draw(0.5)                                            # breathing + sway: a different picture
    assert float(np.abs(a.astype(np.int16) - b.astype(np.int16)).mean()) > 0.2


def test_blink_wave_and_talking_change_the_picture():
    t = Toddler("amara", size=300, seed=0)
    open_ = t.draw(t.blink_at[0] - 0.5)
    shut = t.draw(t.blink_at[0])
    assert not np.array_equal(open_, shut)
    assert not np.array_equal(t.draw(1.0), t.draw(1.0, action="wave"))
    assert not np.array_equal(t.draw(1.0), t.draw(1.0, mouth=0.9))


def test_toddlers_are_the_friends_when_switched_on(monkeypatch):
    monkeypatch.setattr("engine.config.settings", lambda: {"kids_toddlers": True})
    humans = kids._humans()
    assert set(humans) == {t["name"] for t in TODDLERS.values()}
    assert all(spec[1].startswith("toddler:") for spec in humans.values())
    monkeypatch.setattr(kids, "GUESTS", {**kids.GUESTS, **humans})
    name = next(iter(humans))
    assert kids.is_puppet(name) and not kids.needs_credit(name)
    assert kids.credits_line([name]) == ""


def test_no_toddler_copies_a_famous_signature():
    """Benji had a single curl on top (a famous show's baby signature): never again."""
    assert all(t["style"] != "tuft" for t in TODDLERS.values())
