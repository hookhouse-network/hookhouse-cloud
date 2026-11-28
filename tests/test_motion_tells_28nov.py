"""28 Nov (owner's repo review, motionmaxxing-style gates, our own code): empty-frame runs, end hold, final-shot share
are measured; they never change the quality score."""
import numpy as np

from engine import quality


def _frames(n, flat_from=None, flat_to=None, still_last=0):
    rng = np.random.default_rng(1)
    out = []
    for i in range(n):
        f = rng.integers(0, 255, (54, 96)).astype(np.float32)
        if flat_from is not None and flat_from <= i < flat_to:
            f = np.full((54, 96), 20.0, dtype=np.float32)
        out.append(f)
    if still_last:
        for i in range(n - still_last, n):
            out[i] = out[n - still_last - 1].copy()
    return out


def test_a_clean_video_has_no_tells():
    m = quality.motion_tells(None, 10.0, cuts=[3.0, 6.0, 9.0], frames=_frames(300), fps=30)
    assert m["tells"] == [] and m["flat_run"] == 0 and m["end_hold_s"] == 0.0


def test_empty_frames_long_end_hold_and_long_last_shot_are_found():
    m = quality.motion_tells(None, 10.0, cuts=[2.0], frames=_frames(300, 30, 40, still_last=60), fps=30)
    assert m["flat_run"] == 10 and abs(m["flat_at"] - 1.0) < 0.01
    assert m["end_hold_s"] == 2.0 and m["final_shot_share"] == 0.8
    assert len(m["tells"]) == 3 and "empty frames" in m["tells"][0]


def test_three_flat_frames_are_allowed():
    m = quality.motion_tells(None, 10.0, cuts=[9.0], frames=_frames(300, 30, 33), fps=30)
    assert m["flat_run"] == 3 and not any("empty" in t for t in m["tells"])
