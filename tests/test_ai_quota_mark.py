"""21 Nov: Cloudflare's 'daily free allocation used up' (429 / code 4006) was swallowed by visuals.ai_image, so
storyboard.images_blocked() stayed False and story videos shipped with word cards (then held by the gate)."""
from engine import storyboard
from engine.media import visuals


class Resp:
    status_code = 429

    def json(self):
        return {"success": False, "errors": [{"code": 4006, "message": "used up your daily free allocation"}]}


def test_used_up_allowance_is_marked_and_not_retried(monkeypatch, tmp_path):
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "a")
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "t")
    monkeypatch.setattr(storyboard, "QUOTA", tmp_path / "q.json")
    monkeypatch.setattr(storyboard, "QUOTA_PC", tmp_path / "qpc.json")
    calls = []
    monkeypatch.setattr(visuals.requests, "post", lambda *a, **k: calls.append(1) or Resp())
    assert visuals.ai_image("a red apple", "calm") is None
    assert not storyboard._open("cloudflare")                       # marked until the daily reset
    assert visuals.ai_image("a green apple", "calm") is None and len(calls) == 1   # no second wasted call


def test_pictures_use_schnells_four_steps(monkeypatch, tmp_path):
    """22 Nov: 8 steps cost 96 of the 10,000 free daily neurons per picture (4 tiles x 4.8 + 8 x 9.6); schnell is
    distilled for 1-4 steps, so 4 (58 neurons) gives ~67 % more pictures a day. Settings flux_steps, clamped 1-8."""
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "a")
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "t")
    monkeypatch.setattr(storyboard, "QUOTA", tmp_path / "q.json")
    monkeypatch.setattr(storyboard, "QUOTA_PC", tmp_path / "qpc.json")
    sent = []
    monkeypatch.setattr(visuals.requests, "post", lambda *a, **k: sent.append(k["json"]) or Resp())
    visuals.ai_image("a lighthouse in fog", "calm")
    assert sent and sent[0]["steps"] == 4
    monkeypatch.setattr("engine.config.settings", lambda: {"flux_steps": 30})
    assert visuals.flux_steps() == 8
    monkeypatch.setattr("engine.config.settings", lambda: {"flux_steps": "x"})
    assert visuals.flux_steps() == 4
