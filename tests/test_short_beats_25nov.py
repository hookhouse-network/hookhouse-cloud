"""25 Nov: 62 of 133 Short drafts came back over the channel's word range (187-193 words for 115-150): the writer was
asked for 16-22 beats at 3-14 words each. The beat count now follows the word range."""
from engine import story


class Res:
    provider = "test"


def _prompt(ch):
    seen = []

    class Brain:
        def ask_json(self, task, prompt, system="", temperature=0.4):
            seen.append(prompt)
            return {"title": "Apollo 13", "beats": [{"narration": "Houston, we've had a problem."}]}, Res()
    story.write_script(Brain(), ch, "Apollo 13")
    return seen[0]


BASE = {"id": "cosmos_unboxed", "name": "Cosmos Unboxed", "language": "en", "niche": "space history", "market": "US",
        "content_rules": {}, "voice": {"id": "bf_emma"}, "style": {}}


def test_the_short_beat_count_follows_the_channel_word_range():
    p = _prompt(dict(BASE, spec={"short_words": "115-150 words (about 42-55 seconds)"}))
    assert "Length: 115-150 words (about 42-55 seconds), 11-16 beats." in p and "16-22" not in p


def test_the_default_short_range_gets_a_matching_beat_count():
    assert "Length: 120-150 words (about 45-55 seconds), 12-16 beats." in _prompt(dict(BASE, spec={}))
