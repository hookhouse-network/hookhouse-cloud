"""Potential gate: the "viral + earning" half of 100/100 (owner, 20 Nov 2026: "100/100 means the content that we are
generating must be perfect, with quality and has full potential to go viral and it will earn money").

engine/quality.py measures the craft (loudness, peaks, colour, pace, captions, title length...). This gate measures
whether the video can WIN, from the research (docs/GROWTH_PLAN_2026-11-20.md, section 5):
  - YouTube ranks Shorts on "viewed vs swiped away" and average % viewed -> the hook must land in the first second
    and every line must earn the next;
  - Instagram ranks Reels on watch time, likes and SENDS per reach (sends weigh most for non-followers) -> it must be
    worth sending to a friend;
  - high-arousal emotions (awe, amusement/surprise, anger, anxiety) get shared; low-arousal ones (sadness) don't
    (Berger & Milkman, Journal of Marketing Research 2012);
  - YouTube's July 2025 "inauthentic content" rule: mass-produced/template videos without the creator's own insight
    are not monetised -> originality and a real angle are required to EARN;
  - advertiser-friendly guidelines: profanity, graphic violence, sexual content limit ads -> no earning.

Two layers, both must pass (fail closed):
  1. Deterministic: speech/caption starts within hook_start_max_s; the title doesn't nearly repeat one of the
     channel's past titles; no advertiser-unfriendly words.
  2. AI judge (the "checker" route, temperature 0, one call per video version, cached in the ledger): a per-content-
     type rubric from config/gates.yaml, every criterion scored 0-10, ALL must reach min_each (9 = top 5 % of what
     this niche posts). The judge sees the script/what is said, title, hook, channel audience and the topic's demand
     evidence (engine/topic_proof.py). No answer, a partial answer or an invalid one = not judged = blocked.
Findings start with "potential:" so a failing video is remade with the judge's fixes (autopilot._campaign_held)."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

PREFIX = "potential"
# Advertiser-friendly guidelines (support.google.com/youtube/answer/6162278): strong profanity, graphic violence,
# sexual content. True crime may discuss a crime; graphic descriptions limit ads, so only those words are listed.
AD_UNFRIENDLY = re.compile(
    r"\b(fuck\w*|motherf\w*|shit\w*|bitch\w*|cunt\w*|porn\w*|nude\w*|nsfw|sex\s*tape|gor(e|y)|dismember\w*|"
    r"decapitat\w*|mutilat\w*|disembowel\w*|beheading)\b", re.I)
TS = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->")
DEFAULT_RUBRICS = {
    "story": ["hook", "retention", "emotion", "shareability", "originality", "clarity", "packaging", "demand_fit"],
    "brainrot": ["hook", "retention", "emotion", "shareability", "originality", "clarity", "packaging"],
    "kids": ["hook", "learning_goal", "participation", "repetition", "coherence", "originality", "age_safety"],
    "clips": ["hook", "self_contained", "emotion", "shareability", "caption_hook", "brief_fit"],
}
CRITERIA_HELP = {
    "hook": "the first 1-2 seconds stop the scroll: payoff, surprise or a question first, never setup",
    "retention": "every line earns the next; no filler; the viewer stays to the end (and loops)",
    "emotion": "a high-arousal feeling (awe, surprise/amusement, anger, anxiety), not flat or sad",
    "shareability": "a viewer would SEND it to a friend (social currency, practical value, 'you have to see this')",
    "originality": "a real angle or insight of its own, not a generic template (YouTube inauthentic-content rule)",
    "clarity": "easy to follow on the first watch, sound off or on",
    "packaging": "title and caption make the click/stay irresistible without bait or lies",
    "demand_fit": "people want this topic now (use the demand evidence) or the angle is strong enough to create demand",
    "learning_goal": "one clear thing a preschooler learns, shown and said",
    "participation": "the child is invited to answer/act (pauses, questions) like the best preschool shows",
    "repetition": "joyful repetition and a sing-along pattern a toddler can follow",
    "coherence": "the little story makes sense from start to end (YouTube demonetises incoherent AI kids videos)",
    "age_safety": "nothing scary, unsafe to imitate or confusing for ages 2-5",
    "self_contained": "the moment makes sense without the full video",
    "caption_hook": "the on-screen hook/caption makes a stranger stop and watch",
    # 26 Nov: an earlier version of this text carried a history note ("the judge told GTA clips to drop the gameplay");
    # the judge read it as a directive ("drop the gameplay per the 26 Nov directive") and brief_fit fell to 2.5-4.
    # Prompt text states the rule only, never history.
    "brief_fit": "fits the campaign brief's spirit and audience; for a streamer's campaign, gameplay with the "
                 "streamer's face cam or voice on screen is exactly the requested format and scores well",
    # S10 (owner 21 Nov: "the content ... is so obvious for the viewer that this is ai, we need more human like")
    "human_feel": "the words and shots read like a skilled human creator made them: specific concrete details, "
                  "natural spoken phrasing, varied rhythm, real humour or opinion; NOT obvious AI (stock phrases like "
                  "'delve', 'buckle up', 'little did they know', 'not just X but Y', same-shaped sentences, a "
                  "template look, word cards instead of real pictures)",
}
# 23 Nov: the generic texts were written for Shorts and grown-up viewers. The owner-approved Bloop long video (kids,
# 24 Nov 06:30) was judged "can it win on Shorts/Reels", and its human_feel lost points for "same-shaped sentences"
# while its own rubric scores joyful repetition (8/10). These texts replace the generic ones for that format/type.
HELP_KIDS = {
    "human_feel": "it feels made by a skilled human preschool team: warm, natural lines that talk TO the child, "
                  "characters with their own personality, small surprises and gentle jokes, a little story that makes "
                  "sense; the planned sing-along repetition is GOOD here, not an AI tell. Obvious AI = random objects "
                  "or events, lines that make no sense, a stiff template voice, nothing a parent would smile at",
}
HELP_LONG = {
    "hook": "the first 30 seconds deliver on the title's promise right away (no slow intro, no 'in this video'): "
            "viewers who clicked decide here whether to stay",
    "retention": "every minute earns the next: open loops, turns and payoffs keep viewers to the end (watch time)",
}
HUMAN = "human_feel"            # judged with its own bar (ai_tell.min_human): only obviously-AI videos are remade


def _long(it: dict) -> bool:
    return str((it or {}).get("kind") or "") == "long"


def criteria_help(ctype: str, it: dict) -> dict:
    """The rubric texts the judge sees for this video: kids and long videos get their own where the generic ones
    (written for grown-up Shorts) would judge them by the wrong standard."""
    out = dict(CRITERIA_HELP)
    if ctype == "kids":
        out.update(HELP_KIDS)
    if _long(it):
        out.update(HELP_LONG)
    return out


HUMAN_FINDING = "looks/sounds obviously AI-made"


def human_note(ctype: str, kind: str = "") -> str:
    """S10 for the writer (23 Nov): a remake or script rewrite after an 'obviously AI-made' verdict was told only the
    judge's general fixes (hook, pacing), never what the human_feel score measures, so the 22-23 Nov remakes stayed at
    human_feel 5. This is the judge's own criterion text for this content type, so the rewrite aims at what is scored."""
    return (f"The judge said the last version {HUMAN_FINDING} (human_feel below the bar). Human-made here means: "
            f"{criteria_help(ctype, {'kind': kind})[HUMAN]}. Write it the way one skilled person would say it to a "
            "friend: concrete details, varied sentence lengths, a real reaction or opinion, no stock phrases.")


