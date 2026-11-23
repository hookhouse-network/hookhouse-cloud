"""23 Nov: a busy Gemini (503 'currently experiencing high demand') made the eyes check skip the picture, and a skipped
check counts the picture as fine without anyone looking. A busy answer is now asked again twice; a used-up daily
quota or a refused request is not (waiting would not help)."""
import json

import pytest
import requests
from PIL import Image

from engine import storyboard as sb


class R:
    def __init__(self, status, payload=None, text=""):
        self.status_code, self._payload = status, payload
        self.text = text or json.dumps(payload or {})

    def json(self):
        return self._payload


def ok(score):
    return R(200, {"candidates": [{"content": {"parts": [{"text": json.dumps(
        {"shows": "a fish", "score": score, "text": False, "wrong": "none"})}]}}]})


@pytest.fixture
def pic(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    p = tmp_path / "a.jpg"
    Image.new("RGB", (32, 32)).save(p)
    waits = []
    monkeypatch.setattr(sb.time, "sleep", waits.append)
    return p, waits


def _answers(monkeypatch, answers):
    calls = []

    def post(*a, **k):
        calls.append(1)
        x = answers.pop(0)
        if isinstance(x, Exception):
            raise x
        return x
    monkeypatch.setattr(sb.requests, "post", post)
    return calls


def test_a_busy_answer_is_asked_again(pic, monkeypatch):
    p, waits = pic
    calls = _answers(monkeypatch, [R(503, {"error": {"code": 503, "status": "UNAVAILABLE"}}), ok(8)])
    v = sb.eyes(p, "n", "s")
    assert v["score"] == 8 and v["ok"] and len(calls) == 2 and waits == [sb.EYES_RETRY_S[0]]


def test_three_busy_answers_leave_the_picture_unchecked_and_say_so(pic, monkeypatch, capsys):
    p, waits = pic
    calls = _answers(monkeypatch, [R(503, {}), R(503, {}), R(500, {})])
    v = sb.eyes(p, "n", "s")
    assert v == {"score": -1, "text": False, "wrong": "", "ok": True} and len(calls) == 3
    assert waits == list(sb.EYES_RETRY_S) and "eyes check skipped" in capsys.readouterr().out


def test_a_used_up_daily_quota_is_not_asked_again(pic, monkeypatch):
    p, waits = pic
    calls = _answers(monkeypatch, [R(429, {}, text='{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}')])
    assert sb.eyes(p, "n", "s")["score"] == -1 and len(calls) == 1 and waits == []


def test_a_refused_request_is_not_asked_again(pic, monkeypatch):
    p, waits = pic
    calls = _answers(monkeypatch, [R(400, {"error": {"code": 400}})])
    assert sb.eyes(p, "n", "s")["score"] == -1 and len(calls) == 1


def test_a_dropped_connection_is_asked_again(pic, monkeypatch):
    p, waits = pic
    calls = _answers(monkeypatch, [requests.ConnectionError("reset"), ok(6)])
    v = sb.eyes(p, "n", "s")
    assert v["score"] == 6 and not v["ok"] and len(calls) == 2


def test_a_per_minute_limit_is_asked_again(pic, monkeypatch):
    p, waits = pic
    calls = _answers(monkeypatch, [R(429, {}, text='{"quotaId": "GenerateRequestsPerMinutePerProjectPerModel"}'), ok(9)])
    assert sb.eyes(p, "n", "s")["score"] == 9 and len(calls) == 2
