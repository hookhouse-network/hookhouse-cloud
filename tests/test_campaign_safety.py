"""Tests for campaign safety, payout tracking and brand-offer screening (no internet)."""
import sqlite3
import time

from engine import campaign_safety as cs


def _conn():
    return cs.connect(sqlite3.connect(":memory:"))


def test_banned_categories_are_blocked_and_normal_campaigns_pass():
    bad = cs.check_campaign({"name": "Stake casino clips", "url": "https://contentrewards.com/c/1",
                             "description": "Clip our sportsbook odds streams"})
    assert bad["verdict"] == "BLOCK" and any("gambling" in r for r in bad["block"])
    fx = cs.check_campaign({"name": "Funded account prop firm", "url": "https://whop.com/x"})
    assert fx["verdict"] == "BLOCK"
    ok = cs.check_campaign({"name": "Founder podcast clips", "brand": "Acme Podcast",
                            "url": "https://contentrewards.com/campaigns/acme", "cpm_usd": 1.2})
    assert ok["verdict"] == "ALLOW" and ok["payer_id"] == "content_rewards"


def test_unknown_crypto_and_fee_campaigns_are_not_allowed():
    assert cs.check_campaign({"name": "Clips", "url": "https://random-board.xyz/c"})["verdict"] == "REVIEW"
    assert cs.check_campaign({"name": "Clips", "url": "https://promote.fun/c/9"})["verdict"] == "BLOCK"
    fee = cs.check_campaign({"name": "Clips", "url": "https://contentrewards.com/c",
                             "description": "Pay a registration fee of $20 to unlock"})
    assert fee["verdict"] == "BLOCK"


def test_scam_brand_offers_are_caught():
    phish = cs.screen_offer("Hi! Nike wants a deal. Sign in with Google here: https://google-login.brand-verify.com/signin",
                            sender="partnerships@gmail.com", brand_domain="nike.com")
    assert phish["verdict"] == "BLOCK"
    zipped = cs.screen_offer("Contract attached. password: 1234", sender="team@nike.com", brand_domain="nike.com",
                             attachments=["brief.zip"])
    assert zipped["verdict"] == "BLOCK"
    clean = cs.screen_offer("Hello, we'd like to sponsor a video. Rates attached as text.", sender="ads@acme.com",
                            brand_domain="acme.com")
    assert clean["verdict"] == "OK"


def test_exposure_cap_stops_work_until_money_lands_and_trust_grows():
    conn = _conn()
    cs.ledger_add(conn, "content_rewards", "credited", amount_usd=30, fx_mid=85)       # ₹2,550 owed
    ok, why = cs.can_submit(conn, "content_rewards")
    assert not ok and "cap" in why
    for k in range(3):
        cs.ledger_add(conn, "content_rewards", "bank_received", amount_inr=850, occurred_at=time.time() + k)
    assert cs.payer_tier(conn, "content_rewards") == "trusted"
    assert cs.can_submit(conn, "content_rewards")[0]
    assert not cs.can_submit(conn, "promote_fun")[0]                                     # blocked payer


def test_alerts_for_overdue_money_fx_paperwork_and_gst():
    conn = _conn()
    old = time.time() - 40 * 86400
    cs.ledger_add(conn, "vyro", "credited", amount_usd=20, fx_mid=85, occurred_at=old)
    cs.ledger_add(conn, "youtube", "bank_received", amount_inr=1_600_000, fx_mid=85, fx_effective=82,
                  occurred_at=time.time() - 20 * 86400)
    msgs = " | ".join(m for _, m in cs.alerts(conn))
    assert "overdue" in msgs and "below mid-market" in msgs and "FIRA" in msgs and "GST" in msgs


def test_ad_label_length_rule():
    assert cs.disclosure_needed_s(30) == 10 and cs.disclosure_needed_s(6) == 3 and cs.disclosure_needed_s(300) == 3


def test_clip_maker_refuses_blocked_campaigns(monkeypatch):
    from engine import clips
    import pytest
    with pytest.raises(RuntimeError, match="blocked"):
        clips.make_clips(None, "nonexistent.mp4", {"id": "hot_take_hq", "style": {}},
                         campaign={"name": "Stake casino clips", "url": "https://contentrewards.com/c/1"})
