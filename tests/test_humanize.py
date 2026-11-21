"""21 Nov (owner: "current content that system makes is making the content so obvious for the viewer that this is ai,
but we need more human like things from the system"): plan P3r creation workstream, standards S7 + S10."""
import json

import pytest

from engine import humanize as hz, ip_guard, potential_gate as pg

AI_LINES = [
    "Buckle up, because this tiny town holds a secret you won't believe.",
    "It's not just a mine, it's a testament to human greed.",
    "In 1912, 1,500 people died when the ship sank in 2 hours 40 minutes.",
]


def test_tells_find_the_ai_patterns_and_leave_plain_writing_alone():
    ids = {t["id"] for t in hz.tells(" ".join(AI_LINES))}
    assert {"yt_cliche", "not_x_but_y", "ai_word"} <= ids
    for plain in ("In 1912, 1,500 people died when the ship sank in 2 hours 40 minutes.",
                  "The key turned, the door creaked, and nobody was inside.",
                  "She waited three days. Then the letter came.",
                  "Not one of the 40 miners came back up."):
        assert hz.tells(plain) == [], plain
    assert hz.tell_density(AI_LINES[0]) > hz.tell_density(AI_LINES[2]) == 0
    dashy = "He ran — fast — to the door — and then — nothing."
    assert any(t["id"] == "dashes" for t in hz.tells(dashy))


class Brain:
    def __init__(self, reply):
        self.reply, self.calls = reply, []

    def ask_json(self, task, prompt, system="", temperature=0.4):
        self.calls.append((task, prompt))
        return self.reply, None


def test_rewrite_keeps_only_better_lines_with_every_number():
    good = "This tiny town hides a secret nobody talks about."
    plain = "It was a mine that people were ready to kill for."
    b = Brain({"lines": [good, plain, "Lots of people died fast."]})
    out, changed = hz.rewrite_lines(b, AI_LINES, log=lambda *_: None)
    assert out[0] == good and out[1] == plain and changed == 2
    assert out[2] == AI_LINES[2]                     # had no tells: never sent for a rewrite, never replaced
    assert "fix: [0, 1]" in b.calls[0][1]
    too_short = hz.rewrite_lines(Brain({"lines": ["Town secret.", plain, AI_LINES[2]]}), AI_LINES,
                                 log=lambda *_: None)
    assert too_short[0][0] == AI_LINES[0] and too_short[1] == 1     # a line cut to a stub is refused
    # a rewrite that drops a number, keeps the tells or changes the line count is refused
    lines = ["Buckle up: 7 people vanished in 1971 without a trace."]
    out, changed = hz.rewrite_lines(Brain({"lines": ["Some people vanished long ago."]}), lines, log=lambda *_: None)
    assert out == lines and changed == 0
    out, changed = hz.rewrite_lines(Brain({"lines": ["Buckle up, 7 people vanished in 1971!"]}), lines,
                                    log=lambda *_: None)
    assert out == lines and changed == 0
    out, changed = hz.rewrite_lines(Brain({"lines": ["a", "b"]}), lines, log=lambda *_: None)
    assert out == lines and changed == 0


def test_rewrite_failure_keeps_the_original():
    class Broken:
        def ask_json(self, *a, **k):
            raise RuntimeError("All models failed")
    out, changed = hz.rewrite_lines(Broken(), AI_LINES, log=lambda *_: None)
    assert out == AI_LINES and changed == 0
    assert hz.rewrite_lines(None, AI_LINES) == (AI_LINES, 0)


def test_humanize_script_rewrites_and_asks_for_a_new_fact_check():
    script = {"title": "Unveiling the Untold Story of Centralia", "hook_text": "A town on fire",
              "search_phrase": "Centralia mine fire",
              "beats": [{"narration": AI_LINES[0]}, {"narration": "The fire started in 1962."}],
              "_fact_check": {"ok": True, "checked": True}}
    assert hz.script_tells(script)
    b = Brain({"lines": ["Centralia's secret is still burning under the road.", "The fire started in 1962.",
                         "Centralia: the mine fire that never went out", "A town on fire"]})
    out = hz.humanize_script(b, script, log=lambda *_: None)
    assert out["beats"][0]["narration"].startswith("Centralia's secret")
    assert out["title"] == "Centralia: the mine fire that never went out" and out["_fact_check"] == {}
    assert script["title"].startswith("Unveiling")                    # the caller's copy is untouched
    clean = {"title": "The Town That Burns", "beats": [{"narration": "The fire started in 1962."}]}
    assert hz.humanize_script(Brain({}), clean) is clean


def test_title_rewrite_must_keep_the_searched_words():
    script = {"title": "Unveiling the Centralia Mine Fire", "search_phrase": "Centralia mine fire", "beats": []}
    out = hz.humanize_script(Brain({"lines": ["A town that has burned since 1962"]}), script, log=lambda *_: None)
    assert out["title"] == script["title"]


