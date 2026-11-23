"""24 Nov (P5 model tiers): the strong models ran out of their daily quota by 01:20 while about 20 small jobs share
their route. Every call is now counted per day, task and model (calls, characters in/out, errors by kind), so the
routes can be re-planned from numbers. The PC keeps its own file (data/pc: the cloud's data/state replaces the PC's
on every loop); the cloud's lives in data/state."""
import json
import time

from engine.brain import router
from engine.brain.providers import Provider, ProviderError
from engine.brain.router import Brain, Usage


class P(Provider):
    def __init__(self, name, reply=None, error=None):
        self.name, self.reply, self.error = name, reply, error

    def available(self):
        return True

    def complete(self, prompt, system="", temperature=0.7):
        if self.error:
            raise ProviderError(self.error, f"{self.name}: 429", retry_s=60)
        return self.reply


def test_every_call_and_error_is_counted_per_task_and_model(tmp_path):
    b = Brain(providers={"groq": P("groq", error="daily_quota"), "lite": P("lite", '{"ok": 1}')},
              routes={"checker": ["groq", "lite"], "writer": ["lite"]},
              cooldown_minutes={"daily_quota": 720}, cooldown_file=tmp_path / "cool.json")
    b.ask_json("checker", "is it true?", system="be strict")
    b.ask("writer", "x" * 100)
    day = json.loads((tmp_path / "brain_usage.json").read_text(encoding="utf-8"))[time.strftime("%Y-%m-%d")]
    assert day["checker|groq"]["errors"] == {"daily_quota": 1} and day["checker|groq"]["calls"] == 0
    assert day["checker|lite"]["calls"] == 1 and day["checker|lite"]["in"] == len("is it true?") + len("be strict")
    assert day["writer|lite"] == {"calls": 1, "in": 100, "out": len('{"ok": 1}')}


def test_only_the_last_days_are_kept(tmp_path):
    p = tmp_path / "u.json"
    p.write_text(json.dumps({f"2026-11-{d:02d}": {"writer|lite": {"calls": 1, "in": 1, "out": 1}}
                             for d in range(1, 12)}), encoding="utf-8")
    Usage(p, keep_days=8).add("writer", "lite", 1, 1)
    days = sorted(json.loads(p.read_text(encoding="utf-8")))
    assert len(days) == 8 and days[-1] == time.strftime("%Y-%m-%d")


def test_a_broken_file_never_stops_a_call(tmp_path):
    p = tmp_path / "u.json"
    p.write_text("{not json", encoding="utf-8")
    Usage(p).add("writer", "lite", 5, 5)
    assert json.loads(p.read_text(encoding="utf-8"))[time.strftime("%Y-%m-%d")]["writer|lite"]["calls"] == 1


def test_the_pc_and_the_cloud_keep_their_own_file(monkeypatch):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    assert router.usage_path().parts[-2:] == ("pc", "brain_usage.json")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    assert router.usage_path().parts[-2:] == ("state", "brain_usage.json")
