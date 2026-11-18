"""Daily campaign finder rules (can we fulfil it without breaking policy?) and the pitch pipeline."""
import sqlite3

from engine import pitch
from engine.discover import fit_check, to_campaign


def _item(**kw):
    base = {"title": "Some Podcast Clips", "brand": "Some Podcast", "brandSlug": "some-podcast", "seriesSlug": "clips",
            "board": "Content Rewards", "campaignType": "clipping", "platforms": ["instagram", "youtube"],
            "ratePer1kUsd": 1.5, "netPer1kUsd": 1.35, "budgetLeftUsd": 900, "budgetTotalUsd": 1000, "niche": "podcast",
            "pageUrl": "https://clippingalpha.com/x", "alphaScore": 80, "openJoin": True}
    base.update(kw)
    return base


def _brief(**kw):
    b = {"wants": {"footage": "Brand footage only", "languages": [], "audienceCountries": [], "avoid": []},
         "checklist": [{"kind": "disclosure", "text": "Add #ad"}], "join": {"minViews": None, "maxPayoutUsd": 300},
         "briefUrl": "https://contentrewards.com/c/campaigns/abc"}
    for k, v in kw.items():
        b[k] = v
    return b


def test_plain_podcast_clipping_fits_and_goes_to_hot_take():
    brief = _brief()
    verdict, why, acct = fit_check(to_campaign(_item(), brief), brief)
    assert verdict == "OK" and acct == "hot_take_hq"


def test_rejections_tiktok_only_election_regulated_language_tool_face():
    b = _brief()
    assert fit_check(to_campaign(_item(platforms=["tiktok"]), b), b)[0] == "NO"
    assert fit_check(to_campaign(_item(election=True), b), b)[0] == "NO"
    assert fit_check(to_campaign(_item(ageRestricted=True), b), b)[0] == "NO"
    assert fit_check(to_campaign(_item(title="Game Trailer Spanish Clipping"), b), b)[0] == "NO"
    tool = _brief(checklist=[{"kind": "do", "text": "Clips must be made with WayinVideo"}])
    assert fit_check(to_campaign(_item(), tool), tool)[0] == "NO"
    face = _brief(checklist=[{"kind": "do", "text": "Film yourself talking to camera about the product"}])
    assert fit_check(to_campaign(_item(campaignType="ugc"), face), face)[0] == "NO"


def test_us_audience_rule_needs_review_and_movie_ip_note():
    b = _brief(wants={"footage": "x", "languages": [], "audienceCountries": ["US", "UK"], "avoid": []})
    verdict, why, _ = fit_check(to_campaign(_item(), b), b)
    assert verdict == "REVIEW" and any("Tier-1" in w for w in why)
    b2 = _brief()
    _, why2, _ = fit_check(to_campaign(_item(title="Behemoth! Movie Phase 2"), b2), b2)
    assert any("campaign account" in w for w in why2)


def test_pitch_pipeline_statuses_and_followups(tmp_path, monkeypatch):
    monkeypatch.setattr(pitch, "DB", tmp_path / "t.db")
    conn = pitch.connect()
    pid = pitch.add(conn, "Test Show", notes="runs a clipping campaign")
    pitch.set_status(conn, pid, "pitched")
    pl = pitch.pipeline(conn)
    assert pl["counts"]["pitched"] == 1
    assert isinstance(conn, sqlite3.Connection)
