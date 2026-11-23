"""24 Nov: legends told as legends (engine/legends.py). R&D 23 Nov: the strong writer's Haldighati draft told Chetak's
elephant-trunk mask and his three-legged leap as history; the fact-check passes both because the sources mention them
(as legends). The measurement on real drafts: marking every flagged line put "कहते हैं," in front of 10 of 16 lines, so a
whole folk tale is framed ONCE and each legend episode of a true story gets ONE marker at its first narrator line."""
from engine import legends

HALDI = ["चेतक ने युद्ध में हाथी की सूंड क्यों पहनी?",
         "1576 में हल्दीघाटी का युद्ध भीषण था।",
         "चेतक के मुंह पर हाथी का मुखौटा बांधा गया।",
         "ताकि दुश्मन हाथी उसे बच्चा समझें।",
         "महाराणा जाइए, मेवाड़ को आपकी जरूरत है!",
         "रास्ते में 21 फीट चौड़ा नाला आया।",
         "तीन टांगों से चेतक ने 21 फीट छलांग मारी!"]


REFS = ("Chetak was the horse of Maharana Pratap. According to legend, Chetak wore an elephant trunk mask to fool the "
        "war elephants at Haldighati. Legend also says he could leap a stream on three legs. Akbar and Birbal folk "
        "tales are popular across India.")


class Brain:
    def __init__(self, answer):
        self.answer, self.prompts = answer, []

    def ask_json(self, task, prompt, system="", temperature=0.0):
        self.prompts.append((task, prompt))
        return self.answer, None


def _script(lines, speakers=None):
    beats = [{"narration": x} for x in lines]
    for i, sp in (speakers or {}).items():
        beats[i]["speaker"] = sp
    return {"beats": beats, "claims": ["c"], "sources": ["Chetak"], "_fact_check": {"ok": True}}


def _said(out):
    return [b["narration"] for b in out["beats"]]


def test_legend_markers_in_both_languages():
    assert legends.marked("Legend says the horse leapt the stream.")
    assert legends.marked("The story goes that he never slept.")
    assert legends.marked("कहते हैं, चेतक ने हाथी का मुखौटा पहना था।", "hi")
    assert legends.marked("एक मशहूर किस्सा है, अकबर ने बीरबल से कहा।", "hi")
    assert not legends.marked("The horse leapt the stream.")
    assert not legends.marked("He was a legendary bowler.")          # 'legendary' = famous, not a legend marker
    assert not legends.marked("चेतक ने नाला लांघा।", "hi")


def test_each_legend_episode_gets_one_marker_at_its_first_line():
    b = Brain({"whole_story_is_legend": False, "episodes": [
        {"lines": [2, 3], "claim": "elephant trunk mask", "i": 2, "old": HALDI[2], "new": "कहते हैं, " + HALDI[2]},
        {"lines": [5, 6], "claim": "leap on three legs", "i": 5, "old": HALDI[5], "new": HALDI[5]}]})  # no marker
    out, report = legends.check(b, _script(HALDI, {4: "Jhala Man Singh"}), REFS, "hi", log=lambda *a: None)
    said = _said(out)
    assert said[2] == "कहते हैं, " + HALDI[2] and said[3] == HALDI[3]           # the episode's next line goes on
    assert said[5] == "कहते हैं, " + HALDI[5] and said[6] == HALDI[6]           # plain prefix where the edit held none
    assert sum(legends.marked(x, "hi") for x in said) == 2
    assert [r["action"] for r in report] == ["marked", "marked"] and out["_fact_check"] == {}
    assert b.prompts[0][0] == "checker" and "4: महाराणा जाइए" in b.prompts[0][1] and "[spoken by a character]" in b.prompts[0][1]


def test_a_whole_folk_tale_is_framed_once():
    tale = ["बीरबल, मुझे कल सुबह तक सांड का दूध चाहिए!", "अकबर को मज़े लेने की आदत थी।", "बीरबल घर पहुंचे।"]
    b = Brain({"whole_story_is_legend": True,
               "frame": {"i": 1, "old": "अकबर को", "new": "एक मशहूर किस्सा है, अकबर को"}, "episodes": []})
    out, report = legends.check(b, _script(tale, {0: "Akbar"}), REFS, "hi", log=lambda *a: None)
    assert _said(out) == [tale[0], "एक मशहूर किस्सा है, अकबर को मज़े लेने की आदत थी।", tale[2]]
    assert report[0]["action"] == "framed"


def test_a_bad_frame_falls_back_to_the_first_narrator_line():
    tale = ["Bring me bull's milk by morning!", "The emperor loved impossible orders.", "Birbal went home."]
    b = Brain({"whole_story_is_legend": True, "frame": {"i": 0, "old": "not in the line", "new": "x"}})
    out, _ = legends.check(b, _script(tale, {0: "Akbar"}), REFS, "en", log=lambda *a: None)
    assert _said(out) == [tale[0], "Legend says the emperor loved impossible orders.", tale[2]]


def test_more_than_three_episodes_means_the_story_is_framed_once():
    lines = [f"Line {i} of the tale." for i in range(8)]
    claims = {1: "bridge tower", 3: "tower river", 5: "river castle", 7: "castle bridge"}
    eps = [{"lines": [i], "claim": claims[i], "i": i, "old": lines[i], "new": "Legend says " + lines[i]}
           for i in (1, 3, 5, 7)]
    refs = "Legend says many things happened at the bridge, the tower, the river and the castle."
    out, report = legends.check(Brain({"whole_story_is_legend": False, "episodes": eps}), _script(lines), refs, "en",
                                log=lambda *a: None)
    assert sum(legends.marked(x) for x in _said(out)) == 1 and report[0]["action"] == "framed"


