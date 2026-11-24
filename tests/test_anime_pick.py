"""Owner 24 Nov, after the anime look test (data/tmp/loop/anime_ab: one real scene per channel in three anime directions,
drawn by FLUX.2 klein and scored by the eyes check): "Itihaas C, Cricket A, Clutch A". The test's Cricket picture
showed football on the TV (its shot only said "a match"), so sports shots name their sport."""
from engine import storyboard
from engine.config import channel


def _style(cid: str) -> str:
    return channel(cid)["style"]["ai_style"]


def test_the_owners_anime_picks():
    assert _style("itihaas_ke_raaz").startswith("epic dark anime illustration, gritty high-contrast cel shading")
    for cid in ("cricket_ke_kisse", "clutch_tales"):
        assert _style(cid).startswith("cinematic anime key visual, clean cel shading, crisp line art"), cid
    assert "photoreal" in _style("cosmos_unboxed")              # science stays photoreal (owner 23 Nov)


def test_sports_shots_name_their_sport_and_stay_faceless():
    for cid in ("cricket_ke_kisse", "clutch_tales"):
        rules = storyboard._rules(channel(cid))
        assert storyboard.RULES["sport"] in rules and storyboard.RULES["no_faces"] in rules, cid
    assert storyboard.RULES["sport"] not in storyboard._rules(channel("itihaas_ke_raaz"))
