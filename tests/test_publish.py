"""Uploader tests: dry runs never touch the network; real flows are exercised with a fake HTTP session."""
import json
from datetime import date
from pathlib import Path

import pytest

from engine import publish, weekly


class FakeResp:
    def __init__(self, payload=None, headers=None):
        self._p, self.headers = payload or {}, headers or {}

    def json(self):
        return self._p

    def raise_for_status(self):
        pass


class FakeSession:
    def __init__(self, quota_usage=0):
        self.calls, self.quota_usage = [], quota_usage

    def post(self, url, **kw):
        self.calls.append(("POST", url, kw))
        if "oauth2.googleapis.com" in url:
            return FakeResp({"access_token": "tok", "expires_in": 3600})
        if "upload/youtube" in url:
            return FakeResp(headers={"Location": "https://upload.example/session1"})
        if url.endswith("/media"):
            return FakeResp({"id": "container1"})
        if url.endswith("/media_publish"):
            return FakeResp({"id": "media1"})
        return FakeResp({})

    def put(self, url, **kw):
        self.calls.append(("PUT", url, kw))
        return FakeResp({"id": "vid123"})

    def get(self, url, **kw):
        self.calls.append(("GET", url, kw))
        if url.endswith("content_publishing_limit"):
            return FakeResp({"data": [{"quota_usage": self.quota_usage}]})
        return FakeResp({"status_code": "FINISHED"})


@pytest.fixture()
def sandbox(tmp_path, monkeypatch):
    monkeypatch.setattr(publish, "SECRETS", tmp_path / "secrets")
    monkeypatch.setattr(publish, "LOG", tmp_path / "publish_log.jsonl")
    monkeypatch.setattr(publish, "QUOTA_FILE", tmp_path / "quota.json")
    (tmp_path / "secrets").mkdir()
    video = tmp_path / "video.mp4"
    video.write_bytes(b"0" * 1000)
    return tmp_path, video


def test_metadata_is_private_scheduled_and_labelled():
    body = publish.youtube_metadata({"title": "Lake vanished", "format": "short", "ai_label": True,
                                     "hashtags": ["#mystery"]}, "2026-11-16T05:00:00+05:30", made_for_kids=False)
    assert body["status"]["privacyStatus"] == "private" and body["status"]["publishAt"] == "2026-11-15T23:30:00.000Z"
    assert body["status"]["containsSyntheticMedia"] is True and "#shorts" not in body["snippet"]["title"]   # SEO v2: no hashtags in titles
    kids = publish.youtube_metadata({"title": "Count with Bloop", "format": "long"}, None, made_for_kids=True)
    assert kids["status"]["selfDeclaredMadeForKids"] is True and "publishAt" not in kids["status"]


def test_dry_run_never_calls_the_network(sandbox):
    _, video = sandbox
    s = FakeSession()
    a = publish.youtube_upload("unsolved_after_dark", video, {"title": "x", "format": "short"}, None, session=s)
    b = publish.instagram_reel("unsolved_after_dark", video, "caption #a", session=s)
    assert a.details["dry_run"] and b.details["dry_run"] and s.calls == []


def test_real_youtube_flow_with_fake_session(sandbox, monkeypatch):
    tmp, video = sandbox
    monkeypatch.setenv("YOUTUBE_CLIENT_ID", "cid")
    monkeypatch.setenv("YOUTUBE_CLIENT_SECRET", "secret")
    (tmp / "secrets" / "youtube_ch.json").write_text(json.dumps({"refresh_token": "r"}))
    s = FakeSession()
    act = publish.youtube_upload("ch", video, {"title": "t", "format": "long"}, "2026-11-17T05:00:00+05:30",
                                 session=s, dry_run=False)
    assert act.done and act.result["video_id"] == "vid123"
    assert any("uploadType=resumable" in c[1] for c in s.calls) and any(c[0] == "PUT" for c in s.calls)


def test_quota_guard_stops_at_80_percent(sandbox, monkeypatch):
    monkeypatch.setenv("YOUTUBE_DAILY_QUOTA", "2000")
    assert publish.quota_ok(1600)
    publish.add_quota(1600)
    assert not publish.quota_ok(1600)


def test_instagram_limit_guard_and_trial_reel(sandbox):
    tmp, video = sandbox
    (tmp / "secrets" / "meta_ch.json").write_text(json.dumps({"ig_user_id": "17", "access_token": "t", "page_id": "9"}))
    busy = publish.instagram_reel("ch", video, "cap", session=FakeSession(quota_usage=60), dry_run=False)
    assert not busy.done and "limit" in busy.result["error"]
    s = FakeSession()
    ok = publish.instagram_reel("ch", video, "cap #a #b", trial=True, session=s, dry_run=False, poll_s=0)
    assert ok.done and ok.result["media_id"] == "media1"
    created = [c for c in s.calls if c[1].endswith("/media")][0][2]["data"]
    assert created["media_type"] == "REELS" and "trial_params" in created


