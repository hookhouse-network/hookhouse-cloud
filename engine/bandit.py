"""P8 bandits (27 Nov): Thompson sampling, simple and explainable.

Each option (hook type, Brain Snack format, ...) has the scores of the channel's videos made with it. A video "wins"
when it beats the median of ALL the channel's scored videos. Each option draws a number from Beta(1 + wins, 1 +
losses) and the highest draw is used: a proven winner is picked most of the time, an untested option (Beta(1, 1))
still gets tried, and a clear loser rarely comes back. Replaces the fixed 'explore 30 %' rule."""
from __future__ import annotations

import random
import statistics


def record(scores: dict[str, list[float]]) -> dict[str, tuple[int, int]]:
    """{option: (wins, losses)} against the median of every score."""
    pooled = [s for v in scores.values() for s in v]
    if not pooled:
        return {}
    mid = statistics.median(pooled)
    return {k: (sum(1 for s in v if s > mid), sum(1 for s in v if s <= mid)) for k, v in scores.items()}


def pick(options: list[str], scores: dict[str, list[float]], rng=None) -> tuple[str, str]:
    """(option, why) by Thompson sampling."""
    rng = rng or random.Random()
    wl = record({k: v for k, v in scores.items() if k in options})
    draws = {o: rng.betavariate(1 + wl.get(o, (0, 0))[0], 1 + wl.get(o, (0, 0))[1]) for o in options}
    best = max(draws, key=draws.get)
    w, lo = wl.get(best, (0, 0))
    if w + lo == 0:
        return best, "testing this option (no measured video yet)"
    return best, f"Thompson pick: beat the channel's median on {w} of {w + lo} videos"
