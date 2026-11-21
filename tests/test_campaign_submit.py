"""Owner 21 Nov: campaign clips are submitted by the system within 30 minutes of posting (Content Rewards)."""
import time

from engine import campaign_submit as cs


def test_pick_link_follows_the_brief_platforms():
    links = {"youtube": "https://www.youtube.com/shorts/abc", "instagram": "https://instagram.com/reel/x"}
    assert cs.pick_link(links, ["YouTube", "TikTok"]) == links["youtube"]
    assert cs.pick_link(links, ["Instagram"]) == links["instagram"]
    assert cs.pick_link(links, ["TikTok"]) is None
    assert cs.pick_link(links, []) == links["youtube"]


def test_after_post_submits_records_and_reports(monkeypatch, tmp_path):
    sent, calls = [], []
    monkeypatch.setattr("engine.db.connect", lambda *a: __import__("sqlite3").connect(tmp_path / "db.sqlite"))
    camp = {"id": "dasgas", "name": "Dasgasd3m x RUCKUS", "url": "https://contentrewards.com/c/campaigns/1",
            "platforms": ["YouTube", "TikTok"]}

    def ok(url, post, item):
        calls.append((url, post, item))
        return {"ok": True, "message": "submitted", "proof": "p.png"}
    res = cs.after_post({"id": "i1", "channel": "stream_clips"}, {"youtube": "https://www.youtube.com/shorts/abc"},
                        camp, submitter=ok, notify=sent.append, log=lambda *a: None)
    assert res["ok"] and calls == [(camp["url"], "https://www.youtube.com/shorts/abc", "i1")]
    assert "Submitted to Dasgasd3m x RUCKUS automatically" in sent[0]
    import sqlite3
    row = sqlite3.connect(tmp_path / "db.sqlite").execute("SELECT status, post_url FROM submissions").fetchone()
    assert row == ("submitted", "https://www.youtube.com/shorts/abc")


def test_too_late_or_unsupported_is_never_submitted_and_the_owner_is_told(monkeypatch, tmp_path):
    monkeypatch.setattr("engine.db.connect", lambda *a: __import__("sqlite3").connect(tmp_path / "db.sqlite"))
    sent = []
    never = lambda *a: (_ for _ in ()).throw(AssertionError("must not submit"))   # noqa: E731
    res = cs.after_post({"id": "i1"}, {"youtube": "u"}, {"url": "https://contentrewards.com/c/1"},
                        posted_at=time.time() - 31 * 60, submitter=never, notify=sent.append, log=lambda *a: None)
    assert not res["ok"] and "30 minutes" in sent[0]
    assert cs.submit("https://vyro.com/c/1", "u")["message"].startswith("no submit adapter")


def test_a_submitted_post_is_frozen(monkeypatch):
    assert cs.is_frozen({"campaign_submitted_at": 1.0}) and not cs.is_frozen({})
    from engine import autopilot
    it = {"id": "i1", "channel": "stream_clips", "channel_name": "Stream Clips", "status": "posted",
          "youtube_id": "abc", "campaign_submitted_at": 1.0, "publish_at": "2026-11-21T05:00:00+05:30"}
    it["status"] = "approved"                                       # any state that could reach the delete
    monkeypatch.setattr(autopilot, "resolve", lambda tok: ("2026-11-16", "i1", ""))
    monkeypatch.setattr("engine.weekly.load_plan", lambda start: {"items": [it]})
    deleted = []
    monkeypatch.setattr("engine.publish.youtube_delete", lambda *a: deleted.append(a) or True)
    msg = autopilot.decide("t", "reject")
    assert not deleted and "stays as posted" in msg
