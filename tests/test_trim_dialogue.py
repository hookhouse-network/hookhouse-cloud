"""23 Nov (Itihaas 1123 remake 2, the last): the length trim (160 -> 122 words) deleted the girl's answer and the
punchline of the Akbar-Birbal 'bull's milk' story and kept the loop line; quality scored 100 but the judge read the
broken story as stilted, AI-like Hindi (human_feel 4, clarity 4) and the video was held. Spoken lines now survive
every cut (shortened at most), and the writer is told which beats carry them."""
import pytest

from engine import story

BEATS = ["बीरबल, मुझे कल सुबह तक सांड का आधा लीटर दूध चाहिए!",
         "अकबर को मज़े लेने की आदत थी, पर ये मज़ाक कुछ ज़्यादा था।",
         "बीरबल घर पहुंचे, चेहरा उतरा हुआ था, क्योंकि सांड दूध नहीं देता!",
         "बेटी ने सुना, तो मुस्कुराई और बोली, 'पिताजी, आप सो जाओ'!",
         "आधी रात को वो लड़की अकबर की खिड़की के नीचे कपड़े धोने लगी।",
         "पछाड़-पछाड़ की आवाज़ से अकबर की नींद उड़ गई, वो गुस्से में बाहर आए।",
         "'ऐ लड़की! इतनी रात को शोर क्यों मचा रही है?'",
         "लड़की ने कहा, 'महाराज, मेरे पिताजी ने आज बच्चे को जन्म दिया है'!",
         "अकबर बोले— 'पागल है क्या? आदमी भी कहीं बच्चा पैदा करते हैं?'",
         "लड़की ने तुरंत कहा, 'हुज़ूर, अगर सांड दूध दे सकता है, तो आदमी बच्चा क्यों नहीं?'",
         "अकबर समझ गए कि ये बीरबल की चाल है, और बोलती बंद हो गई।",
         "अकबर की ऐसी डिमांड्स ही बीरबल को जीनियस बनाती थीं।",
         "तभी तो अकबर ने एक बार फिर वही पुरानी लाइन दोहराई..."]
CH = {"spec": {"short_words": "110-135 words (about 45-55 seconds)"}}

# the 05:37 cut, as the writer returned it: beats 7 (the answer) and 9 (the punchline) gone, 4 and 6 shortened
CUT_0537 = {"keep": [{"i": i, "narration": t} for i, t in [
    (0, BEATS[0]), (1, BEATS[1]), (2, BEATS[2]), (3, BEATS[3]), (4, "आधी रात लड़की खिड़की के नीचे कपड़े धोती।"),
    (5, BEATS[5]), (6, "ऐ लड़की! रात को शोर क्यों?"), (8, BEATS[8]), (10, BEATS[10]), (11, BEATS[11]), (12, BEATS[12])]]}


class Writer:
    def __init__(self, *answers):
        self.answers, self.prompts = list(answers), []

    def ask_json(self, role, prompt, temperature=0.3):
        self.prompts.append(prompt)
        return self.answers.pop(0), None


def _script():
    return {"title": "अकबर की अजीब शर्त: अकबर बीरबल कहानी", "beats": [{"narration": t, "query": f"q{i}"} for i, t in enumerate(BEATS)]}


def _words(script):
    return sum(len(b["narration"].split()) for b in script["beats"])


def test_the_real_itihaas_cut_keeps_the_answer_and_the_punchline():
    w = Writer(CUT_0537, CUT_0537)
    logs = []
    out = story.fit_length(w, CH, _script(), log=logs.append)
    said = [b["narration"] for b in out["beats"]]
    assert BEATS[7] in said and BEATS[9] in said                       # the girl's answer + the punchline
    assert said.index(BEATS[7]) < said.index(BEATS[8]) < said.index(BEATS[9])    # in story order
    assert any("spoken lines the story needs (beats 7, 9)" in m for m in logs)
    assert "every beat with spoken lines: 3, 6, 7, 8, 9" in w.prompts[0]
    assert "the line that resolves the setup" in w.prompts[0]


def test_spoken_lines_are_found_in_hindi_and_english():
    assert all(story._speech(BEATS[i]) for i in (3, 6, 7, 8, 9))
    assert not any(story._speech(BEATS[i]) for i in (0, 1, 2, 4, 5, 10, 11, 12))
    assert story._speech('The diver radioed, "We are not alone down here."')
    assert story._speech("She said ‘run’ and he ran.")
    assert not story._speech("It's a fish that doesn't blink, and the fish's head is clear.")
    assert not story._speech("The divers' boat left; the crew's logs say nothing.")


def test_a_shortened_spoken_line_is_kept_as_the_writer_shortened_it():
    keep = [{"i": i, "narration": t} for i, t in enumerate(BEATS)]
    keep[9] = {"i": 9, "narration": "लड़की बोली, 'सांड दूध दे सकता है, तो आदमी बच्चा क्यों नहीं?'"}
    for i in (1, 4, 5, 11):
        keep[i] = {"i": i, "narration": " ".join(BEATS[i].split()[:4])}
    out = story.fit_length(Writer({"keep": keep}), CH, _script(), log=lambda m: None)
    assert out["beats"][9]["narration"].startswith("लड़की बोली") and len(out["beats"]) == 13
    assert 110 <= _words(out) <= 135


def test_a_script_without_spoken_lines_trims_as_before():
    beats = [{"narration": " ".join([f"w{i}"] * 10)} for i in range(18)]
    w = Writer({"keep": [{"i": i, "narration": " ".join(["k"] * 10)} for i in range(12)]})
    out = story.fit_length(w, CH, {"beats": beats}, log=lambda m: None)
    assert _words(out) == 120 and ", and every beat with spoken lines" not in w.prompts[0]


def test_a_repeated_index_from_the_writer_never_doubles_a_beat():
    keep = [{"i": i, "narration": BEATS[i]} for i in range(13) if i not in (1, 2, 11)] + [{"i": 3, "narration": BEATS[3]}]
    out = story.fit_length(Writer({"keep": keep}), CH, _script(), log=lambda m: None)
    assert [b["narration"] for b in out["beats"]].count(BEATS[3]) == 1


@pytest.mark.parametrize("line", ["“Stop,” she whispered.", "«Andiamo», disse.", '"Run!"'])
def test_other_quote_marks_count_as_speech(line):
    assert story._speech(line)
