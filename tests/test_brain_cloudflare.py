"""19 Nov: plans stalled on "No AI model available for 'writer'" (every free model resting). Cloudflare Workers AI
(our existing account, free daily neurons, commercial use) joins every route; its URL carries the account id."""
from engine.brain import providers
from engine.config import settings as load_settings


def test_cloudflare_models_are_in_every_route():
    cfg = load_settings()["brain"]
    for task, route in cfg["routes"].items():
        assert "cf_oss" in route and "cf_llama" in route, task
    for name in ("cf_oss", "cf_llama"):
        assert "${CLOUDFLARE_ACCOUNT_ID}" in cfg["providers"][name]["base_url"]


def test_account_id_fills_the_url(monkeypatch):
    p = providers.build("cf_oss", {"kind": "openai_compatible", "model": "@cf/openai/gpt-oss-120b",
                                   "key_env": "CLOUDFLARE_API_TOKEN",
                                   "base_url": "https://api.cloudflare.com/client/v4/accounts/${CLOUDFLARE_ACCOUNT_ID}/ai/v1"})
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "t")
    monkeypatch.delenv("CLOUDFLARE_ACCOUNT_ID", raising=False)
    assert not p.available()                     # no account id: skipped, never a broken URL
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "abc")
    assert p.available()
    sent = {}

    class R:
        status_code, text = 200, ""

        def json(self):
            return {"choices": [{"message": {"content": "hi"}}]}

    monkeypatch.setattr(providers.requests, "post", lambda url, **k: sent.setdefault("url", url) and R())
    assert p.complete("x") == "hi"
    assert sent["url"] == "https://api.cloudflare.com/client/v4/accounts/abc/ai/v1/chat/completions"