def judge_tag(ctype: str, it: dict) -> str:
    """'' for a video the judge sees exactly as before 23 Nov (grown-up Shorts: their cached verdicts stay); otherwise
    a short hash of its own texts, part of the verdict's cache key, so a kids or long video is judged once more by
    the corrected judge and again whenever those texts change (scores can go down as well as up)."""
    own = {k: v for k, v in criteria_help(ctype, it).items() if CRITERIA_HELP.get(k) != v}
    if ctype == "clips":                          # 26 Nov: a clip's verdict follows its rubric texts too (the
        own = {**criteria_help(ctype, it), **own}  # misread brief_fit note stayed cached on every held clip)
    if not own and not _long(it):
        return ""
    return hashlib.sha1(json.dumps([own, _long(it)], sort_keys=True).encode("utf-8")).hexdigest()[:8]


def campaign_bar_ok(scores: dict, today: str | None = None) -> bool:
    """Owner 26 Nov ("campaign bar 7"): until temporary_bar.until, a campaign clip passes the rubric with an average of
    campaign_avg+ and no point under campaign_min (config/gates.yaml). False when no such bar is set."""
    from .content_gate import temporary_bar
    t = temporary_bar(today)
    if t.get("campaign_avg") is None or not scores:
        return False
    vals = [float(v) for v in scores.values()]
    return sum(vals) / len(vals) >= float(t["campaign_avg"]) and min(vals) >= float(t.get("campaign_min", 0))


