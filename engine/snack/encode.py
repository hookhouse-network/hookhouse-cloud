"""Video/audio output for Brain Snack v3: frames are piped straight into ffmpeg (one encode),
then the sound is loudness-matched to -14 LUFS (the level YouTube and Instagram play at) and muxed."""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf

from ..media import ffmpeg
from .audio import SR


def video_args(fps: int) -> list[str]:
    # High quality for fast-moving particles: CRF 18, up to 16 Mbps (YouTube re-encodes anyway;
    # a cleaner upload keeps more detail after its compression).
    return ["-c:v", "libx264", "-preset", "medium", "-crf", "18", "-maxrate", "16M", "-bufsize", "32M",
            "-pix_fmt", "yuv420p", "-color_range", "tv", "-r", str(fps), "-g", str(fps * 2)]


class FrameWriter:
    def __init__(self, path: Path, fps: int, size: tuple[int, int]):
        self.path, self.fps, self.size = Path(path), fps, size
        cmd = [ffmpeg.ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo",
               "-pix_fmt", "bgr24", "-s", f"{size[0]}x{size[1]}", "-r", str(fps), "-i", "-",
               *video_args(fps), str(self.path)]
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
        self.frames = 0

    def write(self, frame: np.ndarray) -> None:
        self.proc.stdin.write(np.ascontiguousarray(frame).tobytes())
        self.frames += 1

    def close(self) -> None:
        self.proc.stdin.close()
        if self.proc.wait() != 0:
            raise RuntimeError(self.proc.stderr.read().decode("utf-8", "replace")[-1500:])

    def __enter__(self):
        return self

    def __exit__(self, exc_type, *_):
        if exc_type is None:
            self.close()
        else:
            try:
                self.proc.stdin.close()
            except OSError:
                pass
            self.proc.kill()


def _loudness(wav: Path) -> dict:
    cmd = [ffmpeg.ffmpeg_bin(), "-hide_banner", "-nostats", "-i", str(wav), "-af",
           "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"]
    out = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace").stderr
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", out, re.S)
    return json.loads(m.group(0)) if m else {}


def mux(video: Path, mix: np.ndarray, out: Path, work: Path, subtitles: Path | None = None,
        fonts_dir: Path | None = None) -> Path:
    """Two-pass loudness normalisation (linear, no pumping), then mux with the silent video."""
    raw = work / "mix_raw.wav"
    sf.write(raw, mix, SR)
    m = _loudness(raw)
    if m and m.get("input_i") not in (None, "-inf"):
        af = ("loudnorm=I=-14:TP=-1.5:LRA=11:linear=true:"
              f"measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}:"
              f"measured_thresh={m['input_thresh']}:offset={m['target_offset']}" + ",alimiter=limit=0.83:attack=5:release=50:level=false")
    else:
        af = "anull"
    args = ["-i", str(video), "-i", str(raw), "-map", "0:v", "-map", "1:a", "-af", af]
    if subtitles:
        rel_sub = subtitles.name
        fonts = Path(fonts_dir).resolve().as_posix().replace(":", r"\:") if fonts_dir else None
        vf = f"subtitles={rel_sub}" + (f":fontsdir='{fonts}'" if fonts else "")
        args += ["-vf", vf, *video_args(int(round(_fps(video))))]
    else:
        args += ["-c:v", "copy"]
    args += ["-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-shortest", "-movflags", "+faststart", str(out.resolve())]
    ffmpeg.run(args, cwd=work)
    return out


def _fps(video: Path) -> float:
    for s in ffmpeg.probe(video)["streams"]:
        if s.get("codec_type") == "video":
            num, den = s.get("r_frame_rate", "30/1").split("/")
            return float(num) / float(den or 1)
    return 30.0
