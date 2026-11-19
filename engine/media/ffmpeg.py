"""Small helpers around ffmpeg (video editing engine, run as a separate program)."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path


def _find(name: str) -> str:
    found = shutil.which(name)
    if found:
        return found
    # winget installs ffmpeg here on Windows; PATH may not be refreshed yet
    base = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
    for exe in base.glob(f"Gyan.FFmpeg*/**/bin/{name}.exe"):
        return str(exe)
    raise FileNotFoundError(f"{name} not found. Install ffmpeg first.")


def ffmpeg_bin() -> str:
    return _find("ffmpeg")


def ffprobe_bin() -> str:
    return _find("ffprobe")


def run(args: list[str], cwd: Path | None = None, retries: int = 1, timeout: float | None = None) -> None:
    """Run ffmpeg; retry once, since Windows sometimes briefly locks a file that was just written."""
    cmd = [ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-y", *map(str, args)]
    for _attempt in range(retries + 1):
        try:
            proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                  timeout=timeout)
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"ffmpeg took longer than {timeout}s: {' '.join(cmd)[:300]}")
        if proc.returncode == 0:
            return
    raise RuntimeError(f"ffmpeg failed:\n{' '.join(cmd)}\n{proc.stderr[-2000:]}")


def probe(path: Path) -> dict:
    out = subprocess.run([ffprobe_bin(), "-v", "error", "-print_format", "json", "-show_format",
                          "-show_streams", str(path)], capture_output=True, text=True, encoding="utf-8")
    if out.returncode != 0:
        raise RuntimeError(f"ffprobe failed on {path}: {out.stderr}")
    return json.loads(out.stdout)


def duration(path: Path) -> float:
    return float(probe(path)["format"]["duration"])


# Shared export settings: good quality, small files (Telegram previews stay under 50 MB).
# maxrate 8M = YouTube's recommended 1080p upload rate; stops film grain from bloating files.
H264 = ["-c:v", "libx264", "-preset", "medium", "-crf", "20", "-maxrate", "8M", "-bufsize", "16M",
        "-pix_fmt", "yuv420p", "-color_range", "tv", "-r", "30"]
AAC = ["-c:a", "aac", "-b:a", "192k", "-ar", "48000"]
# For in-between files that get re-encoded later: fast, near-lossless.
H264_FAST = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-pix_fmt", "yuv420p", "-r", "30"]
