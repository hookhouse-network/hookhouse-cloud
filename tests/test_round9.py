"""Round 9 (12 Nov): all-channel quality scorecard, to-do by platform with auto ticks, doctor, Bloop songs,
duotone for black-and-white pictures, Telegram channel posting, new platform rules."""
import json
import subprocess

import numpy as np
import pytest


def test_quality_scorecard_on_a_real_video(tmp_path):
    from engine import quality
    from engine.media import ffmpeg
    v = tmp_path / "video.mp4"
    subprocess.run([ffmpeg.ffmpeg_bin(), "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=0x223399:s=360x640:d=20",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=20", "-shortest", "-c:v", "libx264", "-c:a", "aac",
                    str(v)], check=True, timeout=120)
    r = quality.check_video({"id": "x", "type": "brainrot"}, v, {}, "short")
    assert 0 <= r["score"] <= 100 and r["seconds"] == pytest.approx(20, abs=1)
    assert r["lufs"] is not None and r["peak"] is not None
    assert any("loudness" in t for _, t in r["issues"])                 # a plain sine is far from -14 LUFS


def test_todo_auto_ticks_and_manual_tick(tmp_path, monkeypatch):
    from engine import todo
    f = tmp_path / "todo.yaml"
    f.write_text('- {id: tg, platform: "Telegram", task: "Token", why: "x", auto: "env:TELEGRAM_BOT_TOKEN", done: false}\n'
                 '- {id: kdp, platform: "Books & music", task: "Publish book", why: "y", done: false}\n')
    monkeypatch.setattr(todo, "FILE", f)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    assert todo.progress() == (0, 2)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    assert todo.progress() == (1, 2)                                     # the system ticked it itself
    todo.tick("kdp", True)
    assert todo.progress() == (2, 2) and "done: true}" in f.read_text()
    txt, kb = todo.telegram_text()
    assert "Telegram" in txt and "Books & music" in txt and kb["inline_keyboard"] == []


def test_doctor_text_lists_fixes():
    from engine import doctor
    txt = doctor.text([{"area": "Telegram", "status": "bad", "seen": "no bot token", "fix": "add it"},
                       {"area": "Disk D:", "status": "good", "seen": "40 GB free", "fix": ""}])
    assert "1 to fix" in txt and "→ add it" in txt


def test_songs_have_one_syllable_per_note():
    from engine import songs
    for s in songs.SONGS:
        for verse in s["verses"]:
            assert all(len(x) == 3 and x[2] > 0 for x in verse)
            assert sum(b for _, _, b in verse) > 0


def test_duotone_only_for_black_and_white(tmp_path):
    from engine import story
    from engine.config import channel
    from engine.media import compose
    look, _ = story.channel_look(channel("deep_blue_files"), (1080, 1920))
    g = compose.Grader(look)
    gray = np.dstack([np.tile(np.linspace(30, 200, 200, dtype=np.uint8), (120, 1))] * 3)
    colour = np.zeros((120, 200, 3), np.uint8)
    colour[..., 2] = 220                                                 # a strongly red picture
    import cv2
    sat = lambda im: float(cv2.cvtColor(im, cv2.COLOR_BGR2HSV)[..., 1].mean())
    assert sat(g(gray)) > 25                                             # grey photo gets the brand tint
    assert abs(sat(g(colour)) - sat(compose.Grader(compose.Look(saturation=look.saturation))(colour))) < 40


def test_telegram_channel_needs_a_channel_name(tmp_path, monkeypatch):
    from engine import links, publish
    monkeypatch.setattr(publish, "LOG", tmp_path / "log.jsonl")
    links.data.cache_clear()
    monkeypatch.setattr(links, "data", lambda: {"unsolved_after_dark": {"live": True}})
    v = tmp_path / "v.mp4"
    v.write_bytes(b"x")
    a = publish.telegram_channel_post("unsolved_after_dark", v, {"title": "T"}, "YT1", dry_run=False)
    assert not a.done and a.details.get("dry_run")                       # no @channel set yet: skipped quietly


def test_new_platform_rules_cover_every_channel():
    from engine import platforms
    from engine.config import channels
    platforms.registry.cache_clear()
    for ch in channels():
        n = sum(1 for p in platforms.registry() if platforms.allowed(ch, p))
        assert n >= (4 if ch.get("type") == "kids" else 7), (ch["id"], n)
