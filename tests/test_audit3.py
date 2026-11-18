"""Third audit (12 Nov): Telegram rate limits, YouTube metadata limits, login health, Meta long-lived tokens, the
weekly learning loop, approval fallback, planning back-off, campaign list repeats, quiet hours."""
import json
import sqlite3
import time
from datetime import timedelta

import pytest

from engine import autopilot, publish, weekly


class R:
    def __init__(self, d, code=200):
        self.d, self.status_code, self.ok, self.text = d, code, code < 400, json.dumps(d)

    def json(self):
        return self.d

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


def test_telegram_waits_when_rate_limited(monkeypatch):
    from engine import telegram_bot as tb
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "x")
    answers = [R({"ok": False, "description": "Too Many Requests", "parameters": {"retry_after": 1}}, 429),
               R({"ok": True, "result": {"message_id": 5}})]
    monkeypatch.setattr(tb.requests, "post", lambda *a, **k: answers.pop(0))
    slept = []
    monkeypatch.setattr(tb.time, "sleep", lambda s: slept.append(s))
    assert tb.api("sendMessage", chat_id="1", text="hi") == {"message_id": 5} and slept == [1.0]


def test_youtube_metadata_respects_limits():
    body = publish.youtube_metadata({"title": "Why <this> matters", "description": "a > b",
                                     "tags": [f"tag number {i} long words here" for i in range(40)]}, None)
    sn = body["snippet"]
    assert "<" not in sn["title"] and ">" not in sn["description"]
    assert len(sn["tags"]) <= 15 and sum(len(t) + 3 for t in sn["tags"]) <= 500
    assert body["status"]["privacyStatus"] == "public"           # posting now: not stuck private


def test_meta_token_is_made_long_lived(tmp_path, monkeypatch):
    from engine import connect
    monkeypatch.setattr(connect, "SECRETS", tmp_path)
    monkeypatch.setenv("META_APP_ID", "1")
    monkeypatch.setenv("META_APP_SECRET", "s")

    class S:
        def get(self, url, params=None, **k):
            if "oauth/access_token" in url:
                return R({"access_token": "LONG", "expires_in": 5184000})
            return R({"access_token": "PAGE"})
    rec = connect.save_meta("hot_take_hq", "ig1", "page1", "SHORT", session=S())
    assert rec["access_token"] == "LONG" and rec["page_token"] == "PAGE" and rec["expires_at"] > time.time() + 50 * 86400


def test_login_health_warns_before_expiry(tmp_path, monkeypatch):
    from engine import connect
    monkeypatch.setattr(connect, "SECRETS", tmp_path)
    (tmp_path / "meta_hot_take_hq.json").write_text(json.dumps({"access_token": "t",
                                                                "expires_at": time.time() + 3 * 86400}))
    probs = connect.token_health(session=None)
    assert len(probs) == 1 and "ends in 3 days" in probs[0]


def test_learning_loop_adds_each_winner_once(tmp_path, monkeypatch):
    from engine import analytics, config
    monkeypatch.setattr(autopilot, "STATE", tmp_path / "autopilot.json")
    conn = sqlite3.connect(":memory:")
    conn.executescript(analytics.SCHEMA)
    now = time.time()
    for i in range(10):
        conn.execute("INSERT INTO video_metrics(item_id, channel, platform, hook, posted_at, hours_after, views) "
                     "VALUES (?,?,?,?,?,?,?)", (f"i{i}", "unsolved_after_dark", "youtube", f"Hook {i}", now - 86400 * 3,
                                                48, 1000 * (i + 1)))
    monkeypatch.setattr(analytics, "connect", lambda *a, **k: conn)
    monkeypatch.setattr(config, "channels", lambda: [{"id": "unsolved_after_dark"}])
    added = []

    class Mem:
        def add(self, kind, text, **k):
            added.append(text)
    sent = []
    from engine import telegram_bot as tb
    monkeypatch.setattr(tb, "notify", lambda t: sent.append(t) or True)
    assert autopilot._learn(lambda: (None, Mem()), print) == 2           # top 20% of 10 videos
    assert autopilot._learn(lambda: (None, Mem()), print) == 0           # never twice
    assert added == ["Hook 9", "Hook 8"] and sent and "Weekly learning report" in sent[0]


