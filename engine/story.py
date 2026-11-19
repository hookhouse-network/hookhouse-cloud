"""Story video pipeline (channels #2-8), v2 — MrBeast pacing, modern look.

idea -> 5 angles -> thumbnail + title FIRST -> beats (2-3 s each) -> fact-check -> voice ->
visuals per beat (AI image / real footage / evidence photo / big text) -> our frame engine
(moves, punch-ins, transitions, grade, emoji, progress bar) -> sound design + music -> video.
"""
from __future__ import annotations

import copy
import json
import math
import re
import time
from pathlib import Path

import numpy as np
import requests
import soundfile as sf

from .policy import never_rules_text, topic_flags
from .config import ROOT
from .media import compose, ffmpeg, footage, sfx, stickers, visuals
from .media.captions import BigText, HookStyle, Label, build_ass
from .media.fonts import FONTS_DIR, caption_font, ensure_fonts, title_font
from .media.transcribe import align_script, transcribe
from .media.voice import synthesize, to_48k

FORMATS = {
    "short": {"size": (1080, 1920), "beats": "16-22", "words": "120-150 words (about 45-55 seconds)",
              "caption_margin_v": 640, "font_size": 128, "sticker": 330, "label_y": 330},
    "long": {"size": (1920, 1080), "beats": "150-220", "words": "1800-2300 words (9-12 minutes; never under 1700)",
             "caption_margin_v": 90, "font_size": 86, "sticker": 220, "label_y": 120},
}

WRITER_SYSTEM = ("You are the head writer of a top faceless YouTube channel. You can make ANY topic gripping, "
                 "even boring ones, using true facts only. You never invent facts, names, dates or numbers.")

WRITER_PROMPT = """Channel: "{channel}" ({niche}). Audience: {audience}. Narration language: {language_name}.
Topic: {topic}
Format: {fmt}

STEP 1 - ANGLE. Think of 5 angles (a secret, money, danger, a conflict, a strange person, a link to the
viewer's own life, "everyone thinks X, actually Y"). Pick the most surprising TRUE one.
STEP 2 - THUMBNAIL + TITLE FIRST (MrBeast rule). The video must deliver exactly what they promise, inside
the first 2 seconds. Never promise anything the video does not show (YouTube removes misleading clickbait).
STEP 3 - BEATS (the structure top story Shorts use in 2026).
- Beat 1 = COLD OPEN: drop the viewer into the most dramatic true moment, mid-action, as a scene
  ("He put his sons in the lifeboat, but instead of climbing in..."). Stakes + an exact number if there is one
  ("India need 15 runs off 6 balls."). No greetings, no "in this video", no "did you know", no "imagine", and never
  open with a date, a year or a full name (viewers swipe before the point arrives): open with the action or the claim.
- Beats 2-3 = "You see," / "It started..." backstory: who, where, when (by 4-8 seconds).
- Middle = escalation; every 6-10 seconds a new question, number or reveal. Around 40-60% a "But..." twist.
- End = the payoff, ideally ironic or surprising. NO call to action, no "follow for more", no "subscribe".
  The last line should flow back into the first line so the Short loops.
- One short sentence per beat (5-12 words, about 2-3 seconds). Simple spoken words, active verbs.
- Exact numbers, names, dates. Compare big numbers with things people know.
- Length: {words}, {beats} beats.
- MrBeast rule: beat 1 delivers the title's promise in its own words and says the title's key words (people search
  them and YouTube reads the narration); the thumbnail's subject is the picture of beat 1.
- SEARCH: "search_phrase" = the 2-5 words a viewer would type to find this story (the name + event/place, e.g.
  "Miracle on Ice 1980"). Say it in beat 1 or 2, start the title with it, and use it in the first sentence of "summary"
  and the first line of "instagram_caption" (YouTube and Instagram search read titles, captions and the narration).
- INTERACTIVE (Shorts): you may invite ONE guess right before a reveal ("Guess how deep it went."), then reveal it.
  Never ask for likes, follows or comments in the narration.
- HUMAN, NOT TEMPLATE: include ONE true detail most retellings of this story miss (the reason this video exists),
  and ONE short honest reaction line in the narrator's own voice ("Honestly, this is the part I can't get over.") -
  never a fake identity, job title or credential, never advice.
- SHARE-WORTHY: give viewers a reason to send it to a friend (a fact they will want to tell someone, or a "this is so
  you" moment). Never ask for likes, shares or follows in the narration.
{long_rules}
STEP 4 - Score it 1-10 for "would a bored 19-year-old keep watching?". Below 8 = rewrite before answering.

VISUAL for each beat (pick what fits best; the picture changes every 2-3 seconds anyway):
- "footage": real video likely exists (space, nature, oceans, cities, weather, old newsreels, machines).
  query = 1-3 simple English words.
- "photo": a real person / place / object / document. query = 2-5 English words. Add a label such as
  "REAL PHOTO · 1872" or "ACTUAL DOCUMENT".
- "ai": a dramatic scene nobody could film (reconstructions, moods). ai_prompt = detailed English image
  prompt, cinematic, photorealistic, no text, no logos, no real celebrities, no real athletes' faces.
- "text": ONLY for a key number or 1-3 word statement shown as a documentary graphic (newspaper headline,
  evidence card, scoreboard, counter). big_text like "183 RUNS", optional sub.
- "chart": ONLY when this beat's narration compares 2-4 numbers, walks through 3-5 dates, or compares 2-3 sizes.
  chart = {{"type": "compare|timeline|scale", "title": "max 5 words", "items": [{{"label": "1-3 words or a year",
  "value": number (compare/scale), "text": "the number as spoken, e.g. $85.3M, or 2-5 words for a timeline"}}]}}.
  Every number on the chart must be said in that beat or the 2 beats before it. Also give a photo query as a backup.
Use "text" at most 2 times and "chart" at most once. Never 3 beats of the same visual type in a row.
emoji: leave "" on almost every beat (emoji spam looks dated); at most 1 in the whole video.
emphasis: 1-2 key words copied exactly from that beat's narration.
moment: "reveal" or "twist" for the 1-3 biggest moments, else "normal".
{lang_rules}
Channel rules: {rules}

What has worked before (copy the style, never the words):
{memory}

Return ONLY JSON:
{{
  "angles": ["5 one-line angles"],
  "chosen_angle": "the one you picked",
  "thumbnail": {{"text": "{thumb_rule}", "text_line2": "optional 1-2 words (counts toward the limit)", "question": "",
                "subject_prompt": "English image prompt: ONE dramatic subject, strong emotion, close-up, bright, no text"}},
  "title": "{title_rule}",
  "title_options": ["3 titles"],
  "hook_text": "{hook_rule}",
  "beats": [{{"narration": "...", "chapter": "", "visual": "footage|photo|ai|text|chart", "query": "...", "ai_prompt": "",
             "label": "", "big_text": "", "sub": "", "chart": null, "emoji": "", "emphasis": [""], "moment": "normal"}}],
  "interest_score": 8,
  "hook_type": "the hook type you used (outcome_first|curiosity_gap|contrarian|stakes_number|direct_question|countdown)",
  "summary": "2 lines. Line 1 = one self-contained factual sentence AI search can quote: the search phrase, the key person or place and the year (what happened, never the ending). Line 2 = the open question the video answers.",
  "search_phrase": "2-5 words people would search",
  "instagram_caption": "first line = the search phrase in a hook question, then 1-2 lines",
  "alt_text": "one plain sentence describing the video for Instagram alt text, with the search phrase",
  "pinned_comment": "one honest question about the story that invites opinions (no 'like and subscribe')",
  "hashtags": ["3-5 specific hashtags (topic, place, person), not generic ones like #viral"],
  "music_mood": "the background music that fits THIS story: mystery|suspense|epic|emotional|hopeful|playful|quirky|calm|lofi|energetic|nostalgic|wonder",
  "claims": ["every factual claim, one per line"],
  "sources": ["Wikipedia page titles that support the claims"]
}}"""

CHECKER_PROMPT = """You are a strict fact-checker. Compare each claim with the reference text.
Claims:
{claims}

Reference text (from Wikipedia):
{refs}

Sort problems into two kinds:
- "contradicted": the reference says something different (wrong number, date, name, place, order of events).
- "unsupported": the reference does not mention this detail at all (it may still be true).
Before marking anything "contradicted": search ALL the reference articles; if any one of them supports the claim
(exact dates, figures), it is NOT contradicted. Work out date gaps and sums exactly from the dates given (e.g.
February 9 to February 22 is 13 days) instead of trusting a vague phrase like "two weeks before". Rounded or
approximate wording in a reference is not a contradiction of an exact figure that another reference gives.
Return ONLY JSON: {{"contradicted": ["claim, and what the reference says instead"], "unsupported": ["claim, and which
detail is missing"]}}"""

LANG_RULES = {
    # research (mythology §5/§7, sports §4/§7, thumbnails §8): Devanagari on thumbnails and on-screen punch text;
    # titles mix a Hindi curiosity phrase with the searchable name ("कर्ण का आख़िरी रहस्य | Karna Story")
    # owner, 13 Nov: "we can use Hinglish as well, make the tone like a normal conversation"
    "hi": "Write narration as a normal CONVERSATION with one friend: everyday Hinglish, the way young Indians actually "
          "talk (Hindi with common English words: स्टोरी, प्रॉब्लम, सीरियसली, लेवल, टाइम), never bookish/शुद्ध Hindi and "
          "never a news-reader tone. Talk TO the listener: 'सोचो…', 'पता है?', 'यार,', 'अब सुनो…' (vary them, at most "
          "3 per video), short sentences, the way people say things out loud. Write it ALL in Devanagari script, every "
          "name and English word too (कपिल देव, वर्ल्ड कप, ज़िम्बाब्वे, टीवी), so the narrator pronounces them right; "
          "numbers as digits. Each beat is one natural breath: a whole short sentence or clause, never cut mid-phrase. "
          "'…' only for a held moment right before a reveal (at most 2 per video), '?' when you ask the listener, '!' "
          "for shock. "
          "hook_text and thumbnail text in Devanagari (2-5 words) unless the channel rules say otherwise. Title: a short "
          "Hindi (Devanagari or Hinglish) curiosity phrase, then \" | \" and the searchable name in Latin letters. "
          "query / ai_prompt stay in English. emphasis words must be copied from the Devanagari narration.",
    "en": "Write in simple American English. US spellings.",
}

# Per channel look (colour grade, music, transitions). Channels can override in their YAML under `look:`.
DEFAULT_LOOKS = {
    # research grades (mystery spec 2: low-key teal/amber, grain 3-5%, vignette 20-30%; mythology: warm teal-orange,
    # grain 3-5%, light vignette; wildlife/space: vivid but natural). Audited 11 Nov: grain 6-7 + vignette 0.45 dulled frames.
    "dark": {"contrast": 1.15, "saturation": 1.12, "warmth": -0.25, "teal_orange": 0.35, "vignette": 0.28,
             "grain": 4.0, "music": "dark", "transitions": ["cut", "cut", "zoom", "cut", "cut", "swipe"]},
    "epic": {"contrast": 1.12, "saturation": 1.3, "warmth": 0.2, "teal_orange": 0.25, "vignette": 0.3,
             "grain": 3.0, "music": "epic", "transitions": ["cut", "swipe", "cut", "cut", "zoom", "cut"]},
    "bright": {"contrast": 1.08, "saturation": 1.25, "warmth": 0.1, "teal_orange": 0.1, "vignette": 0.2,
               "grain": 2.0, "music": "upbeat", "transitions": ["cut", "swipe", "cut", "zoom"]},
    "history": {"contrast": 1.15, "saturation": 1.1, "warmth": 0.4, "teal_orange": 0.3, "vignette": 0.3,
                "grain": 4.0, "music": "dark", "transitions": ["cut", "zoom", "cut", "cut"]},
    "nature": {"contrast": 1.15, "saturation": 1.25, "warmth": 0.1, "teal_orange": 0.12, "vignette": 0.2,
               "grain": 1.5, "music": "epic", "transitions": ["cut", "zoom", "cut", "swipe", "cut"]},
    # niche_playbooks §3: space = deep-blue grade, ocean = cool cyan grade; movie spec: #111/#E50914/#F5F5F1, light
    # grain + vignette
    "space": {"contrast": 1.15, "saturation": 1.15, "warmth": -0.2, "teal_orange": 0.05, "vignette": 0.28,
              "grain": 2.0, "music": "dark", "tint": (-0.02, 0.0, 0.05), "transitions": ["cut"]},
    "ocean": {"contrast": 1.12, "saturation": 1.2, "warmth": -0.15, "teal_orange": 0.05, "vignette": 0.25,
              "grain": 1.5, "music": "dark", "tint": (-0.03, 0.02, 0.04), "transitions": ["cut"]},
    "noir": {"contrast": 1.15, "saturation": 1.05, "warmth": -0.1, "teal_orange": 0.3, "vignette": 0.3,
             "grain": 2.5, "music": "dark", "transitions": ["cut"]},
}
DEFAULT_LOOKS["history"]["particles"] = 0.15          # mythology spec: drifting embers/dust at 10-20% opacity
# Hindi emotion looks (owner, 13 Nov: "dramatic... feel nostalgic and more devoted"): devotion = golden temple light;
# cricket = warm memories of the great days; Bollywood = an old film reel (scratches, flicker, softer colour)
HINDI_LOOKS = {
    "itihaas_ke_raaz": {"glow": 0.35, "particles": 0.18, "warmth": 0.45},
    "cricket_ke_kisse": {"film": 0.3, "leak": 0.22, "warmth": 0.3},
    "picture_abhi_baaki_hai": {"film": 0.6, "leak": 0.28, "warmth": 0.3, "saturation": 1.1, "contrast": 1.1},
}
# Black-and-white archive photos/newsreels get a two-tone brand tint (shadow, highlight), as history and documentary
# channels do, instead of flat grey frames (quality scorecard 12 Nov: a Trieste 1960 Short scored colourfulness 12).
DUOTONES = {"dark": ("#1A1030", "#EBDCC2"), "epic": ("#0F1A33", "#F4D58C"), "bright": ("#0E2A3A", "#FFF0C2"),
            "history": ("#2E1606", "#F7D594"), "nature": ("#10261A", "#E8F4CF"), "space": ("#0A0F33", "#CFE2FF"),
            "ocean": ("#03213A", "#B8F2FF"), "noir": ("#16121A", "#E6D8C4")}
for _mood, _duo in DUOTONES.items():
    DEFAULT_LOOKS[_mood]["duo"] = _duo
CHANNEL_MOOD = {"unsolved_after_dark": "dark", "clutch_tales": "epic", "ending_decoded": "noir",
                "money_cheat_codes": "bright", "itihaas_ke_raaz": "history", "cricket_ke_kisse": "epic",
                "picture_abhi_baaki_hai": "bright", "cosmos_unboxed": "space", "deep_blue_files": "ocean",
                "wild_instinct": "nature"}

# Audio mix per niche (research specs, audit 12 Nov). bed_db = music bed level vs the voice (RMS); duck_db = extra
# dip while someone speaks; attack/release in seconds; swell_db = bed lift on twist/reveal beats; drop = seconds of
# full silence in the bed just before the climax line (sports).
MIX = {
    "unsolved_after_dark": {"bed_db": -14, "duck_db": 6, "swell_db": 4},          # mystery spec 1: -26..-30 LUFS bed
    "clutch_tales": {"bed_db": -10, "duck_db": 6, "drop": 0.4},                   # sports: -22..-26 LUFS, 6 dB duck
    "cricket_ke_kisse": {"bed_db": -8, "duck_db": 4, "drop": 0.45},              # bed ~12 dB under speech, -8 in pauses
    "ending_decoded": {"bed_db": -13, "duck_db": 6},                              # movie: bed -28..-30 vs voice -16
    "money_cheat_codes": {"bed_db": -26, "duck_db": 0, "swell_db": 5},            # money spec B: -26 dB under voice
    # mythology spec: voice 10-12 LU above the bed DURING speech (owner, 12 Nov: "add some background music"; the old
    # -11 dB bed + 10 dB duck left the music ~21 dB down, inaudible); the bed rises in the pauses
    "itihaas_ke_raaz": {"bed_db": -7, "duck_db": 4, "attack": 0.15, "release": 0.4},
    "picture_abhi_baaki_hai": {"bed_db": -9, "duck_db": 4},                       # movie spec: bed 12-14 dB under the voice
}
MIX_DEFAULT = {"bed_db": -16, "duck_db": 6, "attack": 0.05, "release": 0.3, "swell_db": 0, "drop": 0.0}  # 20-24 dB total

