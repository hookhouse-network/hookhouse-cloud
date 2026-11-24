"""24 Nov, the PC's Money Cheat Codes video: its topic came from this week's news ("Nvidia stock plunges 14%, wraps up
longest weekly losing streak since 2008 financial crisis"), but the writer only got the topic and the angle, so the
script was about the January 2025 drop; and the hook of the topic it replaced stayed on the item ('why now: Trending
search "Taylor Sheridan"'). Also: grounded writing (22 Nov) searched Wikipedia with the whole brief (angle, feeling,
why-now) and found no article for any of the PC's 100 scripts; on 20 real plan topics the new search grounds 11, each
on the right article."""
import pytest

from engine import story, weekly

BRIEF = ("Mariner 9 becomes the first spacecraft to orbit another planet (14 November 1971) (angle: it arrived in a "
         "planet-wide dust storm and waited)\nThe feeling this video must deliver: awe\nWhy now: anniversary")


# ---------------------------------------------------------------- grounding: what is searched, what counts
def test_the_core_topic_leaves_out_the_angle_feeling_and_why_now():
    assert story.core_topic(BRIEF) == ("Mariner 9 becomes the first spacecraft to orbit another planet "
                                       "(14 November 1971)")
    assert story.core_topic("Super Bowl LI") == "Super Bowl LI" and story.core_topic("") == ""


def test_the_lead_phrase_is_searched_first_then_the_title_then_its_first_words():
    assert story.ref_queries("Challenger Deep: What James Cameron Saw When He Touched Bottom (angle: x)") == [
        "Challenger Deep", "Challenger Deep What James Cameron Saw When He Touched Bottom"]
    assert story.ref_queries("The whaleship Essex, rammed and sunk by a sperm whale")[0] == "The whaleship Essex"
    q = story.ref_queries("How the Komodo dragon swallows a whole deer in one piece")
    assert q[-2:] == ["Komodo dragon swallows", "Komodo dragon"]
    assert story.ref_queries("Why Nvidia's Stock Crashed 14% Despite Record Earnings")[-1] == "Nvidia Stock"
    assert story.ref_queries(BRIEF)[-1] == "Mariner 9"
    assert all("feeling" not in x and "angle" not in x and "1971" not in x for x in story.ref_queries(BRIEF))
    assert story.ref_queries("🔥🔥 why? how!") == []


@pytest.mark.parametrize("title, topic, ok", [
    ("Pete Rose", "The 8-Day Tragedy That Locked Pete Rose Out of Baseball Forever", True),
    ("Essex (whaleship)", "The whaleship Essex, rammed and sunk by a sperm whale on 20 November 1820", True),
    ("Kobe Bryant's 81-point game", "Kobe Bryant's 81-Point Game against the Toronto Raptors", True),
    ("Skylab 4", "The Skylab 4 'mutiny': did astronauts really go on strike in space?", True),
    ("Super Bowl LI", "Super Bowl LI: The 28-3 Patriots Comeback", True),
    ("Storm", BRIEF, False),                                       # a word of the topic, not its subject
    ("Mariner 10", BRIEF, False),                                  # another mission
    ("Super Bowl LII", "Super Bowl LI: The 28-3 Patriots Comeback", False),
    ("Republican Party (United States)", "Nvidia's Historic 2008-Style Losing Streak", False),
    ("Robert Griffin III", "The Fall of Daniel Jones: From #2 Overall Pick to Being Waived", False),
])
def test_a_hit_must_be_about_the_topic(title, topic, ok):
    assert story.ref_about(title, topic) is ok


def test_the_first_hit_about_the_topic_wins_and_works_and_lists_are_skipped(monkeypatch):
    searched = []
    hits = ["Moby-Dick", "Penny (disambiguation)", "Essex (whaleship)"]
    texts = {"Moby-Dick": "[Moby-Dick] Moby-Dick is an 1851 novel by Herman Melville about a whale.",
             "Essex (whaleship)": "[Essex (whaleship)] Essex was an American whaler from Nantucket, sunk in 1820 by a "
                                  "sperm whale."}
    monkeypatch.setattr(story, "_wiki_hits", lambda q, n=3, lang="en": searched.append(q) or hits)
    monkeypatch.setattr(story, "wikipedia_summaries", lambda titles, chars=9000, focus="", **k: texts[titles[0]])
    ref = story.reference_notes("The whaleship Essex, rammed by a sperm whale: the true story behind Moby-Dick "
                                "(angle: x)\nThe feeling this video must deliver: awe")
    assert ref["titles"] == ["Essex (whaleship)"] and "Nantucket" in ref["rule"]
    assert searched == ["The whaleship Essex"]                     # the novel was read and skipped, not searched again


