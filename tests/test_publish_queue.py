"""20 Nov (owner: "a queue that keeps uploading ... as per its limitations, so we can earn from everywhere"):
every (video, platform) is its own job: a failed platform retries by itself, limits wait, nothing posts twice."""
import json
import time
from datetime import timedelta

import pytest

from engine import autopilot, publish, publish_queue as pq, weekly
from engine.core import governor as gv
from engine.core import ledger


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(weekly, "WEEKS_DIR", tmp_path / "weeks")
    monkeypatch.setattr(autopilot, "STATE", tmp_path / "autopilot.json")
    monkeypatch.setattr(publish, "LOG", tmp_path / "publish_log.jsonl")
    monkeypatch.setattr(gv, "_youtube_quota_ok", lambda: True)
    sent = []
    from engine import telegram_bot as tb
    monkeypatch.setattr(tb, "notify", lambda t: sent.append(t) or True)
    out = tmp_path / "out" / "v1"
    out.mkdir(parents=True)
    (out / "video.mp4").write_bytes(b"x")
    now = autopilot._now()
    plan = {"start": "2099-01-05", "items": [
        {"id": "a", "channel": "unsolved_after_dark", "channel_name": "Unsolved", "kind": "short",
         "publish_at": (now - timedelta(minutes=1)).isoformat(), "status": "approved", "made_at": 1.0,
         "youtube_id": "YT1", "out_dir": str(out), "file": "video.mp4", "topic": "Lake"}]}
    (tmp_path / "weeks" / "2099-01-05").mkdir(parents=True)
    (tmp_path / "weeks" / "2099-01-05" / "plan.json").write_text(json.dumps(plan))
    monkeypatch.setattr(autopilot, "preflight", lambda it: [])
    return {"sent": sent, "now": now}


def _it():
    return weekly.load_plan("2099-01-05")["items"][0]


def _uploader(monkeypatch, results, calls):
    """results: {platform: 'ok' | error text}; logs real-looking actions to the publish log."""
    def up(it, platforms=(), **k):
        calls.append(tuple(platforms))
        acts = []
        for p in platforms:
            r = results.get(p)
            if r is None:
                continue
            a = publish.Action(p, it["channel"], it["id"], f"publish {p}")
            if r == "ok":
                a.done, a.result = True, {"media_id": f"M-{p}"}
            else:
                a.result = {"error": r}
            publish._log(a)
            acts.append(a)
        return acts
    monkeypatch.setattr(publish, "upload_item", up)


def _force_due():
    led = ledger.default()
    led._tx(lambda c: c.execute("UPDATE jobs SET run_after=0 WHERE state='queued'"))


def test_failed_platform_retries_alone_and_the_rest_is_not_posted_again(env, monkeypatch):
    calls = []
    _uploader(monkeypatch, {"instagram": "ok", "facebook": "ConnectionError: reset", "threads": "ok"}, calls)
    autopilot._post_due(lambda m: None)
    assert _it()["status"] == "posted"                              # it went out (Instagram + Threads)
    assert "Facebook: retrying by itself" in env["sent"][-1]
    _uploader(monkeypatch, {"facebook": "ok"}, calls)
    _force_due()
    monkeypatch.setattr(gv, "MIN_GAP_S", {})                         # spacing is tested separately
    autopilot._post_due(lambda m: None)
    assert calls[-1] == ("facebook",)                                # only the failed one is tried again
    states = {j["key"].split(":")[-1]: j["state"] for j in pq.queued("a")}
    assert states["facebook"] == "done" and states["instagram"] == "done"
    assert len(env["sent"]) == 1                                     # the later success is quiet


def test_reconciles_instead_of_double_posting(env, monkeypatch):
    calls = []
    _uploader(monkeypatch, {"instagram": "ok"}, calls)
    publish._log(publish.Action("instagram", "unsolved_after_dark", "a", "publish Reel", done=True,
                                result={"media_id": "M0"}))           # posted, then a crash before the save
    pq.enqueue("2099-01-05", _it(), ["instagram"])
    pq.drain(lambda m: None)
    assert calls == []                                               # asked the log, didn't post again
    assert pq.queued("a")[0]["state"] == "done"


