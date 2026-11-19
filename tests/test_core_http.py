"""engine.core.http: one retry policy for safe network calls; POST never repeats."""
import pytest
import requests

from engine.core.http import _Http


class R:
    def __init__(self, code, headers=None):
        self.status_code, self.headers = code, headers or {}


def _fake(monkeypatch, method, answers):
    calls = []

    def f(url, **kw):
        calls.append(url)
        a = answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return a
    monkeypatch.setattr(requests, method, f)
    return calls


def test_get_retries_server_errors_then_succeeds(monkeypatch):
    calls = _fake(monkeypatch, "get", [R(503), requests.ConnectionError(), R(200)])
    waits = []
    h = _Http(waits=(1, 2, 3), sleep=waits.append)
    assert h.get("u", timeout=5).status_code == 200
    assert len(calls) == 3 and waits == [1, 2]


def test_retry_after_is_respected_and_capped(monkeypatch):
    _fake(monkeypatch, "get", [R(429, {"Retry-After": "500"}), R(200)])
    waits = []
    _Http(waits=(1,), sleep=waits.append).get("u")
    assert waits == [60.0]


def test_last_answer_returned_after_all_tries(monkeypatch):
    calls = _fake(monkeypatch, "put", [R(500), R(500), R(502)])
    r = _Http(waits=(0, 0), sleep=lambda s: None).put("u")
    assert r.status_code == 502 and len(calls) == 3


def test_connection_error_raised_when_tries_run_out(monkeypatch):
    _fake(monkeypatch, "get", [requests.Timeout(), requests.Timeout()])
    with pytest.raises(requests.Timeout):
        _Http(waits=(0,), sleep=lambda s: None).get("u")


def test_post_is_never_retried(monkeypatch):
    calls = _fake(monkeypatch, "post", [R(503), R(200)])
    assert _Http(waits=(0, 0), sleep=lambda s: None).post("u").status_code == 503
    assert len(calls) == 1


def test_client_errors_are_not_retried(monkeypatch):
    calls = _fake(monkeypatch, "get", [R(404), R(200)])
    assert _Http(waits=(0,), sleep=lambda s: None).get("u").status_code == 404 and len(calls) == 1


def test_kaggle_never_starts_for_the_business(monkeypatch):
    """19 Nov: Kaggle's terms are personal/non-commercial and ban server farming (owner: not another GitHub)."""
    from engine import kaggle_gpu
    monkeypatch.delenv("KAGGLE_PERSONAL_TEST", raising=False)
    with pytest.raises(kaggle_gpu.KaggleNotAllowed):
        kaggle_gpu.start()