def test_a_disambiguation_page_is_no_reference(monkeypatch):
    monkeypatch.setattr(story, "_wiki_hits", lambda q, n=3, lang="en": ["Kryptos"])
    monkeypatch.setattr(story, "wikipedia_summaries",
                        lambda titles, chars=9000, focus="", **k: "[Kryptos] Kryptos may refer to: a sculpture; a font")
    assert story.reference_notes("Kryptos, the unsolved code sculpture at CIA headquarters")["titles"] == []


def test_at_most_three_articles_are_read(monkeypatch):
    reads = []
    monkeypatch.setattr(story, "_wiki_hits", lambda q, n=3, lang="en": [f"Kryptos {len(reads)} {q[:3]}"])
    monkeypatch.setattr(story, "wikipedia_summaries",
                        lambda titles, chars=9000, focus="", **k: reads.append(1) or "[K] a 2001 film about Kryptos")
    monkeypatch.setattr(story, "ref_about", lambda title, topic: True)
    assert story.reference_notes("Kryptos, the unsolved code sculpture at CIA headquarters")["titles"] == []
    assert len(reads) <= 3


# ---------------------------------------------------------------- the news headline reaches the writer
NEWS = "Nvidia stock plunges 14%, wraps up longest weekly losing streak since 2008 financial crisis"
ITEM = {"id": "1124_0500_money_cheat_codes_short", "channel": "money_cheat_codes", "kind": "short",
        "status": "planned", "topic": "Nvidia's Historic 2008-Style Losing Streak", "angle": "the 2008 comparison",
        "feeling": "emotional", "news": NEWS,
        "now_hook": "Trending search “Taylor Sheridan” (1 000+ US searches today)"}


def test_why_now_is_the_headline_or_the_switch_reason_never_the_old_hook():
    assert weekly.why_now(ITEM) == NEWS
    assert weekly.why_now({"fresh_at": 1.0, "why": "Artemis II crew named today", "now_hook": "old"}) == \
        "Artemis II crew named today"
    assert weekly.why_now({"now_hook": "Thanksgiving next week"}) == "Thanksgiving next week"
    assert weekly.why_now({"now_hook": "evergreen"}) == "" and weekly.why_now({}) == ""


def test_the_writers_brief_leads_with_the_headline(monkeypatch):
    made = {}
    monkeypatch.setattr("engine.config.channel", lambda cid: {"id": cid, "name": "Money Cheat Codes", "type": "story"})
    monkeypatch.setattr(weekly, "clip_slot", lambda ch, it: False)

    def fake_make(brain, ch, topic, fmt, memory, log, **k):
        made["topic"] = topic
        raise StopIteration
    monkeypatch.setattr(story, "make", fake_make)
    item = dict(ITEM, id="test_news_brief_no_checkpoint")              # no stored checkpoint can stand in
    with pytest.raises(StopIteration):
        weekly.make_item({"items": [item]}, item, brain=object(), log=lambda *a: None)
    brief = made["topic"]
    assert story.news_in_brief(brief) == NEWS
    assert "Taylor Sheridan" not in brief and "Open with what this headline says just happened" in brief
    assert story.core_topic(brief) == "Nvidia's Historic 2008-Style Losing Streak"


def test_a_plan_hook_still_reaches_the_writer_without_news():
    assert weekly.now_line({"now_hook": "Thanksgiving next week"}) == "\nWhy now: Thanksgiving next week"
    assert weekly.now_line({"now_hook": "evergreen"}) == "" and story.news_in_brief("no news here") == ""


class _Checker:
    def __init__(self):
        self.prompts = []

    def ask_json(self, task, prompt, system="", temperature=0.0):
        self.prompts.append(prompt)
        return {"contradicted": [], "unsupported": []}, type("R", (), {"provider": "groq"})()


def test_the_fact_check_reads_the_headline_as_a_source(monkeypatch):
    monkeypatch.setattr(story, "wikipedia_summaries", lambda titles, chars=9000, focus="", **k: "[Nvidia] Nvidia ...")
    b = _Checker()
    v = story.fact_check(b, {"sources": ["Nvidia"], "claims": ["Nvidia fell 14% this week"]}, news=NEWS)
    assert v["ok"] and NEWS in b.prompts[0] and "newer than the articles" in b.prompts[0]
    story.fact_check(b, {"sources": ["Nvidia"], "claims": ["x"]})
    assert "news headline" not in b.prompts[1]