def test_account_limit_waits_without_using_an_attempt(env, monkeypatch):
    calls = []
    _uploader(monkeypatch, {"facebook": "ok"}, calls)
    for i in range(gv.LIMITS["facebook"]):
        a = publish.Action("facebook", "unsolved_after_dark", f"old{i}", "Reel", done=True)
        a.at = time.time() - 3600 - i
        publish._log(a)
    pq.enqueue("2099-01-05", _it(), ["facebook"])
    c = pq.drain(lambda m: None)
    j = pq.queued("a")[0]
    assert calls == [] and c["waiting"] == 1
    assert j["state"] == "queued" and j["attempts"] == 0 and j["run_after"] > time.time() + 3600 * 20


def test_spacing_between_posts_on_one_account():
    g = gv.Governor(now=10_000.0)
    g.record("instagram", "c1", 10_000.0 - 600)
    ok, retry_at, why = g.check("instagram", "c1")
    assert not ok and "spacing" in why and retry_at == 10_000.0 - 600 + gv.MIN_GAP_S["instagram"]
    assert g.check("instagram", "c2")[0]                             # other accounts aren't affected
    assert g.check("telegram", "c1")[0]


def test_youtube_quota_waits_until_pacific_midnight():
    g = gv.Governor(now=1_800_000_000.0, youtube_ok=lambda: False)
    ok, retry_at, _ = g.check("youtube", "c1")
    assert not ok and 0 < retry_at - 1_800_000_000.0 <= 86400 + 60


def test_gives_up_after_max_attempts_tells_the_owner_once_and_files_a_heal_item(env, monkeypatch):
    calls, healed = [], []
    _uploader(monkeypatch, {"instagram": "ok", "facebook": "HTTPError 500"}, calls)
    from engine import heal
    monkeypatch.setattr(heal, "report", lambda area, err, **k: healed.append((area, err)))
    monkeypatch.setattr(gv, "MIN_GAP_S", {})
    for _ in range(pq.MAX_ATTEMPTS):
        autopilot._post_due(lambda m: None)
        _force_due()
    fb = next(j for j in pq.queued("a") if j["key"].endswith(":facebook"))
    assert fb["state"] == "dead"
    assert healed == [("post", "facebook: HTTPError 500")]
    assert sum("gave up" in t for t in env["sent"]) == 1


def test_rule_skips_and_missing_platforms_complete_quietly(env, monkeypatch):
    calls = []

    def up(it, platforms=(), **k):
        calls.append(platforms)
        a = publish.Action("instagram", it["channel"], it["id"], "SKIPPED: not for instagram (kids rule, ...)")
        a.details["dry_run"] = True
        return [a]
    monkeypatch.setattr(publish, "upload_item", up)
    autopilot._post_due(lambda m: None)
    assert all(j["state"] == "done" for j in pq.queued("a"))
    assert _it()["status"] == "posted"                    # it is on YouTube already (scheduled at approval)
    assert "Instagram" not in env["sent"][-1]             # rule skips aren't listed as problems


def test_classify():
    a = publish.Action("facebook", "c", "i", "SKIPPED: Facebook daily Reels limit guard")
    assert pq.classify(a)[0] == "quota"
    b = publish.Action("instagram", "c", "i", "publish Reel")
    b.result = {"error": "(#4) Application request limit reached"}
    assert pq.classify(b)[0] == "quota"
    b.result = {"error": "channel not connected"}
    assert pq.classify(b)[0] == "permanent"
    b.result = {"error": "ReadTimeout"}
    assert pq.classify(b)[0] == "transient"
    assert pq.classify(None)[0] == "skipped"


def test_allow_hands_other_videos_back(env, monkeypatch):
    calls = []
    _uploader(monkeypatch, {"instagram": "ok"}, calls)
    pq.enqueue("2099-01-05", _it(), ["instagram"])
    pq.drain(lambda m: None, allow=lambda it: it["id"] == "other")
    j = pq.queued("a")[0]
    assert calls == [] and j["state"] == "queued" and j["attempts"] == 0


def test_threads_can_post_in_a_later_run_with_the_logged_instagram_id(tmp_path, monkeypatch):
    monkeypatch.setattr(publish, "LOG", tmp_path / "log.jsonl")
    publish._log(publish.Action("instagram", "c", "a", "publish Reel x", done=True, result={"media_id": "M9"}))
    publish._log(publish.Action("instagram", "c", "a", "publish Story teaser", done=True, result={"media_id": "S1"}))
    assert publish.logged_result({"id": "a", "made_at": 0}, "instagram", "media_id") == "M9"
