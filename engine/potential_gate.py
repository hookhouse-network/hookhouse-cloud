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

import difflib
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
    "brief_fit": "fits the campaign brief's spirit and audience",
    # S10 (owner 21 Nov: "the content ... is so obvious for the viewer that this is ai, we need more human like")
    "human_feel": "the words and shots read like a skilled human creator made them: specific concrete details, "
                  "natural spoken phrasing, varied rhythm, real humour or opinion; NOT obvious AI (stock phrases like "
                  "'delve', 'buckle up', 'little did they know', 'not just X but Y', same-shaped sentences, a "
                  "template look, word cards instead of real pictures)",
}
HUMAN = "human_feel"            # judged with its own bar (ai_tell.min_human): only obviously-AI videos are remade


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
    files = [own] if own is not None and own.exists() else sorted(folder.glob("*.srt"))
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
    if said:
        return said[:4000]
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
    # are compared normalised; the video's own title is skipped.
    from .uniq import _norm
    low = _norm(title)
    for old in past_titles:
        if old and _norm(old) != low and difflib.SequenceMatcher(None, low, _norm(old)).ratio() >= \
                float(cfg["title_repeat_ratio"]):
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


def _prompt(ch: dict, it: dict, meta: dict, ctype: str, criteria: list[str], evidence: str) -> str:
    aud = "Indian viewers (Hindi)" if ch.get("language") == "hi" else (
        "Indian viewers" if ch.get("market") == "IN" else "United States viewers")
    if ctype == "kids":
        aud = "children aged 2-5 and their parents"
    rubric = "\n".join(f"- {c}: {CRITERIA_HELP.get(c, c)}" for c in criteria)
    return (
        "You are the strictest head of content at a top short-video studio. Decide if this video can WIN on YouTube "
        "Shorts, Instagram Reels and Facebook Reels and earn money. Score each criterion 0-10 where 9 means top 5% "
        "of what this niche posts this month and 10 means it could be one of the niche's best videos this week. "
        "Be harsh: generic, templated, slow or confusing content scores 6 or less. Platforms reward viewers who stay, "
        "rewatch and SEND videos to friends; YouTube does not monetise mass-produced content without its own insight.\n"
        f"CHANNEL: {ch.get('name', ch.get('id'))} ({ch.get('niche', '')}) for {aud}\n"
        f"TITLE: {str(meta.get('title') or '')[:150]}\n"
        f"HOOK / FIRST LINE: {str(meta.get('hook') or meta.get('hook_text') or '')[:200]}\n"
        f"TOPIC: {str(it.get('topic') or '')[:150]}\n{evidence}\n"
        f"WHAT IS SAID / SHOWN:\n{script_text(it, meta)[:3500]}\n\n"
        f"CRITERIA:\n{rubric}\n\n"
        'Reply JSON only: {"scores": {"<criterion>": <0-10>, ...}, "fixes": ["the most important concrete fix", '
        '"..."], "summary": "one sentence"}')


def judge(it: dict, ch: dict, meta: dict, brain, evidence: str = "") -> dict:
    """{scores, fixes, summary, criteria}. Raises when the answer is missing or incomplete (= not judged)."""
    cfg = _cfg()
    ctype = _ctype(ch, meta, it)
    criteria = _criteria(cfg, ctype)
    data, _res = brain.ask_json("checker", _prompt(ch, it, meta, ctype, criteria, evidence), temperature=0.0)
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
    return {"scores": clean, "fixes": fixes, "summary": str(data.get("summary") or "")[:300], "criteria": criteria}


def problems(it: dict, ch: dict, meta: dict, brain_fn=None, led=None) -> list[str]:
    """[] = full potential. Judged once per version (ledger checkpoint 'potential:<version>')."""
    p = deterministic(it, ch, meta)
    if p:
        return p                                      # fix these first; no AI call for a video that fails anyway
    from .content_gate import version
    from .core import ledger
    led = led or ledger.default()
    stage = f"{PREFIX}:{version(it)}"
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
        if it.get("topic"):
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
    fixes = "; ".join(verdict.get("fixes") or [])
    out = []
    if low:
        scores = ", ".join(f"{c} {s:g}" for c, s in sorted(low.items(), key=lambda x: x[1]))
        out.append(f"{PREFIX}: below {need:g}/10 on {scores}. Fix: {fixes}"[:700])
    if cfg["ai_tell"].get("enabled") and h is not None and h < human:
        out.append(f"{PREFIX}: looks/sounds obviously AI-made ({HUMAN} {h:g}, needs {human:g}). Fix: {fixes}"[:700])
    return out
