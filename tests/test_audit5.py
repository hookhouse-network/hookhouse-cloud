"""Fifth audit (12 Nov): research-driven changes. Separate YouTube upload quota bucket, public uploads, paid
promotion + AI labels, Shorts thumbnails after processing, Instagram Login tokens, campaign footage and budget drain,
repeated title openings."""
import json
import time

from engine import autopilot, publish


class R:
    def __init__(self, d, code=200):
        self.d, self.status_code, self.ok = d, code, code < 400

    def json(self):
        return self.d

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


def test_upload_quota_is_its_own_bucket(tmp_path, monkeypatch):
    monkeypatch.setattr(publish, "QUOTA_FILE", tmp_path / "q.json")
    publish.add_quota(7900)                                   # captions, thumbnails... (general bucket)
    assert not publish.quota_ok(400) and publish.quota_ok(100, "insert")
    publish.add_quota(10 ** 6, "insert")
    assert not publish.quota_ok(100, "insert")


def test_campaign_clip_is_marked_paid_promotion(tmp_path, monkeypatch):
    monkeypatch.setattr(publish, "QUOTA_FILE", tmp_path / "q.json")
    monkeypatch.setattr(publish, "LOG", tmp_path / "log.jsonl")
    monkeypatch.setattr(publish, "yt_access_token", lambda c, s=None: "tok")
    v = tmp_path / "v.mp4"
    v.write_bytes(b"x")
    sent = {}

    class S:
        def post(self, url, headers=None, data=None, timeout=None):
            sent["url"], sent["body"] = url, json.loads(data)
            r = R({})
            r.headers = {"Location": "https://up"}
            return r

        def put(self, *a, **k):
            return R({"id": "VID"})
    a = publish.youtube_upload("hot_take_hq", v, {"title": "T", "campaign": "c1"}, None, session=S(), dry_run=False)
    assert a.done and "paidProductPlacementDetails" in sent["url"]
    assert sent["body"]["paidProductPlacementDetails"]["hasPaidProductPlacement"] is True
    assert sent["body"]["status"]["privacyStatus"] == "public"


def test_instagram_labels_and_instagram_login_host(tmp_path, monkeypatch):
    monkeypatch.setattr(publish, "LOG", tmp_path / "log.jsonl")
    monkeypatch.setattr(publish, "meta_creds", lambda c: {"ig_user_id": "1", "access_token": "t", "login": "instagram"})
    v = tmp_path / "r.mp4"
    v.write_bytes(b"x")
    calls = []

    class S:
        def get(self, url, **k):
            calls.append(url)
            return R({"data": [{"quota_usage": 1}]} if "limit" in url else {"status_code": "FINISHED"})

        def post(self, url, data=None, **k):
            calls.append((url, data))
            if url.endswith("/media"):
                return R({"id": "C1"})
            if "media_publish" in url:
                return R({"id": "M1"})
            return R({})
    act = publish.instagram_reel("x", v, "cap", session=S(), dry_run=False, poll_s=0, ai=True, paid=True)
    media = next(c for c in calls if isinstance(c, tuple) and c[0].endswith("/media"))
    assert act.done and "graph.instagram.com" in media[0]
    assert media[1]["is_ai_generated"] == "true" and media[1]["is_paid_partnership"] == "true"


def test_shorts_thumbnail_waits_for_processing(tmp_path, monkeypatch):
    monkeypatch.setattr(publish, "PENDING_THUMBS", tmp_path / "p.json")
    monkeypatch.setattr(publish, "QUOTA_FILE", tmp_path / "q.json")
    monkeypatch.setattr(publish, "yt_access_token", lambda c, s=None: "tok")
    img = tmp_path / "cover.jpg"
    img.write_bytes(b"x")
    publish.queue_short_thumbnail("ch", "V1", img)
    status = {"v": "processing"}
    setted = []
    monkeypatch.setattr(publish, "youtube_thumbnail", lambda *a, **k: setted.append(a[1]) or publish.Action(
        "youtube", "ch", "", "t", done=True))

    class S:
        def get(self, url, **k):
            return R({"items": [{"processingDetails": {"processingStatus": status["v"]}}]})
    assert publish.process_pending_thumbnails(S()) == 0 and setted == []
    status["v"] = "succeeded"
    assert publish.process_pending_thumbnails(S()) == 1 and setted == ["V1"]
    assert json.loads((tmp_path / "p.json").read_text()) == []


def test_instagram_login_token_renews_itself(tmp_path, monkeypatch):
    from engine import connect
    monkeypatch.setattr(connect, "SECRETS", tmp_path)
    (tmp_path / "meta_x.json").write_text(json.dumps({"login": "instagram", "access_token": "OLD",
                                                      "expires_at": time.time() + 5 * 86400,
                                                      "saved_at": time.time() - 50 * 86400}))

    class S:
        def get(self, url, params=None, **k):
            return R({"access_token": "NEW", "expires_in": 5184000})
    assert connect.refresh_instagram_tokens(S()) == ["x"]
    rec = json.loads((tmp_path / "meta_x.json").read_text())
    assert rec["access_token"] == "NEW" and rec["expires_at"] > time.time() + 50 * 86400


def test_campaign_footage_keeps_only_direct_files():
    from engine import discover

    class M:
        def tool(self, name, **k):
            return {"videos": [{"url": "https://www.twitch.tv/videos/1"},
                               {"moments": [{"url": "https://www.twitch.tv/videos/1?t=0h5m"}]}],
                    "brandAssets": [{"url": "https://drive.google.com/file/d/ABC/view"},
                                    {"url": "https://example.com/logo.png"}]}
    f = discover.campaign_footage("x/y", mcp=M())
    assert f["files"] == ["https://drive.google.com/file/d/ABC/view"] and f["platform_pages"] == 1


def test_draining_campaigns_are_hidden(tmp_path, monkeypatch):
    from engine import db, telegram_bot as tb
    monkeypatch.setattr(tb, "STATE", tmp_path / "s.json")
    conn = db.connect(tmp_path / "c.db")
    soon = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 6 * 3600))
    later = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 6 * 86400))
    db.save_campaign(conn, {"id": "a", "name": "A", "status": "eligible", "fit": "OK", "drain_at": soon})
    db.save_campaign(conn, {"id": "b", "name": "B", "status": "eligible", "fit": "OK", "drain_at": later})
    assert [c["id"] for c in tb.candidates(conn)] == ["b"]


def test_repeated_title_openings_are_flagged(tmp_path, monkeypatch):
    from engine import weekly
    monkeypatch.setattr(weekly, "WEEKS_DIR", tmp_path / "weeks")
    now = autopilot._now()
    items = []
    for i in range(3):
        d = tmp_path / f"o{i}"
        d.mkdir()
        (d / "upload.json").write_text(json.dumps({"title": f"The Ship That Vanished {i}"}))
        items.append({"id": f"p{i}", "channel": "unsolved_after_dark", "status": "posted", "out_dir": str(d),
                      "publish_at": (now.replace(microsecond=0)).isoformat()})
    (tmp_path / "weeks" / "2099-01-05").mkdir(parents=True)
    (tmp_path / "weeks" / "2099-01-05" / "plan.json").write_text(json.dumps({"start": "2099-01-05", "items": items}))
    it = {"id": "new", "channel": "unsolved_after_dark"}
    assert autopilot.title_pattern_repeats(it, "The Ship That Sank Twice") == 3
    assert autopilot.title_pattern_repeats(it, "Nobody Found Her Again") == 0
