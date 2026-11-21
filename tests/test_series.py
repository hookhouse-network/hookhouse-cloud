"""P3r creativity (S8 A13): every fresh story video is an episode of one of its channel's named series."""
import yaml

from engine import series
from engine.config import channels


def test_every_story_channel_has_named_series():
    data = yaml.safe_load(series.FILE.read_text(encoding="utf-8"))
    story = {c["id"] for c in channels() if c.get("type") == "story" and c["id"] != "stream_clips"}
    assert story <= set(data), story - set(data)
    for cid, lst in data.items():
        assert 1 <= len(lst) <= 2, cid
        for s in lst:
            assert s["name"] and len(s["promise"]) > 20 and s["hashtag"].startswith("#") and " " not in s["hashtag"]
            assert "untold story" not in s["promise"].lower()                  # S10: no AI stock phrases


def test_rotation_rule_and_apply():
    a = series.pick("unsolved_after_dark")
    b = series.pick("unsolved_after_dark")
    c = series.pick("unsolved_after_dark")
    assert a["name"] != b["name"] and a["name"] == c["name"]                  # two series, in turn
    assert series.pick("bloop_and_friends") is None and series.rule(None) == ""
    assert a["promise"] in series.rule(a) and "episode" in series.rule(a)
    short = series.apply({"title": "The Town That Vanished", "hashtags": ["#Centralia"]}, a, "short")
    assert short["hashtags"][0] == a["hashtag"] and short["title"] == "The Town That Vanished"
    assert short["series"] == a["name"]
    long_ = series.apply({"title": "The Town That Vanished", "hashtags": []}, a, "long")
    assert long_["title"] == f"{a['name']}: The Town That Vanished"
    huge = series.apply({"title": "x" * 58, "hashtags": [a["hashtag"].lower()]}, a, "long")
    assert huge["title"] == "x" * 58 and huge["hashtags"] == [a["hashtag"]]   # too long: no prefix, no double tag


def test_the_writer_gets_the_series_rule(monkeypatch):
    from engine import story
    seen = {}

    class Brain:
        def ask_json(self, task, prompt, system="", temperature=0.4):
            seen["prompt"] = prompt
            return {"title": "T", "beats": [{"narration": "A line."}], "hashtags": []}, type("R", (), {"provider": "x"})()
    ch = next(c for c in channels() if c["id"] == "cosmos_unboxed")
    story.write_script(Brain(), ch, "Venus days", "short", extra_rules=series.rule(series.for_channel(ch["id"])[0]))
    assert "SERIES: this video is an episode of" in seen["prompt"]
