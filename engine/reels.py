"""Instagram Reel versions of finished Shorts (never byte-identical to the YouTube upload).

Instagram stops recommending accounts that post unoriginal or duplicate content, and campaign boards
reject reused edits. So every Reel differs from its Short: other hook wording where the format has one,
a slightly shorter ending, its own 3:4-grid-safe cover and an Instagram caption with at most 5 hashtags.
(Story Shorts make their Reel inside story.render from the same frames.)
"""
from __future__ import annotations
from engine.core.quiet import noted

import json
import re
from pathlib import Path

from PIL import Image

from .media import ffmpeg


def _caption(text: str, tags: list[str]) -> tuple[str, list[str]]:
    tags = list(dict.fromkeys(t if t.startswith("#") else f"#{t}" for t in tags if t))[:5]
    return f"{text.strip()}\n\n{' '.join(tags)}".strip(), tags


def trimmed_variant(video: Path, out: Path, trim_end: float = 0.5) -> Path:
    """Re-encode with a slightly shorter ending (different bytes, same look)."""
    dur = ffmpeg.duration(video)
    ffmpeg.run(["-i", str(video), "-t", f"{max(1.0, dur - trim_end):.3f}", *ffmpeg.H264, *ffmpeg.AAC,
                "-movflags", "+faststart", str(out)])
    return out


def snack_reel(out_dir: Path, meta: dict, channel: dict) -> dict:
    """Brain Snack: trimmed re-encode (loops keep their full length), second title, own cover."""
    video = out_dir / "video.mp4"
    loop = meta.get("snack_format") == "multiply"
    reel = out_dir / "reel.mp4"
    if loop:
        ffmpeg.run(["-i", str(video), "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p",
                    *ffmpeg.AAC, "-movflags", "+faststart", str(reel)])
    else:
        trimmed_variant(video, reel, 0.35)
    titles = meta.get("title_options") or [meta.get("title", "")]
    hook = titles[1] if len(titles) > 1 else titles[0]
    cap, tags = _caption(hook, channel.get("hashtags", []) + ["#brainsnack", "#satisfying"])
    _cover_from(out_dir / "cover.jpg", hook, channel, out_dir / "reel_cover.jpg")
    info = {"platform": "instagram_reels", "file": "reel.mp4", "cover": "reel_cover.jpg", "hook": hook,
            "caption": cap, "hashtags": tags, "trial_reel_suggested": True}
    (out_dir / "reel.json").write_text(json.dumps(info, indent=2, ensure_ascii=False), encoding="utf-8")
    return info


def clip_reel(out_dir: Path, clip_meta: dict, channel: dict, min_s: float = 0.0) -> dict:
    """Podcast clip: new hook wording drawn over the old box, shorter ending, caption with campaign tags kept.
    min_s: the campaign's minimum length. 20 Nov: a 30.0 s clip's Reel was trimmed to 29.7 s and the clip gate held
    it ("outside the campaign's 30-60s"); the trim never takes the Reel under the minimum (0 = same length)."""
    src = out_dir / clip_meta["file"]
    reel = out_dir / clip_meta["file"].replace(".mp4", "_reel.mp4")
    hooks = [h for h in (clip_meta.get("hook_options") or []) if h]
    dur = float(clip_meta.get("duration_s") or ffmpeg.duration(src))
    trim = min(0.3, max(0.0, dur - float(min_s or 0) - 0.05)) if min_s else 0.3
    trimmed_variant(src, reel, trim)         # hooks are boxless and brief now: a trimmed cut + its own caption
    base = re.sub(r"\s+#\S+", "", clip_meta.get("caption", "")).strip()
    tags = re.findall(r"#\S+", clip_meta.get("caption", ""))
    cap, tags = _caption(base, tags)
    info = {"platform": "instagram_reels", "file": reel.name, "hook": hooks[1] if len(hooks) > 1 else (hooks or [""])[0],
            "caption": cap, "hashtags": tags, "campaign": clip_meta.get("campaign"),
            "note": "Submit to the campaign within 30 minutes of posting if the brief allows Instagram."}
    (out_dir / reel.name.replace(".mp4", ".json")).write_text(json.dumps(info, indent=2, ensure_ascii=False),
                                                               encoding="utf-8")
    return info


def _cover_from(src: Path, label: str, channel: dict, out: Path) -> None:
    if not src.exists():
        return
    try:
        from .media.thumbs_v4 import cover_for
        cover_for(channel, Image.open(src).convert("RGB"), label, out)
    except Exception as _swallowed:  # noqa: BLE001 - never lose a finished Reel over its cover
        noted("reels.py:79", _swallowed)
        pass
