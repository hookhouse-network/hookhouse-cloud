"""22 Nov: Cloudflare retired its two unbilled picture backups (SDXL-Lightning, DreamShaper-8-LCM) on 20 Nov: every call
answered HTTP 410 / code 5028 'Model has been deprecated' and the code skipped it without a word, so nobody noticed
that the free pictures beyond FLUX's 10,000 daily neurons were gone. A retired model now says so loudly and queues a
code fix; FLUX is the only Cloudflare model left; reset_at ignores old, expired marks."""
import time

import pytest

from engine import storyboard as sb
from engine.media import visuals


class Resp:
    def __init__(self, status: int, errors: list | None = None, image: str | None = None):
        self.status_code = status
        self.headers = {"content-type": "application/json"}
        self._j = {"success": image is not None, "errors": errors or [], "result": {"image": image} if image else {}}

    def json(self):
        return self._j


RETIRED = [{"code": 5028, "message": "AiError: Model has been deprecated: @cf/x was deprecated on 2026-11-20."}]


@pytest.fixture
def cf(monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "acct")
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "tok")
    reports = []
    from engine import heal
    monkeypatch.setattr(heal, "report", lambda area, err, **k: reports.append((area, str(err))) or {})
    return reports


def test_only_flux_is_left_in_the_cloudflare_models():
    assert [m for _, m in sb.CF_MODELS] == ["@cf/black-forest-labs/flux-1-schnell"]


def test_a_retired_model_is_reported_and_skipped_for_the_day(cf, monkeypatch):
    sent = []
    monkeypatch.setattr(sb.requests, "post", lambda url, **k: sent.append(url) or Resp(410, RETIRED))
    assert sb._cloudflare("a lighthouse at dusk", 1) is None
    assert len(sent) == 1                                          # no retries on a retired model
    assert cf and cf[0][0] == "pictures" and "retired" in cf[0][1] and "flux-1-schnell" in cf[0][1]
    assert not sb._open("cf_flux") and not sb._open("cloudflare")   # no call per scene for the rest of the hour
    assert sb._cloudflare("a lighthouse at dusk", 1) is None and len(sent) == 1


def test_visuals_ai_image_reports_a_retired_flux_once(cf, monkeypatch, tmp_path):
    monkeypatch.setattr(visuals, "CACHE", tmp_path)
    sent = []
    monkeypatch.setattr(visuals.requests, "post", lambda url, **k: sent.append(url) or Resp(410, RETIRED))
    assert visuals.ai_image("a lighthouse at dusk") is None
    assert visuals.ai_image("a quiet harbour") is None
    assert len(sent) == 1 and len(cf) == 1 and not sb._open("cloudflare")


def test_the_daily_limit_still_blocks_without_a_retired_report(cf, monkeypatch):
    monkeypatch.setattr(sb.requests, "post", lambda url, **k: Resp(429, [{"code": 4006, "message": "daily free allocation"}]))
    assert sb._cloudflare("p", 1) is None and not sb._open("cloudflare") and cf == []


def test_reset_at_ignores_expired_marks():
    now = time.time()
    sb._write(sb.QUOTA_PC, {"cf_sdxl": now - 86400, "cf_dreamshaper": now - 86400})
    assert sb.reset_at() == pytest.approx(now, abs=5)              # nothing blocked any more: now, not yesterday
    sb._write(sb.QUOTA_PC, {"cf_sdxl": now - 86400, "cloudflare": now + 9000, "probe:cloudflare": now + 3600,
                            "hf": now + 7000})
    assert sb.reset_at() == pytest.approx(now + 3600, abs=5)       # the next Cloudflare test call
