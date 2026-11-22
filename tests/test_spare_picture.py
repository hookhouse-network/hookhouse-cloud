"""22 Nov: an AI picture drawn for a beat that the eyes check scores under its bar (but 5+ and without letters) is kept
as the beat's last resort instead of a text card. 21 Nov (Unsolved, Dyatlov Pass): 8 of 9 FLUX pictures were thrown
away for 'modern gear' or a stray logo, six beats became text graphics, and the quality gate held the video for
'6/10 shots are word cards'. Library photos the check turns down stay out (a wrong photo is worse than a card)."""
import pytest

from engine import story, storyboard
from engine.media import visuals


@pytest.fixture
def finder(monkeypatch, tmp_path):
    pic = tmp_path / "cf_x.jpg"
    pic.write_bytes(b"x" * 20_000)
    verdicts = []
    monkeypatch.setattr(visuals, "ai_image", lambda prompt, style="": visuals.Visual(
        pic, "ai_flux_cloudflare", "AI-generated image", "Own (FLUX.1-schnell, Apache 2.0)"))
    monkeypatch.setattr(story, "_photo_candidates", lambda q: [])
    monkeypatch.setattr(story, "_cached", lambda kind, query, fn: [])
    monkeypatch.setattr(storyboard, "scene", lambda *a, **k: None)
    monkeypatch.setattr(storyboard, "photo_verdict", lambda vis, beat, era: verdicts.pop(0))
    beat = {"visual": "ai", "_prompt": "a tent in deep snow at night", "see": "a tent in deep snow at night",
            "narration": "Their tent was found half buried in snow.", "query": "tent snow night"}

    def find(verdict):
        verdicts.append(verdict)
        return story.find_beat_visual(dict(beat), 3.0, ["#000000", "#222222"], tmp_path, 1, "en", "", set(),
                                      (1080, 1920), log=lambda *a: None)
    return find


def test_a_turned_down_ai_picture_beats_a_text_card(finder):
    got = finder({"score": 6, "text": False, "wrong": "modern tent for 1959", "ok": False})
    assert got["source"] == "ai_flux_cloudflare" and got["kind"] == "image" and got["match"] == 0.6


def test_letters_or_a_low_score_still_go_to_the_fallback(finder):
    assert finder({"score": 8, "text": True, "wrong": "", "ok": False})["kind"] == "reuse"    # garbled writing
    assert finder({"score": 4, "text": False, "wrong": "wrong place", "ok": False})["kind"] == "reuse"


def test_a_passing_picture_is_used_as_before(finder):
    got = finder({"score": 8, "text": False, "wrong": "", "ok": True})
    assert got["source"] == "ai_flux_cloudflare" and "match" not in got


def test_only_ai_pictures_are_kept_as_spares():
    v = {"score": 6, "text": False, "ok": False}
    assert story._spare_ok({"source": "ai_scene_cloudflare", "kind": "image"}, v)
    assert not story._spare_ok({"source": "pixabay", "kind": "video"}, v)      # a wrong library clip stays out
    assert not story._spare_ok({"source": "wikimedia", "kind": "image"}, v)
    assert storyboard.check_photo({"path": None}, {"see": "x"}, "") is True    # nothing to check: as before