def test_ai_tell_score_parts():
    shots = [{"kind": "text", "source": "text"}, {"kind": "image", "source": "cloudflare"},
             {"kind": "image", "source": "openverse"}, {"kind": "video", "source": "chart", "graphic": True}]
    s = hz.ai_tell_score(" ".join(AI_LINES), shots)
    assert s["parts"]["word_cards"] == 7.5 and s["parts"]["ai_pictures"] == 5.0 and s["parts"]["text"] > 0
    assert "buckle up" in [m.lower() for m in s["top"]]
    assert hz.ai_tell_score("The fire started in 1962.")["score"] == 0


CH = {"id": "unsolved_after_dark", "name": "Unsolved After Dark", "type": "story", "niche": "true crime",
      "market": "US", "language": "en"}


@pytest.fixture
def vid(tmp_path):
    out = tmp_path / "v"
    out.mkdir()
    it = {"id": "h1", "channel": "unsolved_after_dark", "topic": "Centralia", "out_dir": str(out),
          "file": "video.mp4", "made_at": 10.0}
    return {"it": it, "out": out}


def test_gate_holds_obviously_ai_written_text(vid):
    srt = ("1\n00:00:00,200 --> 00:00:03,000\nBuckle up. Little did they know this vibrant town would burn.\n\n"
           "2\n00:00:03,000 --> 00:00:06,000\nIt stands as a testament to greed.\n")
    (vid["out"] / "captions.srt").write_text(srt, encoding="utf-8")
    meta = {"title": "The Town That Burns", "description": "A real place."}
    probs = pg.deterministic(vid["it"], CH, meta, past_titles=[])
    assert any("reads like AI-written text" in p and "buckle up" in p for p in probs)
    (vid["out"] / "captions.srt").write_text("1\n00:00:00,200 --> 00:00:03,000\nThe fire started in 1962 and "
                                             "never stopped.\n", encoding="utf-8")
    assert pg.deterministic(vid["it"], CH, meta, past_titles=[]) == []


def test_clip_speech_is_the_creators_own(vid):
    (vid["out"] / "clip_01.srt").write_text("1\n00:00:00,200 --> 00:00:03,000\nFundamentally, at its core, "
                                            "let's dive in, buckle up.\n", encoding="utf-8")
    it = dict(vid["it"], kind="clip", file="clip_01.mp4")
    assert not any("AI-written" in p for p in pg.deterministic(it, dict(CH, type="clips"), {"title": "He said it"},
                                                               past_titles=[]))


class Judge:
    def __init__(self, scores):
        self.scores = scores

    def ask_json(self, task, prompt, temperature=0.4):
        assert "human_feel" in prompt
        return {"scores": self.scores, "fixes": ["say it like a person"], "summary": "x"}, None


def test_human_feel_has_its_own_bar(vid, monkeypatch):
    from engine import topic_proof as tp
    monkeypatch.setattr(pg, "deterministic", lambda *a, **k: [])
    monkeypatch.setattr(tp, "proof", lambda topic, ch, **k: {"tier": "hot"})
    monkeypatch.setattr("engine.content_gate.temporary_bar", lambda today=None: {})
    all9 = {c: 9 for c in pg.DEFAULT_RUBRICS["story"]}
    assert pg.problems(vid["it"], CH, {"title": "t"}, brain_fn=lambda: Judge(dict(all9, human_feel=6))) == []
    vid["it"]["made_at"] = 11.0
    probs = pg.problems(vid["it"], CH, {"title": "t"}, brain_fn=lambda: Judge(dict(all9, human_feel=4)))
    assert len(probs) == 1 and "obviously AI-made (human_feel 4, needs 6)" in probs[0]
    from engine.content_gate import fixable_by_remake
    assert fixable_by_remake(probs)                              # remade with the humanize pass, never posted


def test_judge_criteria_add_human_feel_except_for_clips():
    cfg = pg._cfg()
    assert pg._criteria(cfg, "story")[-1] == "human_feel" and "human_feel" in pg._criteria(cfg, "kids")
    assert "human_feel" not in pg._criteria(cfg, "clips")
    off = dict(cfg, ai_tell={"enabled": False})
    assert "human_feel" not in pg._criteria(off, "story")


def test_anime_studio_names_are_never_used():
    for txt in ("a Studio Ghibli style forest", "ghibli-style village at dusk", "in the style of Miyazaki",
                "Totoro under the rain", "Spirited girl in Howl's Moving Castle", "Hayao Miyazaki anime",
                "Naruto Uzumaki running", "a Dragon Ball fight"):
        assert ip_guard.hits(txt), txt
    for txt in ("the Naruto whirlpools in Japan", "Durga, the demon slayer", "Sun Wukong, the Monkey King",
                "Gulliver reaches Laputa", "a hand-painted anime village with watercolour skies",
                "the money was spirited away", "Miyazaki prefecture beaches"):
        assert ip_guard.hits(txt) == [], txt
    p, found = ip_guard.scrub("a girl in a Ghibli-style meadow, soft light")
    assert found and "ghibli" not in p.lower() and "original design" in p


def test_writer_is_told_to_sound_human():
    from engine.story import WRITER_SYSTEM
    assert "buckle up" in WRITER_SYSTEM and "plain spoken words" in WRITER_SYSTEM
    assert json.dumps(hz.PATTERNS)                                   # the catalogue stays serialisable for reports
