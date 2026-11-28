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

import json
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
    cfg = yaml.safe_load(FILE.read_text(encoding="utf-8")) or {}
    try:                                         # P10: the owner's /settings choices (whitelisted switches only)
        from .owner_settings import apply
        return apply(cfg, "gates")
    except Exception as e:  # noqa: BLE001 - the file's own gates still apply
        print(f"owner settings not applied to gates: {type(e).__name__}: {e}")
        return cfg


def rules_for(ch: dict, it: dict | None = None, meta: dict | None = None) -> dict:
    """defaults < content type < channel overrides. A campaign clip cut in a story channel's slot (clips_first,
    made_as "clip") follows the CLIPS rules: there is no script to fact-check, and the strict clip + campaign gates
    judge the footage instead (20 Nov: a gate-approved Stream Clips clip was held for 'fact-check missing').
    22 Nov: the cloud's own make path never wrote made_as into the plan, so Dom's three Kick clips (22:30, 05:00,
    06:30) were held for 'fact-check missing' on every tick; the video's own metadata (campaign / clip, written by
    the clip maker) now counts too."""
    c = config()
    clip = (it or {}).get("made_as") == "clip" or bool(meta and (meta.get("clip") or meta.get("campaign")))
    kind = "clips" if clip else (ch.get("type") or "")
    r = dict(c.get("defaults") or {})
    r.update((c.get("content") or {}).get(kind, {}) or {})
    r.update((c.get("channels") or {}).get(ch.get("id") or "", {}) or {})
    t = temporary_bar()
    if t.get("min_quality") is not None:
        r["min_quality"] = min(float(r.get("min_quality", 100)), float(t["min_quality"]))
    return r


def temporary_bar(today: str | None = None) -> dict:
    """Owner 21 Nov: a time-boxed lower bar while the makers are fixed (config/gates.yaml temporary_bar). Only the
    quality score and the potential rubric move; every policy/safety check stays. {} once `until` has passed."""
    t = config().get("temporary_bar") or {}
    if not t.get("until"):
        return {}
    if today is None:
        from datetime import datetime
        from zoneinfo import ZoneInfo
        today = datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()
    return dict(t) if today <= str(t["until"]) else {}


def potential_mode(it: dict, meta: dict | None = None) -> str:
    """How the potential (viral) judge's findings count for this video. 22 Nov: since the strict judge went live no
    video passed it (real posted Shorts score 3-6; a 1,311-view hit scored below a 68-view flop), and the owner's own
    dashboard approvals (Itihaas 19:00, Bloop long) were blocked right after the tap. Two owner options, both off
    until the owner picks one (config/gates.yaml):
      'coach'  temporary_bar.potential: coach -> while the temporary bar runs, the judge only coaches (the script
               judge still rewrites with its fixes); its rubric findings are recorded, never blocking;
      'owner'  potential.owner_approval_overrides: true -> the owner's own approval (not an auto-approval) waives it
               for that video.
    Otherwise 'block' (as before). Either way only the 1-10 rubric bar is waived (rubric_finding): the judge's other
    findings and the quality, fact-check, policy, copyright and clip/campaign checks never change.
    Owner 22 Nov 23:10: "run them and B option as you have suggested" -> coach (config/gates.yaml). Campaign clips
    stay 'block': the owner wants them super-strict (20 Nov) and B was offered with "clip gates stay strict"; their
    rubric includes brief_fit, how well the clip fits the brand's brief."""
    if meta is not None and (meta.get("clip") or meta.get("campaign")) or (it or {}).get("made_as") == "clip":
        return "block"
    if temporary_bar().get("potential") == "coach":
        return "coach"
    pc = config().get("potential") or {}
    if pc.get("owner_approval_overrides") and it.get("status") == "approved" and not it.get("auto_approved"):
        return "owner"
    return "block"


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