def _cfg() -> dict:
    from .content_gate import config
    c = dict({"min_each": 9, "hook_start_max_s": 0.6, "clip_hook_start_max_s": 1.0, "title_repeat_ratio": 0.85},
             **((config().get("potential") or {})))
    c.setdefault("rubrics", {})
    c["ai_tell"] = dict({"enabled": True, "min_human": 6, "max_text_density": 4.0}, **(c.get("ai_tell") or {}))
    from .content_gate import temporary_bar                      # owner 21 Nov: 8/10 for 7 days, then 9 again
    t = temporary_bar()
    if t.get("min_each") is not None:
        c["min_each"] = min(int(c["min_each"]), int(t["min_each"]))
    return c


def _ctype(ch: dict, meta: dict, it: dict) -> str:
    if meta.get("clip") or meta.get("campaign") or it.get("kind") == "clip" or ch.get("type") == "clips":
        return "clips"
    return ch.get("type") if ch.get("type") in DEFAULT_RUBRICS else "story"


def srt_text(folder: Path, stem: str | None = None) -> tuple[str, float | None]:
    """(what is said, first caption start in seconds) from the video's .srt, if any. A clip folder holds one .srt per
    clip (clip_01.srt, clip_02.srt): `stem` picks the one that belongs to the video."""
    own = folder / f"{stem}.srt" if stem else None
    # 21 Nov: a clip without its own .srt borrowed clip_01.srt (another clip's words), so the judge scored the wrong
    # moment ("counting ... the pen"); another clip's captions are never used, only a folder-wide captions file
    files = [own] if own is not None and own.exists() else sorted(
        f for f in folder.glob("*.srt") if not (stem and f.stem.startswith("clip_") and f.stem != stem))
    if not files:
        return "", None
    raw = files[0].read_text(encoding="utf-8", errors="ignore")
    m = TS.search(raw)
    first = (int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3)) + int(m.group(4)) / 1000) if m else None
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip() and not ln.strip().isdigit() and "-->" not in ln]
    return " ".join(lines), first


def script_text(it: dict, meta: dict) -> str:
    folder = Path(it.get("out_dir") or "")
    said, _ = srt_text(folder, Path(str(it.get("file") or "")).stem or None)
    shown = ""
    try:                                          # 26 Nov: a clip's picture in words (engine/clip_shown.py)
        from .campaign_gate import clip_entry
        entry = clip_entry(it)[0] or {}
        shown = str(entry.get("shown") or "").strip()
    except (OSError, ValueError) as e:
        print(f"potential: clip record unreadable for {it.get('id')}: {e}")
    if said:
        return ((f"SHOWN: {shown}\nSAID: " if shown else "") + said)[:4000]
    sj = folder / "script.json"
    if sj.exists():
        try:
            d = json.loads(sj.read_text(encoding="utf-8"))
            if isinstance(d, dict) and str(d.get("shown") or "").strip():   # 21 Nov: the format's own "what you see"
                return str(d["shown"])[:4000]
            parts: list[str] = []

            def walk(x):
                if isinstance(x, str) and len(x) > 2:
                    parts.append(x)
                elif isinstance(x, dict):
                    for k, v in x.items():
                        if not str(k).startswith("_"):
                            walk(v)
                elif isinstance(x, list):
                    for v in x:
                        walk(v)
            walk(d)
            if parts:
                return " ".join(parts)[:4000]
        except (OSError, ValueError):
            pass
    try:
        from .campaign_gate import clip_entry
        entry, _r, _c = clip_entry(it)
        if entry and entry.get("transcript"):
            return str(entry["transcript"])[:4000]
    except Exception as e:  # noqa: BLE001
        print(f"potential: clip record unreadable for {it.get('id')}: {e}")
    return str(meta.get("description") or "")[:2000]


