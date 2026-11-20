"""20 Nov (owner: "strictest policies, quality control, verifications and validations"; "nothing should bypass these
gates"; "according to channel, platform and content"). Real gates here (conftest opens them for other tests)."""
import json

import pytest

from engine import clip_gate, content_gate as cg, publish

GOOD_PROBE = {"w": 1080, "h": 1920, "audio": True, "dur": 40.0}


@pytest.fixture
def story(tmp_path, monkeypatch):
    out = tmp_path / "v"
    out.mkdir()
    (out / "video.mp4").write_bytes(b"x" * 4096)
    meta = {"title": "The lake that swallowed a town", "description": "A true story.", "format": "short",
            "fact_check": {"checked": True, "ok": True}, "ai_label": True}
    (out / "upload.json").write_text(json.dumps(meta))
    ch = {"id": "unsolved_after_dark", "type": "story"}
    monkeypatch.setattr(cg, "_channel", lambda it: ch)
    monkeypatch.setattr("engine.reach_gate.probe", lambda v: dict(GOOD_PROBE))
    monkeypatch.setattr("engine.media.ffmpeg.duration", lambda v: 40.0)
    monkeypatch.setattr("engine.quality.check_video", lambda c, v, m, f: {"score": 100, "issues": []})
    it = {"id": "s1", "channel": "unsolved_after_dark", "kind": "short", "out_dir": str(out), "file": "video.mp4",
          "publish_at": "2099-01-05T10:00:00+05:30",
          "made_at": 5.0}
    return {"it": it, "out": out, "meta": meta, "ch": ch}


def _meta(story, **kw):
    m = dict(story["meta"], **kw)
    (story["out"] / "upload.json").write_text(json.dumps(m))


def test_a_clean_story_short_passes_everywhere_it_is_allowed(story, monkeypatch):
    monkeypatch.setattr("engine.platforms.allowed", lambda ch, p, meta=None: True)
    assert cg.verify(story["it"]) == []
    for p in ("youtube", "instagram", "facebook", "threads", "telegram"):
        assert cg.verify(story["it"], p) == [], p


@pytest.mark.parametrize("change, expect", [
    ({"fact_check": None}, "fact-check missing"),
    ({"fact_check": {"checked": True, "ok": False, "problems": ["wrong year"]}}, "fact-check failed"),
    ({"title": ""}, "no title"),
    ({"ai_label": False}, "AI disclosure"),
    ({"title": "Mickey Mouse explains the moon"}, "protected franchise"),
    ({"policy_flags": ["gambling"]}, "never-topic"),
])
def test_each_record_problem_blocks(story, change, expect):
    _meta(story, **change)
    assert any(expect in p for p in cg.verify(story["it"])), cg.verify(story["it"])


def test_the_file_is_measured_not_trusted(story, monkeypatch):
    monkeypatch.setattr("engine.reach_gate.probe", lambda v: dict(GOOD_PROBE, w=1920, h=1080))
    assert any("vertical 9:16" in p for p in cg.verify(story["it"]))
    monkeypatch.setattr("engine.reach_gate.probe", lambda v: dict(GOOD_PROBE, audio=False))
    assert "no sound track" in cg.verify(story["it"])
    monkeypatch.setattr("engine.reach_gate.probe", lambda v: (_ for _ in ()).throw(OSError("ffprobe missing")))
    assert any("could not be measured" in p for p in cg.verify(story["it"]))
    (story["out"] / "video.mp4").unlink()
    assert any("missing" in p for p in cg.verify(story["it"]))


