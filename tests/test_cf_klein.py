"""23 Nov: Cloudflare's own usage records showed a FLUX-schnell picture costs 172.8 neurons (the step price is per
512x512 tile), so the free 10,000 a day draw ~57 pictures, and a Short crops each 1024x1024 square to ~576x1024.
FLUX.2 [klein] 4B costs 26.05 neurons per output tile with its 4 steps included, billed on the longer side: a 576x1024
picture in the Short's own shape is ~104 neurons (~96 a day). It is a second Cloudflare model behind settings.yaml
cf_picture_models, with its own request format (multipart form data, a size and a seed)."""
import base64
import io
import json
import time

import pytest
from PIL import Image

from engine import config
from engine import storyboard as sb

KLEIN = "@cf/black-forest-labs/flux-2-klein-4b"
FLUX = "@cf/black-forest-labs/flux-1-schnell"


def _jpeg(size) -> str:
    b = io.BytesIO()
    Image.new("RGB", size, (30, 90, 160)).save(b, "JPEG")
    return base64.b64encode(b.getvalue()).decode()


class Resp:
    def __init__(self, status=200, image=None, errors=None):
        self.status_code = status
        self.headers = {"content-type": "application/json"}
        self._j = {"success": image is not None, "errors": errors or [], "result": {"image": image} if image else {}}

    def json(self):
        return self._j


@pytest.fixture
def cf(monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "acct")
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "tok")
    monkeypatch.setattr(sb, "_CF_SAID", set())
    order = {"cf_picture_models": ["klein", "flux"]}
    monkeypatch.setattr(config, "settings", lambda: order)
    calls, answers = [], []

    def post(url, headers=None, json=None, files=None, timeout=None):
        calls.append({"model": url.split("/ai/run/")[1], "json": json,
                      "form": {k: v[1] for k, v in (files or {}).items()}})
        return answers.pop(0) if answers else Resp(429, errors=[{"code": 4006, "message": "daily free allocation"}])
    monkeypatch.setattr(sb.requests, "post", post)
    return calls, answers, order


def test_the_default_order_is_flux_alone(monkeypatch):
    monkeypatch.setattr(config, "settings", lambda: {})
    assert sb.cf_models() == [("flux", FLUX)]


def test_unknown_names_and_a_broken_setting_keep_a_working_order(monkeypatch):
    monkeypatch.setattr(config, "settings", lambda: {"cf_picture_models": ["sdxl", "nope"]})
    assert sb.cf_models() == [("flux", FLUX)]
    monkeypatch.setattr(config, "settings", lambda: {"cf_picture_models": ["klein", "klein", "flux"]})
    assert sb.cf_models() == [("klein", KLEIN), ("flux", FLUX)]

    def broken():
        raise ValueError("bad yaml")
    monkeypatch.setattr(config, "settings", broken)
    assert sb.cf_models() == [("flux", FLUX)]


def test_klein_draws_the_short_in_its_own_shape_and_comes_back_full_size(cf):
    calls, answers, _ = cf
    answers.append(Resp(image=_jpeg((576, 1024))))
    data = sb._cloudflare("a lighthouse at dusk", 7, (1080, 1920))
    assert Image.open(io.BytesIO(data)).size == (1080, 1920)     # never under 650 px: no small framed card
    assert calls == [{"model": KLEIN, "json": None,
                      "form": {"prompt": "a lighthouse at dusk", "width": "576", "height": "1024", "seed": "7"}}]


def test_a_long_video_gets_a_landscape_klein_picture(cf):
    calls, answers, _ = cf
    answers.append(Resp(image=_jpeg((1024, 576))))
    data = sb._cloudflare("a harbour at night", 3, (1920, 1080))
    assert Image.open(io.BytesIO(data)).size == (1920, 1080)
    assert (calls[0]["form"]["width"], calls[0]["form"]["height"]) == ("1024", "576")


def test_a_flux_square_is_kept_as_it_is(cf):
    calls, answers, order = cf
    order["cf_picture_models"] = ["flux"]
    raw = _jpeg((1024, 1024))
    answers.append(Resp(image=raw))
    assert sb._cloudflare("p", 1) == base64.b64decode(raw)
    assert calls == [{"model": FLUX, "json": {"prompt": "p", "steps": 4}, "form": {}}]


def test_the_daily_limit_tries_each_model_once_then_rests(cf):
    calls, _answers, _ = cf
    assert sb._cloudflare("p", 1) is None
    assert [c["model"] for c in calls] == [KLEIN, FLUX]           # a 4006 answer costs nothing
    assert not sb._open("cloudflare") and not sb._open("cf_klein")
    assert sb._cloudflare("p", 1) is None and len(calls) == 2    # no call per scene for the rest of the hour


def test_an_odd_klein_answer_falls_back_to_flux_and_is_said_once(cf, capsys):
    calls, answers, _ = cf
    bad = [{"code": 5006, "message": "Error: required properties at '/' are 'prompt'"}]
    raw = _jpeg((1024, 1024))
    answers.extend([Resp(400, errors=bad), Resp(image=raw), Resp(400, errors=bad), Resp(image=raw)])
    assert sb._cloudflare("p", 1) == base64.b64decode(raw)
    assert sb._cloudflare("q", 2) == base64.b64decode(raw)
    assert [c["model"] for c in calls] == [KLEIN, FLUX, KLEIN, FLUX]
    assert capsys.readouterr().out.count("Cloudflare klein gave no picture (HTTP 400") == 1
    assert sb._open("cloudflare") and sb._open("cf_klein")       # not a quota answer: nothing blocked


def test_a_retired_klein_is_reported_and_flux_draws(cf, monkeypatch):
    calls, answers, _ = cf
    reports = []
    from engine import heal
    monkeypatch.setattr(heal, "report", lambda area, err, **k: reports.append(str(err)) or {})
    raw = _jpeg((1024, 1024))
    answers.extend([Resp(410, errors=[{"code": 5028, "message": "Model has been deprecated"}]), Resp(image=raw)])
    assert sb._cloudflare("p", 1) == base64.b64decode(raw)
    assert reports and "flux-2-klein-4b" in reports[0] and not sb._open("cf_klein") and sb._open("cf_flux")


def test_the_hourly_test_call_uses_the_first_model_at_its_cheapest_size(cf):
    calls, answers, _ = cf
    sb._block("cloudflare")
    q = json.loads(sb.QUOTA_PC.read_text())
    q.update({k: time.time() - 1 for k in q if k.startswith("probe:")})
    sb.QUOTA_PC.write_text(json.dumps(q))
    answers.append(Resp(image=_jpeg((256, 256))))
    assert sb._open("cloudflare") and sb._open("cf_klein") and len(calls) == 1
    assert calls[0]["model"] == KLEIN and (calls[0]["form"]["width"], calls[0]["form"]["height"]) == ("256", "256")
