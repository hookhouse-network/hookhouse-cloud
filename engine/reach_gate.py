"""Reach gate (owner, 17 Nov 2026: "make sure everything that hurts our reach is caught; improve the virality and SEO
gates so the platforms' algorithms work for us"). Runs on EVERY video right before it is sent for approval:

1. Fixes what it can by itself (metadata only, the picture is never touched):
   - engagement bait removed from title/description/caption ("comment YES", "tag a friend", "like if", "share this
     with"): Meta demotes these five kinds since Dec 2017 (vote/react/share/tag/comment baiting)
   - hashtags capped: Instagram max 5 per Reel (18 Dec 2025), YouTube shows the first 3 and ignores ALL hashtags when
     a video has more than 15 -> we keep 3-5 relevant ones
   - title trimmed to YouTube's 100 characters; fake urgency ("BREAKING:") removed from recordings
   - audio peaks that distort after upload are re-mastered (quality.fix_peaks)
2. Holds the video (it does not reach the owner) for defects the algorithm punishes: no sound, not vertical/too low
   resolution for a Short, black borders (letterbox), longer than the platform's Short limit, distorted audio that
   could not be fixed, a duplicate of something already posted.
3. Scores the rest 0-100 with the weekly quality scorecard's measurements (hook frame, loop, dead air, loudness,
   pace, SEO phrase spoken + in the description, captions file, colour). The score and the top tips go on the
   approval message, so the owner sees the reach health of every video.
"""
from __future__ import annotations

import json
import re
import subprocess
import time
from pathlib import Path

BAIT = re.compile(
    r"(\b(comment|type|drop|reply)\s+(a\s+)?[\"'“”‘’]?(yes|no|amen|1|a\s+heart|🔥|❤️)[\"'“”‘’]?(\s+(if|below|for|to)\b[^.!?\n]*)?)"
    r"|(\btag\s+(a|your|3|three|two|some)\s+(friend|friends|buddy|bestie|someone)[^.!?\n]*)"
    r"|(\b(like|share|follow)\s+if\s+you\b[^.!?\n]*)"
    r"|(\bshare\s+(this\s+)?with\s+(a\s+friend|everyone|10|ten)[^.!?\n]*)"
    r"|(\bsmash\s+(that\s+)?like[^.!?\n]*)"
    r"|(\b(vote|react)\s+with\s+[^.!?\n]*)",
    re.I)
FAKE_URGENCY = re.compile(r"^\W*(breaking(?: news)?|just in|urgent)\s*[:!|\-–—]+\s*", re.I)
HASHTAG = re.compile(r"(?<![\w#])#[\wऀ-ॿ]+")
YT_TITLE_MAX = 100
YT_TAG_LIMIT = 15                  # more than 15 hashtags: YouTube ignores every hashtag on the video
KEEP_TAGS = 5
SHORT_MAX_S = 180                  # YouTube Shorts and Instagram Reels (recommendable up to 3 minutes)