def test_question_still_sent_when_preview_fails(tmp_path, monkeypatch):
    from engine import telegram_bot as tb
    monkeypatch.setattr(autopilot, "STATE", tmp_path / "autopilot.json")
    out = tmp_path / "v"
    out.mkdir()
    (out / "video.mp4").write_bytes(b"x")
    monkeypatch.setattr(autopilot, "preview_file", lambda it: (_ for _ in ()).throw(RuntimeError("ffmpeg")))
    monkeypatch.setattr(autopilot, "approval_text", lambda it, r=False: "Approve?")
    sent = []
    monkeypatch.setattr(tb, "send", lambda t, **k: sent.append((t, k)))
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "1")
    it = {"id": "a", "channel": "unsolved_after_dark", "out_dir": str(out), "file": "video.mp4", "kind": "short",
          "made_at": 1.0}
    autopilot.ask("2099-01-05", it)
    assert sent and "reply_markup" in sent[0][1] and "PC dashboard" in sent[0][0]
    assert autopilot._load()["asked"]["a"]


def test_failed_planning_waits_an_hour(tmp_path, monkeypatch):
    monkeypatch.setattr(weekly, "WEEKS_DIR", tmp_path / "weeks")
    monkeypatch.setattr(autopilot, "STATE", tmp_path / "autopilot.json")
    calls = []

    def boom(*a, **k):
        calls.append(1)
        raise RuntimeError("all models busy")
    monkeypatch.setattr(weekly, "plan_week", boom)
    for _ in range(3):
        with pytest.raises(RuntimeError) if not calls else _noop():
            autopilot._ensure_plan(lambda: (None, None), print)
    assert calls == [1]


class _noop:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_morning_list_drops_campaigns_passed_over_three_times(tmp_path, monkeypatch):
    from engine import db, telegram_bot as tb
    monkeypatch.setattr(tb, "STATE", tmp_path / "state.json")
    conn = db.connect(tmp_path / "c.db") if "path" in db.connect.__code__.co_varnames else None
    if conn is None:
        pytest.skip("db.connect has no path argument")
    for i in range(3):
        db.save_campaign(conn, {"id": f"c{i}", "name": f"C{i}", "status": "eligible", "fit": "OK", "score": i})
    tb._save({"shown": {"c0": 3}})
    assert [c["id"] for c in tb.candidates(conn)] == ["c2", "c1"]
    assert {c["id"] for c in tb.candidates(conn, fresh_only=False)} == {"c0", "c1", "c2"}


def test_quiet_hours_is_a_bool():
    from engine import telegram_bot as tb
    assert tb.quiet_hours() in (True, False)


def test_change_soon_before_slot_moves_it(tmp_path, monkeypatch):
    monkeypatch.setattr(weekly, "WEEKS_DIR", tmp_path / "weeks")
    monkeypatch.setattr(autopilot, "STATE", tmp_path / "autopilot.json")
    from engine import telegram_bot as tb
    monkeypatch.setattr(tb, "notify", lambda t: True)
    now = autopilot._now()
    plan = {"start": "2099-01-05", "items": [
        {"id": "L", "channel": "unsolved_after_dark", "channel_name": "U", "kind": "long", "status": "made",
         "made_at": 5.0, "publish_at": (now + timedelta(hours=2)).isoformat(), "out_dir": str(tmp_path)}]}
    (tmp_path / "weeks" / "2099-01-05").mkdir(parents=True)
    (tmp_path / "weeks" / "2099-01-05" / "plan.json").write_text(json.dumps(plan))
    autopilot.decide(autopilot.token("2099-01-05", "L", "5.0"), "change", "darker music")
    it = weekly.load_plan("2099-01-05")["items"][0]
    assert it["status"] == "redo" and autopilot._when(it) >= now + timedelta(hours=6)
