"""Round 15 (13 Nov): ideas from the third batch of repos.
- Say it right (video-podcast-maker's pronunciation idea): numbers, money, units, Roman numerals and Hindi years
  rewritten into the words a narrator says; a pronunciation file for names.
- Animated charts written as web code and recorded frame by frame (awesome-opus5-5-videos, hyperframes)."""
import json
from pathlib import Path

import pytest

from engine.media import html_scene as hs
from engine.media import say


@pytest.mark.parametrize("text, spoken", [
    ("It cost $4.5B.", "It cost 4.5 billion dollars."),
    ("the Mint lost $85.3 million on pennies", "the Mint lost 85.3 million dollars on pennies"),
    ("Tom paid $1, then $20 million.", "Tom paid 1 dollar, then 20 million dollars."),
    ("₹500 crore budget", "500 crore rupees budget"),
    ("World War II ended in 1945.", "World War Two ended in 1945."),
    ("World War I began in 1914.", "World War One began in 1914."),
    ("After the War I went home.", "After the War I went home."),          # the word "I" stays
    ("Henry VIII and Elizabeth II.", "Henry the Eighth and Elizabeth the Second."),
    ("Apollo XI and Rocky II.", "Apollo Eleven and Rocky Two."),
    ("1/3 of people, 24/7, 245/6.", "one third of people, twenty-four seven, 245 for 6."),
    ("He scored 100* in 2011.", "He scored 100 not out in 2011."),
    ("It weighs 50 kg and runs 300 km/h.", "It weighs 50 kilograms and runs 300 kilometers per hour."),
    ("Mt. Everest is 8,849 m tall.", "Mount Everest is 8,849 meters tall."),
    ("at 9:30 pm and 10:00 am, 7:05 pm", "at 9 30 pm and 10 am, 7 oh 5 pm"),
    ("Tom & Jerry", "Tom and Jerry"),
    ("I'm 5 ft tall and 75% sure.", "I'm 5 feet tall and 75% sure."),
])
def test_english_reads_like_a_narrator(text, spoken):
    assert say.english(text) == spoken


@pytest.mark.parametrize("text, spoken", [
    ("₹15,000 की फिल्म", "15000 रुपये की फिल्म"),                  # was "pandrah, shoonya shoonya shoonya"
    ("18 जून 1983, Tunbridge Wells", "18 जून 19 सौ 83, Tunbridge Wells"),
    ("1911, बॉम्बे.", "19 सौ 11, बॉम्बे."),
    ("1900 में", "19 सौ में"),
    ("2011 में", "2011 में"),                                          # espeak already says "do hazaar gyarah"
    ("1500 रुपये", "1500 रुपये"),                                      # an amount, not a year
    ("1,50,000 दर्शक", "150000 दर्शक"),                              # lakh grouping read as one number
    ("2.5 करोड़ लोग", "ढाई करोड़ लोग"),
    ("1.5 लाख", "डेढ़ लाख"),
    ("₹3.5 करोड़ का", "साढ़े 3 करोड़ रुपये का"),
    ("$10 billion", "10 बिलियन डॉलर"),
    ("1/3 हिस्सा", "एक तिहाई हिस्सा"),
    ("100* बनाए", "100 नॉट आउट बनाए"),
])
def test_hindi_reads_like_a_narrator(text, spoken):
    assert say.hindi(text) == spoken


def test_pronunciation_file_wraps_names_in_phonemes(monkeypatch):
    say._dictionary.cache_clear()
    monkeypatch.setattr(say, "_dictionary", lambda: {"en": {"Ravana": "/ɹˈɑvənə/", "NASA": "Nasa"},
                                                     "hi": {"AI": "एआई"}})
    assert say.normalise("Ravana met NASA.", "en") == "[Ravana](/ɹˈɑvənə/) met Nasa."
    assert say.normalise("AI और", "hi") == "एआई और"
    assert say.normalise("Ravanan", "en") == "Ravanan"                    # whole words only


def test_shipped_pronunciation_file_loads():
    say._dictionary.cache_clear()
    d = say._dictionary()
    assert "Ravana" in d["en"] and d["en"]["Ravana"].startswith("/") and "AI" in d["hi"]


def test_voice_uses_the_rewrite(monkeypatch, tmp_path):
    from engine.media import voice
    seen = []

    class Pipe:
        def __call__(self, text, **k):
            seen.append(text)
            return [type("R", (), {"audio": [0.1] * 2400})()]
    monkeypatch.setattr(voice, "_pipeline", lambda code: Pipe())
    voice.synthesize("World War II cost $4.5B.", tmp_path / "a.wav", "am_michael", "en")
    assert seen == ["World War Two cost 4.5 billion dollars."]


NARR = "In 2024 alone, the Mint lost $85.3 million making pennies, and ending them would save $56 million a year."


