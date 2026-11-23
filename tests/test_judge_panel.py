"""Owner 23 Nov: "panel". The same script scored human_feel 5, 7, 6, 6, 7 from gpt-oss-120b and 7, 7, 6, 6, 7 from
Gemini Flash-Lite across one day, so one answer near the bar of 6 decided S10 partly by chance. Every verdict (script
judge and video judge) is now the average of the panel's models (gates.yaml potential.judge_panel); a resting member
gives its turn to the next one, so a verdict always averages as many answers as the panel has members."""
import pytest

from engine import potential_gate as pg

CH = {"id": "deep_blue_files", "name": "Deep Blue Files", "type": "story", "language": "en", "market": "US"}
REAL_PANEL = pg.judge_panel                        # conftest switches the panel off for every other test


class Res:
    def __init__(self, provider):
        self.provider = provider


class Brain:
    """Routes like the real Brain: the checker task goes to routes['checker'][0]."""
    def __init__(self, human: dict, resting=()):
        self.routes = {"checker": ["groq", "gemini_lite"]}
        self.human, self.resting, self.asked = human, set(resting), []

    def ask_json(self, task, prompt, temperature=0.4):
        name = self.routes[task][0]
        self.asked.append(name)
        if name in self.resting:
            raise RuntimeError(f"No AI model available for '{task}'")
        crit = pg._criteria(pg._cfg(), "story")
        scores = {c: 8 for c in crit}
        scores[pg.HUMAN] = self.human[name]
        return {"scores": scores, "fixes": [f"fix from {name}", "shared fix"], "summary": f"{name} says"}, Res(name)


@pytest.fixture
def panel(monkeypatch):
    members = ["groq", "gemini_lite"]
    monkeypatch.setattr(pg, "judge_panel", lambda cfg: REAL_PANEL({"judge_panel": members}))
    return members


def _judge(brain):
    return pg.judge({"id": "x", "out_dir": "unused", "topic": "t"}, CH, {"title": "A title", "description": "w"}, brain)


def test_the_live_setting_is_the_owners_panel():
    from engine.content_gate import config
    assert REAL_PANEL((config().get("potential") or {})) == ["groq", "gemini_lite"]


def test_each_member_judges_once_and_the_scores_are_averaged(panel):
    b = Brain({"groq": 5, "gemini_lite": 7})
    v = _judge(b)
    assert b.asked == ["groq", "gemini_lite"]
    assert v["scores"][pg.HUMAN] == 6.0 and v["model"] == "groq+gemini_lite"
    assert v["fixes"] == ["fix from groq", "shared fix", "fix from gemini_lite"]       # no repeats
    assert [p["model"] for p in v["panel"]] == ["groq", "gemini_lite"] and v["panel"][0]["scores"][pg.HUMAN] == 5


def test_a_resting_member_gives_its_turn_to_the_next_one(panel):
    b = Brain({"groq": 5, "gemini_lite": 7}, resting={"groq"})
    v = _judge(b)
    assert v["model"] == "gemini_lite+gemini_lite" and v["scores"][pg.HUMAN] == 7.0   # still two answers averaged


def test_no_answer_at_all_is_not_judged(panel):
    with pytest.raises(ValueError, match="no judge on the panel answered"):
        _judge(Brain({"groq": 5, "gemini_lite": 7}, resting={"groq", "gemini_lite"}))


def test_the_script_judge_holds_on_the_averaged_human_feel(panel, monkeypatch):
    monkeypatch.setattr(pg, "_criteria", lambda cfg, ctype: ["hook", pg.HUMAN])
    v = pg.judge_script({"title": "T", "beats": [{"narration": "a line"}]}, CH, "", Brain({"groq": 5, "gemini_lite": 6}))
    assert v["low"].get(pg.HUMAN) == 5.5                  # 5.5 < 6: held, though one member said 6
    v = pg.judge_script({"title": "T", "beats": [{"narration": "a line"}]}, CH, "", Brain({"groq": 5, "gemini_lite": 7}))
    assert pg.HUMAN not in v["low"]                       # 6.0 clears the bar


def test_without_a_panel_one_answer_from_the_checker_route(monkeypatch):
    monkeypatch.setattr(pg, "judge_panel", lambda cfg: [])
    b = Brain({"groq": 5, "gemini_lite": 7})
    v = _judge(b)
    assert b.asked == ["groq"] and v["model"] == "groq" and "panel" not in v
