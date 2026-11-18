"""Full-day rehearsal against simulated platforms (owner, 12 Nov 2026: live checks). The real code runs end to end -
ask on the phone, approve, YouTube scheduled (captions, Shorts thumbnail, playlist), slot time: Instagram (AI label),
Facebook and Dailymotion, the posted message, stats - while a fake network answers like YouTube, Meta, Dailymotion and
Telegram do and records every request so the request formats are checked."""
import json
import sqlite3
import time
from datetime import timedelta

import pytest
import requests

from engine import analytics, autopilot, db, publish, stats_fetch, weekly


class Resp:
    def __init__(self, data=None, status=200, headers=None):
        self._d, self.status_code, self.headers = data if data is not None else {}, status, headers or {}
        self.ok = status < 400
        self.content = json.dumps(self._d).encode()
        self.text = self.content.decode()

    def json(self):
        return self._d

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(response=self)


class FakeNet:
    def __init__(self):
        self.calls = []

    def _route(self, method, url, kw):
        self.calls.append((method, url, kw))
        data = kw.get("data")
        if "api.telegram.org" in url:
            return Resp({"ok": True, "result": {"message_id": 7}})
        if url == "https://oauth2.googleapis.com/token":
            return Resp({"access_token": "G", "expires_in": 3600})
        if url.startswith("https://www.googleapis.com/upload/youtube/v3/videos"):
            return Resp({}, headers={"Location": "https://upload.fake/yt/1"})
        if url == "https://upload.fake/yt/1":
            return Resp({"id": "YT1"})
        if "upload/youtube/v3/captions" in url:
            return Resp({"id": "CAP1"})
        if "youtube/v3/playlists" in url:
            return Resp({"id": "PL1"})
        if "youtube/v3/playlistItems" in url:
            return Resp({"id": "PLI1"})
        if "thumbnails/set" in url:
            return Resp({})
        if url.endswith("/youtube/v3/videos") and method == "GET":
            if "statistics" in str((kw.get("params") or {}).get("part")):   # public counters (< 3 days old)
                return Resp({"items": [{"statistics": {"viewCount": "1200", "likeCount": "50"}}]})
            return Resp({"items": [{"processingDetails": {"processingStatus": "succeeded"}}]})
        if url.endswith("/youtube/v3/videos") and method == "DELETE":
            return Resp({}, 204)
        if url.endswith("/youtube/v3/channels"):
            return Resp({"items": [{"statistics": {"subscriberCount": "42"}}]})
        if "youtubeanalytics" in url:
            return Resp({"columnHeaders": [{"name": n} for n in ("views", "averageViewPercentage", "likes",
                                                                 "subscribersGained")], "rows": [[1200, 74.0, 50, 9]]})
        if "graph.facebook.com" in url or "graph.instagram.com" in url:
            if url.endswith("/content_publishing_limit"):
                return Resp({"data": [{"quota_usage": 1}]})
            if url.endswith("/media") and method == "POST":
                return Resp({"id": "C1"})
            if url.endswith("/C1"):
                return Resp({"status_code": "FINISHED"})
            if url.endswith("/media_publish"):
                return Resp({"id": "IGM1"})
            if url.endswith("/video_reels"):
                phase = (data or {}).get("upload_phase")
                return Resp({"video_id": "FBV1"} if phase == "start" else {"success": True})
            if url.endswith("/insights"):
                return Resp({"data": [{"name": "views", "values": [{"value": 900}]},
                                      {"name": "shares", "values": [{"value": 12}]}]})
            if "followers_count" in str(kw.get("params")):
                return Resp({"followers_count": 77})
        if "rupload.facebook.com" in url:
            return Resp({})
        if url == "https://oauth2.dailymotion.com/v2/token":
            return Resp({"access_token": "D", "expires_in": 3600})
        if url.endswith("/v2/files/upload_sessions"):
            return Resp({"upload_url": "https://upload.fake/dm"})
        if url == "https://upload.fake/dm":
            return Resp({"url": "https://storage.fake/dm.mp4"})
        if "/v2/profiles/P1/videos" in url:
            return Resp({"id": "x7dm"}, 201)
        return Resp({"error": f"unexpected call {method} {url}"}, 404)

    def get(self, url, **kw):
        return self._route("GET", url, kw)

    def post(self, url, **kw):
        return self._route("POST", url, kw)

    def put(self, url, **kw):
        return self._route("PUT", url, kw)

    def delete(self, url, **kw):
        return self._route("DELETE", url, kw)

    def find(self, method, part):
        return [c for c in self.calls if c[0] == method and part in c[1]]


