"""Reach gate (owner, 17 Nov 2026): what the algorithms punish is fixed or held before the owner is asked."""
import subprocess

import pytest

from engine import reach_gate as rg
from engine.media import ffmpeg


def make(path, w=1080, h=1920, audio=True, secs=3, bars=False):
    vf = "drawbox=x=0:y=0:w=iw:h=ih/6:color=black:t=fill,drawbox=x=0:y=ih*5/6:w=iw:h=ih/6:color=black:t=fill" \
        if bars else "null"
    cmd = [ffmpeg.ffmpeg_bin(), "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc2=size={w}x{h}:rate=30:duration={secs}"]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={secs}"]
    cmd += ["-vf", vf, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-shortest"]
    cmd += (["-c:a", "aac"] if audio else []) + [str(path)]
    subprocess.run(cmd, check=True)
    return path


@pytest.mark.parametrize("text", ["Comment YES if you knew this!", "Tag a friend who needs this",
                                  "Like if you agree", "Share this with a friend", "Smash that like button"])
def test_bait_removed(text):
    out, found = rg.strip_bait("Wild fact. " + text)
    assert found and out.startswith("Wild fact")
    assert "friend" not in out.lower() and "comment yes" not in out.lower()


def test_normal_question_is_not_bait():
    out, found = rg.strip_bait("Would you survive this? Watch till the end.")
    assert not found and out.startswith("Would you survive")


def test_hashtags_capped_and_deduped():
    out = rg.cap_hashtags("hi #a #b #a #c #d #e #f #g")
    assert out.split()[1:] == ["#a", "#b", "#c", "#d", "#e"]


def test_fix_meta_title_and_tags():
    m, fixed = rg.fix_meta({"title": "BREAKING: " + "x" * 120, "description": "Tag your friend now! #a #b #c #d #e #f",
                            "hashtags": list("abcdefgh")})
    assert not m["title"].lower().startswith("breaking") and len(m["title"]) <= 100
    assert "#f" not in m["description"] and "friend" not in m["description"].lower()
    assert len(m["hashtags"]) == 5 and len(fixed) >= 4


def test_silent_and_landscape_shorts_are_held(tmp_path, monkeypatch):
    monkeypatch.setattr("engine.quality.check_video", lambda *a, **k: {"score": 90, "issues": [], "peak": -3})
    v = make(tmp_path / "a.mp4", audio=False)
    assert any("no sound" in b for b in rg.check({}, v, {}, "short")["block"])
    v2 = make(tmp_path / "b.mp4", w=1280, h=720)
    assert any("not vertical" in b for b in rg.check({}, v2, {}, "short")["block"])


def test_letterbox_is_held(tmp_path, monkeypatch):
    monkeypatch.setattr("engine.quality.check_video", lambda *a, **k: {"score": 90, "issues": [], "peak": -3})
    v = make(tmp_path / "c.mp4", w=720, h=1280, bars=True)
    assert any("letterbox" in b for b in rg.check({}, v, {}, "short")["block"])
    good = make(tmp_path / "d.mp4", w=720, h=1280)
    res = rg.check({}, good, {"title": "ok"}, "short")
    assert res["block"] == [] and res["score"] == 90
    assert rg.summary(res).startswith("📈 Reach check 90/100")


def test_gate_item_writes_fixes_and_caches(tmp_path, monkeypatch):
    import json
    calls = []
    monkeypatch.setattr("engine.quality.check_video", lambda *a, **k: calls.append(1) or {"score": 80, "issues": [("warn", "x")], "peak": -3})
    monkeypatch.setattr("engine.config.channel", lambda cid: {"id": cid, "type": "story"})
    make(tmp_path / "video.mp4", w=720, h=1280)
    (tmp_path / "upload.json").write_text(json.dumps({"title": "t", "description": "Comment YES below! #a"}), encoding="utf-8")
    it = {"id": "i1", "channel": "x", "out_dir": str(tmp_path), "file": "video.mp4", "kind": "short"}
    r1 = rg.gate_item(it)
    saved = json.loads((tmp_path / "upload.json").read_text(encoding="utf-8"))
    assert "comment yes" not in saved["description"].lower() and saved["reach"]["score"] == 80
    r2 = rg.gate_item(it)
    assert r2["stamp"] == r1["stamp"] and len(calls) == 1          # cached: not measured twice
