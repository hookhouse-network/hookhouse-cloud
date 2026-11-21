"""Phase 2 (Hindi voice throughput): Indic Parler-TTS took ~50 min for 9 lines on the PC CPU, so Hindi videos slipped
past their slots. Each video now has a time budget; a measured speed that predicts more, or a run that hits the
budget, raises ParlerTooSlow and the story maker uses Kokoro (it already falls back on any Parler error)."""
import subprocess

import pytest

from engine.media import parler_voice as pv

CH = {"id": "itihaas_ke_raaz", "language": "hi", "voice": {}}


@pytest.fixture
def ready(monkeypatch, tmp_path):
    monkeypatch.setattr(pv, "available", lambda: True)
    monkeypatch.setattr(pv, "token", lambda: "x")
    monkeypatch.setattr(pv, "description_for", lambda ch: "a calm voice")
    return tmp_path


def _beats(n):
    return [{"narration": f"पंक्ति {i}"} for i in range(n)]


def test_budget_per_format_and_channel_override():
    assert pv.budget_s(CH, "short") == 20 * 60 and pv.budget_s(CH, "long") == 75 * 60
    assert pv.budget_s({"voice": {"parler_budget_short_min": 8}}, "short") == 8 * 60


def test_a_slow_measured_speed_skips_parler_before_it_starts(ready):
    pv._learn_rate(9 * 330, 9)                                   # 50 min for 9 lines = 330 s a line
    assert 320 < pv.rate_s() < 340
    ran = []
    with pytest.raises(pv.ParlerTooSlow, match="predicted"):
        pv.batch(_beats(12), ready, CH, log=lambda *_: None, run=lambda *a, **k: ran.append(1))
    assert ran == []                                             # never even started: Kokoro takes over at once


def test_a_run_that_hits_the_budget_is_stopped_and_remembered(ready):
    def slow(cmd, **kw):
        assert kw["timeout"] == 20 * 60
        raise subprocess.TimeoutExpired(cmd, kw["timeout"])
    with pytest.raises(pv.ParlerTooSlow, match="budget"):
        pv.batch(_beats(4), ready, CH, log=lambda *_: None, run=slow)
    assert pv.rate_s() is not None                               # next time it predicts instead of waiting


def test_a_fast_run_passes_and_teaches_the_speed(ready):
    def fast(cmd, **kw):
        for i in range(3):
            (ready / f"parler_{i:02d}.wav").write_bytes(b"RIFF")
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")
    outs = pv.batch(_beats(3), ready, CH, log=lambda *_: None, run=fast)
    assert len(outs) == 3 and pv.rate_s() is not None and pv.rate_s() < 5
