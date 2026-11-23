"""24 Nov: the strong writer still opened the Haldighati human-story draft with a question ("चेतक ने युद्ध में हाथी की
सूंड क्यों पहनी?") although the template asks for a cold open. Human-story channels get one targeted rewrite of line 1;
it is kept only when it is no question, at most 12 words, and keeps the search words the line had."""
from engine import human_story

HUMAN = {"id": "itihaas_ke_raaz", "language": "hi", "style": {"telling": "human_story"}}
PLAIN = {"id": "deep_blue_files", "language": "en", "style": {}}


class Brain:
    def __init__(self, answer):
        self.answer, self.prompts = answer, []

    def ask_json(self, task, prompt, system="", temperature=0.5):
        self.prompts.append((task, prompt))
        return self.answer, None


def _script(first, **extra):
    return {"beats": [{"speaker": "narrator", "narration": first}, {"speaker": "narrator", "narration": "1576 था।"}],
            "search_phrase": "Chetak Haldighati", "hook_text": first, "_fact_check": {"ok": True}, **extra}


def test_a_question_becomes_a_cold_open():
    b = Brain({"line": "धूल में चेतक दौड़ रहा है, पीछे मुगल सेना।", "speaker": "narrator"})
    out = human_story.cold_open(b, _script("चेतक ने युद्ध में हाथी की सूंड क्यों पहनी?"), HUMAN, log=lambda *a: None)
    assert out["beats"][0]["narration"] == "धूल में चेतक दौड़ रहा है, पीछे मुगल सेना।"
    assert out["hook_text"] == out["beats"][0]["narration"] and out["_fact_check"] == {}
    assert b.prompts[0][0] == "writer" and "1576 था।" in b.prompts[0][1]


def test_the_person_may_speak_it_in_their_own_voice():
    b = Brain({"line": "Chetak, carry me out of Haldighati!", "speaker": "Maharana Pratap"})
    s = _script("Why did Chetak wear a trunk at Haldighati?", cast_voices={"Maharana Pratap": "man"})
    out = human_story.cold_open(b, s, HUMAN, log=lambda *a: None)
    assert out["beats"][0]["speaker"] == "Maharana Pratap"
    b = Brain({"line": "Chetak, carry me out of Haldighati!", "speaker": "A soldier"})   # no cast voice
    out = human_story.cold_open(b, s, HUMAN, log=lambda *a: None)
    assert out["beats"][0]["speaker"] == "narrator"


def test_a_rewrite_that_does_not_fit_is_not_used():
    s = _script("Why did Chetak wear a trunk at Haldighati?")
    for bad in ({"line": "Was it a mask?"}, {"line": ""}, {"line": "A very long line " * 4},
                {"line": "The horse runs through the dust."}):            # lost the search words
        assert human_story.cold_open(Brain(bad), s, HUMAN, log=lambda *a: None) is s, bad


def test_only_human_story_questions_are_touched():
    b = Brain({"line": "x"})
    q = _script("Why did Chetak wear a trunk?")
    assert human_story.cold_open(b, q, PLAIN) is q                          # fact Shorts may open with a question
    cold = _script("Chetak runs through the dust.")
    assert human_story.cold_open(b, cold, HUMAN) is cold and not b.prompts
