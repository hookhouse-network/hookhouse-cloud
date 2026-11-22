"""23 Nov (Deep Blue 1123): both fact corrections failed, the best draft still said "MBARI first filmed a live one in
2004" (the sources say 2008), the PC rendered it for 35 minutes and the gate held it on its last remake. A detail
that cannot be corrected is now deleted (no new claim to get wrong), and the script judge never keeps a draft the
fact gate would hold over one whose facts check out."""
import pytest

from engine import potential_gate, story

WRONG = "MBARI first filmed a live one in 2004 (the reference says 2008)"
CLEAN = {"checked": True, "ok": True, "problems": [], "warnings": []}


def _bad(*problems, warnings=()):
    return {"checked": True, "ok": False, "problems": list(problems), "warnings": list(warnings)}


class Brain:
    def __init__(self, answers):
        self.answers, self.prompts = list(answers), []

    def ask_json(self, route, prompt, temperature=0.0, **kw):
        self.prompts.append(prompt)
        return self.answers.pop(0), None


def _script():
    return {"beats": [{"narration": "MBARI first filmed a live one in 2004, and its head is clear."},
                      {"narration": "Its eyes glow green."}],
            "claims": ["MBARI first filmed a live one in 2004", "Its head is clear", "Its eyes glow green"]}


def _failed_fixes():
    """Two corrections that each make it worse (the 02:26 log): the original draft stays the best."""
    return [{"edits": [{"i": 0, "old": "in 2004", "new": "in 2018"}]},
            {"edits": [{"i": 0, "old": "in 2018", "new": "in 1965"}]}]


def _run(monkeypatch, verdicts, drop_answer):
    seq = iter(verdicts)
    monkeypatch.setattr(story, "fact_check", lambda brain, script, deep=False: next(seq))
    brain = Brain(_failed_fixes() + [drop_answer])
    out = story.check_and_fix(brain, {"content_rules": {"fact_check": True}}, _script(), "barreleye", "short",
                              log=lambda m: None)
    return out, brain


def test_a_detail_that_cannot_be_corrected_is_deleted(monkeypatch):
    drop = {"edits": [{"i": 0, "old": "MBARI first filmed a live one in 2004, and its", "new": "Its"}],
            "claims": ["Its head is clear", "Its eyes glow green"]}
    out, brain = _run(monkeypatch, [_bad(WRONG), _bad("a", "b"), _bad("c", "d"), CLEAN], drop)
    assert out["beats"][0]["narration"] == "Its head is clear."
    assert out["_fact_check"]["ok"] and not out["_fact_check"]["problems"]
    assert not any("2004" in c for c in out["claims"])
    assert "Delete each of these details" in brain.prompts[-1] and WRONG in brain.prompts[-1]
    assert "Do NOT replace" in brain.prompts[-1]


def test_deleting_is_kept_only_when_the_check_gets_better(monkeypatch):
    drop = {"edits": [{"i": 1, "old": "Its eyes glow green.", "new": ""}]}
    out, _ = _run(monkeypatch, [_bad(WRONG), _bad("a", "b"), _bad("c", "d"), _bad(WRONG)], drop)
    assert out["beats"][0]["narration"].startswith("MBARI first filmed") and len(out["beats"]) == 2
    assert out["_fact_check"]["problems"] == [WRONG]                 # still held by the gate, honestly reported


def test_an_unchecked_recheck_never_replaces_a_checked_verdict(monkeypatch):
    drop = {"edits": [{"i": 0, "old": "in 2004", "new": ""}]}
    busy = {"ok": False, "problems": ["No sources found to verify the claims — check manually"], "checked": False}
    out, _ = _run(monkeypatch, [_bad(WRONG, warnings=("x", "y")), _bad("a", "b"), _bad("c", "d"), busy], drop)
    assert out["_fact_check"]["checked"] and out["_fact_check"]["problems"] == [WRONG]


def test_a_failed_deletion_call_keeps_the_best_draft(monkeypatch):
    seq = iter([_bad(WRONG), _bad("a", "b"), _bad("c", "d")])
    monkeypatch.setattr(story, "fact_check", lambda brain, script, deep=False: next(seq))
    brain = Brain(_failed_fixes())                                    # third call: no answer left -> IndexError
    out = story.check_and_fix(brain, {}, _script(), "t", "short", log=lambda m: None)
    assert out["_fact_check"]["problems"] == [WRONG] and "2004" in out["beats"][0]["narration"]


