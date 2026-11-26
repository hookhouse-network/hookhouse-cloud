"""Owner 26 Nov ("campaign bar 7"): until 28 Nov a campaign clip that passes every campaign rule passes the potential
judge with an average of 7+ and no point under 6 (it held 4 GTA clips at 4-7.5)."""
from engine import potential_gate as pg


def test_the_campaign_bar():
    good = {"hook": 7, "self_contained": 7.5, "emotion": 7, "shareability": 6.5, "caption_hook": 7, "brief_fit": 8}
    assert pg.campaign_bar_ok(good, today="2026-11-26")
    assert not pg.campaign_bar_ok(dict(good, shareability=5.5), today="2026-11-26")    # a point under 6
    assert not pg.campaign_bar_ok({k: 6.5 for k in good}, today="2026-11-26")          # average under 7
    assert not pg.campaign_bar_ok(good, today="2026-11-29")                            # the bar has ended
    assert not pg.campaign_bar_ok({}, today="2026-11-26")


def test_clip_verdicts_follow_the_rubric_text_and_carry_no_history():
    """26 Nov: a dated note in brief_fit was read as a directive ('drop the gameplay per the 26 Nov directive') and the
    misjudged verdicts stayed cached; the rubric states rules only and the clip tag follows its texts."""
    assert "26 Nov" not in pg.CRITERIA_HELP["brief_fit"] and "drop" not in pg.CRITERIA_HELP["brief_fit"]
    assert pg.judge_tag("clips", {"id": "x"}) != ""


def test_the_daily_review_survives_a_video_without_a_title():
    """26 Nov: '21:00 daily review: NoneType object is not subscriptable' (a plan item with topic: null)."""
    from engine import daily_review
    rep = daily_review.judge([{"title": None, "kind": "short", "slot": "05:00", "views": 10, "hours": 30.0},
                              {"title": "A", "kind": "short", "slot": "06:30", "views": 0, "hours": 30.0}])
    assert isinstance(rep, dict)
