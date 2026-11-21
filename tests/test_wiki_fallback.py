"""21 Nov: a Hindi script named 'Dwarka (mythology)' (no exact Wikipedia title) -> 'No sources found' -> the video was
held for 'fact-check missing'. A title that doesn't exist is resolved with Wikipedia's search."""
from engine import story


class R:
    def __init__(self, data):
        self.data = data

    def json(self):
        return self.data


def test_missing_title_is_resolved_with_wikipedia_search(monkeypatch):
    calls = []

    def fake_get(url, timeout=30, params=None):
        calls.append(dict(params))
        if params.get("list") == "search":
            return R({"query": {"search": [{"title": "Dwarka"}]}})
        if params.get("titles") == "Dwarka":
            return R({"query": {"pages": {"1": {"extract": "Dwarka is an ancient city. S. R. Rao found walls."}}}})
        return R({"query": {"pages": {"-1": {"missing": ""}}}})
    monkeypatch.setattr(story.visuals, "_get", fake_get)
    txt = story.wikipedia_summaries(["Dwarka (mythology)"], focus="Rao walls")
    assert txt.startswith("[Dwarka]") and "Rao" in txt
    assert any(c.get("list") == "search" for c in calls)
