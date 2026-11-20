"""Telegram pick flow (fake API), hot-topic matching, long-source hot spots, platform-link refusal."""
import json

import pytest

from engine import clips, hot_topics, telegram_bot as tb


def test_hot_match_gta():
    tops = [{"name": "GTA 6", "keywords": ["gta 6", "gta vi", "grand theft auto"], "boost": 30}]
    names, boost = hot_topics.match({"name": "Clip my GTA VI streams", "niche": "streams"}, tops)
    assert names == ["GTA 6"] and boost == 30
    assert hot_topics.match({"name": "Megatask podcast"}, tops) == ([], 0)    # no partial-word match


def test_hotspots_finds_loud_window():
    levels = [-40.0] * 3600
    for s in range(2000, 2100):                       # one loud minute+ in the middle of an hour
        levels[s] = -10.0
    spans = clips.hotspots(levels, window=300, top=2)
    assert any(a <= 2000 and b >= 2100 for a, b in spans)


def test_platform_links_refused(tmp_path):
    for url in ("https://www.youtube.com/watch?v=x", "https://www.twitch.tv/videos/1", "https://kick.com/a/videos/b"):
        with pytest.raises(RuntimeError):
            clips.fetch_source(url, tmp_path)


def test_pick_flow(monkeypatch, tmp_path):
    sent, calls = [], []
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "x")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    monkeypatch.setattr(tb, "STATE", tmp_path / "state.json")
    monkeypatch.setattr(tb, "PICKS", tmp_path / "picks.jsonl")
    camps = {"a": {"id": "a", "name": "GTA streamer clips", "brand": "B1", "fit": "OK", "score": 5, "url": "u1",
                   "hot": ["GTA 6"]},
             "b": {"id": "b", "name": "Podcast clips", "brand": "B2", "fit": "OK", "score": 9, "url": "u2"}}
    saved = {}

    class FakeDB:
        @staticmethod
        def list_campaigns(conn, status=None):
            return list(camps.values()) if status == "eligible" else []

        @staticmethod
        def get_campaign(conn, cid):
            return camps.get(cid)

        @staticmethod
        def save_campaign(conn, c):
            saved[c["id"]] = c["status"]

    import engine
    monkeypatch.setattr(engine, "db", FakeDB, raising=False)
    import sys
    monkeypatch.setitem(sys.modules, "engine.db", FakeDB)

    kbs = []

    def fake_api(method, files=None, http_timeout=30, **p):
        calls.append(method)
        if method == "sendMessage":
            sent.append(p["text"])
            kbs.append(p.get("reply_markup"))
            return {"message_id": 7}
        return True

    monkeypatch.setattr(tb, "api", fake_api)
    tb.digest(conn=object())
    assert "GTA 6" in sent[-1]
    order = json.loads((tmp_path / "state.json").read_text())["digest"]["ids"]
    cb = lambda data: {"callback_query": {"id": "1", "data": data, "message": {"chat": {"id": 42}, "message_id": 7}}}
    tb.handle(cb(f"t:{order.index('a')}"), conn=object())
    tb.handle(cb(f"t:{order.index('b')}"), conn=object())
    # 20 Nov: footage is confirmed first, then the SYSTEM joins (owner: "the join should be done through the system")
    monkeypatch.setattr("engine.picker.footage_check",
                        lambda c, **k: ("ok", "brief files") if c.get("id") == "a" else ("blocked", "only Twitch"))
    requested = []
    monkeypatch.setattr("engine.campaign_join.request", lambda cid, by="owner": requested.append((cid, by)))
    tb.handle(cb("c"), conn=object())
    assert saved == {"a": "picked", "b": "picked"}
    assert "joining it for you now" in sent[-1] and "not joined: footage blocked" in sent[-1]
    assert requested == [("a", "owner (Telegram Confirm)")]
    assert not any(b.get("url") for r in (kbs[-1] or {}).get("inline_keyboard", []) for b in r) or len(kbs) < 2
    # a stranger's chat is ignored
    n = len(sent)
    tb.handle({"message": {"chat": {"id": 99}, "text": "/status"}})
    assert len(sent) == n
