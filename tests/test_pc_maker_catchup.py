"""Option A (19 Nov): PC makes videos for the cloud; the cloud catches up platforms connected after posting, once."""
import json
import time

from engine.cloud import runner


class FakeAct:
    def __init__(self, platform, item_id, done=True):
        self.platform, self.item_id, self.done, self.what, self.result, self.details = platform, item_id, done, "post", {}, {}


def test_catch_up_posts_only_missing_platforms_once(tmp_path, monkeypatch):
    from engine import autopilot, publish
    log_file = tmp_path / "publish_log.jsonl"
    log_file.write_text("\n".join(json.dumps(r) for r in [
        {"item_id": "v1", "platform": "youtube", "done": True, "what": "upload"},
        {"item_id": "v1", "platform": "instagram", "done": True, "what": "reel"},
    ]) + "\n", encoding="utf-8")
    monkeypatch.setattr(publish, "LOG", log_file)
    state = {}
    monkeypatch.setattr(autopilot, "_load", lambda: state)

    def upd(fn):
        fn(state)
        return state
    monkeypatch.setattr(autopilot, "_update_state", upd)
    item = {"id": "v1", "channel": "c", "status": "posted", "posted_at": time.time() - 3600, "out_dir": str(tmp_path)}
    monkeypatch.setattr(autopilot, "items", lambda *a: [("w", item)])
    monkeypatch.setattr(runner.media, "ensure_local", lambda store, it: tmp_path)
    calls = []

    def fake_upload(it, dry_run, platforms, publish_at):
        calls.append(platforms)
        return [FakeAct(p, it["id"]) for p in platforms]
    monkeypatch.setattr(publish, "upload_item", fake_upload)
    assert runner.catch_up_platforms(None, log=lambda m: None) == 1
    assert calls == [("facebook", "threads", "dailymotion")]           # instagram already had it: not again
    assert runner.catch_up_platforms(None, log=lambda m: None) == 0    # tried once: never repeated
    assert len(calls) == 1


def test_old_or_unposted_videos_are_left_alone(tmp_path, monkeypatch):
    from engine import autopilot, publish
    monkeypatch.setattr(publish, "LOG", tmp_path / "none.jsonl")
    monkeypatch.setattr(autopilot, "_load", lambda: {})
    items = [("w", {"id": "old", "status": "posted", "posted_at": time.time() - 30 * 86400}),
             ("w", {"id": "made", "status": "made"})]
    monkeypatch.setattr(autopilot, "items", lambda *a: items)
    monkeypatch.setattr(publish, "upload_item", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not post")))
    assert runner.catch_up_platforms(None, log=lambda m: None) == 0


def test_posted_platforms_ignores_extras_and_dry_runs(tmp_path, monkeypatch):
    from engine import publish
    f = tmp_path / "log.jsonl"
    f.write_text("\n".join(json.dumps(r) for r in [
        {"item_id": "a", "platform": "facebook", "done": True, "what": "reel"},
        {"item_id": "a", "platform": "threads", "done": True, "what": "post", "details": {"dry_run": True}},
        {"item_id": "a", "platform": "youtube", "done": True, "what": "thumbnail set"},
        {"item_id": "b", "platform": "instagram", "done": True, "what": "reel"}]) + "\n", encoding="utf-8")
    monkeypatch.setattr(publish, "LOG", f)
    assert runner.posted_platforms("a") == {"facebook"}
