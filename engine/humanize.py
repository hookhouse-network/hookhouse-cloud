"""Human-sounding text for every script, title, caption and description (plan P3r creation workstream; standards S7
and S10, owner 21 Nov: "current content ... is so obvious for the viewer that this is ai, but we need more human like
things from the system").

Adapted from blader/humanizer (MIT, (c) 2025 Siqi Chen; github.com/blader/humanizer): its catalogue of AI-writing
patterns (staging instead of stating, rhythm by rule, inflation and borrowed authority, chatbot leftovers) is checked
here in code, plus the AI tells typical of YouTube narration ("buckle up", "you won't believe", "little did they know",
"Unveiling ..." titles). `tells()` finds them for free; `rewrite_lines()` asks the writer model once to restate the
marked lines plainly and keeps the result only if the tells drop, every number survives and the length stays close.
`ai_tell_score()` turns text tells, word cards and AI-picture share into one 0-100 number for the gate (S10)."""
from __future__ import annotations

import json
import re

# (id, label, pattern, weight). Patterns are case-insensitive and anchored on word boundaries where it matters.
PATTERNS: list[tuple[str, str, str, int]] = [
    ("not_x_but_y", "not X but Y contrast",
     r"\bnot (?:just|only|merely)\b[^.?!]{0,90}?\bbut\b|\bit'?s not\b[^.?!]{0,70}?[,;:]\s*it'?s\b|\bisn'?t (?:just|only)\b"
     r"|\bthis (?:does not|doesn'?t) mean\b"
     # 23 Nov (Deep Blue): "This isn't a glass sculpture; it's a living animal"
     r"|\b(?:this|that|it) (?:isn'?t|is not|wasn'?t|was not)\b[^.?!]{0,70}?[;:]\s*(?:it|this|that)(?:'s| is| was)\b", 3),
    # 23 Nov: the writer prompt's own example reaction ("Honestly, this is the part I can't get over.") came back word
    # for word in 10 of 33 scripts across channels: the same line in every video is a template, not a voice
    ("stock_reaction", "stock reaction line",
     r"\bthe part i can'?t get over\b|\bi (?:still )?can'?t get over (?:this|that|it)\b"
     r"|\bhonestly,? (?:this|that) (?:is|was) (?:the part|what)\b", 3),
    # 24 Nov: the writer prompt's own example lines came back as templates: a line opening "Guess how/what..." in 16
    # of 29 English scripts since 18 Nov, "You see," in 6 and "It started" in 6. `^` = the start of one line (tells()
    # runs per line in humanize_script; the gate's density check reads the joined captions, so only a video that
    # OPENS this way counts there)
    ("template_line", "template line from a script formula",
     r"^\W*guess (?:how|what|why|who|where|when|which)\b|^\W*you see,|^\W*it (?:all )?started\b"
     r"|\bdid you know\b|\bwhich brings us (?:right )?back\b", 3),
    ("closer", "dramatic one-line closer",
     r"\blet that sink in\b|\bread that again\b|\bthat distinction matters\b|\bthat(?:'s| is) the real (?:win|story|lesson)\b"
     r"|\band that changes everything\b|\bnothing would ever be the same\b"
     r"|\bwhich (?:makes|leaves) (?:you|us) (?:wonder|wondering|thinking)\b", 3),    # 24 Nov A/B: a last line
    ("deep_saying", "saying that sounds deep",
     r"\bthe real question is\b|\bat its core\b|\bwhat really matters\b|\bfundamentally\b|\bthe deeper (?:issue|truth)\b"
     r"|\bthe heart of the matter\b", 3),
    ("run_up", "staged run-up before the point",
     r"\blet'?s (?:dive in|dive into|explore|break (?:this|it) down|unpack)\b|\bhere'?s what you need to know\b"
     r"|\bwithout further ado\b|\bhere'?s the thing\b|\bthe thing is\b|\blet'?s be honest\b|\breal talk\b"
     r"|\bthe (?:hard|new|real|crazy) part is\b", 3),
    ("no_one_argued", "arguing with no one",
     r"\bi'?m not saying\b|\bto be clear\b|\bdon'?t get me wrong\b|\bthis is not to say\b|\bone might be tempted\b"
     r"|\byou might think\b", 2),
    ("ai_word", "overused AI word",
     r"\b(?:additionally|bolstered|crucial|deep dive|delves?|delving|enduring|garner(?:ed|s)?|interplay|intricate|"
     r"intricacies|meticulous(?:ly)?|pivotal|showcas(?:e|es|ed|ing)|tapestry|testament|underscor(?:e|es|ed|ing)|"
     r"vibrant|realm|embark(?:ed|s)?|navigat(?:e|ing) the)\b", 2),
    ("inflated", "inflated significance",
     r"\bstands as a testament\b|\ba (?:pivotal|crucial|defining) moment\b|\bplays? a (?:key|vital|crucial) role\b"
     r"|\breflects a broader\b|\b(?:enduring|lasting) legacy\b|\bsetting the stage for\b|\bevolving landscape\b"
     r"|\bindelible mark\b|\bthe future looks bright\b|\bexciting times ahead\b|\bleft an indelible\b", 3),
    ("ing_tail", "shallow -ing phrase tacked on",
     r",\s*(?:highlighting|underscoring|emphasizing|emphasising|ensuring|reflecting|symbolizing|symbolising|"
     r"contributing to|cultivating|fostering|encompassing|showcasing)\b", 2),
    ("sales", "sales language",
     r"\b(?:rich (?:history|heritage|culture)|profound|exemplifies|nestled|in the heart of|groundbreaking|renowned|"
     r"diverse array|breathtaking|must-see|must-visit|stunning|captivating|awe-inspiring)\b", 2),
    ("borrowed_authority", "borrowed authority",
     r"\b(?:experts (?:say|argue|believe)|observers have|industry reports|some critics|scientists agree)\b", 2),
    ("chatbot", "chatbot residue",
     r"\bi hope this helps\b|\bgreat question\b|\byou'?re absolutely right\b|\bas an ai\b|\bas of my last\b", 4),
    ("yt_cliche", "AI video-script cliche",
     r"\bbuckle up\b|\bget ready to\b|\byou won'?t believe\b|\bimagine a world (?:where|in which)\b"
     r"|\bin a world where\b|\blittle did (?:they|he|she|we) know\b|\bmind[- ]blowing\b|\bgame[- ]changer\b"
     r"|\bstay tuned\b|\bsmash that\b|\bjoin us as we\b|\bwhat happened next will\b|\bthe answer may surprise you\b", 3),
    ("title_cliche", "AI title word",
     r"\b(?:unveil(?:ing|ed|s)?|unravel(?:ing|ed|s)?|unlock(?:ing)? the|the untold (?:story|truth)|a journey (?:through|into))\b", 3),
]
_COMPILED = [(pid, label, re.compile(rx, re.I), w) for pid, label, rx, w in PATTERNS]
DASH = re.compile(r"\s[—–-]\s|—")
AI_SOURCES = {"ai", "cloudflare", "pollinations", "flux", "hf", "zerogpu"}   # picture sources (engine/story.py)


