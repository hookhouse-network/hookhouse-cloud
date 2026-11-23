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


def test_only_opted_in_channels_get_the_story_structure():
    on = human_story.writer_template(story.WRITER_PROMPT, ON)
    assert "STEP 3 - THE STORY" in on and "STEP 3 - BEATS" not in on and "STEP 4 -" in on
    assert "MrBeast rule: beat 1" not in on and "LITERALLY" in on   # the fact-Short beats are gone, the truth rule in
    assert human_story._BEAT_KEYS in story.WRITER_PROMPT         # the output example the swap adds "speaker" to
    assert '"speaker": "narrator|<speaking person>"' in on and '"cast_voices"' in on and "legend says" in on
    assert human_story.writer_template(story.WRITER_PROMPT, OFF) == story.WRITER_PROMPT
    assert human_story.writer_template("no sections here", ON) == "no sections here"


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
    assert "STEP 3 - THE STORY" in seen[0] and s["beats"][0]["speaker"] == "Jim Lovell"
    assert '"cast_voices": {"<name>"' in seen[0]                # literal braces survive the formatting
    story.write_script(Brain(), dict(ch, style={}), "Apollo 13")
    assert "STEP 3 - BEATS" in seen[1] and "STEP 3 - THE STORY" not in seen[1]
