"""Pixabay photos as the fallback when free AI pictures run out (19 Nov)."""
from engine.media import visuals


class R:
    def __init__(self, data):
        self._d = data

    def json(self):
        return self._d


class S:
    def __init__(self, data):
        self.data, self.calls = data, []

    def get(self, url, params=None, **kw):
        self.calls.append(params)
        return R(self.data)


def test_pixabay_parses_and_skips_ai_art(monkeypatch):
    monkeypatch.setenv("PIXABAY_API_KEY", "k")
    s = S({"hits": [{"id": 1, "largeImageURL": "https://x/1.jpg", "tags": "octopus, marine", "user": "ann"},
                    {"id": 2, "largeImageURL": "https://x/2.jpg", "tags": "ai drawing, ai art", "user": "bot"},
                    {"id": 3, "webformatURL": "https://x/3.jpg", "tags": "ai-generated, robot", "user": "bot"}]})
    monkeypatch.setattr(visuals, "session", lambda: s)
    got = visuals.pixabay("deep sea creature", download=False)
    assert [g.meta["url"] for g in got] == ["https://x/1.jpg"]
    assert got[0].source == "pixabay" and "Pixabay" in got[0].credit and got[0].license == "Pixabay Content License"
    assert s.calls[0]["safesearch"] == "true" and s.calls[0]["image_type"] == "photo"


def test_pixabay_without_key_returns_nothing(monkeypatch):
    monkeypatch.delenv("PIXABAY_API_KEY", raising=False)
    assert visuals.pixabay("anything", download=False) == []


def test_scene_description_becomes_search_words():
    from engine.story import _see_query
    assert _see_query("Close-up of a cricket ball hitting the stumps under floodlights") == "cricket ball hitting stumps"
    assert _see_query("") == ""


def test_camera_directions_are_not_searched_for():
    """23 Nov: shot directions became the library search ("low-angle vintage server racks", "extreme digital
    countdown timer") and matched stock junk; the subject is searched instead."""
    from engine.story import _see_query
    assert _see_query("Low-angle shot of vintage server racks in mission control") == "vintage server racks mission"
    assert _see_query("High-angle close-up of glaring solar light grazing the hull") == "glaring solar light grazing"
    assert _see_query("Extreme macro anatomical cross-section animation showing tiny pale bones") == \
        "anatomical tiny pale bones"
    assert _see_query("Grainy black-and-white archive photograph of a diver") == "archive diver"
