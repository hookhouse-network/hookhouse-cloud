"""Second audit (12 Nov): double taps, missed/failed videos, crash recovery, the shared clip pool, double-post check,
retries, Instagram answers, one bot only, /source."""
import json
import time
from datetime import timedelta

import pytest

from engine import autopilot, publish, weekly


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(weekly, "WEEKS_DIR", tmp_path / "weeks")
    monkeypatch.setattr(weekly, "CLIP_STATE", tmp_path / "clip_pool.json")
    monkeypatch.setattr(weekly, "CLIP_SOURCES", tmp_path / "clip_sources.txt")
    monkeypatch.setattr(autopilot, "STATE", tmp_path / "autopilot.json")
    monkeypatch.setattr(autopilot, "LOCK", tmp_path / "render.lock")
    monkeypatch.setattr(publish, "LOG", tmp_path / "publish_log.jsonl")
    sent = []
    from engine import telegram_bot as tb
    monkeypatch.setattr(tb, "notify", lambda t: sent.append(t) or True)
    monkeypatch.setattr(tb, "send", lambda t, **k: sent.append(t))
    out = tmp_path / "out" / "v1"
    out.mkdir(parents=True)
    (out / "video.mp4").write_bytes(b"x")
    (out / "upload.json").write_text(json.dumps({"title": "T"}))
    now = autopilot._now()
    plan = {"start": "2099-01-05", "items": [
        {"id": "a", "channel": "unsolved_after_dark", "channel_name": "Unsolved", "kind": "short",
         "publish_at": (now + timedelta(hours=10)).isoformat(), "status": "made", "made_at": 111.0,
         "out_dir": str(out), "file": "video.mp4", "topic": "Lake"}]}
    (tmp_path / "weeks" / "2099-01-05").mkdir(parents=True)
    (tmp_path / "weeks" / "2099-01-05" / "plan.json").write_text(json.dumps(plan))
    monkeypatch.setattr(autopilot, "preflight", lambda it: [])
    uploads = []
    monkeypatch.setattr(autopilot, "_schedule_youtube", lambda s, it: uploads.append(it["id"]) or "scheduled")
    return {"sent": sent, "tmp": tmp_path, "out": out, "now": now, "uploads": uploads}


def _it():
    return weekly.load_plan("2099-01-05")["items"][0]


def _tok():
    return autopilot.token("2099-01-05", "a", str(_it().get("made_at") or ""))


def test_double_tap_approve_uploads_once(env):
    tok = _tok()
    assert "Approved" in autopilot.decide(tok, "approve")
    assert "Already approved" in autopilot.decide(tok, "approve")
    assert env["uploads"] == ["a"] and _it()["status"] == "approved"


def test_failed_remake_cannot_be_approved_from_old_message(env):
    tok = _tok()
    autopilot.update_item("2099-01-05", "a", status="failed")
    assert "couldn't be finished" in autopilot.decide(tok, "approve")
    assert env["uploads"] == []


def test_change_on_missed_video_moves_it_and_remakes(env, monkeypatch):
    autopilot.update_item("2099-01-05", "a", status="missed",
                          publish_at=(env["now"] - timedelta(hours=2)).isoformat())
    autopilot.decide(_tok(), "change", "scarier hook")
    it = _it()
    assert it["status"] == "redo" and autopilot._when(it) > env["now"] + timedelta(hours=1)


def test_crash_while_making_goes_back_to_queue(env):
    autopilot.update_item("2099-01-05", "a", status="making", note="new hook")
    env["tmp"].joinpath("render.lock").write_text("a")
    assert autopilot.recover(lambda m: None) == 1
    assert _it()["status"] == "redo" and not env["tmp"].joinpath("render.lock").exists()


def test_unasked_video_is_moved_not_missed(env, monkeypatch):
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    autopilot.update_item("2099-01-05", "a", publish_at=(env["now"] - timedelta(minutes=30)).isoformat())
    autopilot._missed(lambda m: None)
    it = _it()
    assert it["status"] == "made" and autopilot._when(it) > env["now"]


def test_asked_video_is_missed(env, monkeypatch):
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    autopilot._update_state(lambda s: s.setdefault("asked", {}).__setitem__("a", time.time()))
    autopilot.update_item("2099-01-05", "a", publish_at=(env["now"] - timedelta(minutes=30)).isoformat())
    autopilot._missed(lambda m: None)
    assert _it()["status"] == "missed"