@pytest.fixture
def day(tmp_path, monkeypatch):
    net = FakeNet()
    for m in ("get", "post", "put", "delete"):
        monkeypatch.setattr(requests, m, getattr(net, m))
    sec = tmp_path / "secrets"
    sec.mkdir()
    cid = "unsolved_after_dark"
    (sec / f"youtube_{cid}.json").write_text(json.dumps({"refresh_token": "r"}))
    (sec / f"meta_{cid}.json").write_text(json.dumps({"ig_user_id": "IG9", "page_id": "PG9", "access_token": "M",
                                                      "page_token": "PT"}))
    (sec / f"dailymotion_{cid}.json").write_text(json.dumps({"client_id": "a", "client_secret": "b", "profile_id": "P1"}))
    for mod, attr, val in ((publish, "SECRETS", sec), (publish, "LOG", tmp_path / "publish_log.jsonl"),
                           (publish, "QUOTA_FILE", tmp_path / "quota.json"), (publish, "PLAYLISTS", tmp_path / "pl.json"),
                           (publish, "PENDING_THUMBS", tmp_path / "thumbs.json"), (stats_fetch, "LOG", tmp_path / "publish_log.jsonl"),
                           (stats_fetch, "SECRETS", sec), (weekly, "WEEKS_DIR", tmp_path / "weeks"),
                           (weekly, "OUTPUT_DIR", tmp_path / "output"), (autopilot, "STATE", tmp_path / "autopilot.json"),
                           (autopilot, "LOCK", tmp_path / "render.lock"), (autopilot, "HEARTBEAT", tmp_path / "hb.txt")):
        monkeypatch.setattr(mod, attr, val)
    monkeypatch.setattr(autopilot, "_connected", lambda c: {"youtube": True, "meta": True})
    publish._DM_TOKENS.clear()
    for k, v in (("YOUTUBE_CLIENT_ID", "x"), ("YOUTUBE_CLIENT_SECRET", "y"), ("TELEGRAM_BOT_TOKEN", "T"),
                 ("TELEGRAM_CHAT_ID", "42")):
        monkeypatch.setenv(k, v)
    out = tmp_path / "output" / cid / "20990101_run"
    out.mkdir(parents=True)
    for f in ("video.mp4", "reel.mp4"):
        (out / f).write_bytes(b"\x00" * 2048)
    (out / "captions.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nHi\n")
    (out / "cover_vertical.jpg").write_bytes(b"jpg")
    (out / "upload.json").write_text(json.dumps({"title": "The Lake That Vanished", "description": "A drill hole.",
                                                 "hashtags": ["#mystery"], "format": "short", "ai_label": True,
                                                 "captions_file": "captions.srt"}))
    (out / "reel.json").write_text(json.dumps({"caption": "The lake vanished. #mystery"}))
    now = autopilot._now()
    plan = {"start": "2099-01-05", "items": [{"id": "it1", "channel": cid, "channel_name": "Unsolved After Dark",
                                              "kind": "short", "status": "made", "made_at": 1000.0, "out_dir": str(out),
                                              "file": "video.mp4", "topic": "Lake",
                                              "publish_at": (now + timedelta(hours=10)).isoformat()}]}
    (tmp_path / "weeks" / "2099-01-05").mkdir(parents=True)
    (tmp_path / "weeks" / "2099-01-05" / "plan.json").write_text(json.dumps(plan))
    return {"net": net, "tmp": tmp_path, "now": now}


def _item():
    return weekly.load_plan("2099-01-05")["items"][0]


