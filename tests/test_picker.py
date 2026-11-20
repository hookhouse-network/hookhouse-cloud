"""20 Nov (owner: "give topic and campaign search and picking module ... similar to the campaign"; "make sure you find
the footage that the campaign offers ... I don't want any issues after joining")."""
import json

import pytest

from engine import picker


def test_footage_is_confirmed_before_joining():
    assert picker.footage_check({"kick": "dasgasd3m"}, live=False)[0] == "ok"
    assert picker.footage_check({"allowed_sources": ["https://drive.google.com/file/d/x"]}, live=False)[0] == "ok"
    assert picker.footage_check({"allowed_sources": ["https://twitch.tv/x"]}, live=False)[0] == "blocked"

    class MCP:
        def __init__(self, assets):
            self.assets = assets

        def tool(self, name, **kw):
            return self.assets
    ca = {"source": "clippingalpha", "id": "c1"}
    locked = MCP({"brandAssetCount": 3})
    assert picker.footage_check(ca, mcp=locked)[0] == "unknown"               # only visible after joining
    pages = MCP({"videos": ["https://www.youtube.com/watch?v=abc"]})
    assert picker.footage_check(ca, mcp=pages)[0] == "blocked"
    files = MCP({"videos": ["https://www.dropbox.com/s/abc/clip.mp4?dl=1"]})
    assert picker.footage_check(ca, mcp=files)[0] == "ok"


def _db(tmp_path, rows):
    from engine import db
    conn = db.connect(tmp_path / "c.db")
    for r in rows:
        db.save_campaign(conn, r)
    return conn


def test_campaign_search_ranks_footage_ok_first_and_hides_blocked(tmp_path, monkeypatch):
    monkeypatch.setattr("engine.campaigns.score_campaign", lambda c, cfg=None: (c.get("_s", 1), ["fits"]))
    conn = _db(tmp_path, [
        {"id": "a", "name": "GTA 6 Kick streamer", "kick": "x", "status": "found", "_s": 2},
        {"id": "b", "name": "GTA 6 Twitch only", "allowed_sources": ["https://twitch.tv/y"], "status": "found", "_s": 9},
        {"id": "c", "name": "Cooking show", "kick": "z", "status": "found", "_s": 5},
        {"id": "d", "name": "GTA 6 ended", "kick": "q", "status": "ended", "_s": 9}])
    rows = picker.find_campaigns("gta", conn=conn, live=False)
    assert [r["id"] for r in rows] == ["a"]                                    # b blocked, c off-topic, d ended
    assert [r["id"] for r in picker.find_campaigns("gta", conn=conn, live=False, show_all=True)] == ["a", "b"]


def test_pick_campaign_refuses_without_footage_and_appends_with(tmp_path, monkeypatch):
    conn = _db(tmp_path, [{"id": "ok1", "name": "Kick one", "kick": "s", "url": "https://cr/1"},
                          {"id": "no1", "name": "Twitch one", "allowed_sources": ["https://twitch.tv/y"]}])
    f = tmp_path / "picked.yaml"
    f.write_text("# owner notes\ncampaigns:\n  - id: old\n    name: Old\n", encoding="utf-8")
    monkeypatch.setattr(picker, "CAMPAIGNS_FILE", f)
    assert picker.pick_campaign("no1", conn=conn, live=False).startswith("🛑")
    assert picker.pick_campaign("ok1", account="stream_clips", conn=conn, live=False).startswith("✅")
    import yaml
    d = yaml.safe_load(f.read_text(encoding="utf-8"))
    assert [c["id"] for c in d["campaigns"]] == ["old", "ok1"] and d["campaigns"][1]["status"] == "picked"
    assert "# owner notes" in f.read_text(encoding="utf-8")                   # comments kept
    assert "already" in picker.pick_campaign("ok1", conn=conn, live=False)


def test_topics_are_checked_ranked_by_demand(monkeypatch):
    monkeypatch.setattr("engine.config.channel", lambda cid: {"id": cid, "name": "Cosmos", "niche": "space facts",
                                                              "market": "US"})
    tiers = {"Why Venus spins backwards": "hot", "Mickey Mouse in space": "hot", "Moon facts": "cold"}
    monkeypatch.setattr("engine.topic_proof.proof", lambda t, ch, **k: {"tier": tiers.get(t, "unknown"), "top": [],
                                                                         "best_per_day": 1})

    class B:
        def ask_json(self, task, prompt, temperature=0.8):
            return {"topics": [{"topic": t, "why": "w"} for t in tiers]}, None
    got = picker.find_topics("space", channel="cosmos_unboxed", brain=B(), log=lambda m: None)
    assert [t["topic"] for t in got] == ["Why Venus spins backwards", "Moon facts"]   # franchise name dropped


def test_best_channel_from_the_niche(monkeypatch):
    chans = [{"id": "cosmos_unboxed", "name": "Cosmos Unboxed", "niche": "space facts universe", "type": "story"},
             {"id": "deep_blue_files", "name": "Deep Blue Files", "niche": "ocean deep sea", "type": "story"}]
    monkeypatch.setattr("engine.config.channels", lambda: chans)
    assert picker.best_channels("weird ocean creatures of the deep sea")[0]["id"] == "deep_blue_files"


def test_pick_topic_takes_the_next_unmade_slot_or_queues(tmp_path, monkeypatch):
    from engine import autopilot
    monkeypatch.setattr(picker, "TOPICS_FILE", tmp_path / "picked.json")
    items = [("w", {"id": "made1", "channel": "c", "status": "made", "kind": "short", "publish_at": "2099-01-01T10:00"}),
             ("w", {"id": "p1", "channel": "c", "status": "planned", "kind": "short", "publish_at": "2099-01-01T12:00"})]
    monkeypatch.setattr(autopilot, "items", lambda *a, **k: items)
    upd = {}
    monkeypatch.setattr(autopilot, "update_item", lambda s, iid, **f: upd.setdefault(iid, f))
    assert picker.pick_topic("Why Venus spins backwards", "c").startswith("✅")
    assert upd["p1"]["topic"] == "Why Venus spins backwards" and upd["p1"]["owner_pick"] is True
    monkeypatch.setattr(autopilot, "items", lambda *a, **k: [])
    assert picker.pick_topic("Saturn's rings are young", "c").startswith("🕒")
    assert [t["topic"] for t in picker.queued_topics("c")] == ["Saturn's rings are young"]
    assert picker.queued_topics("c") == []                                     # taken once
    assert picker.pick_topic("Mickey Mouse explains Mars", "c").startswith("Not picked")


def test_suggest_lists_only_topics_with_demand_now(monkeypatch):
    monkeypatch.setattr("engine.config.channel", lambda cid: {"id": cid, "name": "Cosmos", "niche": "space facts"})
    monkeypatch.setattr("engine.topic_bank.hints", lambda cid, avoid: ["Voyager 1"])
    seen = {}

    def fake_find(query, channel=None, n=8, brain=None, log=print):
        seen["q"] = query
        return [{"topic": "A", "tier": "hot", "channel": channel, "demand": "", "why": ""},
                {"topic": "B", "tier": "cold", "channel": channel, "demand": "", "why": ""},
                {"topic": "C", "tier": "warm", "channel": channel, "demand": "", "why": ""}]
    monkeypatch.setattr(picker, "find_topics", fake_find)
    assert [t["topic"] for t in picker.suggest("cosmos_unboxed", log=lambda m: None)] == ["A", "C"]
    assert "Voyager 1" in seen["q"]
