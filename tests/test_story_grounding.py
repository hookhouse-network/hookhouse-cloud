"""22 Nov: five fact-check failures in one day (the writer wrote from memory, named its sources afterwards). Grounded
writing: the topic's top Wikipedia article goes to the writer first, with the rule that every specific detail must
match it, and it leads the script's sources so the fact-check reads the same text."""
from engine import story


ARTICLE = ("The Sodder children disappearance refers to five children who vanished when their family home in "
           "Fayetteville, West Virginia, burned on Christmas Eve 1945. George and Jennie Sodder ...")


def test_relevant_article_becomes_the_writers_reference(monkeypatch):
    seen = []
    monkeypatch.setattr(story, "_wiki_search", lambda q, lang="en": seen.append(q) or "Sodder children disappearance")
    monkeypatch.setattr(story, "wikipedia_summaries", lambda titles, chars=9000, focus="", **k: ARTICLE)
    ref = story.reference_notes("The Sodder children: the Christmas Eve fire of 1945 🔥", chars=4000)
    assert ref["titles"] == ["Sodder children disappearance"]
    assert ref["rule"].startswith("REFERENCE NOTES") and "Fayetteville" in ref["rule"]
    assert "🔥" not in seen[0]                                           # the search query is plain words


def test_an_unrelated_hit_is_dropped(monkeypatch):
    monkeypatch.setattr(story, "_wiki_search", lambda q, lang="en": "Christmas tree")
    monkeypatch.setattr(story, "wikipedia_summaries",
                        lambda titles, chars=9000, focus="", **k: "A Christmas tree is a decorated evergreen.")
    assert story.reference_notes("The Sodder children: the Christmas Eve fire of 1945")["rule"] == ""


def test_an_article_about_someone_else_or_a_film_is_dropped(monkeypatch):
    """Real 22 Nov trials: Daniel Jones' topic found Robert Griffin III (both #2 picks); Dhoni's 2011 final found
    the 2016 biopic."""
    hits = {"daniel": "Robert Griffin III", "dhoni": "M.S. Dhoni: The Untold Story"}
    texts = {"Robert Griffin III": "Robert Lee Griffin III is an American former football quarterback, the second "
                                   "overall pick in 2012. He fell out of the league after being waived.",
             "M.S. Dhoni: The Untold Story": "M.S. Dhoni: The Untold Story is a 2016 Indian Hindi-language "
                                             "biographical sports drama film about the 2011 World Cup final."}
    monkeypatch.setattr(story, "_wiki_search", lambda q, lang="en": next(v for k, v in hits.items() if k in q.lower()))
    monkeypatch.setattr(story, "wikipedia_summaries", lambda titles, chars=9000, focus="", **k: texts[titles[0]])
    assert story.reference_notes("The Fall of Daniel Jones: From #2 Overall Pick to Being Waived")["rule"] == ""
    assert story.reference_notes("MS Dhoni's 2011 World Cup Final Promotion")["rule"] == ""
    assert story.reference_notes("MS Dhoni: The Untold Story film facts")["titles"] == ["M.S. Dhoni: The Untold Story"]


def test_no_words_no_search(monkeypatch):
    monkeypatch.setattr(story, "_wiki_search", lambda q, lang="en": (_ for _ in ()).throw(AssertionError("searched")))
    assert story.reference_notes("🔥🔥 why? how!")["titles"] == []


def test_reference_leads_the_sources():
    s = story.ground_sources({"sources": ["Fayetteville, West Virginia", "Sodder children disappearance"]},
                             ["Sodder children disappearance"])
    assert s["sources"] == ["Sodder children disappearance", "Fayetteville, West Virginia"]
    assert story.ground_sources({"sources": ["A"]}, [])["sources"] == ["A"]
