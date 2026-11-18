"""Tests for Brain Snack v3 (fast: physics and planning only, no video rendering)."""
import numpy as np
import pytest

from engine.snack import audio as au
from engine.snack import maker, multiply, readfast, spiral, versus
from engine.snack.canvas import blit, text_sprite


def test_melodies_are_playable_notes():
    for name, notes in au.MELODIES.items():
        assert len(notes) >= 12, name
        assert all(36 <= n <= 96 for n in notes), name
    clip = au.render_notes([(0.0, 60, 0.8), (0.05, 62, 0.8), (0.5, 64, 0.8)], 1.5, "marimba")
    assert clip.shape == (int(1.5 * au.SR),) and np.abs(clip).max() > 0.01


def test_spiral_story_always_ends_with_the_winning_try():
    segs = spiral.build_spiral()
    for rule in ("speed", "size", "boost"):
        atts = spiral.plan_attempts(segs, rule, 4, seed=3)
        assert atts[-1].outcome == 1, rule                      # last try reaches the center
        assert all(a.outcome != 1 for a in atts[:-1]), rule     # earlier tries fail
        assert all(a.duration >= 5 for a in atts)


def test_every_multiply_shape_is_a_usable_container():
    for shape in multiply.SHAPES:
        m = multiply.silhouette(shape, "B")
        area = (m > 0).mean()
        assert 0.08 < area < 0.45, shape                         # big, but inside the frame
        assert m[0].max() == 0 and m[-1].max() == 0              # nothing touches the frame edge


def test_multiply_fill_is_paced_not_instant():
    sim = multiply.Sim(multiply.silhouette("heart"), seed=5)
    sim.events = []
    frames = sim.run()
    assert 6.0 <= len(frames) / 60 <= 16.0
    assert len(frames[-1][0]) >= sim.target


def test_fights_end_in_a_ko_and_the_league_counts_head_to_head(tmp_path, monkeypatch):
    frames, events, winner, ko, fighters = versus.plan_fight("Gummo", "Mochi", 3)
    assert ko is not None and 20 <= ko <= 60 and winner in ("Gummo", "Mochi")
    assert min(f.hp for f in fighters) <= 0
    monkeypatch.setattr(versus, "LEAGUE", tmp_path / "league.json")
    assert versus.record("Gummo", "Mochi") == (1, 1, 0)
    assert versus.record("Mochi", "Gummo") == (1, 1, 1)


def test_readfast_words_speed_up_and_bounces_stay_inside():
    d = readfast.schedule(30)
    assert d[0] == pytest.approx(0.45) and d[-1] == pytest.approx(0.14)
    assert all(a > b for a, b in zip(d, d[1:]))
    pts = readfast.bounce_points(30, np.random.default_rng(1))
    assert all(np.hypot(x - readfast.CX, y - readfast.CY) <= readfast.R for x, y in pts)


def test_new_specs_do_not_repeat_recent_combinations():
    history = []
    seen = set()
    for i in range(25):
        spec = maker.new_spec("multiply", history, seed=i)
        key = maker._combo_key(spec)
        assert key not in seen
        seen.add(key)
        history.append(spec)
    assert maker.choose_format([{"format": "spiral"}]) != "spiral"   # never the same format twice in a row


def test_text_sprites_blend_onto_frames():
    frame = np.zeros((200, 400, 3), np.uint8)
    spr = text_sprite("HELLO", "Poppins Black", 60, stroke=6)
    assert spr.shape[2] == 4 and spr[..., 3].max() == 255
    blit(frame, spr, 200, 100)
    blit(frame, spr, -500, -500)                                   # fully off-screen is ignored
    assert frame.max() > 200
