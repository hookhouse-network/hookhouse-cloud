"""23 Nov: the same script scored human_feel 4-5 from gpt-oss-120b (Groq, first in the checker route) and 6-7 from
Gemini Flash-Lite (the fallback while Groq rests), so the model that happened to have quota decided S10 for most
videos, and no verdict said which model judged. Every verdict now records it."""
from engine import potential_gate as pg
from engine import story

CH = {"id": "deep_blue_files", "name": "Deep Blue Files", "type": "story", "language": "en", "market": "US"}


class Res:
    provider = "groq"


class Brain:
    def ask_json(self, task, prompt, temperature=0.4):
        crit = pg._criteria(pg._cfg(), "story")
        return {"scores": {c: 7 for c in crit}, "fixes": ["x"], "summary": "ok"}, Res()


def test_every_verdict_records_the_model_that_judged_it(tmp_path):
    it = {"id": "x", "out_dir": str(tmp_path), "topic": "t"}
    v = pg.judge(it, CH, {"title": "A title", "description": "words"}, Brain())
    assert v["model"] == "groq" and v["scores"]


def test_a_brain_without_a_result_object_records_no_model(tmp_path):
    class Bare(Brain):
        def ask_json(self, task, prompt, temperature=0.4):
            data, _ = super().ask_json(task, prompt, temperature)
            return data, None
    v = pg.judge({"id": "x", "out_dir": str(tmp_path)}, CH, {"title": "A title", "description": "w"}, Bare())
    assert v["model"] == ""


def test_the_script_judge_log_names_the_model(monkeypatch):
    verdicts = [{"scores": {"hook": 5, "clarity": 9}, "fixes": ["x"], "low": {"hook": 5}, "need": 8, "model": "groq"},
                {"scores": {"hook": 9, "clarity": 9}, "fixes": [], "low": {}, "need": 8, "model": "gemini_lite"}]
    monkeypatch.setattr(pg, "judge_script", lambda *a, **k: verdicts.pop(0))
    monkeypatch.setattr(story, "_write_fresh", lambda *a, **k: {"title": "draft 2"})
    monkeypatch.setattr(story, "_script_judge_cfg", lambda: {"enabled": True, "rounds": 2})
    logs = []
    story._judge_loop(object(), CH, {"title": "draft 1"}, "t", "short", None, logs.append, {})
    assert any("(judge: groq); rewriting" in m for m in logs)
