"""Tests for the Week 1 foundation: brain router, memory, campaigns, rule checker,
schedule and license checker. Run: python -m pytest -q"""
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from engine import campaigns as camp
from engine.brain.providers import Provider, ProviderError
from engine.brain.router import Brain, BrainError, extract_json
from engine.licenses import check as license_check
from engine.memory.store import HashEmbedder, Memory
from engine.schedule import next_slots


# ---------- brain router ----------
class FakeProvider(Provider):
    def __init__(self, name, reply=None, error=None, has_key=True):
        self.name, self.reply, self.error, self.has_key, self.calls = name, reply, error, has_key, 0

    def available(self):
        return self.has_key

    def complete(self, prompt, system="", temperature=0.7):
        self.calls += 1
        if self.error:
            raise ProviderError(self.error, f"{self.name} failed")
        return self.reply


def make_brain(tmp_path, providers, route):
    return Brain(providers={p.name: p for p in providers}, routes={"writer": route},
                 cooldown_minutes={"rate_limit": 2, "daily_quota": 720, "error": 5},
                 cooldown_file=tmp_path / "cool.json")


def test_router_uses_first_available(tmp_path):
    a, b = FakeProvider("a", "hi from a"), FakeProvider("b", "hi from b")
    r = make_brain(tmp_path, [a, b], ["a", "b"]).ask("writer", "x")
    assert r.provider == "a" and b.calls == 0


def test_router_falls_back_and_rests_quota(tmp_path):
    a = FakeProvider("a", error="daily_quota")
    b = FakeProvider("b", "hi from b")
    brain = make_brain(tmp_path, [a, b], ["a", "b"])
    assert brain.ask("writer", "x").provider == "b"
    assert brain.status()["a"].startswith("resting")
    brain.ask("writer", "y")
    assert a.calls == 1  # not retried while resting


def test_router_skips_missing_keys_and_errors_clearly(tmp_path):
    a = FakeProvider("a", "x", has_key=False)
    with pytest.raises(BrainError, match="No AI model available"):
        make_brain(tmp_path, [a], ["a"]).ask("writer", "x")


def test_router_all_fail(tmp_path):
    a, b = FakeProvider("a", error="error"), FakeProvider("b", error="rate_limit")
    with pytest.raises(BrainError, match="All models failed"):
        make_brain(tmp_path, [a, b], ["a", "b"]).ask("writer", "x")


def test_extract_json_variants():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('Sure! Here it is: {"a": {"b": "x}y"}} hope that helps') == {"a": {"b": "x}y"}}
    assert extract_json("[1, 2]") == [1, 2]


def test_ask_json_retries_bad_json(tmp_path):
    class Flaky(FakeProvider):
        def complete(self, prompt, system="", temperature=0.7):
            self.calls += 1
            return "not json" if self.calls == 1 else '{"ok": true}'
    data, _ = make_brain(tmp_path, [Flaky("a")], ["a"]).ask_json("writer", "x")
    assert data == {"ok": True}


# ---------- memory ----------
def test_memory_prefers_similar_winners(tmp_path):
    mem = Memory(tmp_path / "m.db", HashEmbedder())
    mem.add("hook", "He turned down one billion dollars", performance=900_000)
    mem.add("hook", "He turned down one billion dollars from Google", performance=1_000)
    mem.add("hook", "The best pasta recipe in Italy", performance=2_000_000)
    hits = mem.search("turned down billion dollars", kind="hook", k=3)
    assert "billion" in hits[0].text and hits[0].performance == 900_000
    assert "pasta" in hits[-1].text


def test_memory_channel_filter_includes_global(tmp_path):
    mem = Memory(tmp_path / "m.db", HashEmbedder())
    mem.add("playbook", "Hook in the first two seconds")
    mem.add("playbook", "Use cricket stats graphics", channel="cricket_ke_kisse")
    mem.add("playbook", "Use dark foggy visuals", channel="unsolved_after_dark")
    texts = [h.text for h in mem.search("visuals and hooks", kind="playbook", channel="cricket_ke_kisse", k=5)]
    assert "Use dark foggy visuals" not in texts and len(texts) == 2


