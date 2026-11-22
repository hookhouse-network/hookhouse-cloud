"""Heal 19 Nov night: Threads got no signed link after HTTP became the default session; Story teasers counted as
videos in stats/reviews; fixed heal items close on their own; Brain Snack captions ask a real question + send line."""
import json

from engine import heal, publish, stats_fetch
from engine.core.http import HTTP


def test_real_sessions_get_the_signed_link():
    import requests
    assert publish._live(HTTP) and publish._live(requests)
    assert not publish._live(object())


def test_the_default_session_posts_our_signed_link(tmp_path, monkeypatch):
    """The real default session must reach share_link (it was skipped since `session is requests` went False)."""
    import requests
    monkeypatch.setattr(publish, "share_link", lambda v, hours=2.0: ("https://w/v/1/2/sig", lambda: None))
    sent = {}

    class R:
        status_code = 200

        def json(self):
            return {"id": "C1"}

    monkeypatch.setattr(requests, "post", lambda url, data=None, **k: sent.update(data or {}) or R())
    cid, err, _ = publish._ig_container("https://h", "1", "t", tmp_path / "r.mp4", {"media_type": "REELS"},
                                        session=HTTP)
    assert cid == "C1" and sent.get("video_url") == "https://w/v/1/2/sig"
    text = open(publish.__file__, encoding="utf-8").read()
    assert "if session is requests" not in text and text.count("if _live(session) else None") == 2


def _log(path, rows):
    path.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")


def test_story_teasers_are_not_videos(tmp_path, monkeypatch):
    log = tmp_path / "log.jsonl"
    _log(log, [
        {"at": 100, "platform": "instagram", "channel": "c", "item_id": "i1", "what": "publish Reel reel.mp4",
         "done": True, "result": {"media_id": "R1"}, "details": {}},
        {"at": 101, "platform": "instagram", "channel": "c", "item_id": "i1", "what": "publish Story story_teaser.mp4",
         "done": True, "result": {"media_id": "S1"}, "details": {}},
    ])
    monkeypatch.setattr(stats_fetch, "LOG", log)
    assert [v["id"] for v in stats_fetch.posted_videos()] == ["R1"]


def test_a_later_good_post_closes_the_upload_error(tmp_path, monkeypatch):
    monkeypatch.setattr(heal, "QUEUE", tmp_path / "q.json")
    log = tmp_path / "log.jsonl"
    old = heal.report("upload:threads", "Threads could not process the video: UNKNOWN", platform="threads")
    assert old["status"] == "open"
    _log(log, [
        {"at": 1000, "platform": "threads", "channel": "c", "item_id": "a", "what": "publish Threads video",
         "done": False, "result": {"error": "Threads could not process the video: UNKNOWN"}, "details": {}},
        {"at": 2000, "platform": "threads", "channel": "c", "item_id": "b", "what": "publish Threads video",
         "done": True, "result": {"thread_id": "9"}, "details": {}},
    ])
    heal.from_publish_log(0, log_path=log)
    assert all(it["status"] == "fixed" for it in heal._load()["items"].values())


def test_a_good_post_before_the_failure_keeps_it_open(tmp_path, monkeypatch):
    monkeypatch.setattr(heal, "QUEUE", tmp_path / "q.json")
    log = tmp_path / "log.jsonl"
    _log(log, [
        {"at": 1000, "platform": "threads", "channel": "c", "item_id": "b", "what": "publish Threads video",
         "done": True, "result": {"thread_id": "9"}, "details": {}},
        {"at": 2000, "platform": "threads", "channel": "c", "item_id": "a", "what": "publish Threads video",
         "done": False, "result": {"error": "Threads could not process the video: UNKNOWN"}, "details": {}},
    ])
    heal.from_publish_log(0, log_path=log)
    assert all(it["status"] == "open" for it in heal._load()["items"].values())


def test_working_insights_close_the_permission_error(tmp_path, monkeypatch):
    monkeypatch.setattr(heal, "QUEUE", tmp_path / "q.json")
    heal.report("stats:instagram", "Instagram insights HTTP 400: (#10) Application does not have permission",
                platform="instagram")
    monkeypatch.setattr(stats_fetch, "SECRETS", tmp_path)
    (tmp_path / "meta_c.json").write_text(json.dumps({"access_token": "t", "login": "instagram"}))

    class R:
        status_code = 200

        def json(self):
            return {"data": [{"name": "views", "values": [{"value": 10}]}]}

    class S:
        def get(self, url, **k):
            return R()

    m = stats_fetch._instagram({"channel": "c", "id": "R1"}, S())
    assert m["views"] == 10
    assert all(it["status"] == "fixed" for it in heal._load()["items"].values())


def test_brain_snack_captions_fit_the_format():
    from engine.snack import maker
    for fmt in maker.FORMATS:
        (q,) = maker.cta_for(fmt)                           # 22 Nov: the question stays, the send ask is gone
        assert q.rstrip().endswith("\U0001F447")
        low = q.lower()
        assert not any(w in low for w in ("share", "send", "tag ", "comment", "like "))   # never ask (Instagram)
    assert "rule" not in maker.cta_for("readfast")[0]           # facts no longer ask "which rule next?"
