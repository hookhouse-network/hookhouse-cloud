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
