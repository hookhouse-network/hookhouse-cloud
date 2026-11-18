"""Thumbnail v4 text rules (no images needed)."""
import numpy as np
from PIL import Image

from engine.media.thumbs_v4 import _text_spot, cover_lines, hook_lines


def test_us_thumbnail_text_is_three_words_and_15_characters_at_most():
    # research (thumbnails_titles.md §8): US 0-3 words, <= 15 characters; never end on an article
    assert hook_lines("DRILL ATE | A LAKE", "en") == ["DRILL ATE"]          # 4 words -> the first line only
    assert hook_lines("NOT THE | FINAL", "en") == ["NOT THE", "FINAL"]      # 3 words, 11 characters: kept whole
    assert hook_lines("LOST 10-3 | 13 DAYS LATER...", "en") == ["LOST 10-3"]
    for h in ("A drill swallowed this lake", "Why a penny costs almost four cents to make", "COURT ORDERED DESTROYED"):
        lines = hook_lines(h, "en")
        words = " ".join(lines).split()
        assert len(words) <= 3 and len("".join(words)) <= 15
        assert words[-1].lower() not in {"a", "the", "almost", "this"}
    assert len(" ".join(hook_lines("COURT ORDERED DESTROYED", "en", max_words=2)).split()) <= 2   # movie: <= 2


def test_hindi_thumbnail_text_allows_up_to_five_words():
    lines = hook_lines("कर्ण का आख़िरी | रहस्य", "hi")
    assert " ".join(lines).split() == ["कर्ण", "का", "आख़िरी", "रहस्य"]


def test_covers_use_short_balanced_lines_of_at_most_six_words():
    lines = cover_lines("This Tiny Bird Flies Pole to Pole", "en")      # cover C1: 2-6 words
    assert " ".join(lines) == "This Tiny Bird Flies Pole to" or len(" ".join(lines).split()) <= 6
    assert len(lines) == 3
    assert cover_lines("Nobody Found Her", "en") == ["Nobody Found", "Her"] or len(cover_lines("Nobody Found Her", "en")) <= 2


def test_text_goes_where_the_subject_is_not_and_never_bottom_right():
    img = Image.new("RGB", (1280, 720), (90, 90, 90))
    m = np.zeros((720, 1280), np.float32)
    m[:, 700:] = 1.0                                          # subject fills the right side
    assert _text_spot(img, m) in ("left", "bottom")
    m2 = np.zeros((720, 1280), np.float32)
    m2[:, :600] = 1.0
    assert _text_spot(img, m2) == "right"