def deterministic(it: dict, ch: dict, meta: dict, past_titles: list[str] | None = None) -> list[str]:
    cfg, p = _cfg(), []
    folder = Path(it.get("out_dir") or "")
    ctype = _ctype(ch, meta, it)
    said, first = srt_text(folder, Path(str(it.get("file") or "")).stem or None)
    limit = cfg["clip_hook_start_max_s"] if ctype == "clips" else cfg["hook_start_max_s"]
    if first is not None and first > float(limit):
        p.append(f"{PREFIX}: speech starts at {first:.1f}s (the hook must land within {limit}s)")
    title = str(meta.get("title") or "")
    if past_titles is None:
        try:
            from .weekly import past_topics
            from .uniq import used_titles
            past_titles = sorted(used_titles(it["channel"])) + past_topics(it["channel"])
        except Exception as e:  # noqa: BLE001
            p.append(f"{PREFIX}: originality check could not run ({type(e).__name__})")
            past_titles = []
    # 21 Nov: used_titles stores titles normalised (lower case, no emoji/punctuation) and includes THIS video's own
    # upload.json, so "Wait for the last try 😳" was judged a repeat of its own "wait for the last try". Both sides
    # are compared normalised; the video's own title is skipped. 23 Nov: a shared series tag at the end no longer
    # makes two different titles a repeat (uniq.repeat_ratio).
    from .uniq import _norm, repeat_ratio
    low = _norm(title)
    for old in past_titles:
        if old and _norm(old) != low and repeat_ratio(low, old) >= float(cfg["title_repeat_ratio"]):
            p.append(f"{PREFIX}: title nearly repeats an earlier one (\"{str(old)[:60]}\")")
            break
    text = " ".join([title, str(meta.get("description") or ""), said])
    bad = sorted({m.group(0).lower() for m in AD_UNFRIENDLY.finditer(text)})
    if bad:
        p.append(f"{PREFIX}: not advertiser-friendly ({', '.join(bad[:5])}): limited or no ads = no earning")
    ai = cfg["ai_tell"]
    if ai.get("enabled"):                 # S10: obviously AI-written words; a clip's speech is the creator's own
        from .humanize import tell_density, tells
        ours = " ".join([title, str(meta.get("description") or "")] + ([] if ctype == "clips" else [said]))
        found = tells(ours)
        if len(found) >= 2 and tell_density(ours) >= float(ai.get("max_text_density", 4.0)):
            words = ", ".join(f'"{m}"' for m in list(dict.fromkeys(t["match"].lower() for t in found))[:4])
            p.append(f"{PREFIX}: reads like AI-written text ({words}): say it plainly like a person would")
    return p


def _criteria(cfg: dict, ctype: str) -> list[str]:
    crit = list(cfg["rubrics"].get(ctype) or DEFAULT_RUBRICS[ctype])
    if cfg["ai_tell"].get("enabled") and ctype != "clips" and HUMAN not in crit:
        crit.append(HUMAN)
    return crit


def campaign_brief(meta: dict) -> str:
    """22 Nov: the clip rubric scores brief_fit ("fits the campaign brief's spirit and audience"), but the judge was
    never shown the brief, only the slot's planned STORY topic (Dom's Kick clips sit in GTA fact slots: 'GTA 6 vs GTA 5
    map size'), so brief_fit came out 2-4. This is the brief from the campaign record (config/campaigns_picked.yaml)."""
    cid = meta.get("campaign")
    if not cid:
        return ""
    try:
        from . import db
        c = db.get_campaign(db.connect(), str(cid)) or {}
    except Exception as e:  # noqa: BLE001 - the judge still sees the clip itself
        return f"(campaign brief unavailable: {type(e).__name__})"
    if not c:
        return ""
    ln = c.get("length_seconds") or {}
    parts = [str(c.get("name") or cid), f"game: {c['game']}" if c.get("game") else "",
             str(c.get("rules") or "; ".join(c.get("other_rules") or [])),
             ("hook ideas: " + "; ".join(c.get("hook_ideas") or [])) if c.get("hook_ideas") else "",
             f"length {ln.get('min')}-{ln.get('max')} s" if isinstance(ln, dict) and ln.get("max") else ""]
    return " | ".join(p for p in parts if p.strip())[:700]