def test_the_script_judge_measures_demand_for_the_plan_topic_like_the_video_gate(monkeypatch):
    """The brief's first 100 characters (topic + angle) were searched on YouTube: other evidence than the video gate
    got for the same video, and one more 100-unit search per script."""
    from engine import potential_gate
    asked = []
    monkeypatch.setattr("engine.topic_proof.proof", lambda topic, ch: asked.append(topic) or {})
    monkeypatch.setattr("engine.topic_proof.evidence_text", lambda p: "demand: test")
    monkeypatch.setattr(potential_gate, "judge", lambda it, ch, meta, brain, evidence="": {
        "scores": {"hook": 9, "human_feel": 8}, "fixes": [], "summary": "", "criteria": ["hook", "human_feel"]})
    brief = (f"{ITEM['topic']} (angle: {ITEM['angle']})\nThe feeling this video must deliver: shocking"
             f"\n{story.NEWS_MARK}\"{NEWS}\". Open with it.")
    potential_gate.judge_script({"title": "t", "beats": [{"narration": "a"}]}, {"id": "money_cheat_codes"}, brief,
                                brain=object())
    assert asked == [ITEM["topic"]]


# ---------------------------------------------------------------- a replaced topic takes its own hook along
def test_a_make_time_switch_drops_the_old_topics_headline(monkeypatch):
    monkeypatch.setattr("engine.trends.trend_hints", lambda brain, log=print: {})
    monkeypatch.setattr(weekly, "pick_topics", lambda *a, **k: [{"topic": "A new topic", "feeling": "awe",
                                                                  "now_hook": "a new hook"}])
    item = dict(ITEM, fresh_at=1.0)
    weekly._refresh_topic({"items": [item]}, item, {"id": "money_cheat_codes", "name": "M"}, brain=object(),
                          log=lambda *a: None)
    assert item["topic"] == "A new topic" and "news" not in item and "fresh_at" not in item
    assert weekly.why_now(item) == "a new hook"


class _Picker:
    def __init__(self, answer):
        self.answer, self.prompts = answer, []

    def ask_json(self, task, prompt, temperature=0.4):
        self.prompts.append(prompt)
        return dict(self.answer), None


def test_a_news_pick_stores_its_headline_as_the_hook_and_its_own_feeling(monkeypatch):
    from engine import autopilot, news_topics
    updates = []
    monkeypatch.setattr(news_topics, "FEEDS", {"money_cheat_codes": [("q", "en-US", "US", "en")]})
    monkeypatch.setattr(news_topics, "due_items", lambda cid, now=None: [("2026-11-23", dict(ITEM, news=None))])
    monkeypatch.setattr(news_topics, "headlines", lambda cid, session=None: [{"title": NEWS, "source": "CNBC"}])
    monkeypatch.setattr("engine.config.channel", lambda cid: {"id": cid, "name": "Money Cheat Codes", "market": "US"})
    monkeypatch.setattr(weekly, "past_topics", lambda cid, limit=25: [])
    monkeypatch.setattr(autopilot, "update_item", lambda s, iid, **f: updates.append(f) or {})
    b = _Picker({"topic": "Nvidia's worst week since 2008", "angle": "a", "why": "w", "feeling": "Shocking",
                 "headline": NEWS})
    assert news_topics.refresh(brain=b, log=lambda *a: None) == 1
    assert "shocking|" in b.prompts[0] or "|shocking" in b.prompts[0]
    f = updates[0]
    assert f["news"] == NEWS and f["now_hook"] == f"in the news: {NEWS}" and f["feeling"] == "shocking"
    b2 = _Picker({"topic": "T", "headline": NEWS, "feeling": "sad-ish"})
    news_topics.refresh(brain=b2, log=lambda *a: None)
    assert updates[1]["feeling"] is None                          # never the replaced topic's feeling


def test_a_trend_switch_stores_its_reason_as_the_hook(monkeypatch):
    from datetime import datetime, timedelta, timezone

    from engine import autopilot, fresh_topics
    now = datetime(2026, 11, 24, 10, 0, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    item = dict(ITEM, news=None, _when=now + timedelta(hours=10))
    updates = []
    monkeypatch.setattr(autopilot, "items", lambda back=0, ahead=3: [("2026-11-23", item)])
    monkeypatch.setattr(autopilot, "_when", lambda it: it["_when"])
    monkeypatch.setattr(autopilot, "update_item", lambda s, iid, **f: updates.append(f) or {})
    monkeypatch.setattr("engine.config.channel", lambda cid: {"id": cid, "name": "Money Cheat Codes", "niche": "money"})
    b = _Picker({"decision": "switch", "topic": "Black Friday's real math", "angle": "a",
                 "why": "Black Friday is Friday", "feeling": "relatable"})
    assert fresh_topics.freshen_due(b, hints={"money_cheat_codes": ["Black Friday"]}, now=now) == 1
    f = updates[0]
    assert f["now_hook"] == "Black Friday is Friday" and f["feeling"] == "relatable"
