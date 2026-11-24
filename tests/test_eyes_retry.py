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
    monkeypatch.setattr(sb, "_EYES_OUT", {})
    p = tmp_path / "a.jpg"
    Image.new("RGB", (32, 32)).save(p)
    waits = []
    monkeypatch.setattr(sb.time, "sleep", waits.append)
    return p, waits


def _answers(monkeypatch, answers, urls=None):
    calls = []

    def post(url, *a, **k):
        calls.append(1)
        if urls is not None:
            urls.append((url.split("/models/")[1].split(":")[0], "responseMimeType" in k["json"]["generationConfig"]))
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


def test_every_model_busy_leaves_the_picture_unchecked_and_says_so(pic, monkeypatch, capsys):
    p, waits = pic
    n = len(sb.EYES_MODELS)
    calls = _answers(monkeypatch, [R(503, {}), R(503, {}), R(500, {})] * n)
    v = sb.eyes(p, "n", "s")
    assert v == {"score": -1, "text": False, "wrong": "", "ok": True} and len(calls) == 3 * n
    assert waits == list(sb.EYES_RETRY_S) * n and "eyes check skipped" in capsys.readouterr().out


DAY_OUT = R(429, {}, text='{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}')


def test_a_used_up_daily_quota_hands_the_check_to_the_next_model_for_the_day(pic, monkeypatch):
    """24 Nov: gemini-3.5-flash-lite was out from ~05:30 to the 13:30 reset and every picture went out unchecked."""
    p, waits = pic
    urls = []
    gemma = R(200, {"candidates": [{"content": {"parts": [{"text": '```json\n{"shows": "a pitch", "score": 8, '
                                                                    '"text": false, "wrong": "none"}\n```'}]}}]})
    calls = _answers(monkeypatch, [DAY_OUT, gemma, ok(7)], urls)
    assert sb.eyes(p, "n", "s")["score"] == 8 and len(calls) == 2 and waits == []      # Gemma's fenced JSON is read
    assert urls == [(sb.EYES_MODEL, True), (sb.EYES_MODELS[1], False)]               # Gemma: no JSON answer mode
    assert sb.eyes(p, "n", "s")["score"] == 7 and urls[-1][0] == sb.EYES_MODELS[1]   # the used-up one is skipped today


def test_every_model_used_up_leaves_it_unchecked(pic, monkeypatch):
    p, waits = pic
    calls = _answers(monkeypatch, [DAY_OUT] * len(sb.EYES_MODELS))
    assert sb.eyes(p, "n", "s")["score"] == -1 and len(calls) == len(sb.EYES_MODELS)
    assert sb.eyes(p, "n", "s")["score"] == -1 and len(calls) == len(sb.EYES_MODELS)   # nobody asked again today


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
