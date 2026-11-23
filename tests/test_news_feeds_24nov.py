"""24 Nov (owner 23 Nov: "you are taking too old trending topics"): only 42% of the last two weeks' story slots had a
real "why now" (Wild Instinct 0 of 16). Four more channels get a daily news-driven topic; the queries were tried on the
live feed first, and the picker never turns a live case into a video."""
from engine import news_topics
from engine.config import channel


def test_the_low_freshness_channels_have_a_news_feed():
    for cid in ("wild_instinct", "deep_blue_files", "unsolved_after_dark", "ending_decoded"):
        assert news_topics.FEEDS.get(cid), cid
        assert channel(cid)["id"] == cid                     # a real channel id


def test_no_feed_asks_for_live_missing_person_cases():
    queries = " ".join(q for feeds in news_topics.FEEDS.values() for q, *_ in feeds).lower()
    assert "unsolved mystery" not in queries and "missing" not in queries


def test_the_picker_never_makes_a_video_of_a_live_case():
    p = news_topics.PROMPT.lower()
    assert "never a live" in p and "still missing" in p and "ongoing investigation" in p