def test_a_spoken_first_line_moves_the_marker_to_the_next_narrator_line():
    lines = ["Run, my king!", "The horse leapt the stream.", "He fell on the far bank."]
    b = Brain({"episodes": [{"lines": [0, 1, 2], "claim": "the leap over the stream", "i": 0, "old": "Run",
                             "new": "Legend says run"}]})
    out, report = legends.check(b, _script(lines, {0: "Jhala"}), REFS, "en", log=lambda *a: None)
    assert _said(out) == ["Run, my king!", "Legend says the horse leapt the stream.", "He fell on the far bank."]
    assert report == [{"i": 1, "claim": "the leap over the stream", "action": "marked"}]


def test_a_question_never_carries_the_marker():
    lines = ["Why did Chetak wear an elephant trunk?", "His riders tied a trunk mask on him.", "It fooled the elephants."]
    b = Brain({"episodes": [{"lines": [0, 1, 2], "claim": "elephant trunk mask", "i": 0, "old": "Why",
                             "new": "Legend says why"}]})
    out, report = legends.check(b, _script(lines), REFS, "en", log=lambda *a: None)
    assert _said(out) == [lines[0], "Legend says his riders tied a trunk mask on him.", lines[2]]
    assert "[spoken by a character]" not in b.prompts[0][1]          # a question is not a character's line


def test_a_legend_already_told_as_one_is_left_alone():
    lines = ["Legend says Chetak wore an elephant mask.", "It fooled the war elephants."]
    b = Brain({"episodes": [{"lines": [0, 1], "claim": "elephant trunk mask", "i": 1, "old": lines[1],
                             "new": "They say " + lines[1]}]})
    out, report = legends.check(b, _script(lines), REFS, "en", log=lambda *a: None)
    assert _said(out) == lines and report[0]["action"] == "already"
    assert out["_fact_check"] == {"ok": True}                            # nothing changed: the old check stands


def test_the_sources_must_call_it_a_legend():
    assert legends.sourced("elephant trunk mask", REFS)
    assert legends.sourced("leap on three legs", REFS)
    cooper = ("Cooper jumped from the aircraft over southwestern Washington. The FBI concluded he probably did not "
              "survive. The case became part of American folklore decades later, inspiring songs.")
    assert not legends.sourced("Cooper jumped from the plane", cooper)       # folklore sits too far from the claim
    assert not legends.sourced("mask", REFS)                                # one word is not enough to place it


def test_an_episode_the_sources_do_not_call_a_legend_stays_as_written():
    lines = ["The FBI search found nothing.", "That was all the Navy allowed him to search."]
    b = Brain({"episodes": [{"lines": [1], "claim": "Navy restricted the search to twelve days", "i": 1,
                             "old": lines[1], "new": "Legend has it that " + lines[1]}]})
    refs = "The Navy allowed Ballard twelve days to search for Titanic after the submarine survey."
    out, report = legends.check(b, _script(lines), refs, "en", log=lambda *a: None)
    assert _said(out) == lines and report == []


def test_nothing_found_changes_nothing():
    s = _script(["Rana raised his spear."])
    out, report = legends.check(Brain({"whole_story_is_legend": False, "episodes": []}), s, "refs", "en")
    assert out is s and report == []


def test_who_gets_the_check(monkeypatch):
    plain = {"id": "deep_blue_files", "style": {}}
    human = {"id": "itihaas_ke_raaz", "style": {"telling": "human_story"}}
    monkeypatch.setattr(legends, "cfg", lambda: {"enabled": True, "channels": []})
    assert legends.applies(human) and not legends.applies(plain)
    monkeypatch.setattr(legends, "cfg", lambda: {"enabled": True, "channels": ["deep_blue_files"]})
    assert legends.applies(plain)
    monkeypatch.setattr(legends, "cfg", lambda: {"enabled": True, "channels": "all"})
    assert legends.applies(plain)
    monkeypatch.setattr(legends, "cfg", lambda: {"enabled": False, "channels": "all"})
    assert not legends.applies(human)


def test_the_pipeline_step_reads_the_scripts_own_sources(monkeypatch):
    import engine.story as story
    asked = []
    monkeypatch.setattr(story, "wikipedia_summaries", lambda titles, **k: asked.append(titles) or REFS)
    human = {"id": "itihaas_ke_raaz", "language": "hi", "style": {"telling": "human_story"}}
    b = Brain({"episodes": [{"lines": [2], "claim": "elephant trunk mask", "i": 2, "old": HALDI[2],
                             "new": "कहते हैं, " + HALDI[2]}]})
    out = legends.from_sources(b, _script(HALDI), human, log=lambda *a: None)
    assert asked == [["Chetak"]] and _said(out)[2].startswith("कहते हैं")
    plain = {"id": "deep_blue_files", "language": "en", "style": {}}
    s = _script(HALDI)
    assert legends.from_sources(b, s, plain) is s                         # not switched on for this channel


def test_a_failing_check_never_stops_the_script(monkeypatch):
    import engine.story as story

    def boom(*a, **k):
        raise TimeoutError("wikipedia")
    monkeypatch.setattr(story, "wikipedia_summaries", boom)
    s = _script(HALDI)
    out = legends.from_sources(Brain({}), s, {"id": "x", "style": {"telling": "human_story"}}, log=lambda *a: None)
    assert out is s
