"""22 Nov: Cloudflare's free allocation did not come back at 00:00 UTC (FLUX answered 4006 at 00:15 and 00:23 UTC;
community reports: hours later, ~24 h after the last use). One failed call at 00:15 UTC then blocked the pictures
until the NEXT 00:00 UTC, a whole day. A blocked Cloudflare source is now re-tested at most hourly by one 1-step FLUX
call; a pass opens every Cloudflare model again, a later 4006 blocks again, other sources keep their daily block."""
import json
import time

import pytest

from engine import storyboard as sb


class Resp:
    def __init__(self, ok: bool):
        self.status_code = 200 if ok else 429
        self._j = {"success": True, "result": {"image": "aGk="}} if ok else {
            "success": False, "errors": [{"code": 4006, "message": "you have used up your daily free allocation"}]}

    def json(self):
        return self._j


@pytest.fixture
def cf(monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "acct")
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "tok")
    calls, answers = [], []

    def post(url, headers=None, json=None, timeout=None):
        calls.append(json)
        return Resp(answers.pop(0) if answers else False)
    monkeypatch.setattr(sb.requests, "post", post)
    return calls, answers


def _test_due_now(path):
    q = json.loads(path.read_text())
    q.update({k: time.time() - 1 for k in q if k.startswith("probe:")})
    path.write_text(json.dumps(q))


def test_a_block_waits_an_hour_then_one_cheap_test_call(cf):
    calls, answers = cf
    sb._block("cloudflare")
    assert not sb._open("cloudflare") and calls == []                     # no call within the hour
    # retries wait for the test, not a day (26 Nov: within an hour of UTC midnight the daily reset comes first)
    assert sb.reset_at() == pytest.approx(min(time.time() + sb.PROBE_S, float(sb._quota()["cloudflare"])), abs=5)
    _test_due_now(sb.QUOTA_PC)
    answers.append(False)
    assert not sb._open("cloudflare")
    assert calls == [{"prompt": "a red apple on a wooden table", "steps": 1}]   # ~10 neurons if it draws
    assert not sb._open("cloudflare") and len(calls) == 1                 # still used up: next test an hour later


def test_a_passing_test_call_opens_every_cloudflare_model(cf):
    calls, answers = cf
    for s in ("cf_flux", "cloudflare"):
        sb._block(s)
    _test_due_now(sb.QUOTA_PC)
    answers.append(True)
    assert sb._open("cloudflare") and sb._open("cf_flux") and sb._open("cf_sdxl") and len(calls) == 1
    sb._block("cloudflare")                                               # a real 4006 later blocks it again
    assert not sb._open("cloudflare") and len(calls) == 1


def test_an_old_block_in_the_cloud_copy_is_tested_at_once(cf, monkeypatch):
    calls, answers = cf
    monkeypatch.delenv("HF_TOKEN", raising=False)
    tomorrow = time.time() + 20 * 3600
    sb.QUOTA.write_text(json.dumps({"cloudflare": tomorrow, "cf_flux": tomorrow}))   # written by the old code
    answers.append(True)
    assert not sb.images_blocked() and len(calls) == 1                    # the queue makes story videos again
    assert "ok:cloudflare" in json.loads(sb.QUOTA_PC.read_text())         # the PC's own mark (pulls replace QUOTA)


def test_other_sources_keep_their_daily_block(cf):
    calls, _answers = cf
    sb._block("hf")
    q = json.loads(sb.QUOTA_PC.read_text())
    assert "probe:hf" not in q and not sb._open("hf") and calls == []
    assert sb.reset_at() == q["hf"] > time.time()                         # hf: the documented daily reset
