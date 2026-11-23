"""23 Nov: 30 of 58 scripts since 20 Nov were written by Flash-Lite: the writer route reached it 4th while
gemini-3.6/3.7-flash sat 7th/8th unused, and 20 small writing jobs share that route. The main script has its own
route (every full model before any Lite one); the small jobs keep "writer"."""
import yaml

from engine import story
from engine.config import ROOT

LITE = {"gemini_lite", "gemini31_lite", "gemini35_lite", "groq20", "gemma31", "gemma26"}


def test_the_script_route_tries_every_full_model_before_any_lite_one():
    routes = yaml.safe_load((ROOT / "config" / "settings.yaml").read_text(encoding="utf-8"))["brain"]["routes"]
    script = routes["script"]
    first_lite = min(i for i, n in enumerate(script) if n in LITE)
    assert {"gemini37", "gemini36", "gemini35", "gemini", "gemini3", "groq"} <= set(script[:first_lite])
    assert set(script) >= set(routes["writer"])                 # nothing the writer route had is lost


class Res:
    provider = "test"


class Brain:
    def __init__(self, routes):
        self.routes, self.tasks = routes, []

    def ask_json(self, task, prompt, system="", temperature=0.4):
        self.tasks.append(task)
        return {"title": "T", "beats": [{"narration": "x"}]}, Res()


CH = {"id": "cosmos_unboxed", "name": "Cosmos Unboxed", "language": "en", "niche": "space", "market": "US",
      "content_rules": {}, "style": {}, "voice": {"id": "bf_emma"}}


def test_the_main_script_uses_the_script_route():
    b = Brain({"script": ["gemini37"], "writer": ["gemini_lite"]})
    story.write_script(b, CH, "Apollo 13")
    assert b.tasks == ["script"]


def test_a_brain_without_a_script_route_still_writes():
    b = Brain({"writer": ["gemini_lite"]})
    story.write_script(b, CH, "Apollo 13")
    assert b.tasks == ["writer"]
