"""Bloop & Friends: counting is always exact, the layout stays clear, the camera stays calm (fast, no audio)."""
import numpy as np

from engine import kids as K


class NoBrain:
    def ask_json(self, *a, **k):
        raise RuntimeError("offline")


def _timed(lines):
    t = 2.0
    for ln in lines:                                   # rough timing, like build_timeline without voices
        ln.update(start=t, end=t + 1.2, hold=t + 1.2 + K.GAPS[ln["kind"]])
        t = ln["hold"]
    return t + 5.0


def test_every_round_counts_exactly_and_no_ctas():
    for seed in range(12):
        ep = K.plan_episode(NoBrain(), seed, "count from 1 to 7" if seed % 2 else None)
        assert K.qa(ep["lines"], ep["count_to"])["counts_ok"]
        assert not any(K.BANNED.search(ln["say"]) for ln in ep["lines"])
        kinds = [ln["kind"] for ln in ep["lines"]]
        colour_q = 1 if ep["object"] in K.OBJECT_COLOUR else 0          # round 16: + a colour question
        assert kinds.count("question") == 2 + colour_q and kinds.count("count") == ep["count_to"]
        assert kinds.count("callout") == 2                               # help us? / say the word


def test_lesson_number_and_beach_limit():
    assert K.plan_episode(NoBrain(), 1, "count from 1 to 8")["count_to"] in (6, 8)   # beach keeps one row (<= 6)
    for seed in range(30):
        ep = K.plan_episode(NoBrain(), seed)
        if ep["scene"] == "beach":
            assert ep["count_to"] <= 6


def test_writer_lines_are_cleaned():
    story = {"intro": [{"who": "Bloop", "say": "Hi friend!"}, {"who": "Zed", "say": "Who am I?"},
                       {"who": "Pip", "say": "Please subscribe!"}, "junk"], "adjective": "Super shiny!"}
    lines = K.build_lines(story, 3, "apple")
    assert lines[0]["say"] == "Hi friend!" and lines[1]["who"] == "narrator"
    assert not any("subscribe" in ln["say"].lower() for ln in lines)
    assert any(ln["say"] == "One red apple!" for ln in lines)   # "super" is not on the gentle list


def test_spots_stay_inside_and_above_the_characters():
    for scene in ("park", "beach", "room"):
        for n in range(3, 11):
            if scene == "beach" and n > 6:
                continue
            for x, y in K.slot_xy(n, scene):
                assert 120 < x < K.CW - 120
                assert y - 110 > K.DIGIT_Y + 60            # never under the big number
                assert y + 120 < K.FEET_Y - 330            # never on the characters' heads


def test_short_layout_keeps_everything_above_the_shorts_buttons():
    K.use_layout("short")
    try:
        assert (K.W, K.H) == (1080, 1920) and K.CW < K.CH
        for scene in ("park", "beach", "room"):
            for n in range(3, 7):
                for x, y in K.slot_xy(n, scene):
                    assert K.SLOT_R + 10 < x < K.CW - K.SLOT_R - 10
                    assert y - K.SLOT_R > K.DIGIT_Y + 80
                    assert y + K.SLOT_R * 1.2 < K.FEET_Y - 280
        assert K.FEET_Y / K.CH < 0.78                                    # bottom ~22% is the Shorts UI
        sx = K.W / K.CW                                                  # canvas -> output pixels
        for name, (_c, _shape, size, _v, x) in K.CAST.items():          # right ~120 px = Shorts buttons
            assert (x + 0.36 * size) * sx <= K.W - 120 and (x - 0.36 * size) * sx >= 20, name
        assert K.FEET_Y * K.H / K.CH <= K.H - 380                        # title / channel / audio line
        ep = K.plan_episode(NoBrain(), 3, max_n=6)
        lines = K.short_lines(ep["lines"])
        assert K.qa(lines, ep["count_to"], rounds_needed=1)["counts_ok"] and ep["count_to"] <= 6
        assert [ln["section"] for ln in lines].count("intro") <= 2
    finally:
        K.use_layout("long")
    assert (K.W, K.H) == (1920, 1080) and K.CAST["Bloop"][4] == 560


def test_shots_are_calm():
    ep = K.plan_episode(NoBrain(), 5, "count from 1 to 5")
    total = _timed(ep["lines"])
    shots = K.plan_shots(ep["lines"], total, K.slot_xy(5, ep["scene"]))
    lens = [b - a for a, b, _ in shots]
    assert min(lens[:-1]) >= 2.5 and sum(lens) / len(lens) >= 4.0
    frame = K.camera(np.zeros((K.CH, K.CW, 3), np.uint8), shots, 10.0)
    assert frame.shape == (K.H, K.W, 3)


def test_week_planner_topics_are_counting_lessons_that_round_trip():
    tops = K.plan_topics(3, 20261116, kinds=["long", "short", "short"])
    assert len({t["topic"].split(": ")[0].split()[-1] for t in tops}) == 3          # three different objects
    for t in tops:
        assert t["topic"].startswith("count from 1 to ")
        ep = K.plan_episode(NoBrain(), 1, t["topic"])
        assert str(ep["count_to"]) in t["topic"] and ep["situation"] in t["topic"]


def test_christmas_season_brings_christmas_counting_topics(monkeypatch):
    """17 Nov: product research #1 was Christmas coloring pages; Bloop's videos follow it from 15 Nov to 31 Dec."""
    from datetime import date
    assert K.christmas_season(date(2026, 11, 20)) and K.christmas_season(date(2026, 12, 31))
    assert not K.christmas_season(date(2026, 11, 10)) and not K.christmas_season(date(2027, 1, 2))
    monkeypatch.setattr(K, "christmas_season", lambda when=None: True)
    tops = K.plan_topics(3, 5, kinds=["short", "short", "long"])
    assert all(any(o in t["topic"] for o in ("present", "ornament", "bell", "snowmen", "stocking", "candy cane")) for t in tops)
    monkeypatch.setattr(K, "christmas_season", lambda when=None: False)
    assert not any("snowmen" in t["topic"] or "present" in t["topic"] for t in K.plan_topics(4, 5))