def test_a_clean_draft_never_reaches_the_deletion_step(monkeypatch):
    monkeypatch.setattr(story, "fact_check", lambda brain, script, deep=False: dict(CLEAN))
    monkeypatch.setattr(story, "drop_wrong", lambda *a: pytest.fail("nothing to delete"))
    out = story.check_and_fix(Brain([]), {}, _script(), "t", "short", log=lambda m: None)
    assert out["_fact_check"]["ok"]


def test_a_line_left_without_words_loses_its_beat():
    brain = Brain([{"edits": [{"i": 1, "old": "Its eyes glow green.", "new": ""},
                              {"i": 0, "old": " in 2004", "new": ""}]}])
    out, applied = story.drop_wrong(brain, _script(), [WRONG])
    assert applied == 2 and [b["narration"] for b in out["beats"]] == ["MBARI first filmed a live one, and its head is clear."]


@pytest.mark.parametrize("after, before, want", [
    ("MBARI filmed it , and its head is clear .", "", "MBARI filmed it, and its head is clear."),
    ("It glows,.", "", "It glows."),
    (", and its head is clear.", "In 2004, and its head is clear.", "And its head is clear."),
    ("यह सच है ।", "", "यह सच है।"),
    ("Wait  for it.", "", "Wait for it."),
])
def test_an_edited_line_stays_tidy(after, before, want):
    assert story._tidy(after, before) == want


# --- the script judge: facts first, then the weakest score ------------------------------------------------------

@pytest.fixture
def loop(monkeypatch):
    verdicts, writes, drafts = [], [], []

    def judge(script, ch, topic, brain, kind=""):
        return verdicts.pop(0)
    monkeypatch.setattr(potential_gate, "judge_script", judge)

    def write(brain, channel, topic, fmt, memory, log, plan, notes=""):
        writes.append(notes)
        return drafts.pop(0)
    monkeypatch.setattr(story, "_write_fresh", write)
    monkeypatch.setattr(story, "_script_judge_cfg", lambda: {"enabled": True, "rounds": 2})
    return verdicts, writes, drafts


def _v(weakest, low=None):
    return {"scores": {"hook": weakest, "clarity": 9}, "fixes": ["say the twist first"], "low": low or {}, "need": 8}


CH = {"id": "deep_blue_files", "name": "Deep Blue Files", "type": "story", "language": "en", "market": "US"}


def test_the_judge_never_keeps_a_draft_the_fact_gate_would_hold(loop):
    verdicts, writes, drafts = loop
    verdicts += [_v(5, {"hook": 5}), _v(6, {"hook": 6}), _v(6, {"hook": 6})]
    drafts += [{"title": "draft 2", "_fact_check": _bad(WRONG)}, {"title": "draft 3", "_fact_check": _bad(WRONG)}]
    first = {"title": "draft 1", "_fact_check": dict(CLEAN)}
    out = story._judge_loop(object(), CH, first, "barreleye", "short", None, lambda *a: None, {})
    assert out["title"] == "draft 1"                    # weakest 5 with true facts beats 6 that the gate will hold


def test_among_drafts_with_true_facts_the_strongest_wins(loop):
    verdicts, writes, drafts = loop
    verdicts += [_v(5, {"hook": 5}), _v(7, {"hook": 7}), _v(6, {"hook": 6})]
    drafts += [{"title": "draft 2", "_fact_check": dict(CLEAN)}, {"title": "draft 3", "_fact_check": dict(CLEAN)}]
    out = story._judge_loop(object(), CH, {"title": "draft 1", "_fact_check": dict(CLEAN)}, "t", "short", None,
                            lambda *a: None, {})
    assert out["title"] == "draft 2"


def test_a_passing_draft_with_wrong_facts_is_rewritten_without_them(loop):
    verdicts, writes, drafts = loop
    verdicts += [_v(9), _v(9)]
    drafts += [{"title": "draft 2", "_fact_check": dict(CLEAN)}]
    out = story._judge_loop(object(), CH, {"title": "draft 1", "_fact_check": _bad(WRONG)}, "t", "short", None,
                            lambda *a: None, {})
    assert out["title"] == "draft 2" and len(writes) == 1 and WRONG in writes[0] and "without them" in writes[0]


def test_drafts_without_a_fact_check_are_judged_on_scores_alone():
    assert story._facts_pass({}) and story._facts_pass({"_fact_check": {}})
    assert not story._facts_pass({"_fact_check": {"checked": False, "ok": False, "problems": ["No sources"]}})
    assert not story._facts_pass({"_fact_check": _bad(WRONG)}) and story._facts_pass({"_fact_check": CLEAN})