def tells(text: str) -> list[dict]:
    """Every AI-writing pattern found in `text`: [{"id", "label", "match", "weight"}]."""
    found = []
    for pid, label, rx, w in _COMPILED:
        for m in rx.finditer(text or ""):
            found.append({"id": pid, "label": label, "match": m.group(0).strip(), "weight": w})
    words = max(1, len(re.findall(r"\w+", text or "")))
    dashes = len(DASH.findall(text or ""))
    if dashes >= 3 and dashes / words > 1 / 40:          # dashes as the universal connector
        found.append({"id": "dashes", "label": "dashes everywhere", "match": f"{dashes} dashes", "weight": 2})
    return found


def tell_density(text: str) -> float:
    """Weighted tells per 100 words."""
    words = max(1, len(re.findall(r"\w+", text or "")))
    return round(100.0 * sum(t["weight"] for t in tells(text)) / words, 2)


def _numbers(text: str) -> set[str]:
    return set(re.findall(r"\d+(?:[.,]\d+)?", text or ""))


REWRITE_PROMPT = """These lines are narration/text for a short video. Some read like AI-written text. Rewrite ONLY the
lines listed under "fix" so they sound like a real person telling the story: state each point plainly, keep it vivid
and specific, vary sentence length, no cliches. Rules: keep every fact, name, number and date exactly; keep the same
language and script; keep each line about the same length (within 20 %); keep the hook energy of the first line; do
not add new facts; do not merge or split lines.
Patterns to remove (from the humanizer catalogue): {patterns}
{keep}
Lines (JSON list, index = position):
{lines}
fix: {fix}
Return JSON only: {{"lines": ["<all lines, rewritten where needed, same count and order>"]}}"""


