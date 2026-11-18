"""Documentary graphics, counters and Hindi shaping (fast, no internet)."""
import numpy as np
import pytest

from engine.media.graphics import STYLES, count_frames, text_graphic
from engine.media.shaping import needs_shaping, text_rgba, text_width
from engine.media.fonts import font_file


def test_numbers_count_up_but_dates_and_years_stay_fixed():
    assert count_frames("55 MINERS", 3)[-1] == "55 MINERS" and count_frames("55 MINERS", 3)[0] != "55 MINERS"
    assert count_frames("$1,000,000,000", 2)[-1] == "$1,000,000,000"
    assert set(count_frames("DEC 4, 1872", 3)) == {"DEC 4, 1872"}
    assert set(count_frames("In 1983", 3)) == {"In 1983"}


@pytest.mark.parametrize("style", list(STYLES))
def test_every_style_renders_a_full_frame(tmp_path, style):
    ch = {"id": "x", "language": "hi" if style in ("parchment", "poster") else "en", "style": {"graphics": style}}
    p = text_graphic(ch, "३ पुत्र" if ch["language"] == "hi" else "17/5", "sub line", (540, 960), tmp_path / "g.png")
    import cv2
    img = cv2.imread(str(p))
    assert img.shape == (960, 540, 3) and img.std() > 5


def test_hindi_is_shaped_not_broken():
    path = str(font_file("Mukta ExtraBold"))
    assert needs_shaping("पुत्र") and not needs_shaping("hello")
    joined = text_width("पुत्र", path, 80)
    apart = sum(text_width(ch, path, 80) for ch in "पुत्र")      # the conjunct must be narrower than loose letters
    assert 0 < joined < apart
    img = text_rgba("पुत्र", path, 80, stroke=4)
    assert img.shape[2] == 4 and img[..., 3].max() == 255


def test_graphic_shots_never_crop_the_card(tmp_path):
    import cv2
    from engine.media import compose
    img = np.zeros((960, 540, 3), np.uint8)
    img[:, :8] = 255                                            # a white border at the very left edge
    path = tmp_path / "card.png"
    cv2.imwrite(str(path), img)
    look = compose.Look(size=(540, 960), grain=0.0, vignette=0.0)
    shot = compose.Shot(0.0, 2.0, "image", path, "push_in", "graphic", "cut")
    r = compose.ShotRenderer(shot, look, compose.Grader(look))
    first = r.frame(0.0)
    assert first.shape == (960, 540, 3) and first[:, :4].mean() > 120   # the edge is still visible at the start
