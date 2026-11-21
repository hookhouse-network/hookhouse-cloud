"""21 Nov: Unsolved After Dark narrated at 139 wpm against a research target of 180 (held at 71/100); the pace
calibration was capped at speed 1.12, so it could never reach the target."""
import numpy as np

from engine import story


def test_pace_ceiling_lets_a_slow_voice_reach_its_target_band():
    speed, measured, target = 1.0, 139, 180
    new = float(np.clip(speed * target / measured, 0.9, story.MAX_PACE_SPEED))
    assert story.MAX_PACE_SPEED >= 1.25 and new * measured >= 0.95 * target
