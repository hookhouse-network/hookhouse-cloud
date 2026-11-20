"""The content gate: one strict, fail-closed check for EVERY video on EVERY platform (owner, 20 Nov 2026: "make the
system's policies, quality control, verifications and validations strictest as much as possible"; "nothing should
bypass these gates, and these gates ... are according to channel, platform and content").

Where it runs (nothing can go around it):
  - publish.upload_item: before any platform API call, per platform (the queue, the approval-time YouTube schedule
    and every repost path all go through upload_item).
  - autopilot.ask: before a video is offered to the owner or auto-approved.
Rules come from config/gates.yaml (defaults <- content type <- channel override; platform limits per platform), so a
new platform, channel or content type is a config entry.

Layers (any problem blocks; missing data blocks):
  1. Record: readable metadata, a title, never-topics (policy.topic_flags), no franchise names (ip_guard).
  2. Content type: fact-check present and passed (story; brainrot when present), kids marked made-for-kids, AI
     disclosure set where AI voice/pictures are used, clips through the strict clip gate (engine/clip_gate.py).
  3. File, measured: exists, plays, has sound, Shorts vertical 9:16 >= 720x1280, long videos 16:9 >= 1280x720.
  4. Quality: engine/quality.py scorecard; any "bad" finding blocks and the score must reach min_quality (100).
     Computed once per video version (ledger checkpoint), so the gate can run per platform cheaply.
  5. Platform: the channel/campaign may use it (platforms.allowed, campaign briefs fail closed), length window,
     title/caption length, hashtag cap, file size."""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import yaml

from .config import ROOT

FILE = ROOT / "config" / "gates.yaml"
HASHTAG = re.compile(r"(?<![\w#])#\w+")
QUALITY = "quality"            # problem prefix: fixable by a remake (auto-redo)


@lru_cache(maxsize=1)
def config() -> dict:
    return yaml.safe_load(FILE.read_text(encoding="utf-8")) or {}


def rules_for(ch: dict, it: dict | None = None) -> dict:
    """defaults < content type < channel overrides. A campaign clip cut in a story channel's slot (clips_first,
    made_as "clip") follows the CLIPS rules: there is no script to fact-check, and the strict clip + campaign gates
    judge the footage instead (20 Nov: a gate-approved Stream Clips clip was held for 'fact-check missing')."""
    c = config()
    kind = "clips" if (it or {}).get("made_as") == "clip" else (ch.get("type") or "")
    r = dict(c.get("defaults") or {})
    r.update((c.get("content") or {}).get(kind, {}) or {})
    r.update((c.get("channels") or {}).get(ch.get("id") or "", {}) or {})
    return r


def platform_rules(platform: str) -> dict:
    return dict((config().get("platforms") or {}).get(platform) or {})


def version(it: dict) -> str:
    return str(int(float(it.get("made_at") or 0)))


def _channel(it: dict) -> dict:
    from .config import channel
    return channel(it["channel"])


def _video(it: dict) -> Path:
    return Path(it.get("out_dir") or "") / (it.get("file") or "video.mp4")


def quality_report(it: dict, ch: dict, meta: dict, led=None) -> dict:
    """The scorecard for this video version, computed once (ledger checkpoint) and reused."""
    from .core import ledger
    from .quality import check_video
    led = led or ledger.default()
    fmt = "long" if (it.get("kind") == "long" or meta.get("format") == "long") else "short"
    stage = f"quality:{version(it)}"

    def produce():
        r = check_video(ch, _video(it), meta, fmt)
        return {"score": r["score"], "issues": [list(x) for x in r["issues"]]}
    return led.run_stage(it["id"], stage, produce, validate=lambda a: isinstance(a, dict) and "score" in a)


def _default_brain():
    from .autopilot import default_brain
    return default_brain()[0]


