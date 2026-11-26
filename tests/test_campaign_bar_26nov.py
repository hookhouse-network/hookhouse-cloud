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
