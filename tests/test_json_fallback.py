"""24 Nov 01:12: a Clutch Tales script reply was cut off mid-JSON ("Unbalanced JSON in reply: { "angles": [...") and
the retry went back to the same model, which cut it off again: BrainError, the slot was lost. A model that breaks the
JSON is skipped for the next try, and a reply the model itself reports as cut off sends the router straight on."""
import pytest

from engine.brain import providers as pv
from engine.brain.providers import Provider, ProviderError
from engine.brain.router import Brain, BrainError


class Fake(Provider):
    def __init__(self, name, replies):
        self.name, self.replies, self.calls = name, list(replies), 0

    def available(self):
        return True

    def complete(self, prompt, system="", temperature=0.7):
        self.calls += 1
        r = self.replies[min(self.calls - 1, len(self.replies) - 1)]
        if isinstance(r, Exception):
            raise r
        return r


def _brain(tmp_path, provs):
    return Brain(providers={p.name: p for p in provs}, routes={"script": [p.name for p in provs]},
                 cooldown_minutes={"rate_limit": 2, "daily_quota": 720, "error": 5},
                 cooldown_file=tmp_path / "cool.json")


CUT = '{"angles": ["The 93:20 code", "The red card trig'


def test_a_model_that_breaks_the_json_is_skipped_for_the_next_try(tmp_path):
    a, b = Fake("a", [CUT]), Fake("b", ['{"title": "Aguero 93:20"}'])
    data, res = _brain(tmp_path, [a, b]).ask_json("script", "write")
    assert data == {"title": "Aguero 93:20"} and res.provider == "b" and a.calls == 1


def test_every_model_broken_names_them_all(tmp_path):
    a, b, c = Fake("a", [CUT]), Fake("b", ["not json"]), Fake("c", ["{"])
    with pytest.raises(BrainError) as e:
        _brain(tmp_path, [a, b, c]).ask_json("script", "write")
    assert "a:" in str(e.value) and "b:" in str(e.value) and "c:" in str(e.value)
    assert (a.calls, b.calls, c.calls) == (1, 1, 1)


def test_a_single_model_route_still_gets_its_second_try(tmp_path):
    a = Fake("a", ["not json", '{"ok": true}'])
    data, res = _brain(tmp_path, [a]).ask_json("script", "write")
    assert data == {"ok": True} and a.calls == 2


def test_no_model_at_all_still_raises_at_once(tmp_path):
    a = Fake("a", [ProviderError("unavailable", "a: key rejected")])
    with pytest.raises(BrainError):
        _brain(tmp_path, [a]).ask_json("script", "write")


class _Resp:
    status_code, text = 200, ""

    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data


@pytest.mark.parametrize("kind,data", [
    ("gemini", {"candidates": [{"finishReason": "MAX_TOKENS", "content": {"parts": [{"text": CUT}]}}]}),
    ("openai", {"choices": [{"finish_reason": "length", "message": {"content": CUT}}]}),
])
def test_a_reply_cut_off_at_the_output_limit_is_too_big(monkeypatch, kind, data):
    monkeypatch.setenv("HH_TEST_KEY", "k")
    monkeypatch.setattr(pv.requests, "post", lambda *a, **k: _Resp(data))
    p = (pv.GeminiProvider("g", "gemini-x", "HH_TEST_KEY") if kind == "gemini"
         else pv.OpenAICompatibleProvider("o", "https://example.invalid/v1", "m", "HH_TEST_KEY"))
    with pytest.raises(ProviderError) as e:
        p.complete("write")
    assert e.value.kind == "too_big"


def test_a_finished_reply_passes(monkeypatch):
    monkeypatch.setenv("HH_TEST_KEY", "k")
    monkeypatch.setattr(pv.requests, "post", lambda *a, **k: _Resp(
        {"choices": [{"finish_reason": "stop", "message": {"content": '{"ok": 1}'}}]}))
    assert pv.OpenAICompatibleProvider("o", "https://example.invalid/v1", "m", "HH_TEST_KEY").complete("x") == '{"ok": 1}'
    monkeypatch.setattr(pv.requests, "post", lambda *a, **k: _Resp(
        {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": "hi"}]}}]}))
    assert pv.GeminiProvider("g", "gemini-x", "HH_TEST_KEY").complete("x") == "hi"


def test_the_router_moves_on_from_a_cut_off_model_without_resting_it(tmp_path):
    a = Fake("a", [ProviderError("too_big", "a: reply cut off at the model's output limit")])
    b = Fake("b", ['{"ok": true}'])
    brain = _brain(tmp_path, [a, b])
    data, res = brain.ask_json("script", "write")
    assert res.provider == "b" and not brain.cooldowns.resting("a")