def base_problems(it: dict, ch: dict | None = None, meta: dict | None = None, quality: bool = True,
                  probe=None, brain_fn=_default_brain) -> list[str]:
    """Everything that doesn't depend on the platform."""
    p: list[str] = []
    try:
        ch = ch or _channel(it)
    except Exception as e:  # noqa: BLE001
        return [f"channel {it.get('channel')} unknown ({type(e).__name__})"]
    if meta is None:
        try:
            from .publish import item_meta
            meta = item_meta(it) or {}
        except Exception as e:  # noqa: BLE001
            return [f"video metadata unreadable ({type(e).__name__})"]
    r = rules_for(ch, it)
    # 1. record
    title = str(meta.get("title") or "").strip()
    if not title:
        p.append("no title")
    text = " ".join(str(meta.get(k) or "") for k in ("title", "description", "instagram_caption", "caption"))
    if meta.get("policy_flags"):
        p.append("touches a never-topic: " + ", ".join(meta["policy_flags"]))
    try:
        from .policy import topic_flags
        flags = topic_flags(text, mode="topic")
        if flags:
            p.append("text touches a never-topic: " + ", ".join(flags))
    except Exception as e:  # noqa: BLE001
        p.append(f"never-topic check could not run ({type(e).__name__})")
    try:
        from .ip_guard import hits
        names = hits(text)
        if names:
            p.append("names a protected franchise/character: " + ", ".join(names))
    except Exception as e:  # noqa: BLE001
        p.append(f"franchise check could not run ({type(e).__name__})")
    # 2. content type
    fc = meta.get("fact_check")
    need = r.get("fact_check", "required")
    if need == "required" and not (isinstance(fc, dict) and fc.get("checked")):
        p.append("fact-check missing")
    if need in ("required", "if_present") and isinstance(fc, dict) and fc.get("checked") and not fc.get("ok"):
        p.append("fact-check failed: " + "; ".join(str(x) for x in (fc.get("problems") or [])[:2]))
    if r.get("made_for_kids") == "required" and not meta.get("made_for_kids"):
        p.append("kids video not marked made-for-kids")
    if r.get("ai_disclosure") == "required" and not (meta.get("ai_label") or meta.get("yt_synthetic")) \
            and not meta.get("clip") and ch.get("type") != "kids":
        p.append("AI disclosure (ai_label) not set")
    from . import clip_gate
    if r.get("clip_gate") == "required" or clip_gate.is_clip(it, meta, ch):
        p += clip_gate.verify(it, ch=ch)
    # 3. file, measured
    video = _video(it)
    if not video.exists() or video.stat().st_size < 1024:
        p.append(f"video file missing or empty ({video.name})")
        return list(dict.fromkeys(p))
    try:
        if probe is None:
            from .reach_gate import probe
        info = probe(video)
    except Exception as e:  # noqa: BLE001
        p.append(f"video could not be measured ({type(e).__name__})")
        info = {}
    w, h, dur = int(info.get("w") or 0), int(info.get("h") or 0), float(info.get("dur") or 0)
    long_ = it.get("kind") == "long" or meta.get("format") == "long"
    if info:
        if dur <= 0:
            p.append("video does not play")
        if not info.get("audio"):
            p.append("no sound track")
        if long_ and not (w and h and w / h >= 1.7 and w >= 1280):
            p.append(f"long video must be 16:9 and at least 1280x720 ({w}x{h})")
        if not long_ and not (w and h and 0.5 <= w / h <= 0.6 and w >= 720 and h >= 1280):
            p.append(f"Short must be vertical 9:16 and at least 720x1280 ({w}x{h})")
    # 4. quality
    if quality and not p:                      # only score a video that is otherwise valid (it costs a few seconds)
        try:
            q = quality_report(it, ch, meta)
            bad = [msg for lv, msg in q["issues"] if lv == "bad"]
            if bad:
                p.append(f"{QUALITY}: " + "; ".join(bad))
            if q["score"] < float(r.get("min_quality", 100)):
                warns = [msg for lv, msg in q["issues"] if lv != "bad"]
                p.append(f"{QUALITY}: score {q['score']}/100 (needs {r.get('min_quality', 100)}): " + "; ".join(warns)[:300])
        except Exception as e:  # noqa: BLE001 - not scored = not passed
            p.append(f"{QUALITY}: scorecard could not run ({type(e).__name__}: {str(e)[:60]})")
    # 5. potential (owner 20 Nov: "100/100 means ... full potential to go viral and it will earn money")
    if quality and not p:
        try:
            from .potential_gate import problems as potential
            p += potential(it, ch, meta, brain_fn=brain_fn)
        except Exception as e:  # noqa: BLE001 - not judged = not passed
            p.append(f"potential: not judged yet (the judge could not run: {type(e).__name__}); it tries again")
    return list(dict.fromkeys(p))