def _prompt(ch: dict, it: dict, meta: dict, ctype: str, criteria: list[str], evidence: str) -> str:
    aud = "Indian viewers (Hindi)" if ch.get("language") == "hi" else (
        "Indian viewers" if ch.get("market") == "IN" else "United States viewers")
    if ctype == "kids":
        aud = "children aged 2-5 and their parents"
    helps = criteria_help(ctype, it)
    rubric = "\n".join(f"- {c}: {helps.get(c, c)}" for c in criteria)
    if ctype == "clips":                          # a clip's brief is the campaign's, not the slot's planned topic
        topic_line = f"CAMPAIGN BRIEF: {campaign_brief(meta) or 'not given'}"
    else:
        topic_line = f"TOPIC: {str(it.get('topic') or '')[:150]}"
    said = script_text(it, meta)
    if _long(it):                                 # 23 Nov: a long video was asked "can it win on Shorts/Reels"
        task = ("You are the strictest head of content at a top YouTube studio. Decide if this LONG video can WIN on "
                "YouTube (viewers arrive from search, suggested videos and autoplay: the title earns the click, the "
                "first 30 seconds earn the stay, then watch time) and earn money. ")
        reward = "YouTube rewards watch time and viewers who are glad they watched"
        shown = "WHAT IS SAID / SHOWN" + (" (the first minutes of a longer video)" if len(said) > 3500 else "")
    else:
        task = ("You are the strictest head of content at a top short-video studio. Decide if this video can WIN on "
                "YouTube Shorts, Instagram Reels and Facebook Reels and earn money. ")
        reward = "Platforms reward viewers who stay, rewatch and SEND videos to friends"
        shown = "WHAT IS SAID / SHOWN"
    return (
        task + "Score each criterion 0-10 where 9 means top 5% "
        "of what this niche posts this month and 10 means it could be one of the niche's best videos this week. "
        f"Be harsh: generic, templated, slow or confusing content scores 6 or less. {reward}; "
        "YouTube does not monetise mass-produced content without its own insight.\n"
        f"CHANNEL: {ch.get('name', ch.get('id'))} ({ch.get('niche', '')}) for {aud}\n"
        f"TITLE: {str(meta.get('title') or '')[:150]}\n"
        f"HOOK / FIRST LINE: {str(meta.get('hook') or meta.get('hook_text') or '')[:200]}\n"
        f"{topic_line}\n{evidence}\n"
        f"{shown}:\n{said[:3500]}\n\n"
        f"CRITERIA:\n{rubric}\n\n"
        'Reply JSON only: {"scores": {"<criterion>": <0-10>, ...}, "fixes": ["the most important concrete fix", '
        '"..."], "summary": "one sentence"}')


def _one_verdict(data, res, criteria: list[str]) -> dict:
    """One judge answer checked: every criterion scored 0-10. Raises when it is missing or incomplete."""
    scores = (data or {}).get("scores") if isinstance(data, dict) else None
    if not isinstance(scores, dict):
        raise ValueError("the judge gave no scores")
    clean = {}
    for c in criteria:
        v = scores.get(c)
        try:
            v = float(v)
        except (TypeError, ValueError):
            raise ValueError(f"the judge skipped '{c}'") from None
        if not 0 <= v <= 10:
            raise ValueError(f"the judge gave '{c}' an invalid score {v}")
        clean[c] = v
    fixes = [str(x)[:200] for x in (data.get("fixes") or []) if str(x).strip()][:5]
    # 23 Nov: the same script scored human_feel 4-5 from gpt-oss-120b (Groq, first in the checker route) and 6-7 from
    # Gemini Flash-Lite (the fallback while Groq rests): which model judged decided S10 for most videos, and no verdict
    # said which one it was. Every verdict now records its model (ledger checkpoint), so verdicts can be audited.
    return {"scores": clean, "fixes": fixes, "summary": str(data.get("summary") or "")[:300],
            "model": str(getattr(res, "provider", "") or "")}


def judge_panel(cfg: dict) -> list[str]:
    """gates.yaml potential.judge_panel: the models that judge every video together (empty = the checker route)."""
    return [str(m).strip() for m in (cfg.get("judge_panel") or []) if str(m).strip()]


