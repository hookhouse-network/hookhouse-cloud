"""24 Nov 02:00: Groq's gpt-oss-120b answered a probe normally (HTTP 200) while it was rested until 13:23: a "tokens per
day" 429 at 01:23 had benched it for the flat 12 hours, though Groq counts a rolling 24 hours and frees tokens within
minutes. Gemini's real daily limits say retryDelay ~41,000 s (back at ~13:30). A model now rests as long as the
provider itself says (plus a minute), never longer than the kind's default; the default only when it says nothing."""
import time

from engine.brain import providers as pv
from engine.brain.providers import Provider, ProviderError
from engine.brain.router import Brain, rest_minutes

DEFAULTS = {"rate_limit": 2, "daily_quota": 720, "error": 5, "busy": 1}


class _Resp:
    def __init__(self, status, text, headers=None):
        self.status_code, self.text, self.headers = status, text, headers or {}


GROQ_TPD = ('{"error":{"message":"Rate limit reached for model `openai/gpt-oss-120b` in organization `org_x` service '
            'tier `on_demand` on tokens per day (TPD): Limit 200000, Used 199500, Requested 2100. Please try again in '
            '7m12.5s. Need more tokens?","type":"tokens","code":"rate_limit_exceeded"}}')
GEMINI_DAY = ('{"error": {"code": 429, "message": "You exceeded your current quota", "details": [{"violations": '
              '[{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}]}, {"@type": '
              '"type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "41249s"}]}}')


def test_the_providers_own_wait_is_read():
    assert pv.retry_after(_Resp(429, GROQ_TPD)) == 7 * 60 + 12.5
    assert pv.retry_after(_Resp(429, GEMINI_DAY)) == 41249
    assert pv.retry_after(_Resp(429, "x", {"retry-after": "30"})) == 30
    assert pv.retry_after(_Resp(429, "Please try again in 1h2m3s")) == 3723
    assert pv.retry_after(_Resp(429, "Please try again in 450ms")) == 0.45
    assert pv.retry_after(_Resp(429, "quota exceeded")) is None


def test_a_429_carries_its_kind_and_wait():
    for text, kind, wait in ((GROQ_TPD, "daily_quota", 432.5), (GEMINI_DAY, "daily_quota", 41249)):
        try:
            pv._raise_for_status(_Resp(429, text), "m")
        except ProviderError as e:
            assert (e.kind, e.retry_s) == (kind, wait)
        else:
            raise AssertionError("no error")


def test_the_rest_follows_the_providers_word():
    assert round(rest_minutes(ProviderError("daily_quota", "groq", retry_s=432.5), DEFAULTS), 1) == 8.2
    assert round(rest_minutes(ProviderError("daily_quota", "gemini", retry_s=41249), DEFAULTS)) == 688
    assert rest_minutes(ProviderError("daily_quota", "x", retry_s=10 ** 6), DEFAULTS) == 720     # capped
    assert rest_minutes(ProviderError("daily_quota", "x"), DEFAULTS) == 720                       # said nothing
    assert rest_minutes(ProviderError("rate_limit", "x", retry_s=1800), DEFAULTS) == 31           # longer when told
    assert rest_minutes(ProviderError("busy", "x"), DEFAULTS) == 1


class _Groq(Provider):
    name = "groq"

    def available(self):
        return True

    def complete(self, prompt, system="", temperature=0.7):
        raise ProviderError("daily_quota", "groq: 429 tokens per day", retry_s=432.5)


class _Lite(Provider):
    name = "lite"

    def available(self):
        return True

    def complete(self, prompt, system="", temperature=0.7):
        return "ok"


def test_the_router_rests_groq_minutes_not_twelve_hours(tmp_path):
    b = Brain(providers={"groq": _Groq(), "lite": _Lite()}, routes={"checker": ["groq", "lite"]},
              cooldown_minutes=DEFAULTS, cooldown_file=tmp_path / "cool.json")
    assert b.ask("checker", "x").provider == "lite"
    until = b.cooldowns.state["groq"]
    assert 7 * 60 < until - time.time() < 10 * 60
