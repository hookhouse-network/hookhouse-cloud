"""Tests for the Week 2 production stack (fast, no models or internet needed)."""
from pathlib import Path

from engine.clips import snap, transcript_text, virality
from engine.media.captions import Word, ass_color, build_ass, chunk_words
from engine.media.transcribe import align_script
from engine.media.visuals import ai_prompt_key, gpu_jobs_from_script, license_ok


def W(text, s, e):
    return Word(text, s, e)


# ---------- captions ----------
def test_ass_color_is_bgr():
    assert ass_color("#FF0000") == "&H000000FF"
    assert ass_color("#00E5FF", alpha=128) == "&H80FFE500"


def test_chunks_break_on_punctuation_and_length():
    words = [W("Nobody", 0, .3), W("ever", .3, .5), W("found", .5, .8), W("her.", .8, 1.1),
             W("Not", 1.2, 1.4), W("the", 1.4, 1.5), W("police,", 1.5, 1.9), W("not", 2.0, 2.2)]
    chunks = [[w.text for w in c] for c in chunk_words(words)]
    assert chunks[0] == ["Nobody", "ever", "found"]
    assert chunks[1] == ["her."]
    assert all(len(c) <= 3 for c in chunks)


def test_hindi_captions_use_zero_letter_spacing(tmp_path):
    # Letter spacing breaks Devanagari shaping in libass (dotted circles) — must be 0 for Hindi.
    words = [W("भारत", 0, .5), W("सिर्फ", .5, 1.0)]
    hi = build_ass(words, tmp_path / "hi.ass", font="Hind", language="hi", hook="Sirf 183 Run").read_text(encoding="utf-8")
    en = build_ass(words, tmp_path / "en.ass", font="Anton", language="en").read_text(encoding="utf-8")
    hi_caption = next(l for l in hi.splitlines() if l.startswith("Style: Caption"))
    en_caption = next(l for l in en.splitlines() if l.startswith("Style: Caption"))
    assert hi_caption.split(",")[13] == "0"
    assert en_caption.split(",")[13] == "1"
    assert "भारत" in hi and "सिर्फ" in hi          # Hindi not uppercased / mangled
    hook_lines = [l for l in hi.splitlines() if "Hook,," in l]
    assert hook_lines and all(l.rsplit("}", 1)[-1].strip() for l in hook_lines)   # hook text after the tags


def test_captions_emphasis_glow_and_count_up(tmp_path):
    from engine.media.captions import BigText
    words = [W("only", 0, .3), W("183", .3, .7), W("runs", .7, 1.0)]
    text = build_ass(words, tmp_path / "e.ass", emphasis_color="#FFD600", emphasis_words={"runs"},
                     big_texts=[BigText(2.0, 3.0, "183 RUNS")]).read_text(encoding="utf-8")
    assert "Glow,," in text                                    # glow layer under captions
    assert "&H0000D6FF\\fscx122" in text                       # number + emphasis word in accent colour
    big = [l for l in text.splitlines() if ",Big,," in l]
    assert len(big) > 5 and big[-1].replace(r"\N", " ").endswith("183 RUNS")   # counts up, ends on the real value


def test_english_captions_uppercase_and_highlight(tmp_path):
    words = [W("hello", 0, .4), W("world", .4, .8)]
    text = build_ass(words, tmp_path / "c.ass", highlight_color="#FFE600").read_text(encoding="utf-8")
    assert "HELLO" in text and "&H0000E6FF" in text


# ---------- script alignment ----------
def test_align_keeps_script_spelling_and_fills_gaps():
    heard = [W("nobody", 0.0, 0.4), W("ever", 0.4, 0.6), W("fond", 0.6, 0.9), W("her", 0.9, 1.2)]
    out = align_script("Nobody ever found her.", heard, total=1.3)
    assert [w.text for w in out] == ["Nobody", "ever", "found", "her."]
    assert out[2].start >= out[1].end - 1e-6 and out[2].end <= out[3].start + 1e-6


def test_align_without_audio_spreads_evenly():
    out = align_script("one two three four", [], total=2.0)
    assert out[0].start == 0 and abs(out[-1].end - 2.0) < 1e-6


# ---------- clip engine ----------
def test_virality_score_weights():
    assert virality({k: 10 for k in ("hook", "emotion", "curiosity", "complete", "ending", "audience_fit", "brand_safe")}) == 100
    assert virality({"hook": 10}) == 25
    assert virality({"hook": 50}) == 25  # clamped


def test_snap_starts_on_sentence_and_ends_after_word():
    words = [W("so", 9.0, 9.2), W("yeah.", 9.2, 9.5), W("He", 10.0, 10.2), W("said", 10.2, 10.5),
             W("no.", 10.5, 10.9), W("Then", 30.0, 30.3), W("left.", 30.3, 30.8)]
    s, e = snap(words, 9.4, 30.5)
    assert abs(s - 9.9) < 1e-6          # starts on "He" (sentence start), not "so"
    assert abs(e - 31.05) < 1e-6         # ends after "left." + small tail


def test_transcript_text_has_timestamps():
    words = [W("Hello", 0, .5), W("there.", .5, 1.0), W("Next", 1.2, 1.5)]
    assert transcript_text(words).splitlines()[0].startswith("[0.0] Hello there.")


# ---------- visuals ----------
def test_only_commercially_safe_image_licenses():
    for ok in ("Public domain", "CC0", "CC BY 4.0", "CC BY 2.0", "PD-USGov"):
        assert license_ok(ok), ok
    for bad in ("CC BY-SA 4.0", "CC BY-NC 2.0", "CC BY-ND 3.0", "Fair use", "All rights reserved", ""):
        assert not license_ok(bad), bad


def test_gpu_jobs_match_renderer_keys():
    script = {"scenes": [{"visual_type": "ai", "ai_prompt": "foggy ocean at night"},
                         {"visual_type": "photo", "visual_query": "Lord's"}]}
    jobs = gpu_jobs_from_script(script, "dark")
    assert len(jobs) == 1 and jobs[0]["key"] == ai_prompt_key("foggy ocean at night", "dark")[1]
