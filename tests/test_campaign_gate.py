"""Campaign gate (owner, 17 Nov 2026): a campaign clip comes for approval if and only if every condition is met."""
import json
import time

import pytest

from engine import campaign_gate as g
from engine import campaign_safety as cs

SEGA = {"id": "sega-steam", "name": "SEGA Steam", "status": "joined", "budget_left_pct": 80, "joined_at": 1000.0,
        "platforms": ["instagram_reels", "tiktok", "youtube_shorts"], "length_seconds": {"min": None, "max": None},
        "required_tags": ["Tag @sega_west on TikTok and YouTube", "Tag @sega on Instagram", "Add #ad to every post",
                          "Tag @segatiktok on TikTok", "No made-up facts, stats, or dates in captions", "#Ad"],
        "banned": [], "disclosure_text": None}


@pytest.fixture(autouse=True)
def _safe(monkeypatch):
    monkeypatch.setattr(cs, "check_campaign", lambda c, conn=None: {"verdict": "PASS", "block": []})


def good_meta(**kw):
    m = {"campaign": "sega-steam", "permission": {"basis": "campaign"}, "made_at": 2000.0, "duration_s": 30,
         "caption": "#ad What a deal.\n@sega_west @sega", "disclosure": True, "logo_shown": False}
    m.update(kw)
    return m


class OkBrain:
    calls = 0

    def ask(self, task, prompt, temperature=0.7):
        OkBrain.calls += 1
        n = prompt.count("\n1. ") and len([ln for ln in prompt.split("RULES:\n")[1].split("\n\n")[0].splitlines() if ln])

        class R:
            def json(self_inner):
                return [{"rule": i + 1, "result": "pass", "why": ""} for i in range(n)]
        return R()


class DeadBrain:
    def ask(self, *a, **k):
        raise RuntimeError("all models busy")


def test_rules_read_sentences_per_platform():
    r = g.rules(SEGA)
    assert r["tags"] == ["@sega_west", "@sega"]          # TikTok-only @segatiktok is not ours
    assert r["ad"] is True
    assert r["soft"] == ["No made-up facts, stats, or dates in captions"]


def test_caption_gets_tags_not_sentences():
    cap = g.fix_caption("What a deal.", SEGA)
    assert cap.startswith("#ad ")
    assert "@sega_west" in cap and "@sega" in cap
    assert "Tag @" not in cap and "every post" not in cap


def test_all_met_passes_with_ai_rule_checked_once():
    cache = {}
    OkBrain.calls = 0
    assert g.check(good_meta(), SEGA, brain=OkBrain(), cache=cache) == []
    assert g.check(good_meta(), SEGA, brain=DeadBrain(), cache=cache) == []     # cached answer, no new call
    assert OkBrain.calls == 1


@pytest.mark.parametrize("change,word", [
    ({"caption": "#ad What a deal.\n@sega_west"}, "missing @sega"),
    ({"caption": "What a deal. @sega_west @sega"}, "#ad"),
    ({"disclosure": False}, "Ad label"),
    ({"permission": {"basis": "public_domain"}}, "campaign's own material"),
    ({"made_at": 500.0}, "before we joined"),
    ({"duration_s": 200}, "length"),
])
def test_each_broken_condition_blocks(change, word):
    probs = g.check(good_meta(**change), SEGA, brain=OkBrain(), cache={})
    assert probs and any(word in p for p in probs), probs


@pytest.mark.parametrize("camp,word", [
    ({"status": "ended"}, "ended"),
    ({"state": "paused"}, "paused"),
    ({"budget_left_pct": 10}, "budget"),
    ({"needs_logo": True}, "logo"),
    ({"platforms": ["tiktok"]}, "none of our platforms"),
])
def test_campaign_state_blocks(camp, word):
    probs = g.check(good_meta(), dict(SEGA, **camp), brain=OkBrain(), cache={})
    assert any(word in p for p in probs), probs


def test_unanswered_ai_rule_holds_the_clip():
    probs = g.check(good_meta(), SEGA, brain=DeadBrain(), cache={})
    assert probs and "not checked yet" in probs[0]
    assert g.check(good_meta(), SEGA, brain=None, cache={})


def test_blocked_safety_check_blocks(monkeypatch):
    monkeypatch.setattr(cs, "check_campaign", lambda c, conn=None: {"verdict": "BLOCK", "block": ["gambling"]})
    assert any("safety" in p for p in g.check(good_meta(), SEGA, brain=OkBrain(), cache={}))


def test_not_a_campaign_clip_is_not_gated():
    assert g.check({"caption": "x"}, None) == []


def test_ask_due_holds_failing_clip(tmp_path, monkeypatch):
    from engine import autopilot as ap
    monkeypatch.setattr(ap, "STATE", tmp_path / "autopilot.json", raising=False)
    store = {}
    monkeypatch.setattr(ap, "_load", lambda: json.loads(json.dumps(store.get("s", {}))))
    monkeypatch.setattr(ap, "_save", lambda s: store.__setitem__("s", s))
    import engine.clip_gate as cg                      # 20 Nov: the strict clip gate wraps the campaign gate
    monkeypatch.setattr(cg, "is_clip", lambda it, *a, **k: False)
    monkeypatch.setattr(cg, "verify", lambda it, brain_fn=None, **k: ["caption is missing @sega"])
    it = {"id": "x1", "channel_name": "Hot Take HQ"}
    assert ap._campaign_held("w", it, log=lambda *_: None) is True
    assert "x1" in ap.gate_held()
    monkeypatch.setattr(cg, "verify", lambda it, brain_fn=None, **k: [])
    assert ap._campaign_held("w", it, log=lambda *_: None) is False
    assert "x1" not in ap.gate_held()


def test_gate_item_rechecks_fresh_campaign_and_saves(tmp_path, monkeypatch):
    from engine import db
    conn = db.connect(tmp_path / "s.db")
    db.save_campaign(conn, dict(SEGA, status="ended"))
    monkeypatch.setattr(db, "connect", lambda *a, **k: conn)
    (tmp_path / "clips.json").write_text(json.dumps([dict(good_meta(), file="clip_01.mp4")]), encoding="utf-8")
    probs = g.gate_item({"out_dir": str(tmp_path), "file": "clip_01.mp4"}, brain_fn=lambda: OkBrain())
    assert any("ended" in p for p in probs)
    saved = json.loads((tmp_path / "clips.json").read_text(encoding="utf-8"))[0]
    assert saved["gate"]["passed"] is False and saved["rule_check"]["passed"] is False
    assert time.time() - saved["gate"]["at"] < 60
