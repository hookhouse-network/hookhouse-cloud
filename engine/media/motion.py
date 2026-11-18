"""Turns a still image into a moving 9:16 shot (slow zoom / pan, "Ken Burns")."""
from __future__ import annotations

from pathlib import Path

from . import ffmpeg

W, H, FPS = 1080, 1920, 30

MOVES = ["zoom_in", "zoom_out", "pan_left", "pan_right", "pan_up"]


def ken_burns(image: Path, out: Path, seconds: float, move: str = "zoom_in", blur_fill: bool = True,
              size: tuple[int, int] = (W, H)) -> Path:
    """Fill 9:16 (blurred copy behind if the image is wide), then animate smoothly.
    Upscaling before zoompan avoids the jitter zoompan has at low resolution."""
    frames = max(int(seconds * FPS), 1)
    w, h = size
    big_w, big_h = int(w * 1.5) // 2 * 2, int(h * 1.5) // 2 * 2
    z = {
        "zoom_in": ("min(1+0.18*on/{f},1.18)", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"),
        "zoom_out": ("max(1.18-0.18*on/{f},1)", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"),
        "pan_left": ("1.12", "(iw-iw/zoom)*(1-on/{f})", "ih/2-(ih/zoom/2)"),
        "pan_right": ("1.12", "(iw-iw/zoom)*on/{f}", "ih/2-(ih/zoom/2)"),
        "pan_up": ("1.12", "iw/2-(iw/zoom/2)", "(ih-ih/zoom)*(1-on/{f})"),
    }[move]
    zoom, x, y = (part.format(f=frames) for part in z)
    if blur_fill:
        fill = (f"[0:v]scale={big_w}:{big_h}:force_original_aspect_ratio=increase,crop={big_w}:{big_h},"
                f"boxblur=40:4,eq=brightness=-0.15[bg];"
                f"[0:v]scale={big_w}:{big_h}:force_original_aspect_ratio=decrease[fg];"
                f"[bg][fg]overlay=(W-w)/2:(H-h)/2[base];")
    else:
        fill = f"[0:v]scale={big_w}:{big_h}:force_original_aspect_ratio=increase,crop={big_w}:{big_h}[base];"
    graph = (f"{fill}[base]zoompan=z='{zoom}':x='{x}':y='{y}':d={frames}:s={w}x{h}:fps={FPS},"
             f"scale=out_range=tv,format=yuv420p[v]")  # JPEGs are full-range; phones expect TV range
    ffmpeg.run(["-loop", "1", "-i", image, "-filter_complex", graph, "-map", "[v]",
                "-frames:v", frames, *ffmpeg.H264_FAST, "-an", out])
    return out