def test_check_chart_accepts_spoken_numbers_only():
    ok, why = hs.check_chart({"type": "compare", "title": "The penny problem", "items": [
        {"label": "Cost", "value": 85.3, "text": "$85.3M"}, {"label": "Saved", "value": 56, "text": "$56M"}]}, NARR)
    assert why == "" and ok["type"] == "compare" and len(ok["items"]) == 2
    bad, why = hs.check_chart({"type": "compare", "items": [
        {"label": "Cost", "value": 85.3, "text": "$85.3M"}, {"label": "Saved", "value": 60, "text": "$60M"}]}, NARR)
    assert bad is None and "60" in why                                     # 60 was never said
    assert hs.check_chart({"type": "pie", "items": []}, NARR)[0] is None
    assert hs.check_chart({"type": "compare", "items": [{"label": "A", "value": 85.3, "text": "$85.3M"}]}, NARR)[0] is None
    assert hs.check_chart({"type": "compare", "items": [{"label": "A", "value": 0, "text": ""},
                                                        {"label": "B", "value": 56, "text": "$56M"}]}, NARR)[0] is None
    assert hs.check_chart({"type": "scale", "items": [{"label": "A", "value": 1, "text": ""},
                                                      {"label": "B", "value": 85.3, "text": ""}]}, NARR)[0] is None   # >60x
    assert hs.check_chart(None, NARR)[0] is None


def test_timeline_years_must_be_spoken():
    narr = "1911 में फाल्के ने फिल्म देखी, 1912 में लंदन गए, और 3 मई 1913 को राजा हरिश्चंद्र आई।"
    items = [{"label": "1911", "text": "फिल्म देखी"}, {"label": "1912", "text": "लंदन"}, {"label": "1913", "text": "रिलीज़"}]
    assert hs.check_chart({"type": "timeline", "items": items}, narr)[0]
    assert hs.check_chart({"type": "timeline", "items": items[:2] + [{"label": "1914", "text": ""}]}, narr)[0] is None


def test_theme_follows_the_channel():
    money = hs.theme_for({"id": "money_cheat_codes", "language": "en", "style": {"highlight_color": "#7C83FD"}})
    assert money["accent"] == "#7C83FD" and money["accent2"] != "#86EFAC"
    hindi = hs.theme_for({"id": "picture_abhi_baaki_hai", "language": "hi"})
    assert hindi["label_font"] == "Mukta ExtraBold"


def test_chart_records_a_real_video(tmp_path):
    from engine.media import ffmpeg
    chart, _ = hs.check_chart({"type": "compare", "title": "Penny", "items": [
        {"label": "Cost", "value": 85.3, "text": "$85.3M"}, {"label": "Saved", "value": 56, "text": "$56M"}]}, NARR)
    out = hs.chart_video({"id": "money_cheat_codes", "language": "en"}, chart, (360, 640), 1.0, tmp_path / "c.mp4",
                         fps=10)
    assert out.exists() and 2.4 <= ffmpeg.duration(out) <= 2.7            # at least 2.5 s
    assert not (tmp_path / "c.html").exists()                             # the page file is cleaned up


def test_story_chart_falls_back_to_a_picture_when_checks_fail(tmp_path):
    from engine import story
    beat = {"visual": "chart", "narration": "It cost 5 dollars.",
            "chart": {"type": "compare", "items": [{"label": "A", "value": 9, "text": "$9"},
                                                   {"label": "B", "value": 5, "text": "$5"}]}}
    logs = []
    assert story._chart_visual(beat, 3.0, tmp_path, 0, set(), (360, 640), {"id": "money_cheat_codes"},
                               logs.append) is None
    assert "never said" in logs[0]
    used = {"chart:done"}                                                   # one chart per video
    assert story._chart_visual(dict(beat, narration="9 dollars vs 5 dollars"), 3.0, tmp_path, 1, used, (360, 640),
                               {"id": "money_cheat_codes"}) is None


def test_story_prompt_offers_the_chart():
    from engine import story
    src = Path(story.__file__).read_text(encoding="utf-8")
    assert '"chart": ONLY when' in src and "footage|photo|ai|text|chart" in src
    json.dumps({"ok": True})


def _talk(hours: float):
    from engine.clips import Word
    out, t, k = [], 0.0, 0
    while t < hours * 3600:
        out.append(Word(f"word{k % 97}" + ("." if k % 12 == 11 else ""), t, t + 0.3))
        t += 0.4
        k += 1
    return out


def test_long_podcasts_are_read_in_overlapping_parts():
    from engine import clips
    short = _talk(0.5)
    assert clips.transcript_parts(short) == [short]
    words = _talk(3.0)                                    # a 3-hour podcast: the old cut stopped near 2 hours
    parts = clips.transcript_parts(words)
    assert len(parts) >= 2 and all(len(clips.transcript_text(p)) <= clips.PART_CHARS for p in parts)
    assert parts[0][0] is words[0] and parts[-1][-1] is words[-1]            # nothing lost at either end
    for a, b in zip(parts, parts[1:]):                    # neighbours overlap: no gap between parts
        assert b[0].start <= a[-1].end - 60


def test_pick_moments_sees_the_last_hour():
    from engine import clips
    words = _talk(3.0)
    asked = []

    class Brain:
        def ask_json(self, role, prompt, **k):
            asked.append(prompt)
            last = float(prompt.rsplit("[", 1)[1].split("]")[0])            # the last time in this part
            m = {"start": last - 40, "end": last - 10, "scores": {x: 8 for x in clips.WEIGHTS}, "hook_options": ["x"],
                 "title": "T"}
            return {"moments": [m]}, type("R", (), {"provider": "test"})()
    got = clips.pick_moments(Brain(), words, keep=5, min_len=20, max_len=55)
    assert len(asked) >= 2
    assert max(m["end"] for m in got) > 2.5 * 3600                          # a moment from the final hour
    assert all(m["picked_by"] == "test" for m in got)