def repair_title(it: dict, ch: dict, problems: list[str], past: list[str] | None = None) -> bool:
    """21 Nov: Brain Snack Shorts were held for 'title nearly repeats an earlier one' although the maker had written
    other title options. Swap in the first option that passes the same repeat test (potential_gate: uniq.repeat_ratio
    vs the channel's used titles and past topics). Returns True if upload.json got a new title."""
    if not any("title nearly repeats" in str(x) for x in problems or []):
        return False
    path = Path(it.get("out_dir") or "") / "upload.json"
    if not path.exists():
        return False
    m = json.loads(path.read_text(encoding="utf-8"))
    try:
        from .potential_gate import _cfg
        ratio = float(_cfg()["title_repeat_ratio"])
        if past is None:
            from .uniq import used_titles
            from .weekly import past_topics
            past = sorted(used_titles(ch.get("id") or it.get("channel"))) + past_topics(ch.get("id") or it.get("channel"))
    except Exception as e:  # noqa: BLE001 - the gate still blocks the repeated title
        print(f"content gate: title repair could not read past titles ({type(e).__name__})")
        return False
    current = str(m.get("title") or "")
    from .uniq import _norm, repeat_ratio

    def fresh(t: str) -> bool:                      # same test as potential_gate
        low = _norm(t)
        if repeat_ratio(low, current) >= ratio:
            return False                                # a near-copy of the flagged title repeats the same thing
        return bool(low) and all(not o or _norm(o) == _norm(current)          # this video's own record is skipped
                                 or repeat_ratio(low, o) < ratio for o in past)
    for t in [str(x) for x in m.get("title_options") or []]:
        if t and t != current and fresh(t):
            m["title"], m["title_options"] = t, list(dict.fromkeys([t, current] + list(m.get("title_options") or [])))
            path.write_text(json.dumps(m, indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"content gate: {it.get('id')} title '{current}' -> '{t}' (the old one repeated an earlier title)")
            return True
    return False


def repair_peaks(it: dict, q: dict, fixer=None) -> bool:
    """21 Nov: approved Brain Snack Shorts made before the limiter fix were blocked for 'peaks +0.2 dB'. When audio
    peaks are the ONLY serious finding, re-master just the audio (quality.fix_peaks: same loudness chain as new renders,
    picture copied untouched) and let the gate score the repaired file. Returns True if the file was repaired."""
    bad = [str(msg) for lv, msg in q.get("issues") or [] if lv == "bad"]
    if not bad or not all(m.startswith("peaks") for m in bad):
        return False
    video = _video(it)
    if not video.exists():
        return False
    try:
        if fixer is None:
            from .quality import fix_peaks as fixer
        ok = bool(fixer(video, log=print))
    except Exception as e:  # noqa: BLE001 - the gate still blocks the unrepaired file
        print(f"content gate: peak repair failed ({type(e).__name__}: {e})")
        return False
    if ok:
        print(f"content gate: audio peaks of {it.get('id')} re-mastered (picture untouched)")
    return ok


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
    r = rules_for(ch, it, meta)
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
    labelled = bool(meta.get("ai_label") or meta.get("yt_synthetic"))
    need_ai = r.get("ai_disclosure")
    if need_ai == "if_used":   # 21 Nov: code-drawn Brain Snack games (no AI voice/pictures) were blocked 22x
        if (meta.get("ai_used") or meta.get("ai_voice") or meta.get("ai_pictures")) and not labelled:
            p.append("AI disclosure (ai_label) not set although AI voice/pictures were used")
    elif need_ai == "required" and not labelled and not meta.get("clip") and ch.get("type") != "kids":
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
            if repair_peaks(it, q):                     # audio-only re-master, then score the repaired file
                from .core import ledger
                ledger.default().invalidate(it["id"], [f"quality:{version(it)}"])
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
            pot = potential(it, ch, meta, brain_fn=brain_fn)
            if repair_title(it, ch, pot):               # one of the maker's own other titles, then judge again
                meta = dict(meta, title=json.loads((Path(it["out_dir"]) / "upload.json").read_text(
                    encoding="utf-8"))["title"])
                pot = potential(it, ch, meta, brain_fn=brain_fn)
            mode = potential_mode(it, meta)
            clip = bool(meta.get("clip") or meta.get("campaign")) or it.get("made_as") == "clip"
            soft = [f for f in pot if coached(f, mode, clip)]
            if soft:                                    # owner's choices (22 Nov "B", 24 Nov): recorded, not blocking
                _potential_waived(it, soft, mode)
            p += [f for f in pot if f not in soft]      # hook start, title repeat, ad-friendly, AI phrases, not judged
        except Exception as e:  # noqa: BLE001 - not judged = not passed
            p.append(f"potential: not judged yet (the judge could not run: {type(e).__name__}); it tries again")
    return list(dict.fromkeys(p))


RUBRIC_FINDING = re.compile(r"^potential: below [\d.]+/10 on ")
HUMAN_JUDGE_FINDING = re.compile(r"^potential: looks/sounds obviously AI-made \(human_feel ")


def human_judge_coaches() -> bool:
    """Owner 24 Nov ("do as you recommendations"): the S10 judge's human_feel score coaches instead of blocking until
    its scores match real views (potential.ai_tell.judge: coach). The deterministic AI-phrase count still blocks."""
    ai = (config().get("potential") or {}).get("ai_tell") or {}
    return str(ai.get("judge") or "block") == "coach"


def coached(finding: str, mode: str, clip: bool = False) -> bool:
    """A potential finding that is recorded but does not block: the 1-10 rubric while potential_mode is not 'block'
    (owner 22 Nov, "B"), and the human_feel judge while it coaches (owner 24 Nov) - never for campaign clips."""
    if rubric_finding(finding) and mode != "block":
        return True
    return bool(HUMAN_JUDGE_FINDING.match(str(finding))) and human_judge_coaches() and not clip


def rubric_finding(finding: str) -> bool:
    """Only the judge's 1-10 rubric bar is coached by the owner's choice (it scored real hits 3-6). Its other
    findings keep blocking: the hook-start and title-repeat checks, advertiser-friendly words, the S10 'obviously
    AI-made' checks and 'not judged yet' (owner 21 Nov: S10 applies to every video; policy checks never relax)."""
    return bool(RUBRIC_FINDING.match(str(finding)))


def _potential_waived(it: dict, findings: list[str], mode: str) -> None:
    """The judge's findings stay on record for the learning loop (scores vs real views) when they do not block."""
    print(f"potential ({mode}): not blocking {it.get('id')}: {'; '.join(findings)[:200]}")
    try:
        from .core import ledger
        ledger.event("potential.waived", item=it.get("id") or "", channel=it.get("channel") or "",
                     data={"mode": mode, "findings": findings[:3]})
    except Exception as e:  # noqa: BLE001 - the record never decides a video
        print(f"potential record: {type(e).__name__}: {e}")


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
    if pr.get("max_mb") and platform != "telegram" and video.exists() and video.stat().st_size > pr["max_mb"] * 1024 * 1024:
        # (telegram: the poster sends a smaller copy, publish.telegram_copy, 25 Nov)
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


PROBLEM_START = re.compile(
    r"^(no title|touches a never-topic|text touches|names a protected|never-topic check|franchise check|fact-check|"
    r"kids video|AI disclosure|clip|campaign|video |no sound|long video|Short must|quality|potential|not allowed|"
    r"channel |the content gate|title |reach|preflight)", re.I)


def split_problems(text: str) -> list[str]:
    """A gate result string back into its problems. '; ' also separates the sub-issues INSIDE one quality finding
    ("quality: score 86/100: dead silence ...; no captions file"), so a part that does not start like a problem
    belongs to the one before it. 21 Nov: the split made the quality finding look unfixable -> no remake, stuck."""
    out: list[str] = []
    for part in [p.strip() for p in str(text).split("; ") if p.strip()]:
        if out and not PROBLEM_START.match(part):
            out[-1] += "; " + part
        else:
            out.append(part)
    return out


def fixable_by_remake(problems: list[str]) -> bool:
    """Only quality/potential findings that a remake with the notes can fix (not "not judged yet" or a check that
    could not run: those clear by themselves on the next tick)."""
    return bool(problems) and all(x.startswith(REMAKE_FIXES) and "not judged yet" not in x
                                  and "could not run" not in x for x in problems)


# 21 Nov: fact-check failures and franchise topics sat in gate_held forever (the owner never saw them, nothing was
# remade). A remake fixes both: the writer gets the exact contradicted claim; weekly.make_item replaces a franchise
# topic before making (and fails early if no clean topic comes).
REMAKE_FIXES = (QUALITY, "potential", "fact-check failed", "names a protected franchise")


def summary(problems: list[str]) -> str:
    return "✅ passed every gate" if not problems else "🛑 blocked: " + "; ".join(problems)[:700]
