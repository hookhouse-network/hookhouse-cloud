"""27 Nov (P5): every budget in one place (AI calls per provider with daily-limit hits, picture sources used up
until when, local pictures against the cap)."""
import json
import time

from engine import budgets


def test_ai_and_picture_budgets(tmp_path):
    day = time.strftime("%Y-%m-%d")
    u = tmp_path / "usage.json"
    u.write_text(json.dumps({day: {"writer|groq": {"calls": 5}, "checker|groq": {"calls": 2, "errors": {"x": 1}},
                                   "checker|cf_llama": {"calls": 0, "errors": {"daily_quota": 1}}}}))
    ai = budgets.ai_today(u, day)
    assert ai[0] == {"provider": "groq", "calls": 7, "errors": 1, "quota_hits": 0}
    assert next(r for r in ai if r["provider"] == "cf_llama")["quota_hits"] == 1
    q = tmp_path / "q.json"
    now = time.time()
    q.write_text(json.dumps({"cloudflare": now + 3600, "hf": now - 10, "probe:cloudflare": now}))
    pics = {p["source"]: p for p in budgets.pictures(q, now)}
    assert not pics["cloudflare"]["open"] and pics["cloudflare"]["until"] and pics["hf"]["open"]
    assert "probe:cloudflare" not in pics
