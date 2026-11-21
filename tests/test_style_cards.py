"""P3r creativity (S8 A3 style card, A16 visual style, A17 humour card): every story channel has a card; the writer
gets the angle/voice/pillars/humour and the storyboard gets the channel look."""
import yaml

from engine import humanize, storyboard, style_cards
from engine.config import channels


def test_every_story_channel_has_a_complete_card():
    data = yaml.safe_load(style_cards.FILE.read_text(encoding="utf-8"))
    story = {c["id"] for c in channels() if c.get("type") == "story" and c["id"] != "stream_clips"}
    assert story <= set(data), story - set(data)
    for cid, c in data.items():
        assert {"angle", "voice", "pillars", "visual", "humour"} <= set(c), cid
        assert 3 <= len(c["pillars"]) <= 5, cid
        text = " ".join([c["angle"], c["voice"], c["visual"], c["humour"]])
        assert not humanize.tells(text), (cid, humanize.tells(text))          # S10: the card itself sounds human


def test_writer_and_storyboard_get_the_card():
    w = style_cards.writer_text("cosmos_unboxed")
    assert w.startswith("CHANNEL STYLE CARD") and "Angle:" in w and "Humour:" in w and "Content pillars" in w
    assert style_cards.writer_text("bloop_and_friends") == "" and style_cards.visual_text("nobody") == ""
    assert "CHANNEL LOOK: real NASA" in storyboard._rules({"id": "cosmos_unboxed"})
    assert "copyrighted" in storyboard._rules({"id": "cosmos_unboxed"})        # the copyright rule stays first


def test_the_writer_prompt_carries_the_card():
    from engine import story
    seen = {}

    class Brain:
        def ask_json(self, task, prompt, system="", temperature=0.4):
            seen["prompt"] = prompt
            return {"title": "T", "beats": [{"narration": "A line."}], "hashtags": []}, type("R", (), {"provider": "x"})()
    ch = next(c for c in channels() if c["id"] == "deep_blue_files")
    story.write_script(Brain(), ch, "Deep sea sounds", "short")
    assert "CHANNEL STYLE CARD" in seen["prompt"] and "submarine log" in seen["prompt"]
