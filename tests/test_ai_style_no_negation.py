"""24 Nov, Cricket Ke Kisse: the channel's picture style ended with "generic cricketers with no real player's likeness",
added to every scene prompt. An image model cannot read "no" (the PC's model runs at guidance 1.0, so a negative
prompt does nothing either): it drew two cricketers' faces for "two captain's armbands lying on a bench", and 7 of 11
scenes became word cards under the sports likeness rule. A style never names the people or faces it forbids."""
import re

from engine import story
from engine.config import channels


def test_no_channel_style_names_the_people_it_forbids():
    for ch in channels():
        st = str((ch.get("style") or {}).get("ai_style") or "").lower()
        assert "likeness" not in st, ch["id"]
        assert not re.search(r"\bno (?:real )?(?:actors?|players?|athletes?|people|persons?|faces?)\b", st), ch["id"]


def test_the_faceless_redraw_never_names_a_face():
    assert "face" not in story.NO_FACE_SUFFIX.lower() and "silhouette" in story.NO_FACE_SUFFIX