def platform_problems(it: dict, platform: str, ch: dict, meta: dict, dur: float | None = None) -> list[str]:
    p: list[str] = []
    from .platforms import allowed
    try:
        if platform != "youtube" and not allowed(ch, platform, meta):
            p.append(f"not allowed on {platform} (channel, kids or campaign rules)")
        if platform == "youtube":
            from .platforms import campaign_allows
            if not campaign_allows("youtube", meta):
                p.append("not allowed on youtube by the campaign brief")
    except Exception as e:  # noqa: BLE001
        p.append(f"platform rules could not be read ({type(e).__name__})")
    pr = platform_rules(platform)
    if not pr and platform not in (config().get("platforms") or {}):
        p.append(f"no rules for platform {platform} in config/gates.yaml (add them first)")
        return p
    video = _video(it)
    if dur is None:
        try:
            from .media import ffmpeg
            dur = ffmpeg.duration(video)
        except Exception:  # noqa: BLE001
            dur = 0.0
    long_ = it.get("kind") == "long" or meta.get("format") == "long"
    if pr.get("short_max_s") and not long_ and dur and dur > pr["short_max_s"]:
        p.append(f"{platform}: a Short must be at most {pr['short_max_s']} s ({dur:.0f} s)")
    if pr.get("min_s") and dur and dur < pr["min_s"]:
        p.append(f"{platform}: shorter than {pr['min_s']} s")
    if pr.get("max_s") and dur and dur > pr["max_s"]:
        p.append(f"{platform}: longer than {pr['max_s']} s ({dur:.0f} s)")
    title = str(meta.get("title") or "")
    if pr.get("title_max") and len(title) > pr["title_max"]:
        p.append(f"{platform}: title longer than {pr['title_max']} characters")
    desc = str(meta.get("description") or "")
    if pr.get("description_max") and len(desc) > pr["description_max"]:
        p.append(f"{platform}: description longer than {pr['description_max']} characters")
    cap = str(meta.get("instagram_caption") or meta.get("caption") or desc)
    if pr.get("caption_max") and platform != "threads" and len(cap) > pr["caption_max"]:
        p.append(f"{platform}: caption longer than {pr['caption_max']} characters")
    if pr.get("hashtags_max") and len(HASHTAG.findall(cap)) > pr["hashtags_max"]:
        p.append(f"{platform}: more than {pr['hashtags_max']} hashtags")
    if pr.get("max_mb") and video.exists() and video.stat().st_size > pr["max_mb"] * 1024 * 1024:
        p.append(f"{platform}: file bigger than {pr['max_mb']} MB")
    if platform in ("instagram", "facebook", "threads") and (meta.get("made_for_kids") or ch.get("type") == "kids"):
        p.append(f"made-for-kids videos never go to {platform} (13+ platform)")
    return p


def verify(it: dict, platform: str | None = None, quality: bool = True, _base: list[str] | None = None) -> list[str]:
    """[] = may go (to `platform`; None = the platform-independent part, used before asking the owner)."""
    try:
        ch = _channel(it)
        from .publish import item_meta
        meta = item_meta(it) or {}
    except Exception as e:  # noqa: BLE001
        return [f"video record unreadable ({type(e).__name__}: {str(e)[:60]})"]
    p = list(_base) if _base is not None else base_problems(it, ch, meta, quality=quality)
    if platform:
        p += platform_problems(it, platform, ch, meta)
        if meta.get("campaign") or meta.get("clip"):
            from . import clip_gate
            p += [x for x in clip_gate.verify(it, platform=platform, ch=ch, check_file=False) if x not in p]
    return list(dict.fromkeys(p))


def fixable_by_remake(problems: list[str]) -> bool:
    """Only quality/potential findings that a remake with the notes can fix (not "not judged yet" or a check that
    could not run: those clear by themselves on the next tick)."""
    return bool(problems) and all(x.startswith((QUALITY, "potential")) and "not judged yet" not in x
                                  and "could not run" not in x for x in problems)


def summary(problems: list[str]) -> str:
    return "✅ passed every gate" if not problems else "🛑 blocked: " + "; ".join(problems)[:700]
