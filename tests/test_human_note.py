"""23 Nov, S10: three videos held as 'obviously AI-made' (human_feel 5, needs 6) had used both remakes. Their remakes and
the script judge's rewrites were told only the judge's general fixes (hook, pacing), never what the human_feel score
measures. Both now also get the judge's own human_feel text for the content type."""
from engine import potential_gate as pg, story, weekly

STORY = {"id": "cosmos_unboxed", "name": "Cosmos Unboxed", "type": "story", "niche": "space", "market": "US",
         "language": "en"}
KIDS = {"id": "bloop_and_friends", "name": "Bloop & Friends", "type": "kids", "niche": "preschool", "market": "US",
        "language": "en"}
HELD = ("potential: looks/sounds obviously AI-made (human_feel 5, needs 6). Fix: Rewrite the opening 1-2 seconds; "
        "quality: score 84/100 (needs 85.0): one shot lasts 8 s")


def test_the_note_is_the_judges_own_text_for_the_type():
    n = pg.human_note("story")
    assert pg.HUMAN_FINDING in n and pg.CRITERIA_HELP[pg.HUMAN] in n
    k = pg.human_note("kids", "long")
    assert pg.HELP_KIDS[pg.HUMAN] in k and "same-shaped sentences" not in k


def test_a_remake_held_as_ai_made_is_told_what_human_made_means():
    it = {"id": "1123_0500_cosmos_unboxed_short", "status": "redo", "gate_note": HELD, "kind": "short"}
    text = weekly.redo_text(it, STORY)
    assert "fix all of this: " + HELD in text and pg.CRITERIA_HELP[pg.HUMAN] in text
    kids = weekly.redo_text(dict(it, kind="long"), KIDS)
    assert pg.HELP_KIDS[pg.HUMAN] in kids
    other = weekly.redo_text(dict(it, gate_note="quality: 4/10 shots are word cards: show the moment instead"), STORY)
    assert "Human-made here means" not in other and "word cards" in other         # only for the S10 finding
    assert weekly.redo_text(dict(it, status="made"), STORY) == ""                # not a remake: nothing added
    assert "The owner asked for this change: shorter" in weekly.redo_text(dict(it, note="shorter"), STORY)


def test_the_script_judge_rewrite_carries_it_only_when_human_feel_is_low(monkeypatch):
    verdicts = [{"scores": {"hook": 7, pg.HUMAN: 5}, "low": {"hook": 7, pg.HUMAN: 5}, "fixes": ["open on the dot"],
                 "need": 8},
                {"scores": {"hook": 7, pg.HUMAN: 7}, "low": {"hook": 7}, "fixes": ["open on the dot"], "need": 8},
                {"scores": {"hook": 9, pg.HUMAN: 7}, "low": {}, "fixes": [], "need": 8}]
    monkeypatch.setattr(pg, "judge_script", lambda *a, **k: verdicts.pop(0))
    notes = []

    def write(brain, channel, topic, fmt, memory, log, plan, notes_=None, **k):
        notes.append(k.get("notes", ""))
        return {"title": f"draft {len(notes) + 1}", "beats": []}
    monkeypatch.setattr(story, "_write_fresh", write)
    monkeypatch.setattr(story, "_script_judge_cfg", lambda: {"enabled": True, "rounds": 2})
    out = story._judge_loop(object(), STORY, {"title": "draft 1", "beats": []}, "pale blue dot", "short", None,
                            lambda *a: None, {})
    assert out["title"] == "draft 3" and len(notes) == 2
    assert pg.CRITERIA_HELP[pg.HUMAN] in notes[0] and "open on the dot" in notes[0]
    assert "Human-made here means" not in notes[1]


def test_an_expansion_that_overshoots_the_range_is_trimmed_back(monkeypatch):
    """Deep Blue Files 23 Nov: 119 words -> 'asking for more true detail' -> 153 (and 112 -> 159) for a 125-150 range;
    nothing trimmed it, and the video lost quality points for its word count."""
    ch = {"spec": {"short_words": "125-150 words (about 43-52 seconds)"}}
    beats = [{"narration": " ".join(["word"] * 10), "visual": "photo", "query": f"q{i}"} for i in range(12)]   # 120
    monkeypatch.setattr(story, "shorten_title", lambda brain, s, log=print: s)

    def expand(brain, s, target=0, log=print, minimum=0, rounds=1):
        s["beats"] = s["beats"] + [{"narration": " ".join(["more"] * 10), "visual": "photo", "query": f"x{i}"}
                                   for i in range(4)]                                             # 160 words
        return s
    monkeypatch.setattr(story, "expand_long", expand)

    class Trim:
        def ask_json(self, role, prompt, temperature=0.3):
            return {"keep": [{"i": i, "narration": " ".join(["word"] * 9)} for i in range(16) if i not in (5, 11)]}, None

    out = story.fit_length(Trim(), ch, {"beats": beats}, log=lambda *a: None)
    n = sum(len(b["narration"].split()) for b in out["beats"])
    assert 125 <= n <= 150 and out["_expanded"] and out["_fact_check"] == {}      # new lines still get checked
    monkeypatch.setattr(story, "expand_long", lambda brain, s, **k: dict(s, beats=s["beats"] + s["beats"][:2]))
    ok = story.fit_length(Trim(), ch, {"beats": beats}, log=lambda *a: None)          # 140: in range, kept as is
    assert sum(len(b["narration"].split()) for b in ok["beats"]) == 140
