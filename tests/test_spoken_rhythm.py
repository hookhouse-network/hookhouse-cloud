"""24 Nov: 6 of the day's held videos were 'looks/sounds obviously AI-made' (human_feel 5, needs 6), and the judge's
rubric names "same-shaped sentences, a template look". The writer was told "One short sentence per beat (5-12
words)", which beat the system prompt's "sentences of different lengths": the scripts read as one flat 8-word
sentence after another. A/B on the same topics, same Lite writer, judged by the panel: human_feel 5.0 -> 6.5 (Money
Cheat Codes, with hook, retention and clarity up) and 6.0 -> 6.5 (Ending Decoded) with a spoken-rhythm rule."""
from engine import story


def test_the_writer_asks_for_spoken_rhythm_not_one_flat_sentence_per_beat():
    p = story.WRITER_PROMPT
    assert "One short sentence per beat" not in p
    assert "vary in length AND shape" in p and "Never three beats in a row of the same length" in p
    assert "about 2-3 seconds" in p                                 # the beat count (one picture each) stays


def test_added_beats_keep_the_scripts_own_rhythm():
    assert "One short sentence per beat" not in story.EXPAND_PROMPT
    assert "own voice and rhythm" in story.EXPAND_PROMPT


def test_the_longest_line_still_fits_one_picture():
    """3-14 words at the research pace (about 185 words a minute) is 1-4.5 s: under the quality gate's 7 s shot."""
    from engine import quality
    assert 14 / 185 * 60 < quality.SHOT_MAX_S