def test_post_retries_after_a_blip(env, monkeypatch):
    autopilot.update_item("2099-01-05", "a", status="approved",
                          publish_at=(env["now"] - timedelta(minutes=1)).isoformat())

    def fail(it, **k):
        a = publish.Action("instagram", "x", "a", "publish Reel")
        a.result = {"error": "ConnectionError"}
        return [a]
    monkeypatch.setattr(publish, "upload_item", fail)
    autopilot._post_due(lambda m: None)
    it = _it()
    assert it["status"] == "approved" and it["post_attempts"] == 1 and it["post_retry_at"] > time.time()


def test_deleted_youtube_upload_is_not_a_double_post(env):
    it = dict(_it(), made_at=100.0)
    log = env["tmp"] / "publish_log.jsonl"
    rows = [{"at": 200, "platform": "youtube", "item_id": "a", "done": True, "details": {}, "result": {"video_id": "Y1"}},
            {"at": 300, "platform": "youtube", "item_id": "", "done": True,
             "details": {"deleted_video_id": "Y1"}, "result": {}}]
    log.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    assert publish.already_posted(it) == []
    log.write_text(log.read_text() + json.dumps({"at": 400, "platform": "instagram", "item_id": "a", "done": True,
                                                 "details": {}, "result": {}}) + "\n")
    assert publish.already_posted(it) == ["instagram"]
    assert publish.already_posted(dict(it, made_at=500.0)) == []          # a newer version may post


def test_clip_pool_is_per_channel_and_never_reclips(env, monkeypatch):
    env["tmp"].joinpath("clip_sources.txt").write_text("D:/a.mp4 channel=stream_clips\nD:/b.mp4\n")
    made = []

    def fake_make(brain, src, ch, campaign=None, memory=None, keep=4, log=print):
        d = env["tmp"] / "output" / ch["id"] / src[-5]
        d.mkdir(parents=True, exist_ok=True)
        for n in (1, 2, 3):
            (d / f"clip_0{n}.mp4").write_bytes(b"x")
        made.append((src, ch["id"]))
        return d, [{"file": f"clip_0{n}.mp4"} for n in (1, 2, 3)]
    from engine import clips
    monkeypatch.setattr(clips, "make_clips", fake_make)
    plan = {"start": "2099-01-05", "items": []}
    first = weekly._make_clip(plan, {}, None, {"id": "hot_take_hq"}, None, print)
    second = weekly._make_clip({"start": "2099-01-12"}, {}, None, {"id": "hot_take_hq"}, None, print)   # next week
    gaming = weekly._make_clip(plan, {}, None, {"id": "stream_clips"}, None, print)
    assert made == [("D:/b.mp4", "hot_take_hq"), ("D:/a.mp4", "stream_clips")]   # each footage cut once
    assert first[1] == "clip_01.mp4" and second[1] == "clip_02.mp4" and "stream_clips" in gaming[0]
    with pytest.raises(weekly.NeedsSource):
        for _ in range(3):
            weekly._make_clip(plan, {}, None, {"id": "hot_take_hq"}, None, print)


def test_instagram_publish_error_is_not_marked_done(tmp_path, monkeypatch):
    monkeypatch.setattr(publish, "LOG", tmp_path / "log.jsonl")
    monkeypatch.setattr(publish, "meta_creds", lambda c: {"ig_user_id": "1", "access_token": "t"})
    v = tmp_path / "r.mp4"
    v.write_bytes(b"x")

    class R:
        def __init__(self, d, code=200):
            self.d, self.status_code = d, code

        def json(self):
            return self.d

    class S:
        def get(self, url, **k):
            return R({"data": [{"quota_usage": 1}]} if "limit" in url else {"status_code": "FINISHED"})

        def post(self, url, **k):
            if url.endswith("/media"):
                return R({"id": "C1"})
            if "media_publish" in url:
                return R({"error": {"message": "Media ID is not available"}})
            return R({}, 200)
    act = publish.instagram_reel("x", v, "cap", session=S(), dry_run=False, poll_s=0)
    assert not act.done and "not available" in act.result["error"]


def test_only_one_bot_can_run():
    from engine import telegram_bot as tb
    assert tb.single_instance(47999) is True
    assert tb.single_instance(47999) is False


def test_source_refuses_platform_links(monkeypatch):
    from engine import telegram_bot as tb
    out = []
    monkeypatch.setattr(tb, "send", lambda t, **k: out.append(t))
    tb.source_start("https://www.twitch.tv/videos/123")
    assert "can't take" in out[0]