# Sound-effect palette per niche: event -> sound name (None = skip), levels in dB vs the voice (playbook §5: SFX about
# 15 dB under speech, whooshes 18-20 dB under)
SFX_PALETTE = {
    # Hindi channels (owner 13 Nov: emotion-driven sound): the score itself plays the shankh, bells, damru rolls,
    # crowd roars and string swells on the story's moments (emotion_music), so effects here only add what it doesn't
    "itihaas_ke_raaz": {"open": None, "card": ("bell", -18), "reveal": None, "twist": None,
                        "whip": None, "punch": None, "riser": None, "cut": None, "max_hits": 4},   # <= 4 hits per Short
    "clutch_tales": {"open": ("impact", -14), "card": ("heartbeat", -16), "reveal": ("crowd", -14), "rewind": ("tape", -16)},
    "cricket_ke_kisse": {"open": ("impact", -14), "card": ("heartbeat", -16), "reveal": None, "riser": None,
                         "rewind": ("tape", -16)},
    "money_cheat_codes": {"open": ("kaching", -16), "card": ("kaching", -16), "cut": ("whoosh", -20), "cut_rate": 0.7,
                          "label": ("tick", -18)},                        # money spec B: a whoosh on most cuts
    "picture_abhi_baaki_hai": {"open": ("projector", -16), "card": ("shutter", -18), "riser": None},   # nostalgia
    "ending_decoded": {"open": ("impact", -12), "card": ("typewriter", -18), "label": ("shutter", -16)},
    "unsolved_after_dark": {"cut": ("impact_soft", -18), "cut_rate": 0.4, "card": ("paper", -18)},   # 30-50% of cuts
}
SFX_DEFAULT = {"open": ("impact", -15), "card": ("impact", -16), "reveal": ("impact", -14), "twist": ("impact", -15),
               "whip": ("whoosh", -19), "riser": ("riser", -16), "punch": ("impact", -20), "label": ("tick", -18),
               "rewind": ("tape", -16), "cut": None, "cut_rate": 0.0, "max_hits": 99}


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "video"


def _relevant(text: str, focus: str, chars: int) -> str:
    """Keep the intro plus the paragraphs that share the most words with `focus`, in article order."""
    if len(text) <= chars or not focus:
        return text[:chars]
    words = {w for w in re.findall(r"[a-z0-9]{3,}", focus.lower())}
    paras = [x for x in text.split("\n") if x.strip()]
    scored = sorted(range(1, len(paras)), key=lambda i: -len(words & set(re.findall(r"[a-z0-9]{3,}", paras[i].lower()))))
    keep, size = {0}, len(paras[0])
    for i in scored:
        if size + len(paras[i]) > chars:
            continue
        keep.add(i)
        size += len(paras[i])
    return "\n".join(paras[i] for i in sorted(keep))


def wikipedia_summaries(titles: list[str], lang: str = "en", limit: int = 6, chars: int = 9000,
                        focus: str = "") -> str:
    """Article text (not just the intro) so the fact-checker can verify details. Long articles keep
    the paragraphs most related to `focus` (the claims), not just the first few thousand characters."""
    out = []
    for t in titles[:limit]:
        t = t.split("wiki/")[-1].replace("_", " ").strip()
        try:
            r = visuals._get(f"https://{lang}.wikipedia.org/w/api.php", timeout=30,   # waits politely on 429
                             params={"action": "query", "format": "json", "prop": "extracts", "explaintext": 1,
                                     "redirects": 1, "titles": t})
            pages = r.json().get("query", {}).get("pages", {})
            text = next(iter(pages.values()), {}).get("extract", "") if pages else ""
            if text:
                out.append(f"[{t}] {_relevant(text, focus, chars)}")
        except (requests.RequestException, ValueError):
            continue
    return "\n\n".join(out)


def _prompt_query(prompt: str) -> str:
    """A short search query from an AI image prompt: its first few concrete words."""
    words = [w for w in re.findall(r"[A-Za-z][A-Za-z\-]{2,}", prompt or "")
             if w.lower() not in STOP and w not in PROMPT_WORDS and w.lower() not in
             ("cinematic", "photorealistic", "dramatic", "lighting", "detailed", "style", "shot", "moody", "high", "wide", "angle", "view", "close", "realistic")]
    return " ".join(words[:4])