def judge_backups(cfg: dict) -> list[str]:
    """gates.yaml potential.judge_backups: who takes a resting panel member's turn (24 Nov: with gpt-oss-120b benched,
    'gemini_lite+gemini_lite' meant one model's temperature-0 answer counted twice, and with both members resting at
    01:24 and 02:26 no script got a verdict at all while gemini-3-flash and three Lite models were ready)."""
    return [str(m).strip() for m in (cfg.get("judge_backups") or []) if str(m).strip()]


def _pinned(brain, name: str):
    """The same brain (providers, cooldowns) with the checker task routed to one model only."""
    import copy
    b = copy.copy(brain)
    b.routes = dict(getattr(brain, "routes", None) or {}, checker=[name])
    return b


def judge(it: dict, ch: dict, meta: dict, brain, evidence: str = "") -> dict:
    """{scores, fixes, summary, criteria, model}. Raises when the answer is missing or incomplete (= not judged).
    gates.yaml potential.judge_panel (owner 23 Nov: "panel"): each listed model judges once and the scores are averaged
    per criterion. The same script scored human_feel 5, 7, 6, 6, 7 from one model and 7, 7, 6, 6, 7 from another
    across one day, so a single answer near the bar of 6 decided a verdict partly by chance; the average of two
    different models is steadier and tracks human ratings better than one judge (Verga et al. 2024, 'Replacing
    Judges with Juries'). A member that rests or fails gives its turn to the other members, then to the backups
    (judge_backups), and the same model never counts twice, so a verdict averages different models whenever enough
    of them answer; it fails only when nobody answers. Empty = the checker route."""
    cfg = _cfg()
    ctype = _ctype(ch, meta, it)
    criteria = _criteria(cfg, ctype)
    prompt = _prompt(ch, it, meta, ctype, criteria, evidence)
    panel = judge_panel(cfg)
    if not panel:
        data, res = brain.ask_json("checker", prompt, temperature=0.0)
        return dict(_one_verdict(data, res, criteria), criteria=criteria)
    got, errors, used, failed = [], [], set(), set()
    backups = [m for m in judge_backups(cfg) if m not in panel]
    for slot in range(len(panel)):
        # its own model first, then the other members, then the backups; never the same model twice
        for name in panel[slot:] + panel[:slot] + backups:
            if name in used or name in failed:
                continue
            try:
                data, res = _pinned(brain, name).ask_json("checker", prompt, temperature=0.0)
                v = _one_verdict(data, res, criteria)
            except Exception as e:  # noqa: BLE001 - resting / no key / broken answer: the next one answers
                errors.append(f"{name}: {type(e).__name__}: {str(e)[:80]}")
                failed.add(name)
                continue
            got.append(dict(v, model=v["model"] or name))
            used.add(name)
            break
    if not got:
        raise ValueError("no judge on the panel answered: " + "; ".join(errors[-6:]))
    fixes = list(dict.fromkeys(f for v in got for f in v["fixes"]))[:5]
    return {"scores": {c: round(sum(v["scores"][c] for v in got) / len(got), 2) for c in criteria},
            "fixes": fixes, "summary": got[0]["summary"], "criteria": criteria,
            "model": "+".join(v["model"] for v in got),
            "panel": [{"model": v["model"], "scores": v["scores"]} for v in got]}


