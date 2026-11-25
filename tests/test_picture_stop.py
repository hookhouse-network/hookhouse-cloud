"""22 Nov: the renderer's picture-limit stop and the quality gate counted word cards differently (stop: scenes only,
over 30 %; gate: all shots, over 20 %), so a video between the two (Cosmos Unboxed 23 Nov 05:00, 3 of 13 shots) was
finished, then blocked, and its redo was spent. One count now (quality.card_count / CARD_MAX). A stopped try keeps
its pictures in the item's bank, and the very same shot comes back without a second eyes check."""
import json
from pathlib import Path

import pytest
from PIL import Image

from engine import quality, story, storyboard, weekly


def _beats(cards: int, total: int) -> list[dict]:
    out = []
    for i in range(total):
        vis = ({"kind": "text", "source": "text"} if i < cards else
               {"kind": "image", "source": "ai_scene_cloudflare", "path": f"p{i}.jpg", "match": "0.8"})
        out.append({"see": f"shot {i}", "_visual": vis})
    return out


def test_the_stop_and_the_gate_use_one_count(tmp_path, monkeypatch):
    monkeypatch.setattr(storyboard, "images_blocked", lambda: True)
    for cards, total in ((2, 13), (3, 13), (2, 10), (3, 10), (9, 11)):
        beats = _beats(cards, total)
        shots = [{"see": b["see"], **b["_visual"]} for b in beats]
        (tmp_path / "shots.json").write_text(json.dumps(shots), encoding="utf-8")
        gate_blocks = any(sev == "bad" for sev, _ in quality.story_issues(tmp_path))
        try:
            story._picture_stop(beats, tmp_path)
            stopped = False
        except storyboard.NoPictures:
            stopped = True
        assert stopped == gate_blocks == (cards / total > quality.CARD_MAX), (cards, total)


def test_cosmos_23_nov_is_stopped_and_carries_its_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(storyboard, "images_blocked", lambda: True)
    with pytest.raises(storyboard.NoPictures) as e:
        story._picture_stop(_beats(3, 13), tmp_path)
    assert "3/13 shots" in str(e.value) and e.value.out_dir == tmp_path
    from engine import autopilot
    assert autopilot.free_limit_wait(e.value)                                   # waits for the reset, keeps its tries


def test_with_pictures_available_the_render_goes_on(tmp_path, monkeypatch):
    from engine.media import local_sd
    monkeypatch.setattr(local_sd, "DROPPED", [])
    monkeypatch.setattr(storyboard, "images_blocked", lambda: False)
    assert story._picture_stop(_beats(3, 13), tmp_path) is None                # the gate decides (redo)
    designed = [{"see": "the number", "_visual": {"kind": "image", "source": "graphic"}}] + _beats(0, 3)
    monkeypatch.setattr(storyboard, "images_blocked", lambda: True)
    with pytest.raises(storyboard.NoPictures):                                  # graphics count, as in the gate
        story._picture_stop(designed, tmp_path)


def _pic(tmp_path, name):
    p = tmp_path / f"{name}.jpg"
    Image.new("RGB", (64, 112), (90, 60, 30)).save(p)
    return str(p)


