"""P3b asset bank (22 Nov): a remake writes a new script, so every shot prompt changed and every picture was drawn
again (Itihaas 22 Nov 12:30 three times in one morning; the redos took the free picture allowance). The last versions'
pictures are offered first; word overlap ranks them, the eyes check against the NEW narration decides, the opening
shot is always drawn new, and a picture is used once per video."""
import json

from PIL import Image

from engine import storyboard, weekly

COURT_OLD = "A medium shot of Raja Raghu standing in his pillared royal court with empty treasury chests around him"
COURT_NEW = "Medium shot of the royal treasury room with empty stone chests, Raja Raghu standing alone in the court"
BOW_OLD = "A medium shot of Kautsa bowing respectfully with folded hands before his guru in a forest hermitage"
SKY = "Wide shot of the night sky over a desert with a single comet"


def _pic(tmp_path, name):
    p = tmp_path / f"{name}.jpg"
    Image.new("RGB", (64, 112), (120, 90, 40)).save(p)
    return str(p)


def _bank(tmp_path):
    return [{"see": COURT_OLD, "path": _pic(tmp_path, "court"), "source": "ai_scene_cloudflare", "kind": "image"},
            {"see": BOW_OLD, "path": _pic(tmp_path, "bow"), "source": "ai_scene_local_sd", "kind": "image"}]


def _eyes(score=8, ok=True, seen=None):
    def fake(path, narration, see, era=""):
        if seen is not None:
            seen.append(str(path))
        return {"score": score, "text": False, "wrong": "", "ok": ok}
    return fake


def test_overlap_ranks_the_same_moment_above_another_scene():
    assert storyboard.shot_overlap(COURT_NEW, COURT_OLD) > storyboard.shot_overlap(COURT_NEW, BOW_OLD)
    assert storyboard.shot_overlap(COURT_NEW, COURT_OLD) >= storyboard.REUSE_MIN
    assert storyboard.shot_overlap(SKY, COURT_OLD) == 0.0
    assert storyboard.shot_overlap("", COURT_OLD) == 0.0