def strip_bait(text: str) -> tuple[str, list[str]]:
    found = [m.group(0).strip() for m in BAIT.finditer(text or "")]
    if not found:
        return text, []
    out = BAIT.sub("", text)
    out = re.sub(r"[ \t]{2,}", " ", out)
    out = re.sub(r"\s+([.!?,])", r"\1", out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip(), found


def cap_hashtags(text: str, keep: int = KEEP_TAGS) -> str:
    """Keep the first `keep` distinct hashtags, drop the rest (and repeats)."""
    seen: list[str] = []

    def repl(m):
        t = m.group(0)
        if t.lower() in (x.lower() for x in seen) or len(seen) >= keep:
            return ""
        seen.append(t)
        return t
    out = HASHTAG.sub(repl, text or "")
    return re.sub(r"[ \t]{2,}", " ", out).strip()


def fix_meta(meta: dict) -> tuple[dict, list[str]]:
    """Metadata fixes. Returns (new meta, what was fixed)."""
    fixed: list[str] = []
    m = dict(meta)
    for key in ("title", "description", "caption", "instagram_caption"):
        if not m.get(key):
            continue
        new, bait = strip_bait(str(m[key]))
        if bait:
            fixed.append(f"removed engagement bait from the {key}: \"{bait[0][:40]}\"")
            m[key] = new
    t = str(m.get("title") or "")
    if FAKE_URGENCY.search(t):
        m["title"] = FAKE_URGENCY.sub("", t).strip()
        fixed.append("removed fake urgency from the title")
    if len(str(m.get("title") or "")) > YT_TITLE_MAX:
        m["title"] = str(m["title"])[:YT_TITLE_MAX - 1].rsplit(" ", 1)[0]
        fixed.append("title shortened to YouTube's 100 characters")
    for key in ("description", "caption", "instagram_caption"):
        if m.get(key) and len(HASHTAG.findall(str(m[key]))) > KEEP_TAGS:
            m[key] = cap_hashtags(str(m[key]), KEEP_TAGS)
            fixed.append(f"{key}: hashtags cut to {KEEP_TAGS}")
    if isinstance(m.get("hashtags"), list) and len(m["hashtags"]) > KEEP_TAGS:
        m["hashtags"] = list(dict.fromkeys(m["hashtags"]))[:KEEP_TAGS]
        fixed.append(f"hashtag list cut to {KEEP_TAGS}")
    return m, fixed


def probe(video: Path) -> dict:
    from .media import ffmpeg
    r = subprocess.run([ffmpeg.ffprobe_bin(), "-v", "error", "-show_entries",
                        "stream=codec_type,width,height", "-of", "json", str(video)],
                       capture_output=True, text=True, timeout=60)
    try:
        streams = json.loads(r.stdout or "{}").get("streams") or []
    except ValueError:
        streams = []
    v = next((s for s in streams if s.get("codec_type") == "video"), {})
    return {"w": int(v.get("width") or 0), "h": int(v.get("height") or 0),
            "audio": any(s.get("codec_type") == "audio" for s in streams), "dur": ffmpeg.duration(video)}


def letterboxed(video: Path, dur: float) -> bool:
    """Black bars on top AND bottom through the video (a landscape picture pasted into 9:16)."""
    from .quality import _frames
    import numpy as np
    frames = _frames(video, dur, n=4)
    if not frames:
        return False
    hits = 0
    for f in frames:
        h = f.shape[0]
        band = max(4, h // 12)
        top, bot = f[:band], f[-band:]
        if float(np.percentile(top, 98)) < 25 and float(np.percentile(bot, 98)) < 25 and float(f[h // 3: 2 * h // 3].std()) > 12:
            hits += 1
    return hits >= 3


def check(ch: dict, video: Path, meta: dict, fmt: str, posted_on=None) -> dict:
    """Full gate for one finished video. Returns {"block": [...], "fixed": [...], "tips": [...], "score": int,
    "meta": fixed meta}."""
    block: list[str] = []
    meta2, fixed = fix_meta(meta)
    info = probe(video)
    short = fmt != "long"
    if not info["audio"]:
        block.append("no sound track (silent videos are not recommended)")
    if short:
        if info["h"] <= info["w"]:
            block.append(f"not vertical ({info['w']}x{info['h']}): Shorts/Reels need 9:16")
        elif info["w"] < 720:
            block.append(f"low resolution ({info['w']}x{info['h']}): blurry videos are not recommended")
        if info["dur"] > SHORT_MAX_S:
            block.append(f"{info['dur']:.0f} s is longer than a Short/Reel may be (3 min)")
        if info["w"] and info["h"] > info["w"] and letterboxed(video, info["dur"]):
            block.append("black bars above and below the picture (letterbox): fill the 9:16 frame")
    if posted_on:
        block.append(f"already posted on {', '.join(posted_on)}")
    q = {"score": 100, "issues": []}
    try:
        from . import quality
        q = quality.check_video(ch, video, meta2, fmt)
        if q.get("peak") is not None and q["peak"] > quality.TARGETS["true_peak"]:
            if quality.fix_peaks(video, log=lambda *_: None):
                fixed.append("audio peaks re-mastered (no distortion after upload)")
                q = quality.check_video(ch, video, meta2, fmt)
            else:
                block.append(f"audio peaks {q['peak']:+.1f} dB distort after upload and could not be fixed")
    except Exception as e:  # noqa: BLE001 - a scorecard that cannot run never blocks, it shows as a tip
        q = {"score": 70, "issues": [("warn", f"reach scorecard could not run ({str(e)[:60]})")]}
    tips = [t for lv, t in q.get("issues", []) if lv != "bad" and not t.startswith("peaks")]
    block += [t for lv, t in q.get("issues", []) if lv == "bad" and not t.startswith("peaks")]   # serious defects
    return {"block": block, "fixed": fixed, "tips": tips, "score": int(q.get("score", 100)), "meta": meta2,
            "at": time.time()}


def summary(res: dict) -> str:
    if res.get("block"):
        return "🛑 Reach check: " + "; ".join(res["block"])
    s = f"📈 Reach check {res.get('score', 100)}/100"
    if res.get("fixed"):
        s += " · fixed: " + "; ".join(res["fixed"][:2])
    if res.get("tips"):
        s += " · tips: " + "; ".join(res["tips"][:2])
    return s


def _stamp(video: Path, meta: dict) -> str:
    import hashlib
    body = json.dumps({k: v for k, v in meta.items() if k != "reach"}, sort_keys=True, default=str)
    return f"{video.stat().st_size}:{int(video.stat().st_mtime)}:{hashlib.sha1(body.encode()).hexdigest()[:12]}"


def gate_item(it: dict) -> dict | None:
    """Run the gate for a queued plan item, write metadata fixes back (upload.json or clips.json), cache the result
    per video file (re-run only when the file or metadata changes)."""
    from .config import channel as get_channel
    out = Path(it.get("out_dir") or "")
    video = out / (it.get("file") or "video.mp4")
    if not video.exists():
        return None
    up, cj = out / "upload.json", out / "clips.json"
    rows, entry = None, None
    if up.exists():
        meta = json.loads(up.read_text(encoding="utf-8"))
    elif cj.exists():
        rows = json.loads(cj.read_text(encoding="utf-8"))
        entry = next((c for c in rows if c.get("file") == it.get("file")), None)
        if entry is None:
            return None
        meta = entry
    else:
        return None
    old = meta.get("reach") or {}
    if old.get("stamp") == _stamp(video, meta):
        return old
    fmt = "long" if it.get("kind") == "long" or meta.get("format") == "long" else "short"
    res = check(get_channel(it["channel"]), video, meta, fmt)
    new = res.pop("meta")
    stored = dict(res)
    new["reach"] = stored
    stored["stamp"] = _stamp(video, new)
    if up.exists():
        up.write_text(json.dumps(new, indent=2, ensure_ascii=False), encoding="utf-8")
    else:
        entry.clear()
        entry.update(new)
        cj.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    return stored