def test_the_same_shot_is_reused_without_a_second_eyes_check(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(storyboard, "eyes", lambda *a, **k: seen.append(a) or {"score": 8, "ok": True})
    see = "Wide shot of the comet over the desert at night"
    bank = [{"see": "A wide shot of the comet over the desert", "path": _pic(tmp_path, "near"), "match": "0.9",
             "source": "ai_scene_cloudflare", "kind": "image"},
            {"see": see.upper() + "  ", "path": _pic(tmp_path, "same"), "match": "0.8",
             "source": "ai_scene_local_sd", "kind": "image"}]
    got = storyboard.reuse({"see": see, "narration": "x"}, bank, log=lambda *a: None, i=0)
    assert got["path"].name == "same.jpg" and got["match"] == 0.8 and seen == []
    assert [b["path"] for b in bank] == [str(tmp_path / "near.jpg")]
    weak = [{"see": see, "path": _pic(tmp_path, "weak"), "match": "0.5", "source": "ai_scene_x", "kind": "image"}]
    assert storyboard.reuse({"see": see, "narration": "x"}, weak, log=lambda *a: None, i=2)
    assert len(seen) == 1                                                       # a weak stored score: checked again


def test_the_opening_shot_comes_from_the_bank_only_when_it_is_the_very_same(tmp_path, monkeypatch):
    asked, drawn = [], []
    monkeypatch.setattr(storyboard, "reuse", lambda beat, bank, era="", log=print, i=0: asked.append(i) or
                        {"kind": "image", "path": Path("old.jpg"), "source": "ai_scene_reuse"})
    monkeypatch.setattr(storyboard, "scene", lambda beat, era, size, log=print, i=0, tries=3, seed=None:
                        drawn.append(i) or {"kind": "image", "path": Path("new.jpg"), "source": "ai_scene_x"})
    beat = {"visual": "scene", "_prompt": "p", "see": "Raja Raghu in the empty treasury", "narration": "x"}
    args = (2.5, ["#000000"], tmp_path, 0, "hi", "awe", set(), (1080, 1920))
    same = [{"see": "raja raghu in the empty  treasury", "path": "x.jpg"}]
    other = [{"see": "Raja Raghu on his chariot", "path": "y.jpg"}]
    got = story.find_beat_visual(beat, *args, log=lambda *a: None, bank=same)
    assert got["source"] == "ai_scene_reuse" and asked == [0] and drawn == []
    got = story.find_beat_visual(beat, *args, log=lambda *a: None, bank=other)
    assert got["path"].name == "new.jpg" and asked == [0] and drawn == [0]


def test_a_stopped_try_keeps_its_pictures_and_its_script(tmp_path, monkeypatch):
    from engine import config
    monkeypatch.setattr(config, "channel", lambda cid: {"id": cid, "name": "Cosmos Unboxed", "type": "story"})
    monkeypatch.setattr(weekly, "clip_slot", lambda ch, it: False)
    monkeypatch.setattr(weekly, "story_paused", lambda ch: None)
    monkeypatch.setattr(weekly, "franchise_names", lambda it: [])
    monkeypatch.setattr(weekly, "_refresh_topic", lambda *a, **k: None)
    out = tmp_path / "out"
    out.mkdir()
    shots = [{"see": "Saturn's rings edge-on", "kind": "image", "path": _pic(tmp_path, "rings"), "match": "0.9",
              "source": "ai_scene_cloudflare"}, {"see": "the number", "kind": "text", "source": "text"}]
    (out / "shots.json").write_text(json.dumps(shots), encoding="utf-8")
    script = {"title": "Saturn loses its rings", "beats": [{"see": "Saturn's rings edge-on", "_prompt": "p"}]}

    def make(brain, ch, topic=None, fmt="short", script=None, memory=None, log=print, on_script=None, bank=None):
        on_script(dict(script or {}, title="Saturn loses its rings"))
        e = storyboard.NoPictures("10/13 shots would be word cards")
        e.out_dir = out
        raise e
    monkeypatch.setattr(story, "make", make)
    item = {"id": "1123_0500_cosmos_unboxed_short", "channel": "cosmos_unboxed", "kind": "short",
            "status": "planned", "topic": "Saturn's rings", "refreshed": True}
    with pytest.raises(storyboard.NoPictures):
        weekly.make_item({"items": [item]}, item, brain=object(), log=lambda *a: None)
    assert [b["see"] for b in weekly.shot_bank(item)] == ["Saturn's rings edge-on"]
    assert weekly.shot_bank(item)[0]["match"] == "0.9"
    assert weekly.checkpoint(item)["script"]["title"] == script["title"]        # the retry resumes the same script


def test_local_drawing_that_dropped_out_mid_video_stops_it(tmp_path, monkeypatch):
    """25 Nov: Clutch Tales went on battery mid-video and Cricket's local pictures timed out: 8/15 word cards were
    finished anyway (a cloud source still counted as open), blocked by the gate, and the remake spent."""
    from engine.media import local_sd
    monkeypatch.setattr(storyboard, "images_blocked", lambda: False)
    monkeypatch.setattr(local_sd, "DROPPED", ["the PC runs on its battery", "the PC runs on its battery"])
    with pytest.raises(storyboard.NoPictures) as e:
        story._picture_stop(_beats(8, 15), tmp_path)
    assert "local pictures dropped out (the PC runs on its battery)" in str(e.value)
    monkeypatch.setattr(local_sd, "DROPPED", ["TimeoutExpired"])
    assert story._picture_stop(_beats(2, 15), tmp_path) is None                # few cards: the video goes on


def test_a_failed_local_draw_is_remembered(monkeypatch):
    from engine.media import local_sd
    monkeypatch.setattr(local_sd, "DROPPED", [])
    monkeypatch.setattr(local_sd, "why_not", lambda start=False: "the PC runs on its battery")
    assert local_sd.draw("a lake", 1) is None and local_sd.DROPPED == ["the PC runs on its battery"]