def _too_plain(path, strict: bool = False) -> bool:
    """Mostly white / mostly black / no detail pictures make dead frames (audit 11 Nov: a near-black hook, white pages).
    strict = the opening shot, which must be clearly readable."""
    try:
        import cv2
        img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if img is None and str(path).lower().endswith((".mp4", ".webm", ".mov", ".mkv")):
            cap = cv2.VideoCapture(str(path))                     # clips: judge a frame from the middle
            n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
            cap.set(cv2.CAP_PROP_POS_FRAMES, n // 2)
            ok, frame = cap.read()
            cap.release()
            img = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if ok else None
        if img is None:
            return False
        g = cv2.resize(img, (96, 96)).astype(np.float32)
        dark, bright = float((g < 25).mean()), float((g > 235).mean())     # calibrated 11 Nov on real outputs:
        detail = float(np.abs(cv2.Laplacian(g, cv2.CV_32F)).mean())       # near-black space 0.74 dark, blank page
        if strict:                                                         # 0.70 bright; Nosferatu still 0.45 dark = ok
            return dark > 0.6 or bright > 0.4 or detail < 8
        return dark > 0.6 or bright > 0.55 or detail < 3
    except Exception:  # noqa: BLE001
        return False


_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _sync_numbers(beat: dict) -> None:
    """On-screen numbers must match the spoken ones (the fact-fixer may correct the narration only: a card once said
    150-FOOT while the voice said 164-foot). One number each: copy the spoken one; otherwise drop the card text."""
    for key in ("big_text",):                       # labels describe the picture (its year), not the narration
        shown = beat.get(key) or ""
        nums_shown = _NUM.findall(shown)
        if not nums_shown:
            continue
        spoken = [n.replace(",", "") for n in _NUM.findall(beat.get("narration", ""))]
        if not spoken:
            continue                                   # numbers said in words ("ten"): nothing to compare
        bad = [n for n in nums_shown if n.replace(",", "") not in spoken]
        if not bad:
            continue
        if len(nums_shown) == 1 and len(spoken) == 1:
            raw = _NUM.findall(beat.get("narration", ""))[0]
            beat[key] = shown.replace(nums_shown[0], raw, 1)
        else:
            beat[key] = ""


def normalize_script(script: dict) -> dict:
    """Accept old scripts ("scenes") and new ones ("beats"). Without an AI image source, "ai" beats become
    photo searches built from their image prompt."""
    if script.get("beats"):
        for b in script["beats"]:
            _sync_numbers(b)
        if not visuals.ai_image_available():
            for b in script["beats"]:
                if b.get("visual") == "ai":
                    b["visual"] = "photo"
                    b["query"] = b.get("query") or _prompt_query(b.get("ai_prompt", ""))
        return script
    beats = []
    for sc in script.get("scenes", []):
        kind = {"photo": "photo", "ai": "ai"}.get(sc.get("visual_type"), "photo")
        beats.append({"narration": sc.get("narration", ""), "visual": kind, "query": sc.get("visual_query", ""),
                      "ai_prompt": sc.get("ai_prompt", ""), "label": "", "big_text": "", "emoji": "",
                      "emphasis": [], "moment": "normal", "sub": ""})
    script["beats"] = beats
    script.setdefault("thumbnail", {"text": script.get("hook_text", "")})
    return script


LONG_RULES = """- Long video: put the searchable name, event or place in the FIRST 5 WORDS of the title.
- Re-hook every 20-40 seconds: a new question, raised stakes, a countdown or a twist, so viewers keep watching.
- End with the channel's signature sign-off line (brand recall), exactly: "{catchphrase}"."""

LONG_MIN_WORDS = 1700          # ~8.5+ min at the long-video voice speed (mid-rolls need 8:00)

EXPAND_PROMPT = """This YouTube script has {n} words of narration; it needs about {target} words (research length).
Add about {add} words this time (not more).
Write ADDITIONAL beats with true, specific detail (scenes, context, what the records say, the people involved) to
insert where the story is thinnest. Never invent facts, names, numbers or dates. One short sentence per beat, same
language and style. Never insert before beat 0 or after the last beat (the hook stays first, the ending stays last). Return ONLY JSON:
{{"insert": [{{"after": 12, "beats": [{{"narration": "...", "visual": "photo|footage|ai|text", "query": "...",
"ai_prompt": "", "label": "", "big_text": "", "sub": "", "emoji": "", "emphasis": [""], "moment": "normal",
"chapter": ""}}]}}], "claims": ["every NEW factual claim, one per line"]}}
Current beats (index: narration):
{lines}"""


def _range(text: str) -> list[int]:
    nums = [int(x.replace(",", "")) for x in re.findall(r"\d[\d,]*", str(text or ""))[:2]]
    return nums if len(nums) == 2 else []


def expand_long(brain, script: dict, target: int = LONG_MIN_WORDS + 150, log=print, minimum: int = LONG_MIN_WORDS,
                rounds: int = 3) -> dict:
    """Adds beats to a script that came back too short (inserted in place; new claims get fact-checked)."""
    for _ in range(max(1, rounds)):
        before = sum(len(b.get("narration", "").split()) for b in script.get("beats") or [])
        if before >= minimum:
            return script
        script = _expand_once(brain, script, target, minimum, log)
        if sum(len(b.get("narration", "").split()) for b in script.get("beats") or []) <= before:
            break
    return script


def _expand_once(brain, script: dict, target: int, minimum: int, log=print) -> dict:
    beats = script.get("beats") or []
    words = sum(len(b.get("narration", "").split()) for b in beats)
    log(f"Script: {words} words is under {minimum} (research length); asking for more true detail")
    lines = "\n".join(f"{i}: {b.get('narration', '')}" for i, b in enumerate(beats))
    add = max(40, min(900, target - words))
    data, _ = brain.ask_json("writer", EXPAND_PROMPT.format(n=words, target=target, add=add, lines=lines), temperature=0.6)
    inserts = [x for x in data.get("insert") or [] if isinstance(x, dict) and x.get("beats")]
    for ins in sorted(inserts, key=lambda x: int(x.get("after", len(beats))), reverse=True):
        at = max(1, min(len(beats) - 1, int(ins.get("after", len(beats))) + 1))   # hook first, ending last
        new = [dict(b, chapter="") for b in ins["beats"] if isinstance(b, dict) and b.get("narration")]
        beats[at:at] = new
    script["beats"] = beats
    script["claims"] = list(script.get("claims") or []) + [str(c) for c in data.get("claims") or []]
    log(f"Script: now {sum(len(b.get('narration', '').split()) for b in beats)} words")
    return script


TRIM_PROMPT = """This YouTube Short script has {n} words; the research target for this channel is {target}.
Tighten it to about {goal} words: drop the weakest beats and shorten long sentences. Keep beat 0 (the hook), the
payoff and the last line (it loops back to the start). NEVER add facts, names, numbers or dates; only remove or
shorten. Same language. Return ONLY JSON: {{"keep": [{{"i": 0, "narration": "same or shortened text"}}]}}
Beats (index: narration):
{lines}"""


def fit_length(brain, channel: dict, script: dict, log=print) -> dict:
    """Shorts over the channel's researched word range are tightened by the writer (removal only), then re-checked."""
    rng = (channel.get("spec") or {}).get("short_words", "")
    nums = [int(x) for x in re.findall(r"\d+", rng)[:2]]
    beats = script.get("beats") or []
    n = sum(len(b.get("narration", "").split()) for b in beats)
    script = _short_title(script)
    if len(nums) == 2 and n < nums[0]:          # too short for the niche's researched length (movie: 55-75 s)
        out = expand_long(brain, copy.deepcopy(script), target=(nums[0] + nums[1]) // 2, log=log, minimum=nums[0],
                          rounds=2)
        if sum(len(b.get("narration", "").split()) for b in out.get("beats") or []) > n:
            out["_fact_check"] = {}                     # new lines: check again before upload
            out["_expanded"] = True
            return out
        return script
    if len(nums) < 2 or n <= nums[1]:               # strict: the research range is the limit (53.7 s slipped through)
        return script
    goal = (nums[0] + nums[1]) // 2
    log(f"Script: {n} words is over this channel's research range ({rng}); tightening to ~{goal}")
    lines = "\n".join(f"{i}: {b.get('narration', '')}" for i, b in enumerate(beats))
    data, _ = brain.ask_json("writer", TRIM_PROMPT.format(n=n, target=rng, goal=goal, lines=lines), temperature=0.3)
    keep = [k for k in (data or {}).get("keep") or [] if isinstance(k, dict) and str(k.get("i", "")).isdigit()]
    new = []
    for k in keep:
        i = int(k["i"])
        if 0 <= i < len(beats) and k.get("narration"):
            nb = dict(beats[i], narration=str(k["narration"]).strip())
            if nb["narration"] != beats[i].get("narration"):
                nb.pop("narration_roman", None)            # the Roman caption copy must follow the new wording
            new.append(nb)
    m = sum(len(b["narration"].split()) for b in new)
    if len(new) < 8 or m >= n or 0 not in [int(k["i"]) for k in keep]:
        log("  trim rejected (too few beats or lost the hook); keeping the original")
        return script
    out = dict(script, beats=new)
    out["_fact_check"] = {}                     # wording changed: check again before upload
    log(f"Script: now {m} words in {len(new)} beats")
    return out


CHAPTER_PROMPT = """This long YouTube script needs {n} chapters (one every 3-5 minutes), and the first chapter starts
at line 0. Pick the line indexes where a new section clearly starts and give each a short chapter title (2-6 words, same
language as the script, no numbering). Where it fits naturally, phrase a title as the question viewers type into search
("Why Was the Ship Empty?"), because chapters show up as search results and AI answers. Never spoil the ending in a title.
Return ONLY JSON: {{"chapters": [{{"i": 0, "title": "..."}}]}}
Lines (index: narration):
{lines}"""


def add_chapters(brain, script: dict, wpm: float = 175, log=print) -> dict:
    """Long videos: make sure there is a chapter about every 4 minutes (research: 3-5 min mystery; 90-150 s mythology)."""
    beats = script.get("beats") or []
    words = sum(len(b.get("narration", "").split()) for b in beats)
    minutes = words / max(wpm, 1)
    want = max(3, round(minutes / 4))
    have = sum(1 for b in beats if b.get("chapter"))
    if have >= want or not beats:
        return script
    lines = "\n".join(f"{i}: {b.get('narration', '')}" for i, b in enumerate(beats))
    try:
        data, _ = brain.ask_json("writer", CHAPTER_PROMPT.format(n=want, lines=lines), temperature=0.3)
    except Exception as e:  # noqa: BLE001 - chapters are metadata, never block a render
        log(f"Chapters skipped: {e}")
        return script
    marks = {}
    for c in (data or {}).get("chapters") or []:
        try:
            i = int(c.get("i"))
        except (TypeError, ValueError):
            continue
        if 0 <= i < len(beats) and str(c.get("title", "")).strip():
            marks[i] = str(c["title"]).strip()[:60]
    if len(marks) >= 3:
        marks.setdefault(0, beats[0].get("chapter") or "Intro")
        for i, b in enumerate(beats):
            b["chapter"] = marks.get(i, "")
        log(f"Chapters: {len(marks)} placed (was {have})")
    return script


def _short_title(script: dict) -> dict:
    """Research (thumbnails §8): Shorts titles 20-40 characters. Keep the title if it fits, else the best option that
    fits (same promise, from the writer's own title options)."""
    title = str(script.get("title") or "")
    if 20 <= len(title) <= 40:
        return script
    opts = [str(t) for t in (script.get("title_options") or []) if 20 <= len(str(t)) <= 40]
    phrase = str(script.get("search_phrase") or "").lower()
    if opts:
        best = max(opts, key=lambda t: (phrase.split()[0] in t.lower() if phrase else False, -abs(len(t) - 34)))
        script = dict(script, title=best, title_options=list(dict.fromkeys([best, title] + list(script.get("title_options") or []))))
    return script


def check_and_fix(brain, channel: dict, script: dict, topic: str, fmt: str, memory=None, log=print) -> dict:
    """Fact-check; only real mistakes get fixed (small targeted edits; one careful rewrite if no edit fits); the
    best version wins, so a fix can never make the script worse. "Unsupported" details go to the owner."""
    log("Fact-check: comparing claims with Wikipedia")
    deep = fmt == "long"
    verdict = fact_check(brain, script, deep=deep)
    best = (copy.deepcopy(script), verdict)
    for attempt in range(2):
        wrong = verdict.get("problems") or []
        if not verdict.get("checked") or not wrong:
            break
        log(f"Fact-check (fix {attempt + 1}/2): wrong={wrong}")
        script, applied = fix_script(brain, copy.deepcopy(script), wrong)
        log(f"Fact-check: {applied} targeted edits applied")
        if applied == 0 and not deep:
            script = write_script(brain, channel, f"{topic}\nFix these factual problems exactly, change nothing else "
                                  f"that is true: {wrong}", fmt, memory)
        verdict = fact_check(brain, script, deep=deep)
        if _fc_score(verdict) < _fc_score(best[1]):
            best = (copy.deepcopy(script), verdict)
    if _fc_score(verdict) > _fc_score(best[1]):
        log("Fact-check: the fix made it worse; keeping the earlier, better version")
        script, verdict = best
    script["_fact_check"] = verdict
    return script


def _fc_score(verdict: dict) -> tuple[int, int]:
    """Lower is better: (wrong details, unsupported details)."""
    return len(verdict.get("problems") or []), len(verdict.get("warnings") or [])


def script_flags(script: dict) -> list[str]:
    """Never-topic categories touched anywhere in the script (title, hook, narration, on-screen text)."""
    parts = [script.get("title", ""), script.get("hook_text", "")]
    parts += [f"{b.get('narration', '')} {b.get('big_text', '')} {b.get('sub', '')}" for b in script.get("beats", [])]
    return topic_flags(" ".join(str(x) for x in parts), mode="topic")


def _tuning_rules(cid: str, fmt: str = "short") -> str:
    """19 Nov: the channel's own numbers (swipe-away, watch %, likes, plateaus) -> rules for this script, plus the
    hook type this Short tests or exploits (content_tuning.next_hook: the self-improving hook loop)."""
    try:
        from .content_tuning import next_hook, writer_rules
        hook = next_hook(cid)[0] if fmt == "short" else None
        return writer_rules(cid, hook=hook)
    except Exception:  # noqa: BLE001 - the script is still written with the base rules
        return ""


def write_script(brain, channel: dict, topic: str, fmt: str = "short", memory=None) -> dict:
    f = dict(FORMATS[fmt])
    if fmt == "short" and (channel.get("spec") or {}).get("short_words"):
        f["words"] = channel["spec"]["short_words"]         # research length/pace for this niche
    if fmt == "long" and (channel.get("spec") or {}).get("long_words"):
        lo = _range(channel["spec"]["long_words"])
        if lo and lo[0] <= 2300:                            # fits one writer call
            f["words"] = channel["spec"]["long_words"]
            f["beats"] = f"{lo[0] // 11}-{lo[1] // 9}"
        # longer targets: first draft at the default 1,800-2,300 words; make() expands it step by step
    mem_text = memory.context_block(topic, channel["id"]) if memory else ""
    prompt = WRITER_PROMPT.format(
        fmt="vertical YouTube Short" if fmt == "short" else "long horizontal YouTube video with chapters",
        channel=channel["name"], niche=channel["niche"], topic=topic,
        audience="United States viewers" if channel["market"] == "US" else "Indian viewers",
        language_name="Hindi" if channel["language"] == "hi" else "English",
        words=f["words"], beats=f["beats"], lang_rules=LANG_RULES[channel["language"]],
        # research (thumbnails §8): Shorts titles 20-40 characters, keyword first, max 1 emoji; long titles under 60;
        # thumbnail text: US 0-3 words (15 characters max), Hindi 2-5 words
        title_rule=("20-40 characters, the searchable name first, at most 1 emoji, no hashtags" if fmt == "short"
                    else "under 60 characters, the searchable name in the first 5 words, matches the thumbnail"),
        thumb_rule=("2-5 huge Devanagari words" if channel["language"] == "hi"
                    else "0-3 huge words, 15 characters max in total (a number or short claim works best)"),
        hook_rule=("max 6 words shown in the first 3 seconds" if channel["language"] != "hi"
                   else "2-5 words shown in the first 3 seconds (Devanagari unless the channel rules say otherwise)"),
        long_rules=(LONG_RULES.format(catchphrase=channel.get("catchphrase") or "a calm, memorable closing line")
                    if fmt == "long" else ""),
        rules=json.dumps(channel.get("content_rules", {})) + "\n" + (channel.get("writer_rules") or "") + "\n"
        + _tuning_rules(channel["id"], fmt) + "\n"
        + never_rules_text() + (
            "" if visuals.ai_image_available() else
            "\nAI images are switched OFF right now: never use visual \"ai\". Use photo, footage or text, and give "
            "EVERY beat a concrete 1-5 word English query for a real object, place, document or era scene from this "
            "story (e.g. \"salt mine tunnel\", \"1980 oil drilling rig\"), never an abstract word."),
        memory=mem_text or "(no history yet)")
    script, result = brain.ask_json("writer", prompt, system=WRITER_SYSTEM, temperature=0.8)
    script["_written_by"] = result.provider
    return normalize_script(script)


def fact_check(brain, script: dict, deep: bool = False) -> dict:
    """deep=True (long videos, many claims): read much more of each article, so true details that sit
    further down the page are not reported as "unsupported"."""
    refs = wikipedia_summaries(script.get("sources", []), focus=" ".join(script.get("claims", [])),
                               chars=30000 if deep else 9000)
    if not refs and script.get("sources"):              # Wikipedia busy: one more try after a pause
        time.sleep(30)
        refs = wikipedia_summaries(script.get("sources", []), focus=" ".join(script.get("claims", [])),
                                   chars=30000 if deep else 9000)
    if not refs or not script.get("claims"):
        return {"ok": False, "problems": ["No sources found to verify the claims — check manually"], "checked": False}
    verdict, result = brain.ask_json("checker", CHECKER_PROMPT.format(
        claims="\n".join(f"- {c}" for c in script["claims"]), refs=refs[:90000 if deep else 40000]), temperature=0.0)
    contradicted = [str(x) for x in verdict.get("contradicted") or []]
    unsupported = [str(x) for x in verdict.get("unsupported") or []]
    if "ok" in verdict and not contradicted and not unsupported:      # older-style answer
        contradicted = [] if verdict.get("ok") else [str(x) for x in verdict.get("problems") or []]
    # Only contradictions fail the check (they block upload). Unsupported details are warnings for the owner.
    return {"ok": not contradicted, "problems": contradicted, "warnings": unsupported,
            "checked": True, "checked_by": result.provider}


FIX_PROMPT = """These details in a video script are wrong according to the sources:
{problems}
Script lines (index: narration):
{lines}
Fix each wrong detail with the smallest change that makes it match the sources, or remove the detail.
If the sources disagree with each other (different numbers, dates or names for the same thing), do NOT pick one:
replace it with a safe statement every source supports (e.g. "over 1,000 times the pressure at the surface").
Keep the same language and style. Return ONLY JSON:
{{"edits": [{{"i": 0, "old": "exact words copied from that line", "new": "replacement words"}}],
"claims": ["the corrected full list of factual claims, one per line"]}}"""


def fix_script(brain, script: dict, problems: list[str]) -> tuple[dict, int]:
    """Targeted fix for long scripts: small find/replace edits instead of rewriting 100+ lines
    (a full rewrite is slow and can bring in new mistakes)."""
    beats = script.get("beats") or []
    lines = "\n".join(f"{i}: {b.get('narration', '')}" for i, b in enumerate(beats))
    data, _ = brain.ask_json("writer", FIX_PROMPT.format(problems="\n".join(f"- {p}" for p in problems),
                                                         lines=lines), temperature=0.2)
    applied = 0
    for e in data.get("edits") or []:
        try:
            i = int(e.get("i"))
        except (TypeError, ValueError):
            continue
        old, new = str(e.get("old") or ""), str(e.get("new") or "")
        if not old or not 0 <= i < len(beats) or old not in beats[i].get("narration", ""):
            continue
        beats[i]["narration"] = re.sub(r"\s{2,}", " ", beats[i]["narration"].replace(old, new, 1)).strip()
        for key in ("big_text", "sub", "label"):                     # on-screen words repeating the detail
            if isinstance(beats[i].get(key), str) and old in beats[i][key]:
                beats[i][key] = beats[i][key].replace(old, new)
        applied += 1
    if data.get("claims"):
        script["claims"] = [str(c) for c in data["claims"]]
    return script, applied


def chapters_block(chapters: list[tuple[float, str]]) -> list[str]:
    """YouTube chapters: at least 3, each at least 10 s, the first at 0:00, ascending."""
    ch = sorted(chapters)
    if not ch or len(ch) < 3:
        return []
    ch[0] = (0.0, ch[0][1])
    keep = [ch[0]]
    for t, title in ch[1:]:
        if t - keep[-1][0] >= 10:
            keep.append((t, title))
    if len(keep) < 3:
        return []
    fmt = lambda t: f"{int(t // 3600)}:{int(t % 3600 // 60):02d}:{int(t % 60):02d}" if t >= 3600 else f"{int(t // 60)}:{int(t % 60):02d}"
    return ["Chapters:"] + [f"{fmt(t)} {title}" for t, title in keep]


def seo_tags(channel: dict, script: dict) -> list[str]:
    """YouTube tags: the search phrase first, then the topic's hashtags and the channel's niche words (tags matter little,
    but they help with misspellings and names)."""
    out = []
    sp = (script.get("search_phrase") or "").strip()
    if sp:
        out.append(sp)
    out += [t.lstrip("#") for t in script.get("hashtags", []) if t]
    out += [t for t in (channel.get("seo_tags") or [])]
    out.append(channel["name"])
    return [t for t in dict.fromkeys(x.strip() for x in out if x and x.strip())][:15]


def write_srt(words: list, dest: Path, max_words: int = 7, max_gap: float = 0.6) -> Path:
    """Captions file for YouTube (search reads it; accurate Hindi beats auto-captions; viewers with sound off)."""
    def ts(t: float) -> str:
        ms = int(round(max(0.0, t) * 1000))
        return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"
    cues, cur = [], []
    for w in words:
        if cur and (len(cur) >= max_words or w.start - cur[-1].end > max_gap):
            cues.append(cur)
            cur = []
        cur.append(w)
    if cur:
        cues.append(cur)
    lines = []
    for k, c in enumerate(cues, 1):
        lines += [str(k), f"{ts(c[0].start)} --> {ts(c[-1].end)}", " ".join(w.text for w in c), ""]
    dest.write_text("\n".join(lines), encoding="utf-8")
    return dest


def build_description(channel: dict, script: dict, credits: list[str], chapters: list | None = None) -> str:
    rules = channel.get("content_rules", {})
    lines = [script.get("summary", "") or script.get("hook_text", ""), "",       # keyword-rich first line (search)
             f"🔔 Follow {channel['name']} for a new story every day."]
    if channel.get("catchphrase"):                                               # signature line (brand recall)
        lines.append(f"“{channel['catchphrase']}”")
    if chapters:
        block = chapters_block(chapters)
        if block:
            lines += [""] + block
        facts = [str(c).strip() for c in (script.get("claims") or []) if str(c).strip()][:3]
        if facts:                      # long videos: quotable, fact-checked statements (AI answers + trust)
            lines += ["", "Key facts:"] + [f"• {f}" for f in facts]
    if script.get("sources"):
        lines += ["", "Sources:"] + [f"• https://en.wikipedia.org/wiki/{s.replace(' ', '_')}"
                                     for s in script["sources"][:5]]
    from .affiliate import links as affiliate_links
    aff = affiliate_links(channel, script)                # off until the owner adds an Associate tag
    if aff:
        lines += ["", f"📚 {aff[0]}", aff[1]]
    if credits:
        lines += ["", "Credits (images, footage, music):"] + [f"• {c}" for c in dict.fromkeys(credits)]
    if rules.get("disclaimer") and rules["disclaimer"].lower() not in (script.get("summary") or "").lower():
        lines += ["", rules["disclaimer"]]
    ai_pics = any("AI-generated" in str(c) for c in credits or [])
    lines += ["", "Narration uses an AI voice; some visuals are AI-generated." if ai_pics else
              "Narration uses an AI voice.", "",
              # YouTube shows the first 3 hashtags above the title: the story's specific tags first, max 5 in total
              " ".join(list(dict.fromkeys(script.get("hashtags", []) + channel.get("hashtags", [])))[:5])]
    return "\n".join(lines).strip()


def channel_look(channel: dict, size: tuple[int, int]) -> tuple[compose.Look, dict]:
    style = channel.get("style", {})
    base = dict(DEFAULT_LOOKS[CHANNEL_MOOD.get(channel["id"], "dark")])
    base.update(HINDI_LOOKS.get(channel["id"], {}))
    base.update(channel.get("look", {}))
    look = compose.Look(size=size, palette=style.get("palette", ["#111111", "#333333"]),
                        accent=style.get("highlight_color", "#FF3B3B"),
                        contrast=base["contrast"], saturation=base["saturation"], warmth=base["warmth"],
                        teal_orange=base["teal_orange"], vignette=base["vignette"], grain=base["grain"],
                        tint=tuple(base.get("tint", (0.0, 0.0, 0.0))), particles=float(base.get("particles", 0.0)),
                        duo=tuple(base["duo"]) if base.get("duo") else None,
                        film=float(base.get("film", 0.0)), glow=float(base.get("glow", 0.0)),
                        leak=float(base.get("leak", 0.0)),
                        sticker_y=0.58 if size[1] > size[0] else 0.62)
    return look, base


# ---------- visuals per beat ----------
def _match(items: list, texts: list[str], scene_text: str) -> tuple[int, float]:
    if not items:
        return -1, 0.0
    emb = visuals._embedder()
    q = emb.encode([scene_text], is_query=True)[0]
    scores = emb.encode(texts) @ q
    i = int(np.argmax(scores))
    return i, float(scores[i])


_SEARCH_CACHE: dict[tuple, list] = {}


def _image_size(path) -> tuple[int, int]:
    try:
        from PIL import Image
        with Image.open(path) as im:
            return im.size
    except Exception:
        return (0, 0)


def _cached(kind: str, query: str, fn):
    """Beats often repeat a search; ask each site only once per query."""
    key = (kind, query.lower().strip())
    if key not in _SEARCH_CACHE:
        try:
            _SEARCH_CACHE[key] = fn()
        except Exception:
            _SEARCH_CACHE[key] = []
    return _SEARCH_CACHE[key]


GENERIC_SEARCH = re.compile(r"\b(portrait|poster|still|photo|photograph|picture|image|antique|vintage|old|close[- ]?up|"
                            r"document|sign|scene|view)\b", re.I)


def _photo_candidates(query: str) -> list:
    """Wikimedia + Pexels + Pixabay. Empty? Retry without generic words ("portrait", "poster"...: every word must match
    on Wikimedia), then accept smaller historical pictures (most pre-1950 photos are under 900 px wide)."""
    def search():
        got = (visuals.wikimedia(query, download=False) + visuals.pexels(query, download=False)
               + visuals.pixabay(query, download=False))     # 19 Nov: everyday scenes when AI pictures run out
        short = re.sub(r"\s+", " ", GENERIC_SEARCH.sub(" ", query)).strip()
        if not got and short and short != query:
            got = visuals.wikimedia(short, download=False)
        if not got:
            got = visuals.wikimedia(short or query, download=False, min_width=500)
        return got
    return _cached("photo", query, search)


def topic_pool(script: dict) -> list:
    """Photos about the main subject (from the script's sources), used when a beat finds nothing."""
    pool = []
    for title in (script.get("sources") or [])[:3]:
        pool += _cached("pool", title, lambda t=title: visuals.wikimedia(t, limit=12, download=False))
    return pool


SENSITIVE = ("stalin", "mao zedong", "mao tse", "hitler", "nazi", "swastika", "lenin", "mussolini", "khomeini",
             "bin laden", "isis", "kkk",
             # heads of state / top politicians often found in free photo archives (e.g. Kremlin, White House):
             # only when the scene itself is about that person
             "putin", "medvedev", "trump", "biden", "obama", "clinton", "bush", "modi", "rahul gandhi", "xi jinping",
             "erdogan", "erdoğan", "netanyahu", "zelensky", "zelenskyy", "macron", "merkel", "kim jong", "lukashenko",
             "imran khan", "sharif", "kremlin", "white house", "president of russia", "president of the united states",
             "prime minister of")


MODERN = re.compile(r"\b(actor|actress|singer|cricketer|politician|businessman|businesswoman|entrepreneur|founder|"
                    r"ceo|youtuber|blogger|journalist|professor|student|athlete|player|coach|model|selfie|headshot|"
                    r"born \d|soldiers?|army|military|troops|police|war|protest|riot|refugees?|demolish\w*|destroyed|"
                    r"street|traffic|car|bus|train|apartment|office|airport|smartphone|laptop)\b", re.I)
OFFICIAL = re.compile(r"secretary of|senator|congress(wo)?man|governor|minister|president|politician|press conference|"
                      r"speaks (at|to|during)|addresses|podium|ceremony|swearing[- ]in|campaign|official portrait|"
                      r"\bMP\b|\bMLA\b|delegation|summit", re.I)


GENERIC_CAPS = {"Secretary", "Labor", "Labour", "Department", "Administration", "Office", "Event", "Meeting",
                "Health", "Safety", "National", "State", "United", "States", "Press", "Conference", "Official",
                "Portrait", "Ceremony", "Government", "Minister", "Ministry", "President", "Governor", "Senator"}


def _shares_name(meta_text: str, scene_text: str) -> bool:
    """True when a capitalised name in the picture's description also appears in the scene."""
    names = {w for w in re.findall(r"\b[A-Z][a-z]{3,}\b", meta_text)} - PROMPT_WORDS - GENERIC_CAPS
    return any(re.search(rf"\b{re.escape(n)}\b", scene_text) for n in names)   # case-sensitive: a proper noun


INDIA = re.compile(r"(india|indian|bombay|mumbai|delhi|calcutta|kolkata|madras|chennai|bengal|punjab|hindu|"
                   r"mughal|raj|gandhi|nehru|himalaya|ganges|ganga|cricket|bollywood|hindustan)", re.I)
SPACE = re.compile(r"\b(galaxy|galaxies|nebula|hubble|telescope|supernova|exoplanet|asteroid|comet|planet|"
                   r"astronaut|space station|outer space|cosmos|milky way|star cluster|lunar|moon|apollo)\b", re.I)
STOP = {"with", "from", "that", "this", "they", "their", "there", "were", "what", "when", "where", "which", "while",
        "into", "over", "under", "after", "before", "about", "than", "then", "them", "very", "just", "only", "also",
        "photo", "image", "picture", "footage", "video", "real", "actual", "shot", "scene", "view", "close", "closeup"}


def _keywords(query: str) -> set[str]:
    return {w[:6] for w in re.findall(r"[a-z]{4,}", (query or "").lower()) if w not in STOP}


def _lexical_ok(query: str, text: str) -> bool:
    """At least one real keyword of the search query appears in the clip/photo's own text (no query words = ok)."""
    keys = _keywords(query)
    if not keys:
        return True
    words = {w[:6] for w in re.findall(r"[a-z]{4,}", (text or "").lower())}
    return bool(keys & words)


BRANDED = re.compile(r"amazon prime|prime video|netflix|disney\+?|hbo max|\bhulu\b|paramount\+|apple tv|"
                     r"\bai[- ]generated\b|midjourney|stable diffusion|dall-?e", re.I)


NO_FACES = {"clutch_tales", "cricket_ke_kisse"}     # sports spec: no recognisable real faces (likeness orders)


def _big_face(path) -> bool:
    """True when a picture shows a clear real face larger than 8% of its width (YuNet, already used for clips)."""
    try:
        import cv2
        from .clips import _detector
        img = cv2.imread(str(path))
        if img is None:
            return False
        h, w = img.shape[:2]
        k = 640 / max(h, w)
        small = cv2.resize(img, (max(1, int(w * k)), max(1, int(h * k))))
        det = _detector(small.shape[1], small.shape[0])
        _, faces = det.detect(small)
        return faces is not None and any(f[2] > 0.08 * small.shape[1] for f in faces)
    except Exception:  # noqa: BLE001 - no detector: keep the picture
        return False


YEAR = re.compile(r"(?<!\d)(1[6-9]\d\d|20[0-3]\d)(?!\d)")
EVENTISH = re.compile(r"fire|disaster|explosion|explod|census|election|war\b|battle|accident|crash|flood|storm|"
                      r"hurricane|earthquake|tsunami|riot|protest|match|game|final|olympic|cup\b|championship|"
                      r"ceremony|funeral|launch|wreck|sinking|attack|newspaper|report|record", re.I)
_STORY_YEARS: set[int] = set()                     # years named in the current script (set by render)


def _year_ok(text: str, scene_text: str) -> bool:
    """A picture whose title names years is only used if one of them is within 10 years of a year the story names
    (or of a year this beat names)."""
    years = {int(y) for y in YEAR.findall(text or "")}
    if not years or not EVENTISH.search(text or ""):   # a generic object photo (e.g. "Drill bits 2017") is timeless
        return True
    ok = _STORY_YEARS | {int(y) for y in YEAR.findall(scene_text or "")}
    return any(abs(y - k) <= 10 for y in years for k in ok)


STUDIO = re.compile(r"focus features|universal pictures|warner bros|paramount pictures|sony pictures|columbia pictures|"
                    r"20th century|walt disney|pixar|\bmarvel\b|lionsgate|\ba24\b|netflix|yash raj|dharma productions|"
                    r"t-series|red chillies|\beros (international|now)\b", re.I)
POSTER = re.compile(r"\b(poster|key art|teaser|one-sheet|film still|screenshot|movie still|promotional)\b", re.I)


def _studio_art(text: str) -> bool:
    """Movie spec: no studio posters, stills or logos (a 2024 'Nosferatu' teaser poster slipped in as 'public domain').
    Posters/stills are fine only when the title dates them to 1930 or earlier (US public domain)."""
    if STUDIO.search(text or ""):
        return True
    if POSTER.search(text or ""):
        years = [int(y) for y in YEAR.findall(text or "")]
        return not years or min(years) > 1930
    return False


def _subject_names(script: dict) -> list[str]:
    """Proper names in the search phrase ("Nosferatu", "Lake Peigneur"): the opening shot must show one of them."""
    phrase = str(script.get("search_phrase") or "")
    return [w for w in re.findall(r"\b[A-Z][\w'-]{2,}", phrase)
            if w.lower() not in {"the", "why", "how", "what", "who", "when", "usa", "us"}][:3]


def _pick_photo(cands: list, scene_text: str, used: set, min_score: float, must: str = ""):
    """Best-matching unused photo above min_score; downloads only the winner (tries the next on failure).
    must = the beat's search query: the photo's own text must share a real keyword with it."""
    cands = [c for c in cands if str(c.path) not in used]
    cands = [c for c in cands if not NUDITY.search(f"{c.meta.get('text', '')} {c.credit}")]   # never nude art
    # movie spec: no studio/streaming posters or stills; never someone else's AI images (ours are labelled)
    cands = [c for c in cands if not BRANDED.search(f"{c.meta.get('text', '')} {c.credit}")]
    cands = [c for c in cands if not _studio_art(f"{c.meta.get('text', '')} {c.credit}")]
    if _STORY_YEARS:                               # accuracy: no photo labelled with a far-off year (a 2010 rig fire and a
        cands = [c for c in cands if _year_ok(f"{c.meta.get('text', '')} {c.credit}", scene_text)]   # 1940 census page
                                                   # once illustrated a 1980 story)
    if not SPACE.search(scene_text):
        cands = [c for c in cands if not SPACE.search(c.meta.get("text", "") or c.credit or "")]
    if must:
        cands = [c for c in cands if _lexical_ok(must, c.meta.get("text", "") or c.credit)]
    # sensitive political figures / symbols only when this scene is actually about them
    cands = [c for c in cands if not any(w in (c.meta.get("text", "") or "").lower() and w not in scene_text.lower()
                                         for w in SENSITIVE)]
    # officials / politicians / press events only when the scene names that person: showing a real person next to
    # a story they weren't part of is misleading (and political)
    cands = [c for c in cands if not (OFFICIAL.search(c.meta.get("text", "") or "")
                                      and not _shares_name(c.meta.get("text", "") or "", scene_text))]
    if not cands:
        return None
    emb = visuals._embedder()
    q = emb.encode([scene_text], is_query=True)[0]
    scores = emb.encode([c.meta.get("text", c.credit) for c in cands]) @ q
    for idx in np.argsort(-scores)[:3]:
        if scores[idx] < min_score:
            break
        c = cands[int(idx)]
        if visuals.fetch(c):
            used.add(str(c.path))
            # Old archive photos look dated full-screen: show them as framed "evidence" cards instead
            return {"kind": "image", "path": c.path, "frame": "card" if c.source == "wikimedia" else "full",
                    "credit": c.credit, "source": c.source, "match": round(float(scores[idx]), 3)}
    return None


PROMPT_WORDS = {"The", "A", "An", "In", "On", "At", "Of", "With", "And", "Cinematic", "Photorealistic", "Indian",
                "Ancient", "Divine", "Golden", "Close", "Wide", "No", "Text", "Dramatic", "Epic", "Scene", "Portrait",
                "Painting", "Oil", "Classical", "Warm", "Light", "Lighting", "Style", "Detailed", "Highly", "Vertical"}


def _chart_visual(beat: dict, seconds: float, work: Path, i: int, used: set, size: tuple[int, int],
                  channel: dict | None, log=print, said: str = "") -> dict | None:
    """An animated chart drawn by our own code (html_scene): one per video. Every number on it must be spoken in
    this beat or the two before it (`said`), so the screen never shows a number the viewer didn't hear."""
    from .media import html_scene
    if channel is None or "chart:done" in used:
        return None
    chart, why = html_scene.check_chart(beat.get("chart"), said or beat.get("narration", ""))
    if not chart:
        log(f"  beat {i + 1}: chart skipped ({why}); using a picture")
        return None
    try:
        path = html_scene.chart_video(channel, chart, size, seconds + 0.6, work / f"chart_{i:02d}.mp4")
    except Exception as e:  # noqa: BLE001 - a missing browser must not stop the video
        log(f"  beat {i + 1}: chart recording failed ({e}); using a picture")
        return None
    used.add("chart:done")
    return {"kind": "video", "path": path, "frame": "full", "credit": "", "source": "chart", "graphic": True,
            "match": 1.0}


_SEE_STOP = {"a", "an", "the", "of", "in", "on", "at", "with", "and", "or", "to", "from", "by", "for", "is", "are", "his",
             "her", "their", "its", "close", "up", "close-up", "shot", "wide", "view", "scene", "showing", "shows", "while",
             "as", "into", "over", "under", "behind", "front", "background", "foreground", "dramatic", "cinematic"}


def _see_query(see: str, words: int = 4) -> str:
    """A storyboard scene description ("A diver's torch lights a huge octopus in the dark") -> stock-library keywords
    ("diver torch lights huge"), used when the beat has no search query (19 Nov: AI pictures ran out, library empty)."""
    toks = [w for w in re.findall(r"[A-Za-z][A-Za-z'-]+", see or "") if w.lower() not in _SEE_STOP and len(w) > 2]
    return " ".join(re.sub(r"'s$", "", w).lower() for w in toks[:words])   # only a possessive 's goes


def find_beat_visual(beat: dict, seconds: float, palette: list[str], work: Path, i: int, language: str,
                     mood: str, used: set, size: tuple[int, int], log=print, pool: list | None = None,
                     paintings: str = "", painting_context: str = "", era: str = "", channel: dict | None = None,
                     said: str = "") -> dict:
    """Returns {"kind": image|video|text|reuse, "path", "frame": full|card, "credit", "source"}."""
    kind = beat.get("visual", "photo")
    if beat.get("_prompt") and kind in ("scene", "photo", "ai", "footage"):
        from . import storyboard
        era_text = beat.get("_era", "")
        if kind == "scene":                        # drawn + checked shot of exactly this moment
            got = storyboard.scene(beat, era_text, size, log, i, tries=3 if size[1] > size[0] else 2)   # long: lighter
            if got:
                return got
            kind = "photo"                         # no free picture left today: the library search (checked below)
    if kind == "chart":
        got = _chart_visual(beat, seconds, work, i, used, size, channel, log, said=said)
        if got:
            return got
        kind = "photo"                             # checks failed: the backup photo query
    query = beat.get("query") or _see_query(beat.get("see", "")) or beat.get("narration", "")[:60]
    scene_text = f"{query}. {beat.get('narration', '')}"
    if era == "space":                             # space channel: space pictures always fit
        scene_text = f"space. {scene_text}"
    orientation = "portrait" if size[1] > size[0] else "landscape"

    def try_ai():
        v = visuals.ai_image(beat.get("ai_prompt") or f"{query}, {beat.get('narration', '')[:120]}", mood)
        return {"kind": "image", "path": v.path, "frame": "full", "credit": v.credit, "source": v.source} if v else None

    def try_footage(min_score=0.80):
        items = [f for f in _cached("footage" + orientation, query, lambda: footage.search(query, orientation))
                 if f.url not in used]
        items = [f for f in items if _lexical_ok(query, f.text)]      # a real keyword match, not just "similar"
        # archive.org items are whole films: a word in the long description doesn't mean the random segment shows it
        # ("Progress Parade" came up for "drill pipe" and showed a baby). The keyword must be in the film's title.
        items = [f for f in items if f.source != "internet_archive" or _lexical_ok(query, f.title)]
        if language == "hi":                       # archive.org is mostly US/Europe: Indian stories need Indian footage
            items = [f for f in items if f.source != "internet_archive" or INDIA.search(f.text or "")]
        if not SPACE.search(scene_text):          # NASA's library only for space scenes (it gave a hockey video
            items = [f for f in items if f.source != "nasa" and not SPACE.search(f.text or "")]   # NASA clips)
        idx, score = _match(items, [f.text for f in items], scene_text)
        if idx < 0 or score < min_score:
            return None
        f = items[idx]
        used.add(f.url)                       # mark even on failure so a broken file isn't retried
        seg = footage.fetch_segment(f, seconds + 0.6)
        if not seg:
            return None
        old = f.source == "internet_archive"
        return {"kind": "video", "path": seg, "frame": "card" if old else "full", "credit": f.credit,
                "source": f.source, "match": round(score, 3), "auto_label": "ARCHIVE FOOTAGE" if old else ""}

    def try_photo():
        cands = _photo_candidates(query)
        if era == "ancient":                       # temples, sculptures, manuscripts yes; modern people/scenes no
            cands = [c for c in cands if not MODERN.search((c.meta or {}).get("text") or c.credit or "")]
            # mythology spec (anachronism QA): no modern stock photos, and the picture must be Indian (a European
            # suit of armour once stood in for Karna's kavach)
            cands = [c for c in cands if getattr(c, "source", "") not in ("pexels", "pixabay")
                     and (INDIA.search((c.meta or {}).get("text") or c.credit or "")
                          or (painting_context and re.search(painting_context, (c.meta or {}).get("text") or "", re.I)))]
        return _pick_photo(cands, scene_text, used, 0.78, must=query)

    def try_pool():
        got = _pick_photo(pool or [], scene_text, used, 0.79, must=query)
        return dict(got, from_pool=True) if got else None

    def try_paintings():
        """Public-domain classical paintings of the characters in this beat (e.g. Raja Ravi Varma, d. 1906)."""
        if not paintings:
            return None
        src = f"{beat.get('ai_prompt', '')} {beat.get('query', '')}"
        names = [w for w in dict.fromkeys(re.findall(r"\b[A-Z][a-z]{2,}\b", src)) if w not in PROMPT_WORDS][:2]
        if not names:
            return None
        for q in ([f"{paintings} {n}" for n in names] + [f"{n} painting" for n in names])[:4]:
            # accuracy first: the painting's own title/description must name a character of this beat
            cands = [v for v in _photo_candidates(q)
                     if any(re.search(rf"(?<![a-z]){n.lower()}(?![a-z])", ((v.meta or {}).get("text") or "").lower())
                            for n in names)
                     and (not painting_context or re.search(painting_context, (v.meta or {}).get("text") or "", re.I))]
            got = _pick_photo(cands, scene_text, used, 0.76)
            if got:
                return dict(got, source="painting")
        return None

    if kind == "text":
        return {"kind": "text", "path": None, "frame": "full", "credit": "", "source": "text"}
    order = {"ai": [try_ai, try_paintings, try_footage, try_photo], "footage": [try_footage, try_ai, try_photo],
             "photo": [try_photo, try_paintings, try_ai, try_footage]}.get(kind, [try_photo, try_ai, try_footage]) + [try_pool]
    if era == "ancient" and paintings:            # characters: a classical painting beats any photo
        order = [try_paintings] + [f for f in order if f is not try_paintings]
    if era == "ancient":                           # stock footage is modern (a pier with lightning played "Indra")
        order = [f for f in order if f is not try_footage]
    for fn in order:
        try:
            got = fn()
        except Exception as e:      # one bad source must not stop the video
            log(f"  visual source error ({fn.__name__}): {e}")
            got = None
        if got and beat.get("_prompt") and not got.get("graphic") and got.get("source") != "chart":
            from . import storyboard
            if not storyboard.check_photo(got, beat, beat.get("_era", "")):
                log(f"  beat {i + 1}: {got.get('source')} picture doesn't show this moment; next source")
                used.add(str(got.get("path")))
                continue
        if got:
            return got
    if beat.get("_prompt") and beat.get("visual") != "scene":   # a real photo was wanted but none fits: draw it
        from . import storyboard
        got = storyboard.scene(beat, beat.get("_era", ""), size, log, i)
        if got:
            return got
    return {"kind": "reuse", "path": None, "frame": "full", "credit": "", "source": "reuse"}


# ---------- sound ----------
SFX_BANK = {"whoosh": lambda k: sfx.whoosh(seed=k), "impact": lambda k: sfx.impact(),
            "bass_drop": lambda k: sfx.bass_drop(), "pop": lambda k: sfx.pop(pitch=800 + 120 * (k % 4)),
            "tick": lambda k: sfx.tick(), "ding": lambda k: sfx.ding(), "riser": lambda k: sfx.riser(),
            "conch": lambda k: sfx.conch(), "bell": lambda k: sfx.bell(), "heartbeat": lambda k: sfx.heartbeat(),
            "crowd": lambda k: sfx.crowd(seed=k), "kaching": lambda k: sfx.kaching(), "shutter": lambda k: sfx.shutter(),
            "paper": lambda k: sfx.paper(), "typewriter": lambda k: sfx.typewriter(), "tape": lambda k: sfx.tape(),
            "impact_soft": lambda k: sfx.impact_soft(), "projector": lambda k: _em().projector(seed=k)}


def _em():
    from .media import emotion_music
    return emotion_music


def breath_after(text: str, base: float = 0.07) -> float:
    """Pause after a beat, from its last punctuation (how a narrator breathes): a full stop, question or shock gets a
    real breath; '…' a held moment; a comma or no punctuation (the sentence continues) barely any."""
    end = text.strip()[-1:] if text.strip() else ""
    if end in "…":
        return 0.45
    if end in "।.!?":
        return 0.3
    if end in ",;:-–—":
        return 0.12
    return max(base, 0.08)


def _process_voice(voice48: Path, reverb: bool = False, pitch: float = 0.0) -> Path:
    """Research (playbook §3, podcast spec): 80 Hz high-pass + light compression; mythology spec: small-hall reverb,
    8-12% wet."""
    out = voice48.with_name(voice48.stem + "_proc.wav")
    # owner 18 Nov (voice = what holds the audience): de-ess BEFORE compression and the presence lift (the lift would
    # sharpen the "s" sounds), then +2.5 dB wide at 3 kHz so the words cut through phone speakers and the music.
    chain = ("highpass=f=80,deesser=i=0.35:m=0.5:f=0.55,"
             "acompressor=threshold=-20dB:ratio=2.5:attack=8:release=120:makeup=1.5,"
             "equalizer=f=3000:t=q:w=0.9:g=2.5")
    if abs(pitch) > 0.05:                               # deeper narrator (mythology/mystery specs), same timing
        r = 2 ** (pitch / 12)
        chain = f"asetrate={int(48000 * r)},aresample=48000,atempo={1 / r:.5f}," + chain
    if reverb:
        chain += ",aecho=0.9:0.9:38|61|89:0.10|0.07|0.05"
    try:
        ffmpeg.run(["-i", str(voice48), "-af", chain, "-ar", "48000", str(out)])
        return out
    except Exception:                                   # never lose a render over voice polish
        return voice48


def switch_bed(bed: np.ndarray, second: Path | np.ndarray, at: float, sr: int, fade_in: float = 0.15,
               fade_out: float = 0.35) -> np.ndarray:
    """Music change at the climax (owner 18 Nov: "transition music"): the first track fades out just before `at`, the
    second (looped to the rest of the video, levelled to the same loudness) comes in on the hit. The silence drop
    before the climax and the impact SFX on it stay as they were, so the turn lands hard."""
    a = int(max(at, 0) * sr)
    if a <= 0 or a >= len(bed):
        return bed
    rest = len(bed) - a
    if isinstance(second, np.ndarray):
        b2 = second[:rest].astype(np.float32)
    else:
        from .media.music_library import bed as track_bed
        b2 = track_bed(second, rest / sr, sr=sr).astype(np.float32)
    if len(b2) < rest:
        b2 = np.pad(b2, (0, rest - len(b2)))
    r1 = float(np.sqrt(np.mean(bed[:a] ** 2))) or 1e-6
    r2 = float(np.sqrt(np.mean(b2 ** 2))) or 1e-6
    b2 = b2 * (r1 / r2) * 1.12                                   # a touch louder: the climax lifts
    out = bed.astype(np.float32).copy()
    fo = min(int(fade_out * sr), a)
    out[a - fo:a] *= np.linspace(1, 0, fo, dtype=np.float32)
    fi = min(int(fade_in * sr), rest)
    b2[:fi] *= np.linspace(0, 1, fi, dtype=np.float32)
    out[a:] = b2
    return out


def cut_on_beats(shots, labels, bigs, stick, events, quiet, ai_spans, music_file, total: float,
                 music_file2=None, switch_at=None, keep=None, sr: int = 22050, log=print, bed_audio=None):
    """Owner 18 Nov ("transition music ... creates the interest"): cuts land on the music's beat. The bed is built
    exactly as the mix builds it (same track, same loop, same climax switch), its beats are found in-house
    (media/beats.py), and each cut between two shots moves to a beat within +-0.15 s. The words never move (captions
    are word-timed); the climax cut stays on its line; labels, big texts, stickers and the cut sounds that sat on a
    moved cut move with it. Returns the updated lists."""
    import dataclasses
    from .media import beats as bt
    if bed_audio is None:
        from .media.music_library import bed as track_bed
        bed_audio = track_bed(music_file, total, sr=sr)
        if music_file2 is not None and switch_at:
            bed_audio = switch_bed(bed_audio, music_file2, switch_at, sr)
    grid = bt.beat_times(bed_audio, sr)
    cuts = [shots[k].start for k in range(1, len(shots)) if abs(shots[k - 1].end - shots[k].start) < 1e-3]
    moved = bt.snap_cuts(cuts, grid, keep=keep or [])
    if not moved:
        log(f"Beat sync: {len(grid)} beats, no cut needed moving" if grid else "Beat sync: no steady beat in this track")
        return shots, labels, bigs, stick, events, quiet, ai_spans
    out = list(shots)
    for k in range(1, len(out)):
        old = out[k].start
        if old in moved and abs(out[k - 1].end - old) < 1e-3:
            d = moved[old] - old
            out[k - 1] = dataclasses.replace(out[k - 1], end=moved[old])
            off = getattr(out[k], "offset", 0.0)
            out[k] = dataclasses.replace(out[k], start=moved[old], offset=max(0.0, off + d) if off else off)
    rm = lambda t: bt.remap(t, moved)                                   # noqa: E731
    labels = [dataclasses.replace(x, start=rm(x.start), end=rm(x.end)) for x in labels]
    bigs = [dataclasses.replace(x, start=rm(x.start), end=rm(x.end)) for x in bigs]
    stick = [dataclasses.replace(x, start=rm(x.start), end=rm(x.end)) if hasattr(x, "start") else x for x in stick]
    events = [(max(0.0, rm(e[0])),) + tuple(e[1:]) for e in events]
    quiet = [(rm(a), rm(b)) for a, b in quiet]
    ai_spans = [(rm(a), rm(b)) for a, b in ai_spans]
    log(f"Beat sync: {len(moved)}/{len(cuts)} cuts moved onto the beat ({len(grid)} beats found)")
    return out, labels, bigs, stick, events, quiet, ai_spans


def button_end(bed: np.ndarray, voice: np.ndarray, sr: int, decay: float = 0.45) -> np.ndarray:
    """Editors end the music ON a beat (a "button"), not in a slow fade. The first beat after the last spoken word
    keeps its hit, then the music rings out over `decay` seconds and stops (videos end ~0.5 s after the last word).
    No steady beat (ambient bed) or no beat in reach: unchanged."""
    from .media import beats as bt
    n = len(bed)
    if n < sr * 4:
        return bed
    act = np.flatnonzero(np.abs(voice[:n]) > 0.01)
    v_end = (act[-1] / sr) if len(act) else n / sr - 1.0
    grid = bt.beat_times(bed, sr)                        # the whole track: its tempo carries through the fade-out
    end = n / sr
    after = [b for b in grid if v_end - 0.05 <= b <= end - 0.12]   # never stop the music under a word
    hit = after[0] if after else None
    if hit is None:
        return bed
    out = bed.copy()
    h = int((hit + 0.06) * sr)                           # keep the hit's attack whole
    d = min(int(decay * sr), n - h)
    if d > 0:
        out[h:h + d] *= np.exp(-np.linspace(0, 6, d)).astype(out.dtype)
    out[h + max(d, 0):] = 0.0
    return out


def _mix(voice48: Path, events: list[tuple[float, str, float]], music_mood: str, out: Path, seed: int = 0,
         mix: dict | None = None, swells: list[tuple[float, float]] | None = None,
         drops: list[float] | None = None, reverb: bool = False, pitch: float = 0.0,
         music_file: Path | None = None, music_file2: Path | None = None, switch_at: float | None = None) -> Path:
    """events = (time, sound, level in dB relative to the voice). mix = per-niche bed level and ducking (MIX).
    Hindi palettes (devotional / dhol / retro) get an emotional score that follows the story: it builds, falls
    silent before the climax (drops[0]) and hits on it and on each reveal (swells)."""
    mx = dict(MIX_DEFAULT, **(mix or {}))
    voice, sr = sf.read(_process_voice(voice48, reverb, pitch), dtype="float32")
    if voice.ndim == 1:
        voice = np.column_stack([voice, voice])
    total = voice.copy()
    n = len(total)
    v_mono = voice.mean(axis=1)
    active = np.abs(v_mono) > 0.01
    v_rms = float(np.sqrt(np.mean(v_mono[active] ** 2))) if np.any(active) else 0.1
    for k, (at, name, db) in enumerate(events):
        s0 = int(max(at, 0) * sr)
        if s0 >= n or name not in SFX_BANK:
            continue
        snd = SFX_BANK[name](k).astype(np.float32)
        loud = np.abs(snd) > 0.02 * (np.abs(snd).max() + 1e-9)
        s_rms = float(np.sqrt(np.mean(snd[loud] ** 2))) if np.any(loud) else 1e-6
        snd = snd * (v_rms / max(s_rms, 1e-6)) * 10 ** (db / 20)
        e = min(s0 + len(snd), n)
        total[s0:e] += snd[: e - s0, None]
    if music_mood:
        bed = None
        if music_file is not None and music_mood not in _em().PALETTES:   # a real track that fits this video
            try:
                from .media.music_library import bed as track_bed
                bed = track_bed(music_file, n / sr, sr=sr).astype(np.float32)
            except Exception:  # noqa: BLE001 - never fail a video over music: the synthesised bed instead
                bed = None
        if bed is not None:
            if music_file2 is not None and switch_at:      # the climax turns to its own, stronger track
                bed = switch_bed(bed, music_file2, switch_at, sr)
        elif music_mood in _em().PALETTES:
            bed = _em().score(n / sr, music_mood, climax=(drops or [None])[0],
                              reveals=[a for a, _ in (swells or [])], seed=seed).astype(np.float32)
        else:
            bed = sfx.music_bed(n / sr, music_mood, seed=seed)
        b_rms = float(np.sqrt(np.mean(bed ** 2))) or 1e-6
        bed = bed * (v_rms / b_rms) * 10 ** (mx["bed_db"] / 20)
        bed = sfx.duck_db(bed, voice, db=mx["duck_db"], attack=mx["attack"], release=mx["release"])
        if mx.get("carve_db", 4.0) > 0:            # dynamic EQ: the speech band of the music steps aside for the words
            bed = sfx.carve_mid(bed, voice, db=mx.get("carve_db", 4.0), attack=mx["attack"], release=mx["release"])
        if music_file is not None and mx.get("button", True):   # the music's last hit lands right after the last word
            bed = button_end(bed, v_mono, sr)
        if mx.get("swell_db") and swells:              # mystery: +4 dB on the "But" reversal and the payoff
            g = np.ones(len(bed), np.float32)
            for t0, t1 in swells:
                a, b = int(t0 * sr), min(int(t1 * sr), len(bed))
                if b > a:
                    ramp = np.minimum(1, np.minimum(np.arange(b - a), np.arange(b - a)[::-1]) / (0.25 * sr))
                    g[a:b] = 10 ** (mx["swell_db"] * ramp / 20)
            bed = bed * g
        if mx.get("drop") and drops and music_mood not in _em().PALETTES:   # (emotional scores make their own)
            for t in drops:
                a, b = int(max(t - mx["drop"], 0) * sr), int(t * sr)
                fade = int(0.05 * sr)
                bed[a:b] = 0.0
                if a > fade:
                    bed[a - fade:a] *= np.linspace(1, 0, fade)
        total[: len(bed)] += bed[:, None]
    peak = np.abs(total).max()
    if peak > 0.98:
        total *= 0.98 / peak
    raw = out.with_name(out.stem + "_raw.wav")
    sf.write(raw, total, sr)
    from .snack.encode import _loudness           # two-pass loudness: -14 LUFS integrated, true peak -1 dBTP
    m = _loudness(raw)
    if m and m.get("input_i") not in (None, "-inf"):
        af = ("loudnorm=I=-14:TP=-1.5:LRA=11:linear=true:"
              f"measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}:"
              f"measured_thresh={m['input_thresh']}:offset={m['target_offset']}" + ",alimiter=limit=0.83:attack=5:release=50:level=false")
        ffmpeg.run(["-i", str(raw), "-af", af, "-ar", str(sr), str(out)])
    else:
        raw.replace(out)
    return out


DOCUMENT_HINT = re.compile(r"newspaper|herald|times|gazette|tribune|journal|article|letter|page|document|manuscript|"
                           r"map|scan|diagram|chart|engraving|telegram|certificate|record|census|report|notice",
                           re.I)


HANGING = {"to", "a", "an", "the", "of", "and", "or", "in", "on", "for", "with", "at", "by", "from", "is", "was",
           "his", "her", "their", "its", "that", "who", "into", "onto", "about", "over", "under", "after", "before",
           "as", "than", "but", "so", "are", "were", "be", "has", "have", "had", "my", "your", "our", "will",
           "would", "can", "could", "not", "very", "every", "each", "all", "more", "most", "just", "ko", "ki", "ka", "ke", "ne", "se", "mein", "aur", "par", "bhi"}
YT_ONLY_TAGS = {"#shorts", "#short", "#youtubeshorts", "#ytshorts", "#shortsfeed", "#shortvideo"}


def _alt_hook(script: dict) -> str:
    """A different on-screen hook for the Instagram Reel (from the writer's other titles), max 8 words."""
    hook = (script.get("hook_text") or "").strip()
    cands = []
    for cand in (script.get("title_options") or []) + [script.get("title") or ""]:
        c = re.sub(r"[#@]\S+|[\U0001F000-\U0001FAFF☀-➿]", "", cand or "").strip(" -|:")
        if c.split() and c.lower() != hook.lower():
            cands.append(c)
    for c in cands:                                   # prefer a whole title that already fits
        if len(c.split()) <= 8:
            return c
    for c in cands:                                   # else cut, but never end on "to / the / of ..."
        words = c.split()[:8]
        while words and words[-1].lower() in HANGING:
            words.pop()
        if len(words) >= 3:
            return " ".join(words)
    return hook


def _chart_like(path) -> bool:
    """Charts, graphs, documents and diagrams: mostly white/flat with thin dark lines. Never a thumbnail hero."""
    try:
        import cv2
        img = cv2.imread(str(path))
        if img is None:
            return True
        img = cv2.resize(img, (240, int(240 * img.shape[0] / max(1, img.shape[1]))))
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        white = ((hsv[..., 2] > 225) & (hsv[..., 1] < 25)).mean()
        dark_lines = (hsv[..., 2] < 90).mean()
        edges = (cv2.Canny(img, 80, 160) > 0).mean()
        return bool(white > 0.45 and 0.005 < dark_lines < 0.2 and edges > 0.03)
    except Exception:  # noqa: BLE001
        return False


NUDITY = re.compile(r"\b(nude|nudes|naked|nudity|nymphs?|bathers|erotic|topless|undress\w*|"
                    r"odalisque|sensual|lingerie|bikini|harem)\b", re.I)


CHART_WORDS = re.compile(r"\b(chart|graph|plot|diagram|figure|fig\.|density|curve|axis|dataset|statistic|table|"
                         r"infographic|schematic|cross[- ]section|kg/m|psi|bar\b)", re.I)


def rank_heroes(script: dict) -> list[Path]:
    """Picture candidates for thumbnails and covers, best first: real photos (no text cards, charts or documents),
    sharp ones first, then the ones most about the video's main subject."""
    thumb = script.get("thumbnail", {}) or {}
    cands, texts, named, opening, credits_ = [], [], [], [], []
    for bi, b in enumerate(script.get("beats", [])):
        vis = b.get("_visual", {})
        path = vis.get("path")
        if vis.get("kind") != "image" or not path or not Path(path).exists() or "graphic_" in Path(path).name:
            continue
        meta = f"{vis.get('credit', '')} {vis.get('text', '')} {b.get('query', '')}"
        if Path(path) in cands or CHART_WORDS.search(meta) or NUDITY.search(meta) or _chart_like(path):
            continue
        cands.append(Path(path))
        texts.append(f"{b.get('query', '')} {b.get('label', '')} {b.get('narration', '')}")
        named.append(f"{vis.get('credit', '')} {b.get('narration', '')}")
        credits_.append(str(vis.get("credit", "")))
        opening.append(bi < 2)
    if len(cands) <= 1:
        return cands
    from PIL import Image
    idea = f"{thumb.get('subject_prompt', '')} {script.get('title', '')} {script.get('hook_text', '')}"
    emb = visuals._embedder()
    scores = emb.encode(texts) @ emb.encode([idea], is_query=True)[0]
    sharp = [min(Image.open(c).size) >= 650 for c in cands]
    # the thumbnail must show the real subject: pictures whose own title (or beat) names it win (a big steamship
    # photo once beat the actual Mary Celeste painting because the beat text scored higher)
    subject = script.get("search_phrase") or script.get("title") or ""
    names = [w.lower() for w in re.findall(r"\b[A-Z][\w'-]+", subject) if w.lower() not in {"the", "a", "an", "why", "how", "what"}]
    boost = [0.25 if names and all(n in t.lower() for n in names) else 0.0 for t in named]
    scores = scores + np.array(boost, dtype=np.float32) + np.array([0.15 if o else 0.0 for o in opening], np.float32)
    credit_named = [bool(names) and all(n in c.lower() for n in names) for c in credits_]
    ranked = sorted(zip(sharp, scores.tolist(), cands, boost, credit_named), key=lambda t: (t[0], t[1]), reverse=True)
    script["_named_heroes"] = [str(r[2]) for r in ranked if r[3] > 0]
    # V3 may switch to another picture only if that picture's own title names the subject; otherwise it shows the
    # same subject with another framing (accuracy beats variety)
    script["_v3_ok"] = len(ranked) > 1 and ranked[1][4]
    return [r[2] for r in ranked]


def _write_reel_extras(channel: dict, script: dict, out_dir: Path, reel_hook: str | None, beats: list) -> None:
    """reel_cover.jpg (3:4-grid safe) + reel.json (caption with at most 5 hashtags, Trial Reel suggestion)."""
    from .media.thumbs_v4 import cover_for
    from PIL import Image
    imgs = rank_heroes(dict(script, beats=beats))                 # same hero choice as the thumbnails
    try:
        if imgs:
            cover_for(channel, Image.open(imgs[0]).convert("RGB"), reel_hook or script.get("hook_text", ""),
                      out_dir / "reel_cover.jpg")
    except Exception:  # noqa: BLE001 - a cover problem must not lose the finished Reel
        pass
    tags = [t if t.startswith("#") else f"#{t}" for t in (script.get("hashtags") or []) + channel.get("hashtags", [])]
    tags = [t for t in dict.fromkeys(tags) if t.lower() not in YT_ONLY_TAGS][:5]   # Instagram: max 5, no #shorts
    caption = (script.get("instagram_caption") or script.get("summary") or "").strip()
    reel = {"platform": "instagram_reels", "file": "reel.mp4", "cover": "reel_cover.jpg", "hook": reel_hook,
            "alt_text": script.get("alt_text", ""),
            "caption": f"{caption}\n\n{' '.join(tags)}".strip(), "hashtags": tags, "trial_reel_suggested": True,
            "note": "Same frames as the YouTube Short, different hook wording and a shorter ending (never byte-identical)."}
    (out_dir / "reel.json").write_text(json.dumps(reel, indent=2, ensure_ascii=False), encoding="utf-8")


def _v3_frame(vis: dict) -> str:
    """Full-screen 3D-photo motion for real scenes; framed card for documents, scans and tiny or odd images."""
    text = f"{vis.get('source', '')} {vis.get('credit', '')} {vis.get('path', '')}"
    try:
        w, h = _image_size(vis["path"])
    except Exception:  # noqa: BLE001
        return vis.get("frame", "card")
    if DOCUMENT_HINT.search(text) or min(w, h) < 650 or w / max(h, 1) > 2.3 or h / max(w, 1) > 2.6:
        return "card"
    return "parallax"


def render(channel: dict, script: dict, out_dir: Path, fmt: str = "short", log=print) -> dict:
    script = normalize_script(script)
    f = FORMATS[fmt]
    size = f["size"]
    out_dir.mkdir(parents=True, exist_ok=True)
    work = out_dir / "work"
    work.mkdir(exist_ok=True)
    ensure_fonts()
    lang = channel["language"]
    voice = channel["voice"]
    style = channel.get("style", {})
    kind = "history" if channel["id"] == "itihaas_ke_raaz" else "story"
    look, look_cfg = channel_look(channel, size)
    beats = [b for b in script["beats"] if b.get("narration", "").strip()]
    v3 = style.get("renderer", "v3") != "v2"
    _STORY_YEARS.clear()
    _STORY_YEARS.update(int(y) for b in beats for y in YEAR.findall(b.get("narration", "")))       # v3 = 2026 look; set renderer: v2 in a channel to compare

    # 1. Voice per beat, silence trimmed for a tight pace
    log(f"Voice: {len(beats)} beats with Kokoro ({voice['id']})")
    parts, durations = [], []
    speed = voice.get("speed", 1.1)
    if fmt == "long":                                    # long videos: a calmer, more natural read
        speed = voice.get("long_speed", min(speed, 1.0))
    pz = {"base": 0.07, "after_reveal": 0.22, "before_reveal": 0.0, "after_question": 0.0, **(voice.get("pauses") or {})}
    target_wpm = (channel.get("spec") or {}).get("long_wpm" if fmt == "long" else "short_wpm")
    emo_raw = None                                       # emotional Hindi voice (opt-in per channel, Kokoro fallback)
    if voice.get("engine") == "emotional" and lang == "hi" and (fmt == "short" or voice.get("emotional_long")):
        try:
            from .media import emotional_voice
            emo_raw = emotional_voice.batch(beats, work, lang, log)
            if voice.get("emotional_speed"):             # Chatterbox's own pace is the reference (1.0)
                speed = float(voice["emotional_speed"])
            else:
                speed = 1.0
        except Exception as e:  # noqa: BLE001 - never lose a video over the voice
            log(f"  emotional voice unavailable ({str(e)[:160]}); using Kokoro")
            emo_raw = None

    from .media import google_voice
    use_google = (not emo_raw and lang == "hi" and voice.get("engine") != "kokoro_only" and google_voice.available())
    google_failed = []
    if use_google:                                       # try the first line before committing the whole video
        try:
            from .media.say import normalise
            google_voice.synthesize(normalise(beats[0]["narration"], lang, engine="google"), work / "gtest.wav",
                                    google_voice.voice_for(channel))
            log(f"  voice: Google Chirp 3 HD ({google_voice.voice_for(channel)}), natural Hindi")
        except Exception as e:  # noqa: BLE001
            log(f"  Google voice unavailable ({str(e)[:120]}); using Kokoro")
            use_google = False

    parler_raw = None                                    # free Indic Parler-TTS (owner: "no card")
    if not emo_raw and not use_google and lang == "hi" and voice.get("engine") != "kokoro_only":
        from .media import parler_voice
        if parler_voice.available():
            try:
                parler_raw = parler_voice.batch(beats, work, channel, log)
                speed = float(voice.get("parler_speed", 1.0))
            except Exception as e:  # noqa: BLE001 - never lose a video over the voice
                log(f"  Indic Parler-TTS unavailable ({str(e)[:160]}); using Kokoro")
                parler_raw = None

    def read(k: int, b: dict, path: Path, spd: float, pause: float) -> float:
        if parler_raw:
            from .media import parler_voice
            return parler_voice.line(parler_raw[k], path, spd, pause)
        if emo_raw:
            from .media import emotional_voice
            return emotional_voice.line(emo_raw[k], path, spd, pause)
        if use_google and not google_failed:
            try:
                from .media.say import normalise
                google_voice.synthesize(normalise(b["narration"], lang, engine="google"), path,
                                        google_voice.voice_for(channel), speed=spd)
                a, sr_ = sf.read(path, dtype="float32")
                if pause:
                    a = np.concatenate([a, np.zeros(int(sr_ * pause), dtype=np.float32)])
                sf.write(path, a, sr_)
                return len(a) / sr_
            except Exception as e:  # noqa: BLE001 - rare after the first-line test: Kokoro for this line
                google_failed.append(str(e))
                log(f"  Google voice failed on beat {k + 1} ({str(e)[:120]}); Kokoro for this line")
        return synthesize(b["narration"], path, voice["id"], lang, speed=spd, pause_s=pause, trim=True)
    if target_wpm:                                       # calibrate on a few beats, then read everything at that speed
        sample = beats[:min(8, len(beats))]
        secs = sum(read(i, b, work / f"cal_{i:02d}.wav", speed, 0.0) for i, b in enumerate(sample))
        n_words = sum(len(b["narration"].split()) for b in sample)
        secs += pz["base"] * len(sample) + 0.04 * len(sample)   # the real read adds a pause after every beat
        measured = n_words / max(secs, 0.1) * 60
        new = float(np.clip(speed * target_wpm / max(measured, 1), 0.9, 1.12))    # never rushed or dragged
        log(f"  pace: {measured:.0f} wpm at speed {speed:.2f} -> speed {new:.2f} for {target_wpm} wpm (research target)")
        speed = new
    for attempt in range(2):
        parts, durations = [], []
        for i, b in enumerate(beats):
            wav = work / f"voice_{i:02d}.wav"
            big = ("reveal", "twist")
            pause = breath_after(b["narration"], pz["base"])                # follows the punctuation
            if b.get("moment") in big:
                pause = max(pause, pz["after_reveal"])
            if i + 1 < len(beats) and beats[i + 1].get("moment") in big:
                pause = max(pause, pz["before_reveal"])                 # a breath before the big moment
            if i == 0 and b["narration"].strip().endswith("?"):
                pause = max(pause, pz["after_question"])                # let the opening question land
            # a human narrator slows down for the big moment and leans in on twists (flat, even pacing = "AI voice")
            beat_speed = speed * {"reveal": 0.97, "twist": 0.98}.get(b.get("moment", "normal"), 1.0)
            durations.append(read(i, b, wav, beat_speed, pause))
            parts.append(sf.read(wav, dtype="float32")[0])
        if not target_wpm or attempt:
            break
        words_all = sum(len(b["narration"].split()) for b in beats)
        real = words_all / max(0.15 + sum(durations) + 0.5, 0.1) * 60      # what the audit measures
        if abs(real / target_wpm - 1) <= 0.04:
            break
        new = float(np.clip(speed * target_wpm / real, 0.9, 1.12))      # 2nd pass: whole read measured (the 8-beat
        log(f"  pace check: whole read {real:.0f} wpm vs {target_wpm}; re-voicing at speed {new:.2f}")   # sample drifts)
        speed = new
    # real narrators breathe: a soft inhale at the end of the longer pauses (>= 0.25 s), 30 dB under the voice
    try:
        from .media.sfx import breath
        for k in range(len(parts) - 1):
            seg = parts[k]
            tail = 0
            while tail < len(seg) and abs(seg[len(seg) - 1 - tail]) < 0.003:
                tail += 1
            if tail >= int(0.25 * 24000) and k % 2 == 0:
                rms = float(np.sqrt(np.mean(seg[seg != 0] ** 2))) if np.any(seg) else 0.05
                br = breath(0.22, sr=24000) * rms * 10 ** (-30 / 20) / 0.1
                at = len(seg) - len(br) - int(0.04 * 24000)
                if at > 0:
                    seg = seg.copy()
                    seg[at:at + len(br)] += br.astype(seg.dtype)
                    parts[k] = seg
    except Exception:  # noqa: BLE001 - breaths are polish, never a failure
        pass
    lead_in = 0.15
    narration = work / "narration_24k.wav"
    sf.write(narration, np.concatenate([np.zeros(int(24000 * lead_in), np.float32)] + parts), 24000)
    starts = [lead_in + float(x) for x in np.cumsum([0.0] + durations[:-1])]
    total = lead_in + float(sum(durations)) + 0.5

    # 2. Word timings (Whisper listens; the script keeps the spelling)
    log("Captions: aligning words")
    heard = transcribe(narration, language=lang)
    words = align_script(" ".join(b["narration"] for b in beats), heard, total)
    beat_words, k = [], 0
    for b in beats:
        n = len(b["narration"].split())
        beat_words.append(words[k:k + n])
        k += n

    # 3. Visuals -> shots (split long beats so the picture changes every ~2.5 s)
    log("Visuals: AI images / footage / evidence photos")
    credits, used, shots, labels, bigs, stick, events = [], set(), [], [], [], [], []
    transitions = look_cfg["transitions"]
    moves = ["push_in", "pan_left", "push_in", "pan_right", "drift_up"]   # never pull out after a push in
    pal = dict(SFX_DEFAULT, **SFX_PALETTE.get(channel["id"], {}))
    spec = channel.get("spec") or {}
    # research (playbook §8, round0): mostly hard cuts; a whip on section changes (max 2 in a Short); ONE flash on the
    # biggest reveal; sports: tape-rewind into the backstory; mythology: a gold light-leak instead of a white flash
    moments = [b.get("moment", "normal") for b in beats]
    reveals = [k for k, m in enumerate(moments) if m == "reveal" and k > 0]
    twists = [k for k, m in enumerate(moments) if m == "twist" and k > 0]
    flash_i = reveals[-1] if reveals else (twists[-1] if twists else -1)
    if fmt == "short":
        whip_is = set([k for k in twists if k != flash_i][:2])
    else:                                          # long videos: a whip into each chapter (section change)
        whip_is = {k for k, b in enumerate(beats) if k > 0 and b.get("chapter")}
    rewind_i = 1 if (fmt == "short" and channel["id"] in ("clutch_tales", "cricket_ke_kisse") and len(beats) > 3) else -1
    big_trans = "leak" if channel["id"] == "itihaas_ke_raaz" else "flash"
    swells, drops, ai_spans, quiet, cut_n = [], [], [], [], 0
    hook_in_card = False

    def sfx_at(t, key, prio=1):                   # (time, sound, dB, priority) from this niche's palette
        hit = pal.get(key)
        if hit:
            events.append((t, hit[0], hit[1], prio))
    last_visual, found, reuse_count = None, [], {}
    shot_uses: dict[str, int] = {}                  # v3: how many shots each picture has filled (max 2)
    graphics_used, max_graphics = 0, max(2, round(0.3 * len(beats)))
    pool = topic_pool(script)
    for i, (b, st, d) in enumerate(zip(beats, starts, durations)):
        end = st + d if i + 1 < len(beats) else total
        t_beat = time.time()
        vis = None
        names0 = _subject_names(script) if (i == 0 and v3 and channel["id"] not in NO_FACES
                                            and b.get("shot", "real") == "real") else []
        if names0:
            # MrBeast/first-frame rule: the opening shot shows the named subject (a generic "old film reel" query
            # once opened a Nosferatu Short on a 1939 World's Fair reel). Search the names first; keep the result
            # only if the picture's own title names the subject.
            try0 = dict(b, query=" ".join(names0), visual="photo")
            got0 = find_beat_visual(try0, end - st, look.palette, work, i, lang, style.get("ai_style") or style.get("mood", ""),
                                    used, size, log, pool=pool, paintings=style.get("painting_search", ""),
                                    painting_context=style.get("painting_context", ""), era=style.get("visual_era", ""))
            key = max(names0, key=len)                 # the rarest name ("Peigneur", not "Lake")
            if got0.get("path") and key.lower() in str(got0.get("credit", "")).lower():
                vis = dict(got0, match=max(float(got0.get("match") or 0), 0.85))
                log(f"  beat 1: opening shot names the subject ({', '.join(names0)})")
        if vis is None:
            vis = find_beat_visual(b, end - st, look.palette, work, i, lang, style.get("ai_style") or style.get("mood", ""), used, size, log,
                                   pool=pool, paintings=style.get("painting_search", ""),
                                   painting_context=style.get("painting_context", ""), era=style.get("visual_era", ""),
                                   channel=channel, said=" ".join(x.get("narration", "") for x in beats[max(0, i - 2):i + 1]))
        if channel["id"] in NO_FACES and vis.get("kind") == "image" and vis.get("path") and _big_face(vis["path"]):
            log(f"  beat {i + 1}: picture shows a real person's face (sports rule: no likeness); replacing")
            vis = {"kind": "reuse"}
        if (vis["kind"] == "video" and not vis.get("graphic") and i < 3 and _too_plain(vis.get("path"), strict=True)):
            log(f"  beat {i + 1}: clip too dark/plain for the opening seconds; replacing")
            vis = {"kind": "reuse"}
        if vis["kind"] == "image" and not vis.get("graphic") and _too_plain(vis.get("path"), strict=(i == 0)):
            if i == 0:                             # the hook must be a strong, readable picture
                log(f"  beat 1: picture too plain for the hook (blank / white page / near-black); replacing")
                vis = {"kind": "reuse"}
            else:                                  # objects on white, diagrams, night shots: framed card, not full-bleed
                vis["force_card"] = True
        if vis["kind"] == "reuse":
            # Never hold one picture for more than a beat: show an older picture with a new crop,
            # or a big-text screen if the previous beat already reused something.
            older = [v for v in found if v.get("path") != (last_visual or {}).get("path")
                     and (not v3 or shot_uses.get(str(v.get("path")), 0) < 2)]
            if older and not (last_visual or {}).get("reused"):
                # least-used older picture; full screen only if it is sharp enough, else a new card crop
                pick = min(older, key=lambda v: (reuse_count.get(str(v.get("path")), 0), -older.index(v)))
                reuse_count[str(pick.get("path"))] = reuse_count.get(str(pick.get("path")), 0) + 1
                vis = dict(pick, crop_zoom=1.35, reused=True, auto_label="")
                sharp = pick["kind"] == "image" and min(_image_size(pick["path"])) >= 1000
                vis["frame"] = "full" if sharp and pick.get("frame") == "card" else "card"
            else:
                vis = {"kind": "text", "path": None, "frame": "full", "source": "text"}
        elif vis["kind"] in ("image", "video") and vis.get("source") != "chart":
            found.append(vis)                      # (a chart's numbers belong to its own beat: never reused)
        if v3 and vis["kind"] == "image" and graphics_used < max_graphics and not b.get("see"):
            key = str(vis.get("path"))
            weak_opener = i == 0 and (vis.get("from_pool") or vis.get("reused") or float(vis.get("match") or 0) < 0.82)
            if weak_opener or shot_uses.get(key, 0) >= 2:   # the first frame must be strong; no picture 3x
                vis = {"kind": "text", "path": None, "frame": "full", "source": "text"}
        if (v3 and vis["kind"] == "text" and b.get("visual") != "text" and graphics_used >= max_graphics
                and any(v["kind"] == "image" for v in found)):
            # graphics cap reached: a fresh crop of the least-used earlier picture beats another text card
            pick = min((v for v in found if v["kind"] == "image"), key=lambda v: shot_uses.get(str(v.get("path")), 0))
            if shot_uses.get(str(pick.get("path")), 0) < 2:
                vis = dict(pick, crop_zoom=1.3, reused=True, auto_label="")
        if v3 and vis["kind"] == "text":           # documentary graphic instead of a plain gradient slab
            graphics_used += 1
            from .media.graphics import text_graphic
            emph = [e for e in b.get("emphasis", []) if e]
            big = b.get("big_text") or " ".join(emph[:2]) or " ".join(b["narration"].split()[:3])
            from .media.graphics import STYLE_BY_CHANNEL, animated_text_graphic
            gstyle = (channel.get("style") or {}).get("graphics") or STYLE_BY_CHANNEL.get(channel["id"], "casefile")
            if i == 0 and fmt == "short" and script.get("hook_text"):
                # the opening card carries the hook itself (an overlaid 2-line hook collided with the card), so the
                # first frame is still picture + hook (MrBeast/first-frame rule) without two headlines
                big = script["hook_text"]
                hook_in_card = True
            anim = None
            try:                                   # numbers count up (motion), dates/words stay still
                anim = animated_text_graphic(channel, big, b.get("sub", ""), size, work / f"graphic_{i:02d}.mp4",
                                             seed=i) if big else None
            except Exception as e:  # noqa: BLE001 - fall back to the still card
                log(f"  counter animation failed, using a still card: {e}")
            # research cut pace (cricket 2-3 s, Bollywood 1.5 s): a card beat's 2nd shot is a DIFFERENT card design with
            # the same words, a real visual change (a 1.1x re-frame of the same card does not read as a cut)
            alt_style = {"scoreboard": "poster", "poster": "scoreboard", "casefile": "proof", "proof": "casefile",
                         "parchment": "poster"}.get(gstyle, "casefile")
            alt_png = None
            try:
                alt_png = text_graphic(dict(channel, style=dict(channel.get("style") or {}, graphics=alt_style)), big,
                                       b.get("sub", ""), size, work / f"graphic_{i:02d}_b.png", seed=i + 50) if big else None
            except Exception:  # noqa: BLE001 - the re-frame cut stays as the fallback
                alt_png = None
            prev_g = bool((last_visual or {}).get("graphic"))
            if anim:
                vis = {"kind": "video", "path": anim, "frame": "graphic", "source": "graphic", "graphic": True}
            else:
                gch = channel
                alt = (channel.get("style") or {}).get("graphics_alt")
                if alt and not re.search(r"\d", big or ""):    # numbers stay on the main card; words get the 2nd
                    gch = dict(channel, style=dict(channel.get("style") or {}, graphics=alt))   # design (variety)
                gpath = text_graphic(gch, big, b.get("sub", ""), size, work / f"graphic_{i:02d}.png", seed=i)
                vis = {"kind": "image", "path": gpath, "frame": "graphic", "source": "graphic", "graphic": True}
            if alt_png:
                vis["alt_path"] = alt_png
                if prev_g and vis["kind"] == "image" and not (last_visual or {}).get("alt_first"):
                    vis["path"], vis["alt_path"] = alt_png, vis["path"]        # the previous card used design A
                    vis["alt_first"] = True
            sfx_at(st, "card", 2)
        elif v3 and vis["kind"] == "image" and vis.get("path"):
            vis["frame"] = "card" if vis.get("force_card") else _v3_frame(vis)
        log(f"  beat {i + 1}/{len(beats)}: wanted {b.get('visual', 'photo')} -> {vis.get('source', vis['kind'])}"
            f" ({time.time() - t_beat:.0f}s)")
        if vis.get("credit") and not vis.get("reused"):
            credits.append(vis["credit"])
        b["_visual"] = {k2: str(v) for k2, v in vis.items() if k2 in ("kind", "source", "path", "frame", "match", "credit")}
        emph = {re.sub(r"[^\w]", "", e.lower()) for e in b.get("emphasis", []) if e}
        punch_times = [w.start for w in beat_words[i] if re.sub(r"[^\w]", "", w.text.lower()) in emph]
        moment = b.get("moment", "normal")
        if not v3:
            trans = "flash" if moment in ("reveal", "twist") else ("cut" if i == 0 else transitions[i % len(transitions)])
        elif i == 0:
            trans = "cut"
        elif i == flash_i:
            trans = big_trans
        elif i == rewind_i:
            trans = "rewind"
        elif i in whip_is:
            trans = "whip"
        else:
            trans = "cut"
        if trans == "zoom":                        # zoom-blur transition = a zoom in + zoom out between shots
            trans = "cut"
        shot_s = (spec.get("hook_shot_s", 1.3) if st < 10 else spec.get("shot_s", 2.6)) if fmt == "short" \
            else spec.get("long_shot_s", 3.5)
        n_sub = max(1, math.ceil((end - st) / (shot_s if v3 else 3.2)))
        if vis["kind"] == "video" and not vis.get("graphic"):
            n_sub = min(n_sub, 4) if v3 else 1     # a long clip is cut into re-framed parts (research cut pace)
        if vis.get("graphic"):                     # a graphic: re-frame cuts at the channel's pace (max 3)
            n_sub = max(1, min(3, round((end - st) / shot_s)))
            if channel["id"] == "money_cheat_codes" and fmt == "short":
                quiet.append((st, end))            # money spec: no captions while a number card is on screen
        if vis.get("source") == "chart":           # an animated chart plays once, whole: it has its own motion, and
            n_sub = 1                              # its labels carry the words (captions would sit on the bars)
            if fmt == "short" and (st, end) not in quiet:
                quiet.append((st, end))
        if (vis.get("source") in ("ai", "cloudflare", "pollinations", "flux")
                or "AI-generated" in str(vis.get("credit", ""))) and not vis.get("graphic"):
            ai_spans.append((st, end))
        if v3 and vis["kind"] == "image" and not vis.get("graphic"):
            key = str(vis.get("path"))
            n_sub = max(1, min(n_sub, 2 - shot_uses.get(key, 0)))
            shot_uses[key] = shot_uses.get(key, 0) + n_sub
        elif v3 and vis["kind"] == "video" and not vis.get("graphic"):
            key = str(vis.get("path"))              # clips count too (one NASA clip had filled 5 beats)
            shot_uses[key] = shot_uses.get(key, 0) + 1
        is_clip = vis["kind"] == "video" and not vis.get("graphic")
        # owner 15 Nov: "the zoom in zoom out issues are still there". A 2nd part of the SAME picture/clip was a closer
        # crop (1.15-1.28x) and the next picture started wide again: on screen that is zoom in, zoom out. Now one
        # picture = one shot with one slow, steady move; only a different design (alt card) may cut in between.
        if not (vis.get("graphic") and vis.get("alt_path")):
            n_sub = 1
        # human editors vary the rhythm: sub-shot boundaries move up to +-18% (never a metronome)
        cuts_at = [st + (end - st) * jj / n_sub for jj in range(n_sub + 1)]
        for jj in range(1, n_sub):
            wob = ((i * 7 + jj * 13) % 10 - 4.5) / 4.5 * 0.18
            cuts_at[jj] += wob * (end - st) / n_sub
        for j in range(n_sub):
            s0, s1 = cuts_at[j], cuts_at[j + 1]
            kind_j, path_j = vis["kind"], vis.get("path")
            if j > 0 and vis.get("graphic") and vis["kind"] == "video":   # counter card: later shots = its final frame
                frames = sorted(Path(str(path_j)).with_suffix("").glob("u*.png"))
                if frames:
                    kind_j, path_j = "image", frames[-1]
            alt_shot = j % 2 == 1 and bool(vis.get("alt_path"))
            if alt_shot:                                                  # 2nd design of the same card
                kind_j, path_j = "image", vis["alt_path"]
            zoom_j = 1.0                                      # never a closer re-crop of the same picture
            shots.append(compose.Shot(
                s0, s1, kind_j, path_j, (b.get("action") if (j == 0 and b.get("action")) else moves[(i + j) % len(moves)]),
                vis.get("frame", "full"),
                trans if j == 0 else "cut", [],      # no mid-shot snap zooms (owner 13 Nov: zoom in/out looked awful)
                focus=(0.5, 0.45),
                crop_zoom=vis.get("crop_zoom", 1.0) * zoom_j,
                offset=(s0 - st) if (is_clip and kind_j == "video") else 0.0))
            if (j > 0 or i > 0) and (j > 0 or trans == "cut"):
                cut_n += 1
                rate = float(pal.get("cut_rate", 0.0))   # mystery: SFX on ~40% of cuts; money: whoosh on most cuts
                if rate and math.floor(cut_n * rate) > math.floor((cut_n - 1) * rate):
                    sfx_at(s0, "cut", 3)
        last_visual = vis
        # text layers
        # The writer's label ("THE REAL SHIP · 1872") is a claim about the picture: only show it when the
        # picture was found for this beat and matches strongly — never on fallback or reused pictures.
        trusted = (not vis.get("reused") and not vis.get("from_pool") and vis.get("match", 0) >= 0.82
                   and "ai_scene" not in str(vis.get("source", "")))
        label = (b.get("label") if trusted else "") or ("" if vis.get("reused") else vis.get("auto_label", ""))
        lab0 = st + 0.1
        if fmt == "short" and script.get("hook_text") and not hook_in_card:
            lab0 = max(lab0, 3.05)                 # never under the hook (first 3 s): the two collided
        if label and vis.get("frame") == "card" and end - 0.05 - lab0 > 0.6:
            labels.append(Label(lab0, end - 0.05, label, x=70 if size[1] > size[0] else 120, y=f["label_y"],
                                bg=style.get("highlight_color", "#E50914")))
            sfx_at(st + 0.1, "label", 3)
        # The opening beat sits under the hook strips (until 3.0 s); if it runs longer, its big text follows.
        hook_until = 3.0 if fmt == "short" and script.get("hook_text") and i == 0 else 0.0
        big_start = max(st, hook_until)
        if vis["kind"] == "text" and end - big_start > 0.4:
            emph = [e for e in b.get("emphasis", []) if e]
            big = b.get("big_text") or " ".join(emph[:2]) or " ".join(b["narration"].split()[:3])
            bigs.append(BigText(big_start, end, big, style.get("highlight_color", "#FFD600"), sub=b.get("sub", "")))
            sfx_at(big_start, "card", 2)
        if b.get("emoji") and not v3:              # v3: no emoji stickers (research: reads as dated)
            png = stickers.emoji_png(b["emoji"])
            if png:
                stick.append(compose.Sticker(png, st + 0.15, min(st + 1.5, end), f["sticker"]))
                events.append((st + 0.15, "pop", -14, 3))
        # sound (research: restraint; niche palette; levels in dB under the voice)
        if i == 0:
            sfx_at(0.0, "open", 0)
        elif trans in ("whip", "zoom", "swipe"):
            sfx_at(st - 0.12, "whip", 2)
        elif trans == "rewind":
            sfx_at(st, "rewind", 1)
        if i == flash_i:
            sfx_at(st, "reveal", 0)
            drops.append(st)                       # sports: silence in the bed just before the climax line
        elif moment == "twist":
            sfx_at(st, "twist", 1)
        if moment in ("reveal", "twist"):
            sfx_at(max(st - 1.5, 0), "riser", 2)
            swells.append((st, end))               # mystery: bed +4 dB on the reversal and the payoff
        if punch_times:
            sfx_at(punch_times[0], "punch", 3)

    try:                                           # what each beat showed (quality: "shows the story" check)
        (out_dir / "shots.json").write_text(json.dumps([{"see": b.get("see", ""), **(b.get("_visual") or {})}
                                                        for b in beats], indent=1, ensure_ascii=False), encoding="utf-8")
    except (OSError, TypeError):
        pass
    # owner 15 Nov: a storyboard video whose pictures ran out (free daily limit) became word cards and was still sent.
    # Stop instead: the item is retried after the picture limits reset.
    from . import storyboard
    sb_beats = [b for b in beats if b.get("see") and b.get("shot") != "number"]
    as_cards = [b for b in sb_beats if (b.get("_visual") or {}).get("kind") == "text"
                or (b.get("_visual") or {}).get("source") in ("graphic", "text")]
    if sb_beats and len(as_cards) / len(sb_beats) > 0.3 and storyboard.images_blocked():
        raise storyboard.NoPictures(f"{len(as_cards)}/{len(sb_beats)} scenes had no picture: free picture limit "
                                    "reached; this video is made after the daily reset")
    # 4. Sound: voice + effects + our own music bed (ducked under the voice)
    log("Audio: voice, sound effects, music")
    voice48 = to_48k(narration, work / "narration_48k.wav")
    if v3 and fmt == "short" and channel["id"] == "money_cheat_codes" and len(shots) > 3:
        import dataclasses                         # money spec B: the last shot returns to the opening card (loop)
        shots[-1] = dataclasses.replace(shots[-1], kind=shots[0].kind, path=shots[0].path, frame=shots[0].frame,
                                        crop_zoom=1.0, offset=0.0, punches=[])
    # mythology: at most 4 hits per Short (priority: open, reveal, twist, cards...)
    limit = int(pal.get("max_hits", 99))
    if fmt == "short" and len(events) > limit:
        events = sorted(sorted(events, key=lambda e: (e[3] if len(e) > 3 else 1, e[0]))[:limit], key=lambda e: e[0])
    events = [(e[0], e[1], e[2]) for e in events]
    mixspec = dict(MIX.get(channel["id"], {}), **(channel.get("mix") or {}))
    look_music = look_cfg.get("music", "dark")
    music_file = music_file2 = switch_at = None
    if look_music not in _em().PALETTES:            # owner 18 Nov: music that fits THIS video, not one bed per channel
        try:
            from .media import music_library
            mood = music_library.mood_for(channel, script, fallback=look_music)
            got = music_library.track(mood, channel["id"], log=log)
            if got:
                music_file, t = got
                credits.append(music_library.credit(t))
                script["music_mood"] = mood
                log(f"Music: {mood}: {t['title'][:40]} ({t['license']})")
                turn = music_library.climax_mood(mood)
                switch_at = drops[0] if drops else (swells[0][0] if swells else None)   # climax, else first reveal
                if turn and switch_at and switch_at > 4.0:   # the climax gets its own, stronger track
                    got2 = music_library.track(turn, channel["id"], log=log)
                    if got2 and got2[0] != music_file:
                        music_file2, t2 = got2
                        credits.append(music_library.credit(t2))
                        log(f"Music at the climax ({switch_at:.1f}s): {turn}: {t2['title'][:40]}")
        except Exception as e:  # noqa: BLE001
            log(f"Music library: {e} (synthesised bed instead)")
    if music_file is not None:
        try:
            shots, labels, bigs, stick, events, quiet, ai_spans = cut_on_beats(
                shots, labels, bigs, stick, events, quiet, ai_spans, music_file, total, music_file2, switch_at,
                keep=list(drops) + ([switch_at] if switch_at else []), log=log)
        except Exception as e:  # noqa: BLE001
            log(f"Beat sync skipped: {e}")
    mix = _mix(voice48, events, look_music, work / "mix.wav", seed=len(beats), mix=mixspec,
               swells=swells, drops=drops, reverb=channel["id"] == "itihaas_ke_raaz",
               pitch=0.0 if lang == "hi" else float(voice.get("pitch", 0.0)), music_file=music_file,
               music_file2=music_file2, switch_at=switch_at)

    # 5. Text layers (.ass) + render
    log("Render: frames + text, one pass")
    accent = style.get("highlight_color", "#FF3B3B")
    # Hook = two colour strips: white with black text, then the channel colour with white text
    hook_style = HookStyle(lines_bg=["#FFFFFF", accent], lines_fg=["#000000", "#FFFFFF"], font=title_font(lang, kind),
                           # bigger when the hook is the whole opening screen
                           size=(150 if beats[0].get("_visual", {}).get("kind") == "text" else 118)
                           if size[1] > size[0] else 96,
                           # opening on a text screen: hook sits mid-screen as the headline; else at the top
                           y=(int(size[1] * 0.3) if beats[0].get("_visual", {}).get("kind") == "text" else 250)
                           if size[1] > size[0] else 120,
                           until=3.0)
    emphasis = {e for b in beats for e in b.get("emphasis", []) if e}
    if v3:      # 2026 look: sentence-case captions, boxless hook, one accent colour (per-channel research spec)
        from .media.shaping import needs_shaping
        portrait = size[1] > size[0]
        cap = channel.get("caption") or {}
        cap_font = cap.get("font") or ("Mukta ExtraBold" if lang == "hi" else "Poppins ExtraBold")
        # measured in libass (12 Nov): Poppins ExtraBold cap = 0.41 x fs, so fs 151 = 62 px (research: 3.2% of height);
        # Mukta ExtraBold +10% for Devanagari (round0); Bebas Neue cap = 0.56 x fs, fs 115 = 88-96 px type (movie spec)
        cap_fs = int(cap.get("size") or {"Mukta ExtraBold": 155, "Bebas Neue": 115}.get(cap_font, 151))
        cap_accent = cap.get("accent", style.get("accent_color") or accent) or "#FFFFFF"   # null = no keyword colour
        karaoke = cap.get("karaoke", True)          # money spec: no karaoke (white keyword captions only)
        hl_col = cap_accent if karaoke else "#FFFFFF"
        cap_words = words
        if cap.get("script") == "roman" and lang == "hi":     # cricket spec: Roman-Hinglish captions
            cap_words = _roman_words(beats, beat_words) or words
        # owner 17 Nov: "remove the AI generated watermarks from all the videos". No on-screen AI chip; disclosure
        # stays where the platforms want it (YouTube "altered or synthetic" setting, Meta "AI info", description line)
        chips = []

        def _hook_style(text):
            n = len((text or "").split())
            deva = needs_shaping(text or "")
            # length decides size (research): 2-4 words = cover-sized label (C1 / mythology 110-130 px type);
            # 5-8 words = 64-72 px type (podcast spec); top edge y 300 (below Meta's 14% line), shown 0-3 s
            hsize = (223 if n <= 5 else 160) if deva else (240 if n <= 4 else 135)
            second = cap_accent if cap.get("hook_accent") else "#FFFFFF"
            return HookStyle(lines_bg=["#FFFFFF", "#FFFFFF"], lines_fg=["#FFFFFF", second],
                             font="Mukta ExtraBold" if deva else "Poppins ExtraBold",
                             size=hsize if portrait else 140, y=300 if portrait else 70, until=3.0)

        hook_txt = script.get("hook_text") if (fmt == "short" and not hook_in_card) else None
        cap_v = 600 if portrait else f["caption_margin_v"]          # caption centre y ~1250 (65%; research)
        common = dict(font=cap_font, language=lang, caption_color="#FFFFFF", highlight_color=hl_col,
                      emphasis_color=hl_col, emphasis_words=emphasis, labels=labels, big_texts=bigs,
                      big_font=title_font(lang, kind), caption_margin_v=cap_v, size=size, modern=True, chips=chips,
                      skip_spans=quiet, pop_emphasis=bool(cap.get("pop")))
        # long videos: no burned-in captions (research: case-file/documentary long-form uploads an SRT instead)
        ass = build_ass(cap_words if portrait else [], work / "captions.ass", hook=hook_txt,
                        hook_style=_hook_style(hook_txt), font_size=cap_fs if portrait else 100,
                        max_words=3 if portrait else 5, max_chars=14 if portrait else 30, **common)
        ass_reel, reel_hook = None, None
        if fmt == "short":                         # Instagram Reel: same frames, different hook wording
            reel_hook = _alt_hook(script)
            ass_reel = build_ass(cap_words, work / "captions_reel.ass", hook=None if hook_in_card else reel_hook,
                                 hook_style=_hook_style(reel_hook),
                                 font_size=cap_fs, max_words=3, max_chars=14, **common)
    else:
        ass, ass_reel, reel_hook = None, None, None
    ass = ass or build_ass(words, work / "captions.ass", font=caption_font(lang, kind), language=lang,
                    caption_color=style.get("caption_color", "#FFFFFF"), highlight_color=accent,
                    emphasis_color="#FFD600" if accent.upper() != "#FFD600" else "#FFFFFF",
                    emphasis_words=emphasis, hook=script.get("hook_text") if fmt == "short" else None,
                    hook_style=hook_style, labels=labels, big_texts=bigs, big_font=title_font(lang, kind),
                    caption_margin_v=f["caption_margin_v"], font_size=f["font_size"], size=size,
                    max_words=2 if fmt == "short" else 4, max_chars=16 if fmt == "short" else 30)
    final = out_dir / "video.mp4"
    mascot = None
    if v3 and style.get("mascot"):                 # recurring channel character (e.g. Penny on Money Cheat Codes)
        from .media.mascot import Mascot, mouth_track
        mc = style["mascot"]
        portrait = size[1] > size[0]
        mascot = {"sprite": Mascot(size=int(mc.get("size", 200 if portrait else 230)), body=mc.get("body", "#F5C542"),
                                   outline=mc.get("outline", "#B8860B"), seed=7),
                  "mouth": mouth_track(narration, fps=look.fps), "look": -0.4,
                  # Shorts: top-right corner (clear of the right-edge buttons, the cards and the captions),
                  # appearing after the 3 s hook box; long videos: lower right
                  "x": int(size[0] * (0.86 if portrait else 0.9)), "y": int(size[1] * (0.165 if portrait else 0.7)),
                  "start": 3.1 if portrait and fmt == "short" and script.get("hook_text") else 0.0}
    alt = None
    if ass_reel is not None:
        alt = {"ass": ass_reel, "out": out_dir / "reel.mp4", "trim_end": 0.4 + (len(beats) % 5) * 0.12}
    compose.render(shots, look, total, final, audio=mix, ass=ass, fonts_dir=FONTS_DIR, stickers=stick, log=log,
                   alt=alt, mascot=mascot)
    if alt and (out_dir / "reel.mp4").exists():
        _write_reel_extras(channel, script, out_dir, reel_hook, beats)

    meta = {
        "channel": channel["id"], "format": fmt, "created": time.strftime("%Y-%m-%d %H:%M"),
        "title": script.get("title"), "title_options": script.get("title_options", []),
        "hook_text": script.get("hook_text"), "thumbnail": script.get("thumbnail", {}),
        "angle": script.get("chosen_angle"), "interest_score": script.get("interest_score"),
        "description": build_description(channel, script, credits,
                                         [(st, b["chapter"]) for b, st in zip(beats, starts) if b.get("chapter")]
                                         if fmt == "long" else None),
        "chapters": [(round(st, 1), b["chapter"]) for b, st in zip(beats, starts) if b.get("chapter")] if fmt == "long" else [],
        "instagram_caption": script.get("instagram_caption", ""),
        "search_phrase": script.get("search_phrase", ""), "alt_text": script.get("alt_text", ""),
        "pinned_comment": script.get("pinned_comment", ""),
        "tags": seo_tags(channel, script),
        "captions_file": str(write_srt(words, out_dir / "captions.srt")) if words else "",
        "hashtags": script.get("hashtags", []), "duration_s": round(total, 2),
        "credits": list(dict.fromkeys(credits)), "ai_label": True,      # AI narrator voice -> Meta "AI info"
        "yt_synthetic": bool(any("AI-generated" in str(c) for c in credits or [])),   # realistic AI pictures only
        "midroll_eligible": (total >= 480) if fmt == "long" else None,
        "policy_flags": script.get("_policy_flags") or [],
        "fact_check": script.get("_fact_check"), "written_by": script.get("_written_by"),
        "beats": beats,
    }
    # 6. Three thumbnails (Lallantop / MrBeast / question styles) for YouTube's thumbnail test
    log("Thumbnails")
    try:
        meta["thumbnails"] = [str(p) for p in make_thumbnails(channel, script, out_dir)]
    except Exception as e:          # a thumbnail problem must not lose the finished video
        log(f"  thumbnail error: {e}")
    (out_dir / "upload.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return meta


def _roman_words(beats: list, beat_words: list) -> list:
    """Cricket spec: Roman-Hinglish captions over Hindi narration. Uses each beat's `narration_roman` (written once by
    the brain, same word count); beats without a matching transliteration keep the Devanagari words."""
    out, changed = [], 0
    for b, ws in zip(beats, beat_words):
        rom = str(b.get("narration_roman") or "").split()
        if rom and len(rom) == len(ws):
            out += [type(w)(r, w.start, w.end) for w, r in zip(ws, rom)]
            changed += 1
        else:
            out += list(ws)
    return out if changed else []


ROMAN_PROMPT = """Write each Hindi line below in Roman script the way Indians type Hinglish on YouTube (e.g. "Sirf 12
minute... aur 13 gend pe 22 run"). Keep EXACTLY the same number of words as the Hindi line, word for word, same order.
Numbers stay as digits. Return ONLY JSON: {{"lines": [{{"i": 0, "roman": "..."}}]}}
Lines (index: Hindi):
{lines}"""


def add_roman(brain, channel: dict, script: dict, log=print) -> dict:
    """Store a Roman-Hinglish copy of every beat (word-for-word) for channels whose captions are Roman (cricket)."""
    if (channel.get("caption") or {}).get("script") != "roman" or channel.get("language") != "hi":
        return script
    beats = script.get("beats") or []
    need = [i for i, b in enumerate(beats)               # missing, or stale after a trim (word counts differ)
            if len(str(b.get("narration_roman") or "").split()) != len(b.get("narration", "").split())]
    if not need:
        return script
    lines = "\n".join(f"{i}: {beats[i].get('narration', '')}" for i in need)
    try:
        data, _ = brain.ask_json("writer", ROMAN_PROMPT.format(lines=lines), temperature=0.2)
    except Exception as e:  # noqa: BLE001 - captions fall back to Devanagari
        log(f"Roman captions skipped: {e}")
        return script
    ok = 0
    for row in (data or {}).get("lines") or []:
        try:
            i = int(row.get("i"))
        except (TypeError, ValueError):
            continue
        if 0 <= i < len(beats) and len(str(row.get("roman", "")).split()) == len(beats[i].get("narration", "").split()):
            beats[i]["narration_roman"] = str(row["roman"]).strip()
            ok += 1
    log(f"Roman-Hinglish captions: {ok}/{len(beats)} lines matched word-for-word")
    return script


def make_thumbnails(channel: dict, script: dict, out_dir: Path) -> list[Path]:
    from .media import thumbnail
    thumb = script.get("thumbnail", {}) or {}
    images, ai_first = [], []
    if thumb.get("subject_prompt"):                 # AI subject made just for the thumbnail
        v = visuals.ai_image(thumb["subject_prompt"], channel.get("style", {}).get("mood", ""))
        if v:
            ai_first = [v.path]
    rest = [p for p in rank_heroes(script) if p not in ai_first]  # photos only: no cards, charts or documents
    pair = rest[:2]
    images = ai_first + rest
    pair = (ai_first + pair)[:2]
    if channel.get("style", {}).get("renderer", "v3") != "v2":
        # v3: research templates per channel; skip graphics (they are text cards, not heroes)
        from .media.thumbs_v4 import make_set as make_set_v4   # v4: full-bleed depth look
        heroes = [p for p in images if "graphic_" not in Path(p).name] or images
        hook = thumb.get("text") or script.get("hook_text") or ""
        if thumb.get("text_line2"):
            hook = f"{hook} | {thumb['text_line2']}"
        named = set(script.get("_named_heroes") or [])
        same = (bool(named) and str(heroes[0]) in named and (len(heroes) < 2 or str(heroes[1]) not in named)) \
            or not script.get("_v3_ok", True)
        return make_set_v4(channel, heroes[:6], hook, out_dir, cover_label=script.get("hook_text") or hook,
                           v3_same=same)       # V3 never switches to a picture that isn't the real subject
    return thumbnail.make_set(images, thumb, out_dir, accent=channel.get("style", {}).get("highlight_color", "#E50914"),
                              language=channel["language"], channel_name=channel["name"], pair=pair)


def make(brain, channel: dict, topic: str | None = None, fmt: str = "short", script: dict | None = None,
         memory=None, log=print) -> tuple[Path, dict]:
    fresh = script is None
    if script is None:
        log(f"Script: writing '{topic}' for {channel['name']}")
        script = write_script(brain, channel, topic, fmt, memory)
        if fmt == "long":
            lw = _range((channel.get("spec") or {}).get("long_words", ""))
            script = expand_long(brain, script, log=log, minimum=lw[0] if lw else LONG_MIN_WORDS,
                                 target=(sum(lw) // 2) if lw else LONG_MIN_WORDS + 150, rounds=4)
            script = add_chapters(brain, script, wpm=(channel.get("spec") or {}).get("long_wpm", 175), log=log)
        flags = script_flags(script)
        if flags:                                   # owner's rule: never-topics are rewritten out, not just warned
            log(f"Never-topics in the script ({', '.join(flags)}); rewriting once without them")
            script = write_script(brain, channel, f"{topic}\nDo not touch these subjects at all: {', '.join(flags)}",
                                  fmt, memory)
            flags = script_flags(script)
        script["_policy_flags"] = flags
        if fmt == "short":
            script = fit_length(brain, channel, script, log)
        if channel.get("content_rules", {}).get("fact_check"):
            script = check_and_fix(brain, channel, script, topic, fmt, memory, log)
    else:
        if fmt == "short":
            if brain is None:
                from .brain import Brain
                brain = Brain()
            script = fit_length(brain, channel, script, log)
    if not fresh and channel.get("content_rules", {}).get("fact_check") and not (script.get("_fact_check") or {}).get("ok"):
        log("Fact-check: re-checking the saved script")       # old result may be stale
        if brain is None:
            from .brain import Brain
            brain = Brain()
        if script.pop("_expanded", False):                    # new lines were added: check AND fix them
            script = check_and_fix(brain, channel, script, topic or script.get("title", ""), fmt, memory, log)
        else:
            script["_fact_check"] = fact_check(brain, script)
    if (channel.get("caption") or {}).get("script") == "roman":
        if brain is None:
            from .brain import Brain
            brain = Brain()
        script = add_roman(brain, channel, script, log)
    if not script.get("search_phrase"):            # older saved script: add the SEO fields (one short call)
        try:
            from .seo import fill_seo
            if brain is None:
                from .brain import Brain
                brain = Brain()
            script = fill_seo(brain, channel, script, fmt)
        except Exception as e:  # noqa: BLE001 - SEO text must never stop a render
            log(f"SEO fill skipped: {e}")
    script = normalize_script(script)
    from . import storyboard                       # owner 15 Nov: every shot shows what is being said
    if storyboard.enabled(channel) and not all(b.get("see") for b in script.get("beats") or []):
        if brain is None:
            from .brain import Brain
            brain = Brain()
        storyboard.plan(brain, script, channel, fmt, log)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    out_dir = ROOT / "output" / channel["id"] / f"{stamp}_{_slug(script.get('title') or topic or 'video')}"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "script.json").write_text(json.dumps(script, indent=2, ensure_ascii=False), encoding="utf-8")
    meta = render(channel, script, out_dir, fmt, log)
    return out_dir, meta
