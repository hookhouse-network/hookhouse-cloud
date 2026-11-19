"""Cut-on-the-beat: the in-house beat tracker finds a click track's tempo and beats, ignores pulse-less pads, and the
story render moves cuts (and the text/sounds on them) onto beats without touching the climax."""
import numpy as np

from engine.media import beats as bt
from engine.media.captions import BigText, Label
from engine.media.compose import Shot

SR = 22050


def click_track(bpm=120.0, seconds=20.0, offset=0.25):
    x = np.random.default_rng(0).normal(0, 0.01, int(SR * seconds)).astype(np.float32)
    period = 60.0 / bpm
    t = offset
    k = np.arange(int(0.03 * SR))
    hit = (np.sin(2 * np.pi * 180 * k / SR) * np.exp(-k / (0.006 * SR))).astype(np.float32)
    while t < seconds - 0.1:
        a = int(t * SR)
        x[a:a + len(hit)] += hit
        t += period
    return x


def test_tempo_and_beats_of_a_click_track():
    x = click_track(120, offset=0.25)
    env, fps = bt.onset_envelope(x, SR)
    bpm, conf = bt.tempo(env, fps)
    assert abs(bpm - 120) < 4 or abs(bpm - 60) < 2 or abs(bpm - 240) < 8
    beats = bt.beat_times(x, SR)
    assert len(beats) >= 15
    # every found beat sits on a real click (within 30 ms)
    clicks = np.arange(0.25, 20, 0.5)
    assert all(np.min(np.abs(clicks - b)) < 0.03 for b in beats)


def test_no_beats_in_a_pad():
    t = np.arange(int(SR * 15)) / SR
    pad = (0.3 * np.sin(2 * np.pi * 220 * t) * (0.8 + 0.2 * np.sin(2 * np.pi * 0.1 * t))).astype(np.float32)
    assert bt.beat_times(pad, SR) == []


def test_snap_cuts_rules():
    beats = [1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0]
    moved = bt.snap_cuts([1.1, 2.3, 3.04, 3.2], beats, keep=[3.04])
    assert moved[1.1] == 1.0                        # within 0.15 s -> onto the beat
    assert 2.3 not in moved                          # 0.2 s away: stays
    assert 3.04 not in moved                         # the climax never moves
    assert 3.2 not in moved                          # would leave a shot shorter than 0.6 s
    assert bt.snap_cuts([1.1], []) == {}


def test_render_step_moves_shots_text_and_sounds(tmp_path):
    from engine.story import cut_on_beats
    bed = click_track(120, seconds=8, offset=0.0)    # beats at 0, 0.5, 1.0 ...
    shots = [Shot(0.0, 2.1, "image"), Shot(2.1, 4.4, "image"), Shot(4.4, 8.0, "image")]
    labels = [Label(2.2, 4.35, "THE SHIP")]
    bigs = [BigText(2.1, 4.4, "1872")]
    events = [(2.1, "cut.wav", -12.0), (6.0, "punch.wav", -10.0)]
    out, lab, big, st, ev, q, ai = cut_on_beats(shots, labels, bigs, [], events, [(2.1, 4.4)], [], None, 8.0,
                                                bed_audio=bed, sr=SR, log=lambda *_: None)
    assert abs(out[0].end - 2.0) < 0.03 and out[1].start == out[0].end
    assert abs(out[1].end - 4.5) < 0.03 and out[2].start == out[1].end
    assert abs(lab[0].start - (2.2 + out[1].start - 2.1)) < 1e-6      # the label moved with its cut
    assert big[0].start == out[1].start and big[0].end == out[1].end
    assert abs(ev[0][0] - out[1].start) < 1e-6 and ev[1][0] == 6.0   # cut sound moved; the punch did not
    assert q[0] == (out[1].start, out[1].end)


def test_render_step_keeps_the_climax(tmp_path):
    from engine.story import cut_on_beats
    bed = click_track(120, seconds=8, offset=0.0)
    shots = [Shot(0.0, 2.1, "image"), Shot(2.1, 8.0, "image")]
    out, *_ = cut_on_beats(shots, [], [], [], [], [], [], None, 8.0, keep=[2.1], bed_audio=bed, sr=SR,
                           log=lambda *_: None)
    assert out[0].end == 2.1 and out[1].start == 2.1
