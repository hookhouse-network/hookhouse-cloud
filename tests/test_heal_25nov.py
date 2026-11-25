"""Heal 25 Nov: a Short over 48 MB was blocked for the Telegram channel instead of being sent as a smaller copy."""
import subprocess

from engine import publish
from engine.media import ffmpeg


def test_big_video_gets_a_telegram_sized_copy(tmp_path, monkeypatch):
    src = tmp_path / "video.mp4"
    subprocess.run([ffmpeg.ffmpeg_bin(), "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=1080x1920:r=30:d=4",
                    "-f", "lavfi", "-i", "sine=d=4", "-c:v", "libx264", "-b:v", "8M", "-c:a", "aac", "-shortest",
                    str(src)], check=True)
    monkeypatch.setattr(publish, "TG_BOT_MAX", src.stat().st_size // 2)
    out = publish.telegram_copy(src)
    assert out != src and out.stat().st_size <= publish.TG_BOT_MAX
    w, h = ffmpeg.probe(out)["streams"][0]["width"], ffmpeg.probe(out)["streams"][0]["height"]
    assert (w, h) == (1080, 1920)                              # same picture size, only a lower bitrate
    assert publish.telegram_copy(src) == out                   # made once


def test_gate_never_blocks_a_video_only_for_telegram_size():
    import inspect
    from engine import content_gate
    assert 'platform != "telegram"' in inspect.getsource(content_gate)


def test_letterboxed_source_is_cropped_to_its_picture(tmp_path):
    """25 Nov: a landscape-in-9:16 campaign source kept its black bars; the gate held the clip."""
    from engine import clips
    src = tmp_path / "boxed.mp4"
    subprocess.run([ffmpeg.ffmpeg_bin(), "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=720x404:r=30:d=3",
                    "-f", "lavfi", "-i", "sine=d=3", "-vf", "pad=720:1280:0:438:black", "-c:v", "libx264",
                    "-c:a", "aac", "-shortest", str(src)], check=True)
    out = clips.remove_letterbox(src, log=lambda m: None)
    v = next(s for s in ffmpeg.probe(out)["streams"] if s["codec_type"] == "video")
    assert out != src and int(v["height"]) < 500 and int(v["width"]) >= 700
    plain = tmp_path / "plain.mp4"
    subprocess.run([ffmpeg.ffmpeg_bin(), "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=720x1280:r=30:d=3",
                    "-c:v", "libx264", str(plain)], check=True)
    assert clips.remove_letterbox(plain, log=lambda m: None) == plain


def test_account_hold_skips_instagram_and_threads_only(monkeypatch):
    """25 Nov: Instagram hid @brainsnackdose until the owner confirms it's human; never post there meanwhile."""
    from engine import links
    monkeypatch.setattr(links, "data", lambda: {"brain_snack": {"instagram_hold": "confirm you're human"},
                                                "clutch_tales": {}})
    assert "confirm" in links.hold_note("brain_snack", "instagram")
    assert links.hold_note("brain_snack", "threads") == links.hold_note("brain_snack", "instagram")
    assert links.hold_note("brain_snack", "youtube") == "" and links.hold_note("clutch_tales", "instagram") == ""


def test_atomic_replace_retries_a_briefly_locked_file(tmp_path, monkeypatch):
    """25 Nov: Windows answered 'Access is denied' on renames while a scanner held the new file (4 suite failures)."""
    import os

    from engine.core import atomic
    real, calls = os.replace, []

    def flaky(a, b):
        calls.append(1)
        if len(calls) < 3:
            raise PermissionError(5, "Access is denied")
        real(a, b)
    monkeypatch.setattr(atomic.os, "replace", flaky)
    monkeypatch.setattr(atomic.time, "sleep", lambda s: None)
    atomic.write_json(tmp_path / "q.json", {"a": 1})
    assert (tmp_path / "q.json").read_text(encoding="utf-8").strip().startswith("{") and len(calls) == 3
    calls.clear()
    monkeypatch.setattr(atomic.os, "replace", lambda a, b: (_ for _ in ()).throw(PermissionError(5, "denied")))
    import pytest
    with pytest.raises(PermissionError):
        atomic.write_json(tmp_path / "r.json", {"a": 1})


def test_stats_skip_an_instagram_account_on_hold(monkeypatch, tmp_path):
    """25 Nov: Brain Snack's hidden account raised a HIGH heal item on every stats run ('object does not exist')."""
    from engine import links, stats_fetch
    (tmp_path / "meta_brain_snack.json").write_text('{"access_token": "x"}', encoding="utf-8")
    monkeypatch.setattr(stats_fetch, "SECRETS", tmp_path)
    monkeypatch.setattr(links, "data", lambda: {"brain_snack": {"instagram_hold": "human check"}})

    class NoCall:
        def get(self, *a, **k):
            raise AssertionError("a held account must not be asked")
    assert stats_fetch._instagram({"channel": "brain_snack", "id": "1"}, NoCall()) is None
