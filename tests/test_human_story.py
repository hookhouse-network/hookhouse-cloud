"""Owner 23 Nov: human stories follow the template channel he named (one person, a cold open in their voice, a
literary narrator, a short acted dialogue, each speaker in their own voice). A channel opts in with style.telling:
human_story; the others keep their telling."""
from engine import human_story, story

ON = {"id": "cosmos_unboxed", "name": "Cosmos Unboxed", "language": "en", "style": {"telling": "human_story"}}
OFF = {"id": "brain_snack", "name": "Brain Snack", "language": "en", "style": {}}


def _script():
    return {"cast_voices": {"Jim Lovell": "older man", "Marilyn": "woman"}, "beats": [
        {"narration": "Houston, we've had a problem.", "speaker": "Jim Lovell"},
        {"narration": "The cabin lights flicker over his hands.", "speaker": "narrator"},
        {"narration": "Are they coming home?", "speaker": "Marilyn"},
        {"narration": "Nobody in that room had an answer.", "speaker": ""}]}


def test_only_opted_in_channels_get_the_telling():
    assert "STORY TELLING" in human_story.rules_for(ON) and human_story.rules_for(OFF) == ""
    assert "{{" not in human_story.RULES                    # passed as a value, never formatted


def test_every_speaker_gets_a_voice_of_their_own_never_the_narrators():
    v = human_story.voices(_script(), "en", narrator="bm_george")
    assert set(v) == {"Jim Lovell", "Marilyn"}
    assert v["Marilyn"] in human_story.KOKORO["en"]["woman"]
    assert v["Jim Lovell"] != "bm_george" and len(set(v.values())) == 2
    g = human_story.voices(_script(), "hi", narrator="hi-IN-Chirp3-HD-Charon", engine="google")
    assert g["Marilyn"].startswith("hi-IN-Chirp3-HD-") and "hi-IN-Chirp3-HD-Charon" not in g.values()


def test_narrator_lines_are_not_speakers():
    assert human_story.speaker({"speaker": "Narrator"}) == "" and human_story.speaker({}) == ""
    assert human_story.acted(_script()) and not human_story.acted({"beats": [{"narration": "x"}]})


def test_the_description_says_spoken_lines_are_voiced_and_some_dramatized():
    d = story.build_description({"id": "cosmos_unboxed", "name": "Cosmos Unboxed", "hashtags": []},
                                dict(_script(), summary="Apollo 13."), [])
    assert "some are dramatized" in d
    d2 = story.build_description({"id": "cosmos_unboxed", "name": "Cosmos Unboxed", "hashtags": []},
                                 {"summary": "Apollo 13.", "beats": [{"narration": "x"}]}, [])
    assert "dramatized" not in d2


def test_the_writer_gets_the_telling_for_an_opted_in_channel(monkeypatch):
    seen = []

    class Res:
        provider = "test"

    class Brain:
        def ask_json(self, task, prompt, system="", temperature=0.4):
            seen.append(prompt)
            return {"title": "Apollo 13", "beats": [{"narration": "Houston, we've had a problem.",
                                                     "speaker": "Jim Lovell"}]}, Res()
    ch = dict(ON, niche="space history", market="US", content_rules={}, voice={"id": "bf_emma"})
    s = story.write_script(Brain(), ch, "Apollo 13")
    assert "STORY TELLING" in seen[0] and s["beats"][0]["speaker"] == "Jim Lovell"
    story.write_script(Brain(), dict(ch, style={}), "Apollo 13")
    assert "STORY TELLING" not in seen[1]
