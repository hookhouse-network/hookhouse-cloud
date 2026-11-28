"""27 Nov (P8 operator brief, master plan 5.6): posted by platform, held and why, the making gap, quotas, earnings,
one next action; the weekly earnings board on Mondays."""
import json
import time

from engine import operator_brief as ob


def _log(path, rows):
    path.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")


def test_the_brief_counts_posts_and_holds(tmp_path, monkeypatch):
    now = time.time()
    rows = [
        {"at": now - 100, "platform": "youtube", "item_id": "a", "what": "upload video.mp4", "done": True},
        {"at": now - 90, "platform": "youtube", "item_id": "a", "what": "add X to playlist", "done": True},
        {"at": now - 80, "platform": "instagram", "item_id": "a", "what": "publish Reel", "done": True},
        {"at": now - 70, "platform": "threads", "item_id": "b", "what": "publish Threads video", "done": False,
         "details": {"dry_run": True}},
        {"at": now - 60, "platform": "youtube", "item_id": "c", "what": "BLOCKED by the content gate",
         "details": {"problems": ["potential: hook 4"]}},
        {"at": now - 50, "platform": "instagram", "item_id": "c", "what": "BLOCKED by the content gate",
         "details": {"problems": ["potential: hook 4"]}},
        {"at": now - 3 * 86400, "platform": "youtube", "item_id": "old", "what": "upload", "done": True},
    ]
    p = tmp_path / "log.jsonl"
    _log(p, rows)
    monkeypatch.setattr(ob, "making_gap", lambda: ["Cosmos Unboxed"])
    monkeypatch.setattr(ob, "earnings", lambda: (1200.0, 3.5))
    from engine import budgets
    monkeypatch.setattr(budgets, "summary", lambda: {"ai": [], "pictures": [{"source": "cloudflare", "open": False}],
                                                     "local": {"used": 120, "cap": 120}})
    t = ob.brief(now=now, log_path=p)
    assert "Posted (24 h): 2 - youtube 1, instagram 1" in t
    assert "Held: potential 1" in t and "Slots passed unmade: 1 (Cosmos Unboxed)" in t
    assert "cloudflare" in t and "PC pictures 120/120" in t and "Rs 1,200 received, $3.50 pending" in t
    assert "Next: Nothing urgent" in t


def test_next_action_priorities():
    assert "Heal and Improve" in ob.next_action(2, [("potential", 5)], ["a"] * 4, 0)
    assert "'potential' (5 videos)" in ob.next_action(0, [("potential", 5)], [], 3)
    assert "keep the PC on" in ob.next_action(0, [], ["a", "b", "c"], 3)
    assert "Nothing posted" in ob.next_action(0, [], [], 0)


def test_picture_free_share(monkeypatch):
    from engine import config
    monkeypatch.setattr(config, "channels", lambda: [{"id": "snack", "type": "brainrot"}, {"id": "cosmos", "type": "story"}])
    rows = [{"platform": "youtube", "channel": "snack", "item_id": "1127_0500_snack_short", "what": "upload", "done": True},
            {"platform": "instagram", "channel": "snack", "item_id": "1127_0500_snack_short", "what": "publish", "done": True},
            {"platform": "youtube", "channel": "cosmos", "item_id": "1127_0500_cosmos_short", "what": "upload", "done": True},
            {"platform": "youtube", "channel": "cosmos", "item_id": "1127_0500_cosmos_long", "what": "upload", "done": True}]
    assert ob.picture_free_share(rows) == (1, 2)


def test_hold_reasons_read_the_same_on_every_platform():
    a = ob.reason_of("not allowed on instagram (channel, kids or campaign rules)", "instagram")
    b = ob.reason_of("not allowed on threads (channel, kids or campaign rules)", "threads")
    assert a == b and "this platform" in a
    assert ob.reason_of("quality: score 79/100 (needs 85.0): narration too slow") == "quality"
    assert ob.reason_of("youtube: 🛑 blocked: potential: hook 4", "youtube") == "potential"