def test_full_posting_day(day, monkeypatch):
    net = day["net"]
    autopilot._ask_due(lambda m: None)                                         # 1) the question reaches the phone
    assert net.find("POST", "sendVideo") or net.find("POST", "sendMessage")
    reply = autopilot.decide(autopilot.token("2099-01-05", "it1", "1000.0"), "approve")
    assert "Approved" in reply and "YT1" in reply                              # 2) YouTube scheduled at once
    it = _item()
    assert it["status"] == "approved" and it["youtube_id"] == "YT1"
    start = net.find("POST", "upload/youtube/v3/videos")[0]
    body = json.loads(start[2]["data"])
    assert body["status"]["privacyStatus"] == "private" and body["status"]["publishAt"].endswith("Z")
    assert body["status"]["containsSyntheticMedia"] is True and body["snippet"]["defaultLanguage"] == "en"
    assert net.find("POST", "upload/youtube/v3/captions"), "captions (relative path) were not uploaded"
    assert net.find("POST", "youtube/v3/playlists") and net.find("POST", "youtube/v3/playlistItems")
    assert publish.process_pending_thumbnails() == 1                          # Shorts thumbnail after processing
    autopilot.update_item("2099-01-05", "it1", publish_at=(day["now"] - timedelta(minutes=1)).isoformat())
    autopilot._post_due(lambda m: None)                                        # 3) slot time
    it = _item()
    assert it["status"] == "posted"
    media = net.find("POST", "/IG9/media")[0][2]["data"]
    assert media["is_ai_generated"] == "true" and media["media_type"] == "REELS"
    assert net.find("POST", "/IG9/media_publish") and net.find("POST", "/PG9/video_reels")
    dm = json.loads(net.find("POST", "/v2/profiles/P1/videos")[0][2]["data"])
    assert dm["is_ai_altered"] is True and dm["visibility"] == "public"
    done = {json.loads(ln)["platform"] for ln in (day["tmp"] / "publish_log.jsonl").read_text().splitlines()
            if json.loads(ln).get("done") and json.loads(ln).get("item_id") == "it1"}
    assert done == {"youtube", "instagram", "facebook", "dailymotion"}
    posted_msgs = [c for c in net.find("POST", "sendMessage") if "Posted" in json.dumps(c[2].get("json", {}))]
    assert posted_msgs, "the 'posted' message never reached the phone"
    # 4) stats a few hours later
    conn = sqlite3.connect(day["tmp"] / "analytics.db")
    conn.executescript(analytics.SCHEMA)
    real = time.time
    monkeypatch.setattr(stats_fetch.time, "time", lambda: real() + 14 * 3600)
    monkeypatch.setenv("YOUTUBE_API_KEY", "test")            # public counters for a 14-hour-old video
    orig_db = db.connect
    monkeypatch.setattr(db, "connect", lambda path=None: orig_db(day["tmp"] / "sys.db"))
    assert stats_fetch.fetch(log=lambda m: None, conn=conn) == 2
    views = dict(conn.execute("SELECT platform, views FROM video_metrics").fetchall())
    assert views == {"youtube": 1200, "instagram": 900}


def test_change_after_approval_removes_the_scheduled_upload(day):
    tok = autopilot.token("2099-01-05", "it1", "1000.0")
    autopilot.decide(tok, "approve")
    autopilot.decide(tok, "change", "scarier hook")
    assert day["net"].find("DELETE", "/youtube/v3/videos")
    it = _item()
    assert it["status"] == "redo" and it["youtube_id"] is None
    assert publish.already_posted(dict(it, made_at=0)) == []               # the deleted upload is not a double post


def test_approve_all_only_approves_what_was_shown(day):
    assert "Nothing is waiting" in autopilot.approve_all_shown()               # never shown: never approved
    assert _item()["status"] == "made"
    autopilot._ask_due(lambda m: None)                                         # the preview reaches the phone
    reply = autopilot.approve_all_shown()
    assert "Approved 1 of 1" in reply and _item()["status"] == "approved"
    assert "Nothing is waiting" in autopilot.approve_all_shown()               # second tap: no double upload