def test_quality_must_be_100_and_bad_findings_block(story, monkeypatch):
    monkeypatch.setattr("engine.quality.check_video",
                        lambda c, v, m, f: {"score": 93, "issues": [("warn", "ends on black")]})
    probs = cg.verify(story["it"])
    assert any("score 93/100" in p and "ends on black" in p for p in probs) and cg.fixable_by_remake(probs)
    story["it"]["made_at"] = 6.0                                   # a new version is scored again
    monkeypatch.setattr("engine.quality.check_video",
                        lambda c, v, m, f: {"score": 85, "issues": [("bad", "peaks +1 dB")]})
    assert any("peaks" in p for p in cg.verify(story["it"]))
    monkeypatch.setattr("engine.quality.check_video", lambda *a: (_ for _ in ()).throw(RuntimeError("x")))
    story["it"]["made_at"] = 7.0
    assert any("scorecard could not run" in p for p in cg.verify(story["it"]))      # not scored = not passed


def test_platform_rules(story, monkeypatch):
    monkeypatch.setattr("engine.platforms.allowed", lambda ch, p, meta=None: p != "dailymotion")
    assert any("not allowed on dailymotion" in p for p in cg.verify(story["it"], "dailymotion"))
    monkeypatch.setattr("engine.media.ffmpeg.duration", lambda v: 120.0)
    assert any("longer than 90" in p for p in cg.verify(story["it"], "facebook"))
    _meta(story, instagram_caption="x " + " ".join(f"#t{i}" for i in range(7)))
    assert any("more than 5 hashtags" in p for p in cg.verify(story["it"], "instagram"))
    assert any("no rules for platform tiktok" in p for p in cg.verify(story["it"], "tiktok"))   # new = add rules


def test_kids_rules(story, monkeypatch):
    kids = {"id": "bloop_and_friends", "type": "kids"}
    monkeypatch.setattr(cg, "_channel", lambda it: kids)
    _meta(story, fact_check=None, ai_label=False, made_for_kids=False)
    assert "kids video not marked made-for-kids" in cg.verify(story["it"])
    _meta(story, fact_check=None, ai_label=False, made_for_kids=True)
    monkeypatch.setattr("engine.platforms.allowed", lambda ch, p, meta=None: True)
    assert any("never go to instagram" in p for p in cg.verify(story["it"], "instagram"))


def test_upload_item_cannot_post_past_the_gate(story, monkeypatch, tmp_path):
    monkeypatch.setattr(publish, "LOG", tmp_path / "log.jsonl")
    _meta(story, fact_check=None)
    called = []
    monkeypatch.setattr(publish, "youtube_upload", lambda *a, **k: called.append(1))
    monkeypatch.setattr(publish, "instagram_reel", lambda *a, **k: called.append(1))
    acts = publish.upload_item(story["it"], dry_run=False, platforms=("youtube", "instagram"))
    assert called == [] and all(a.what.startswith("BLOCKED") for a in acts) and len(acts) == 2
    from engine import publish_queue as pq
    assert pq.classify(acts[0])[0] == "permanent"


