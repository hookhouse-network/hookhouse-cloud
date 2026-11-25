"""25 Nov (P7): the first GTA clips passed the campaign rules but the judge held them (hook 3.5, caption_hook 2.5:
nothing happens in the first 2 s; the explosion payoff only at the end). Stream clips now open with a 1.5 s flash of
the payoff, GTA's own subtitles (which still showed the muted swear words) are blurred, and captions sit clear of the
streamer's Kick badge."""
import numpy as np

from engine import clipv3


def _thumbs(start, dur, busy_at=None):
    out, rng = [], np.random.default_rng(1)
    for i in range(int(dur * 10)):
        t = start + i / 10
        base = np.full((36, 64), 100, np.float32)
        if busy_at and busy_at[0] <= t < busy_at[1]:
            base = rng.uniform(0, 255, (36, 64)).astype(np.float32)
        out.append((t, base))
    return out


def test_the_payoff_teaser_starts_just_before_the_loud_busy_moment():
    start, dur = 100.0, 30.0
    rms = np.full(int(dur * 10), 300.0)
    rms[200:215] = 6000.0                                  # the explosion + yelling at 20.0-21.5 s
    p0 = clipv3.payoff_start(rms, _thumbs(start, dur, (120.0, 121.5)), start, start + dur)
    assert p0 is not None and 119.0 <= p0 <= 120.0


def test_no_teaser_for_a_flat_or_short_clip():
    flat = np.full(300, 500.0)
    assert clipv3.payoff_start(flat, _thumbs(0, 30), 0, 30) is None
    assert clipv3.payoff_start(np.full(80, 500.0), _thumbs(0, 8), 0, 8) is None


def test_burned_in_subtitles_are_blurred_and_a_clean_picture_is_left_alone():
    game = np.full((1280, 1080, 3), 60, np.uint8)
    assert clipv3.blur_burned_subtitles(game) is game          # nothing to hide
    sub = game.copy()
    sub[1150:1175, 300:780] = 255                               # a white subtitle line, bottom middle
    out = clipv3.blur_burned_subtitles(sub)
    assert out[1150:1175, 300:780].mean() < 230 and out[:1000].mean() == sub[:1000].mean()


def test_stream_captions_sit_below_the_kick_badge():
    assert clipv3.STREAM_CAPTION_MIN_Y >= clipv3.CAM_PANE_H + 400