def rewrite_lines(brain, lines: list[str], keep_words: list[str] | None = None, log=print) -> tuple[list[str], int]:
    """One writer call for all lines that carry tells. Returns (lines, number of lines changed). The rewrite is kept
    line by line only where it has fewer tells, keeps every number and stays within 35 % of the length."""
    marked = {i: tells(t) for i, t in enumerate(lines)}
    fix = [i for i, t in marked.items() if t]
    if not fix or brain is None:
        return lines, 0
    pats = sorted({t["label"] for i in fix for t in marked[i]})
    keep = f"Keep these words in the text: {', '.join(keep_words)}" if keep_words else ""
    try:
        data, _ = brain.ask_json("writer", REWRITE_PROMPT.format(patterns="; ".join(pats), keep=keep,
                                                                 lines=json.dumps(lines, ensure_ascii=False), fix=fix),
                                 temperature=0.5)
    except Exception as e:  # noqa: BLE001 - the original text still goes out; the gate reports the tells
        log(f"humanize: rewrite skipped ({type(e).__name__}: {e})")
        return lines, 0
    new = (data or {}).get("lines") if isinstance(data, dict) else None
    if not isinstance(new, list) or len(new) != len(lines):
        log("humanize: the rewrite came back with a different line count; kept the original")
        return lines, 0
    out, changed = list(lines), 0
    for i in fix:
        cand = str(new[i] or "").strip()
        old = lines[i]
        if not cand or cand == old:
            continue
        if len(tells(cand)) >= len(marked[i]) or not _numbers(old) <= _numbers(cand):
            continue
        if abs(len(cand) - len(old)) > 0.35 * max(len(old), 20):
            continue
        if keep_words and any(k.lower() in old.lower() and k.lower() not in cand.lower() for k in keep_words):
            continue
        out[i], changed = cand, changed + 1
    return out, changed


def _script_fields(script: dict) -> tuple[list[tuple[str, int | None]], list[str]]:
    beats = script.get("beats") or []
    fields = [("beat", i) for i, b in enumerate(beats) if str(b.get("narration", "")).strip()]
    fields += [(k, None) for k in ("title", "hook_text", "description") if str(script.get(k) or "").strip()]
    return fields, [str(beats[i]["narration"]) if k == "beat" else str(script[k]) for k, i in fields]


def script_tells(script: dict) -> list[dict]:
    """All AI-writing tells in a story script's narration, title, hook text and description (free, no AI call)."""
    return [t for line in _script_fields(script)[1] for t in tells(line)]


def humanize_script(brain, script: dict, log=print) -> dict:
    """Narration beats, title, hook text and description of a story script, rewritten where they carry AI tells."""
    fields, lines = _script_fields(script)
    if not any(tells(t) for t in lines):
        return script
    phrase = [w for w in re.findall(r"\w+", str(script.get("search_phrase") or "")) if len(w) > 3][:3]
    new, changed = rewrite_lines(brain, lines, keep_words=phrase, log=log)
    if not changed:
        return script
    import copy
    out = copy.deepcopy(script)
    for (k, i), text in zip(fields, new):
        if k == "beat":
            out["beats"][i]["narration"] = text
        else:
            out[k] = text
    out["_fact_check"] = {}                             # wording changed: the fact-check runs on the new text
    left = sum(len(tells(t)) for t in new)
    log(f"humanize: {changed} line(s) rewritten to sound human; {left} tell(s) left")
    return out


def ai_tell_score(text: str, shots: list[dict] | None = None) -> dict:
    """0-100, higher = more obviously AI-made (S10 AI-tell judge v1, measured from what the system knows):
    text tells per 100 words (up to 50 points), share of word cards (up to 30), share of AI-generated pictures where a
    real picture could stand (up to 20). Returns {"score", "parts", "top"}."""
    density = tell_density(text)
    part_text = min(50.0, density * 10)
    shots = shots or []
    n = max(1, len(shots))
    cards = sum(1 for s in shots if s.get("kind") == "text" or s.get("source") in ("graphic", "text"))
    ai_pics = sum(1 for s in shots if not s.get("graphic") and (
        str(s.get("source") or "") in AI_SOURCES or "AI-generated" in str(s.get("credit") or "")))
    part_cards = 30.0 * cards / n if shots else 0.0
    part_ai = 20.0 * ai_pics / n if shots else 0.0
    found = tells(text)
    top = sorted({t["match"] for t in found}, key=len, reverse=True)[:5]
    return {"score": round(part_text + part_cards + part_ai, 1),
            "parts": {"text": round(part_text, 1), "word_cards": round(part_cards, 1), "ai_pictures": round(part_ai, 1)},
            "top": top}