def test_a_gate_that_crashes_blocks(story, monkeypatch, tmp_path):
    monkeypatch.setattr(publish, "LOG", tmp_path / "log.jsonl")
    monkeypatch.setattr(cg, "base_problems", lambda it, *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    called = []
    monkeypatch.setattr(publish, "youtube_upload", lambda *a, **k: called.append(1))
    acts = publish.upload_item(story["it"], dry_run=False, platforms=("youtube",))
    assert called == [] and "could not run" in acts[0].result["error"]


# ---------------------------------------------------------------- the strict clip gate
@pytest.fixture
def clip(tmp_path, monkeypatch):
    out = tmp_path / "c"
    out.mkdir()
    (out / "clip_01.mp4").write_bytes(b"x" * 4096)
    entry = {"file": "clip_01.mp4", "campaign": "c1", "duration_s": 40.0, "edit_hash": "h1",
             "permission": {"basis": "campaign", "evidence": "https://brief"}}
    (out / "clips.json").write_text(json.dumps([entry]))
    (out / "upload.json").write_text(json.dumps({"title": "T", "clip": True, "campaign": "c1"}))
    monkeypatch.setattr("engine.campaign_gate.gate_item", lambda it, brain_fn=None: [])
    camp = {"id": "c1", "platforms": ["youtube_shorts", "instagram_reels"], "length_seconds": {"min": 15, "max": 60}}
    monkeypatch.setattr("engine.db.connect", lambda *a, **k: None)
    monkeypatch.setattr("engine.db.get_campaign", lambda conn, cid: dict(camp))
    monkeypatch.setattr("engine.reach_gate.probe", lambda v: dict(GOOD_PROBE))
    monkeypatch.setattr("engine.reach_gate.letterboxed", lambda v, d: False)
    monkeypatch.setattr("engine.campaign_safety.video_hash", lambda v: "h1")
    it = {"id": "k1", "channel": "hot_take_hq", "kind": "clip", "out_dir": str(out), "file": "clip_01.mp4"}
    return {"it": it, "out": out, "entry": entry, "camp": camp, "ch": {"id": "hot_take_hq", "type": "clips"}}


def test_a_verified_campaign_clip_passes_only_on_its_brief_platforms(clip):
    assert clip_gate.verify(clip["it"], ch=clip["ch"]) == []
    assert clip_gate.verify(clip["it"], platform="instagram", ch=clip["ch"]) == []
    assert any("not allowed on facebook" in p for p in clip_gate.verify(clip["it"], "facebook", ch=clip["ch"]))


def test_clip_gate_fails_closed(clip, monkeypatch):
    (clip["out"] / "clips.json").unlink()                           # record gone: never "not a clip"
    assert any("without its clip record" in p for p in clip_gate.verify(clip["it"], ch=clip["ch"]))


@pytest.mark.parametrize("patch, expect", [
    ({"edit_hash": "OTHER"}, "hash mismatch"),
    ({"duration_s": 20.0}, "not the checked edit"),
    ({"permission": {}}, "no permission record"),
])
def test_each_clip_problem_blocks(clip, patch, expect):
    (clip["out"] / "clips.json").write_text(json.dumps([dict(clip["entry"], **patch)]))
    assert any(expect in p for p in clip_gate.verify(clip["it"], ch=clip["ch"]))


def test_unknown_brief_platforms_block_everywhere(clip, monkeypatch):
    monkeypatch.setattr("engine.db.get_campaign", lambda conn, cid: dict(clip["camp"], platforms=[]))
    assert any("lists no platforms" in p for p in clip_gate.verify(clip["it"], "youtube", ch=clip["ch"]))


def test_file_outside_the_campaign_length_or_letterboxed_blocks(clip, monkeypatch):
    monkeypatch.setattr("engine.reach_gate.probe", lambda v: dict(GOOD_PROBE, dur=75.0))
    (clip["out"] / "clips.json").write_text(json.dumps([dict(clip["entry"], duration_s=75.0)]))
    assert any("outside the campaign" in p for p in clip_gate.verify(clip["it"], ch=clip["ch"]))
    monkeypatch.setattr("engine.reach_gate.probe", lambda v: dict(GOOD_PROBE))
    (clip["out"] / "clips.json").write_text(json.dumps([clip["entry"]]))
    monkeypatch.setattr("engine.reach_gate.letterboxed", lambda v, d: True)
    assert any("black bars" in p for p in clip_gate.verify(clip["it"], ch=clip["ch"]))


def test_register_footage_needs_evidence(clip):
    (clip["out"] / "clips.json").write_text(json.dumps([dict(clip["entry"], campaign=None,
                                                            permission={"basis": "written_permission"})]))
    (clip["out"] / "upload.json").write_text(json.dumps({"title": "T", "clip": True}))
    assert any("no evidence" in p for p in clip_gate.verify(clip["it"], ch=clip["ch"]))


def test_the_campaign_gate_problems_come_through(clip, monkeypatch):
    monkeypatch.setattr("engine.campaign_gate.gate_item", lambda it, brain_fn=None: ["caption is missing @brand"])
    assert "caption is missing @brand" in clip_gate.verify(clip["it"], ch=clip["ch"])