def judge_script(script: dict, ch: dict, topic: str, brain, kind: str = "") -> dict:
    """P3 (22 Nov): the gate's own rubric on the SCRIPT, before voice, pictures and render. Since the strict judge
    went live (20-21 Nov) no video passed it (story Shorts 5-7 of 10 against 8 on every point), and each rejected
    story Short had already cost ~12 pictures and ~35 minutes. Same prompt and bar as the video gate; the script's
    narration stands in for the captions. {scores, fixes, summary, criteria, low: {criterion: score}, need}. Raises
    like judge() when the answer is unusable."""
    from .config import ROOT
    beats = script.get("beats") or []
    said = " ".join(str(b.get("narration") or "") for b in beats if isinstance(b, dict)).strip()
    meta = {"title": str(script.get("title") or ""), "description": said or str(script.get("script") or ""),
            "hook": str((beats[0] or {}).get("narration") or "") if beats and isinstance(beats[0], dict) else ""}
    it = {"id": "script", "topic": topic, "kind": kind,           # "long": judged as a long video (23 Nov)
          "out_dir": str(ROOT / "data" / "tmp" / "script_judge_no_folder")}
    evidence = ""
    if topic:
        try:
            from .story import core_topic
            from .topic_proof import evidence_text, proof
            # 24 Nov: the brief's first 100 characters (topic + angle) were searched, so the script judge saw other
            # demand evidence than the video gate (which checks the plan topic) and every script cost one more
            # YouTube search (100 units); the plan topic is the cached search the topic picker already made
            evidence = evidence_text(proof(core_topic(str(topic)), ch))
        except Exception as e:  # noqa: BLE001 - the judge works without it, as in problems()
            evidence = f"demand: unknown ({type(e).__name__})"
    v = judge(it, ch, meta, brain, evidence)
    cfg = _cfg()
    need, human = float(cfg["min_each"]), float(cfg["ai_tell"].get("min_human", 6))
    scores = dict(v["scores"])
    h = scores.pop(HUMAN, None)
    low = {c: s for c, s in scores.items() if s < need}
    if cfg["ai_tell"].get("enabled") and h is not None and h < human:
        low[HUMAN] = h
    return dict(v, low=low, need=need)


def problems(it: dict, ch: dict, meta: dict, brain_fn=None, led=None) -> list[str]:
    """[] = full potential. Judged once per version (ledger checkpoint 'potential:<version>[:<judge tag>]')."""
    p = deterministic(it, ch, meta)
    if p:
        return p                                      # fix these first; no AI call for a video that fails anyway
    from .content_gate import version
    from .core import ledger
    led = led or ledger.default()
    tag = judge_tag(_ctype(ch, meta, it), it)
    stage = f"{PREFIX}:{version(it)}" + (f":{tag}" if tag else "")
    cp = led.checkpoint(it["id"], stage)
    if not (cp and cp["status"] == "completed"):
        brain = None
        if brain_fn is not None:
            try:
                brain = brain_fn()
            except Exception as e:  # noqa: BLE001
                return [f"{PREFIX}: not judged yet (no AI judge: {type(e).__name__}); it tries again"]
        if brain is None:
            return [f"{PREFIX}: not judged yet (no AI judge available here); it tries again"]
        evidence = ""
        if it.get("topic") and _ctype(ch, meta, it) != "clips":   # a clip slot's planned topic says nothing about it
            try:
                from .topic_proof import evidence_text, proof
                evidence = evidence_text(proof(str(it["topic"]), ch))
            except Exception as e:  # noqa: BLE001 - the judge works without it
                evidence = f"demand: unknown ({type(e).__name__})"
        try:
            verdict = led.run_stage(it["id"], stage, lambda: judge(it, ch, meta, brain, evidence),
                                    validate=lambda a: isinstance(a, dict) and isinstance(a.get("scores"), dict))
        except Exception as e:  # noqa: BLE001 - not judged = not passed
            return [f"{PREFIX}: not judged yet ({type(e).__name__}: {str(e)[:80]}); it tries again"]
    else:
        verdict = cp["artifact"]
    cfg = _cfg()
    need, human = float(cfg["min_each"]), float(cfg["ai_tell"].get("min_human", 6))
    scores_all = dict(verdict.get("scores") or {})
    h = scores_all.pop(HUMAN, None)                   # older verdicts have no human_feel: nothing to hold
    low = {c: s for c, s in scores_all.items() if s < need}
    if low and meta.get("campaign") and _ctype(ch, meta, it) == "clips" and campaign_bar_ok(scores_all):
        low = {}                                  # the campaign's own rules were checked by the campaign gate
    fixes = "; ".join(verdict.get("fixes") or [])
    out = []
    if low:
        scores = ", ".join(f"{c} {s:g}" for c, s in sorted(low.items(), key=lambda x: x[1]))
        out.append(f"{PREFIX}: below {need:g}/10 on {scores}. Fix: {fixes}"[:700])
    if cfg["ai_tell"].get("enabled") and h is not None and h < human:
        out.append(f"{PREFIX}: looks/sounds obviously AI-made ({HUMAN} {h:g}, needs {human:g}). Fix: {fixes}"[:700])
    return out