def test_the_closest_picture_the_eyes_accept_is_reused_once(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(storyboard, "eyes", _eyes(seen=seen))
    bank = _bank(tmp_path)
    got = storyboard.reuse({"see": COURT_NEW, "narration": "khazana khali tha"}, bank, log=lambda *a: None, i=3)
    assert got["source"] == "ai_scene_reuse" and got["path"].name == "court.jpg" and got["match"] == 0.8
    assert seen == [str(tmp_path / "court.jpg")]                     # one eyes check: the best-ranked picture only
    assert [b["see"] for b in bank] == [BOW_OLD]                      # never twice in one video
    again = storyboard.reuse({"see": COURT_NEW, "narration": "x"}, bank, log=lambda *a: None, i=4)
    assert again is None                                              # the bow picture does not overlap enough


def test_a_picture_the_eyes_refuse_stays_and_a_new_one_is_drawn(tmp_path, monkeypatch):
    monkeypatch.setattr(storyboard, "eyes", _eyes(score=4, ok=False))
    bank = _bank(tmp_path)
    assert storyboard.reuse({"see": COURT_NEW, "narration": "x"}, bank, log=lambda *a: None, i=2) is None
    assert len(bank) == 2


def test_without_the_eyes_check_only_a_near_identical_shot_is_reused(tmp_path, monkeypatch):
    monkeypatch.setattr(storyboard, "eyes", _eyes(score=-1, ok=True))          # no key / checker down
    bank = _bank(tmp_path)
    loose = "Raja Raghu looks at the empty treasury in the palace"
    assert storyboard.REUSE_MIN <= storyboard.shot_overlap(loose, COURT_OLD) < storyboard.REUSE_BLIND
    assert storyboard.reuse({"see": loose, "narration": "x"}, bank, log=lambda *a: None, i=2) is None
    assert storyboard.shot_overlap(COURT_NEW, COURT_OLD) >= storyboard.REUSE_BLIND      # 8 of 14 words shared
    got = storyboard.reuse({"see": COURT_NEW, "narration": "x"}, bank, log=lambda *a: None, i=2)
    assert got and got["match"] == 0.85


def test_missing_files_and_other_sources_are_never_offered(tmp_path, monkeypatch):
    monkeypatch.setattr(storyboard, "eyes", _eyes())
    bank = [{"see": COURT_OLD, "path": str(tmp_path / "gone.jpg"), "source": "ai_scene_cloudflare", "kind": "image"},
            {"see": COURT_OLD, "path": _pic(tmp_path, "stock"), "source": "pexels", "kind": "image"}]
    assert storyboard.reuse({"see": COURT_NEW, "narration": "x"}, bank, log=lambda *a: None, i=1) is None


def test_the_opening_shot_is_always_drawn_new(tmp_path, monkeypatch):
    from engine import story
    asked, drawn = [], []
    monkeypatch.setattr(storyboard, "reuse", lambda beat, bank, era="", log=print, i=0: asked.append(i) or
                        {"kind": "image", "path": tmp_path / "court.jpg", "source": "ai_scene_reuse"})
    monkeypatch.setattr(storyboard, "scene", lambda beat, era, size, log=print, i=0, tries=3, seed=None:
                        drawn.append(i) or {"kind": "image", "path": tmp_path / "new.jpg", "source": "ai_scene_x"})
    beat = {"visual": "scene", "_prompt": "p", "see": COURT_NEW, "narration": "x"}
    args = (2.5, ["#000000"], tmp_path, 0, "hi", "awe", set(), (1080, 1920))
    first = story.find_beat_visual(beat, *args[:3], 0, *args[4:], log=lambda *a: None, bank=_bank(tmp_path))
    assert first["path"].name == "new.jpg" and asked == [] and drawn == [0]
    later = story.find_beat_visual(beat, *args[:3], 5, *args[4:], log=lambda *a: None, bank=_bank(tmp_path))
    assert later["source"] == "ai_scene_reuse" and asked == [5] and drawn == [0]
    plain = story.find_beat_visual(beat, *args[:3], 5, *args[4:], log=lambda *a: None)          # no bank: drawn
    assert plain["path"].name == "new.jpg" and drawn == [0, 5]


def test_make_item_remembers_each_version_and_offers_it_to_the_remake(tmp_path, monkeypatch):
    from engine import config, story
    monkeypatch.setattr(config, "channel", lambda cid: {"id": cid, "name": "Itihaas Ke Raaz", "type": "story"})
    monkeypatch.setattr(weekly, "clip_slot", lambda ch, it: False)
    monkeypatch.setattr(weekly, "story_paused", lambda ch: None)
    monkeypatch.setattr(weekly, "franchise_names", lambda it: [])
    monkeypatch.setattr(weekly, "_refresh_topic", lambda *a, **k: None)
    monkeypatch.setattr("engine.training_data.record", lambda item: None)
    offered, n = [], [0]

    def make(brain, ch, topic=None, fmt="short", script=None, memory=None, log=print, on_script=None, bank=None):
        offered.append([b["see"] for b in bank or []])
        n[0] += 1
        out = tmp_path / f"out{n[0]}"
        out.mkdir()
        shots = [{"see": COURT_OLD if n[0] == 1 else "Raja Raghu on his chariot", "kind": "image",
                  "path": _pic(tmp_path, f"v{n[0]}"), "source": "ai_scene_cloudflare"},
                 {"see": "title card", "kind": "image", "path": _pic(tmp_path, f"g{n[0]}"), "source": "graphic"},
                 {"see": "count", "kind": "text", "path": None, "source": "text"}]
        if n[0] == 2:                                                 # the remake reused the court picture
            shots.append({"see": COURT_NEW, "kind": "image", "path": str(tmp_path / "v1.jpg"),
                          "source": "ai_scene_reuse"})
        (out / "shots.json").write_text(json.dumps(shots), encoding="utf-8")
        (out / "video.mp4").write_bytes(b"x")
        return out, {}
    monkeypatch.setattr(story, "make", make)
    item = {"id": "1122_1230_itihaas_ke_raaz_short", "channel": "itihaas_ke_raaz", "kind": "short",
            "status": "planned", "topic": "Raja Raghu", "refreshed": True}
    weekly.make_item({"items": [item]}, item, brain=object(), log=lambda *a: None)
    assert offered == [[]]                                            # the first version: nothing to reuse yet
    redo = dict(item, status="redo", gate_note="potential: hook 5")
    weekly.make_item({"items": [redo]}, redo, brain=object(), log=lambda *a: None)
    assert offered[1] == [COURT_OLD]                                  # only AI scene pictures are offered
    bank = weekly.shot_bank(item)
    assert sorted(b["see"] for b in bank) == sorted([COURT_NEW, "Raja Raghu on his chariot"])   # newest wording wins
    (tmp_path / "v1.jpg").unlink()                                    # the PC's cache was cleaned
    assert [b["see"] for b in weekly.shot_bank(item)] == ["Raja Raghu on his chariot"]


def test_old_bank_files_are_removed(tmp_path, monkeypatch):
    import os
    import time
    weekly.ITEM_SHOTS.mkdir(parents=True)
    old = weekly.ITEM_SHOTS / "1101_0500_old_short.json"
    old.write_text("[]", encoding="utf-8")
    past = time.time() - (weekly.BANK_KEEP_D + 1) * 86400
    os.utime(old, (past, past))
    out = tmp_path / "out"
    out.mkdir()
    (out / "shots.json").write_text(json.dumps([{"see": SKY, "kind": "image", "path": _pic(tmp_path, "sky"),
                                                 "source": "ai_scene_local_sd"}]), encoding="utf-8")
    assert weekly.remember_shots({"id": "1123_0500_x_short"}, out, log=lambda *a: None) == 1
    assert not old.exists() and (weekly.ITEM_SHOTS / "1123_0500_x_short.json").exists()
    assert weekly.remember_shots({"id": "y"}, tmp_path / "nothing", log=lambda *a: None) == 0
