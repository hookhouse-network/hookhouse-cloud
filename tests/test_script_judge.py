"""22 Nov (P3 core): the potential gate's rubric judges the SCRIPT before voice, pictures and render. Since the strict
judge went live no video passed it (story Shorts 5-7 of 10 vs 8 on every point), each after ~12 pictures and ~35
minutes. A weak script is rewritten with the judge's own fixes (up to `rounds` times) and the best draft is kept."""
import pytest

from engine import potential_gate, story

CH = {"id": "cosmos_unboxed", "name": "Cosmos Unboxed", "type": "story", "language": "en", "market": "US"}
SCRIPT = {"title": "The pale blue dot", "beats": [{"narration": "Earth is one pixel."}, {"narration": "Sagan asked."}]}


class Brain:
    def __init__(self, answers):
        self.answers, self.prompts = list(answers), []

    def ask_json(self, route, prompt, temperature=0.0):
        self.prompts.append((route, prompt))
        return self.answers.pop(0), None


def _scores(v: float, **over) -> dict:
    s = {c: v for c in potential_gate.DEFAULT_RUBRICS["story"]}
    s["human_feel"] = 8
    s.update(over)
    return {"scores": s, "fixes": ["open with the pixel itself"], "summary": "ok"}


def test_the_script_is_judged_with_the_gate_rubric_and_bar(monkeypatch):
    monkeypatch.setattr("engine.topic_proof.proof", lambda topic, ch: {})
    monkeypatch.setattr("engine.topic_proof.evidence_text", lambda p: "demand: test")
    brain = Brain([_scores(8, hook=6, retention=7)])
    v = potential_gate.judge_script(SCRIPT, CH, "Voyager", brain)
    route, prompt = brain.prompts[0]
    assert route == "checker" and "Earth is one pixel. Sagan asked." in prompt and "TITLE: The pale blue dot" in prompt
    assert "HOOK / FIRST LINE: Earth is one pixel." in prompt
    assert v["need"] == potential_gate._cfg()["min_each"] and v["low"] == {"hook": 6, "retention": 7}


def test_obviously_ai_scripts_count_as_below_the_bar(monkeypatch):
    monkeypatch.setattr("engine.topic_proof.proof", lambda topic, ch: {})
    monkeypatch.setattr("engine.topic_proof.evidence_text", lambda p: "")
    v = potential_gate.judge_script(SCRIPT, CH, "", Brain([_scores(9, human_feel=3)]))
    assert v["low"] == {"human_feel": 3}


@pytest.fixture
def loop(monkeypatch):
    verdicts, writes = [], []

    def judge(script, ch, topic, brain):
        v = verdicts.pop(0)
        if isinstance(v, Exception):
            raise v
        return v
    monkeypatch.setattr(potential_gate, "judge_script", judge)

    def write(brain, channel, topic, fmt, memory, log, plan, notes=""):
        writes.append(notes)
        return {"title": f"draft {len(writes) + 1}", "beats": []}
    monkeypatch.setattr(story, "_write_fresh", write)
    monkeypatch.setattr(story, "_script_judge_cfg", lambda: {"enabled": True, "rounds": 2})
    return verdicts, writes


def _v(weakest: float, low: dict | None = None) -> dict:
    return {"scores": {"hook": weakest, "clarity": 9}, "fixes": ["say the twist first"], "low": low or {}, "need": 8}


def test_a_weak_script_is_rewritten_with_the_fixes_until_it_passes(loop):
    verdicts, writes = loop
    verdicts += [_v(5, {"hook": 5}), _v(8)]
    out = story._judge_loop(object(), CH, {"title": "draft 1"}, "Voyager", "short", None, lambda *a: None, {})
    assert out["title"] == "draft 2" and len(writes) == 1
    assert "hook 5" in writes[0] and "say the twist first" in writes[0] and "8/10" in writes[0]


def test_the_best_draft_is_kept_when_none_passes(loop):
    verdicts, writes = loop
    verdicts += [_v(5, {"hook": 5}), _v(7, {"hook": 7}), _v(6, {"hook": 6})]
    out = story._judge_loop(object(), CH, {"title": "draft 1"}, "Voyager", "short", None, lambda *a: None, {})
    assert len(writes) == 2 and out["title"] == "draft 2"          # weakest point 7 beats 5 and 6


def test_no_verdict_renders_the_script_as_written(loop):
    verdicts, writes = loop
    verdicts.append(ValueError("the judge gave no scores"))
    out = story._judge_loop(object(), CH, {"title": "draft 1"}, "Voyager", "short", None, lambda *a: None, {})
    assert out["title"] == "draft 1" and writes == []


def test_switched_off_means_no_judge_call(loop, monkeypatch):
    verdicts, writes = loop
    monkeypatch.setattr(story, "_script_judge_cfg", lambda: {"enabled": False, "rounds": 2})
    assert story._judge_loop(object(), CH, {"title": "x"}, "t", "short", None, lambda *a: None, {}) == {"title": "x"}


def test_the_real_settings_switch_it_on():
    import yaml
    from engine.config import ROOT
    sj = yaml.safe_load((ROOT / "config" / "settings.yaml").read_text(encoding="utf-8"))["script_judge"]
    assert sj.get("enabled") is True and True not in sj and sj["rounds"] >= 1