def test_only_approved_items_are_planned(sandbox, monkeypatch):
    tmp, video = sandbox
    monkeypatch.setattr(weekly, "WEEKS_DIR", tmp / "weeks")
    plan = weekly.plan_week(None, date(2026, 11, 16), only=["brain_snack"], log=lambda m: None)
    out = tmp / "out1"
    out.mkdir()
    (out / "video.mp4").write_bytes(b"1")
    (out / "reel.mp4").write_bytes(b"2")
    (out / "upload.json").write_text(json.dumps({"title": "Spiral", "format": "short"}))
    (out / "reel.json").write_text(json.dumps({"caption": "cap #brainsnack"}))
    for k, it in enumerate(plan["items"]):
        it["status"], it["out_dir"], it["file"] = "made", str(out), "video.mp4"
    weekly.save_plan(plan)                               # planned -> made -> approved (legal steps)
    plan["items"][0]["status"] = "approved"
    weekly.save_plan(plan)
    acts = publish.plan_uploads("2026-11-16")
    assert [a.platform for a in acts] == ["youtube", "instagram", "instagram", "facebook"]   # one approved item (Reel + Story teaser)
    assert all(a.details.get("dry_run") for a in acts)


def test_consent_url_asks_only_for_youtube_scopes_and_offline_access():
    from engine.connect import consent_url, SCOPES
    url = consent_url("cid.apps.googleusercontent.com", "http://127.0.0.1:8799/", "st")
    assert "access_type=offline" in url and "accounts.google.com" in url and "state=st" in url
    assert all("youtube" in s or "yt-analytics" in s for s in SCOPES)


def test_youtube_metrics_parsing(sandbox, monkeypatch):
    from engine import connect
    tmp, _ = sandbox
    monkeypatch.setattr(connect, "yt_access_token", lambda ch, s=None: "tok")

    class S:
        def get(self, url, **kw):
            return FakeResp({"columnHeaders": [{"name": "views"}, {"name": "averageViewPercentage"}],
                             "rows": [[1234, 81.5]]})
    m = connect.fetch_youtube_metrics("ch", "vid1", "2026-11-16", "2026-11-18", session=S())
    assert m == {"views": 1234, "averageViewPercentage": 81.5}


def test_failed_fact_check_is_never_uploaded(sandbox, monkeypatch):
    tmp, _ = sandbox
    monkeypatch.setattr(weekly, "WEEKS_DIR", tmp / "weeks")
    plan = weekly.plan_week(None, date(2026, 11, 30), only=["brain_snack"], log=lambda m: None)
    out = tmp / "bad"
    out.mkdir()
    (out / "video.mp4").write_bytes(b"1")
    (out / "upload.json").write_text(json.dumps({"title": "x", "format": "short",
                                                 "fact_check": {"checked": True, "ok": False, "problems": ["wrong date"]}}))
    plan["items"][0].update(status="made", out_dir=str(out), file="video.mp4")
    weekly.save_plan(plan)                                   # planned -> made -> approved (legal steps)
    plan["items"][0]["status"] = "approved"
    weekly.save_plan(plan)
    acts = publish.plan_uploads("2026-11-30")
    assert len(acts) == 1 and "SKIPPED" in acts[0].what and acts[0].result["error"] == "fact-check failed"


def test_captions_upload_builds_multipart(tmp_path, monkeypatch):
    from engine import publish
    srt = tmp_path / "c.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nhello\n", encoding="utf-8")
    sent = {}

    class R:
        def raise_for_status(self): pass
        def json(self): return {"id": "cap1"}

    class S:
        def post(self, url, headers=None, data=None, timeout=None):
            sent.update(url=url, headers=headers, data=data)
            return R()

    monkeypatch.setattr(publish, "yt_access_token", lambda ch, session=None: "tok")
    monkeypatch.setattr(publish, "quota_ok", lambda u: True)
    monkeypatch.setattr(publish, "add_quota", lambda u: None)
    monkeypatch.setattr(publish, "_log", lambda a: None)
    act = publish.youtube_captions("ch", "vid1", srt, "hi", session=S(), dry_run=False)
    assert act.done and act.result["caption_id"] == "cap1"
    assert b'"videoId": "vid1"' in sent["data"] and b"hello" in sent["data"] and "multipart/related" in sent["headers"]["Content-Type"]