# ---------- campaigns ----------
CFG = {"auto_stop_budget_pct": 30, "min_cpm_usd": 0.5, "home_country": "IN"}


def base_campaign(**over):
    c = camp.normalize({"name": "Big Podcast Clips", "cpm_usd": 1.5, "budget_left_pct": 80,
                        "platforms": ["youtube_shorts", "instagram_reels", "tiktok"],
                        "content_type": "podcast clips", "allowed_sources": ["youtube.com/@bigpodcast"]})
    c.update(over)
    return c


def test_india_verdicts():
    assert camp.india_verdict(base_campaign())[0] == "YES"
    assert camp.india_verdict(base_campaign(clipper_residency=["United States"]))[0] == "NO"
    assert camp.india_verdict(base_campaign(platforms=["tiktok"]))[0] == "NO"
    assert camp.india_verdict(base_campaign(geo_requirement={"us_min_pct": 70}))[0] == "MAYBE"


def test_scores_good_vs_bad():
    good, _ = camp.score_campaign(base_campaign(), CFG)
    strict, _ = camp.score_campaign(base_campaign(geo_requirement={"us_min_pct": 70}), CFG)
    cheap, _ = camp.score_campaign(base_campaign(cpm_usd=0.2), CFG)
    blocked, _ = camp.score_campaign(base_campaign(clipper_residency=["US"]), CFG)
    assert good > strict > blocked and cheap <= 3 and blocked == 0 and good >= 8


def test_budget_auto_stop_and_resume():
    c = camp.evaluate(base_campaign(budget_left_pct=20), CFG)
    assert c["status"] == "paused_low_budget"
    c["budget_left_pct"] = 60
    assert camp.evaluate(c, CFG)["status"] == "active"


def test_account_country_rule():
    c = base_campaign(geo_requirement={"tier1_min_pct": 40})
    assert not camp.account_qualifies(c, None)[0]
    assert not camp.account_qualifies(c, {"us_pct": 20, "tier1_pct": 30})[0]
    assert camp.account_qualifies(c, {"us_pct": 35, "tier1_pct": 55})[0]


# (the old clip rule checker, engine/compliance.py, was replaced by engine/campaign_gate.py: tests/test_campaign_gate.py)


# ---------- schedule ----------
def test_next_slots_rolls_to_next_day():
    ist = ZoneInfo("Asia/Kolkata")
    after = datetime(2026, 11, 9, 23, 50, tzinfo=ist)
    slots = next_slots("US", 3, after=after, slots=["22:30", "23:45", "05:00", "06:30"], tz="Asia/Kolkata")
    assert [s.strftime("%d %H:%M") for s in slots] == ["10 05:00", "10 06:30", "10 22:30"]


# ---------- licenses ----------
def test_license_checker():
    assert license_check(installed=set()) == []
    bad = {"allowed_licenses": ["MIT"], "components": [{"name": "x", "license": "CC-BY-NC-4.0"}],
           "denied_packages": ["f5-tts"]}
    problems = license_check(bad, installed={"f5-tts"})
    assert len(problems) == 2


# ---------- .env loading ----------
def test_env_inline_comments_are_ignored(tmp_path, monkeypatch):
    from engine.config import load_env
    for k in ("A_KEY", "B_KEY", "C_KEY", "D_KEY"):
        monkeypatch.delenv(k, raising=False)
    env = tmp_path / ".env"
    env.write_text('A_KEY=        # get it from the website\nB_KEY=abc123  # note\n'
                   'C_KEY="x # y"\n# D_KEY=zzz\n', encoding="utf-8")
    load_env(env)
    import os
    assert "A_KEY" not in os.environ
    assert os.environ["B_KEY"] == "abc123" and os.environ["C_KEY"] == "x # y"
    assert "D_KEY" not in os.environ
