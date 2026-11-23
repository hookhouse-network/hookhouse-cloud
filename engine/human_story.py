"""Human-story telling for story channels (owner, 23 Nov 2026: "for human like stories i am talking about this
https://www.youtube.com/channel/UCb-5VFy2fxgtrsbA9ZOUBVQ channel's content and we can adapt this template for story
videos and shorts. for kids channels that is a different story and template").

The reference (studied 23 Nov, docs/templates/human_story.md) tells one hero's life as scenes: a cold open in the
hero's own voice, a literary narrator with concrete images, personal details that also fix the hero's look, short
acted dialogue between named characters (each in its own voice), foreshadowing, chapters and a cliffhanger. Our own
fact Shorts were the opposite (one fact per line, no person, no voice), which is what the S10 'obviously AI-made'
judge kept marking. A channel opts in with style.telling: human_story (config/channels/*.yaml).

Dialogue rule (accuracy): historical, legendary and animal stories may act a scene in words faithful to the sources;
a real person of the last 100 years only says words on record (that quote then goes into the claims the fact gate
checks). Acted lines never go into the claims, and the description says the video is a dramatized retelling."""
from __future__ import annotations

# 23 Nov: appending RULES to the fact-Short prompt was not enough (A/B with the real writer: Apollo 13 5.5 -> 6.0, a
# Hindi story without dialogue and with a false hook): the old beat structure won. Opted-in channels now get STRUCTURE
# in place of the writer prompt's "STEP 3 - BEATS" section (writer_template). It is part of the format template, so
# literal braces are doubled; {words}, {beats} and {long_rules} are filled like the section it replaces.
STRUCTURE = """STEP 3 - THE STORY (human-story telling: told the way the best history storytellers tell it, as a scene
around ONE person, never as a list of facts).
- Choose ONE person at the heart of the topic (for an animal story: ONE animal) and the ONE moment that matters most.
  Everything is seen through them: what they see, want, fear and decide. Every fact stays true.
- Beat 1 = COLD OPEN (at most 10 words): the person speaks in the first person, present tense, at the moment of the
  greatest pressure; OR the narrator drops the viewer into that moment, mid-action. The cold open must be LITERALLY
  TRUE: no exaggeration, no legend told as fact, no miracle, no number, no question to the viewer. hook_text shows the
  same promise on screen.
- Beats 2-3: who they are, through ONE personal detail the camera can show (a scar, a worn cloak, trembling hands),
  and where we are (light, sound, weather). Say the search_phrase in beat 1 or 2.
- Middle: the pressure rises; every beat is a concrete image, an action or a feeling. Names, dates and numbers are
  woven into the scene, never listed.
- The turning point: ONE short exchange, two lines by two different speakers, each at most 12 words.
- One beat just before the reveal makes the viewer lean in (who will move first, what is about to break).
- The reveal, then a last line that echoes beat 1, so the Short loops.
- NARRATOR: a storyteller's voice: vivid, warm, serious; 5-12 words a line; sensory detail; active verbs. Never slang,
  never "guess", "you see", "imagine" or a question to the viewer, never a list, never a stock phrase.
- SPOKEN LINES: a real person of the last 100 years only says words on record (add "<name> said: <exact quote>" to
  claims); historical, legendary and animal stories may act a scene in words faithful to the sources. Acted lines
  never go into claims. Never invent an event, a number or a quote for a modern person. A spoken line is its OWN
  beat with that person as "speaker" (never "he said: ..." inside a narrator line).
- LEGENDS: what tradition tells but history cannot prove is told as a legend ("legend says...", "the bards sang..."),
  never as fact; never say a book or a source says something unless the sources you list say it.
- SEARCH: "search_phrase" = the 2-5 words a viewer would type to find this story (the name + event/place). Start the
  title with it and use it in the first sentence of "summary" and the first line of "instagram_caption".
- Length: {words}, {beats} beats. EVERY beat has "speaker": "narrator" or the speaking person's name; add
  "cast_voices": {{"<name>": "man|woman|older man|older woman|young man|young woman"}} for every speaking person.
- SHARE-WORTHY: a true detail most retellings miss, the reason this video exists.
{long_rules}
"""
_STEP3, _STEP4 = "STEP 3 - BEATS", "STEP 4 -"
# The output example at the end of the writer prompt shows the beat keys; the writer copies it, so a human-story beat
# shows "speaker" first (23 Nov: a Hindi script wrote 'Pratap said: "..."' inside a narrator line, no speaker).
_BEAT_KEYS = '"beats": [{{"narration": "...", "chapter": ""'
_BEAT_KEYS_HUMAN = ('"cast_voices": {{"<speaking person>": "man|woman|older man|older woman|young man|young woman"}},\n'
                    '  "beats": [{{"speaker": "narrator|<speaking person>", "narration": "...", "chapter": ""')

# Speaking characters' voices per engine. Kokoro (Apache 2.0, local): the voices in our install (23 Nov).
KOKORO = {"en": {"man": ["am_michael", "am_eric"], "young man": ["am_adam", "am_puck"], "older man": ["bm_george"],
                 "woman": ["af_heart", "af_sarah"], "young woman": ["af_bella", "af_nicole"],
                 "older woman": ["bf_isabella"]},
          "hi": {"man": ["hm_psi", "hm_omega"], "young man": ["hm_psi", "hm_omega"],
                 "older man": ["hm_omega", "hm_psi"], "woman": ["hf_alpha"], "young woman": ["hf_alpha"],
                 "older woman": ["hf_alpha"]}}
GOOGLE_HI = {"man": ["hi-IN-Chirp3-HD-Fenrir", "hi-IN-Chirp3-HD-Orus"], "young man": ["hi-IN-Chirp3-HD-Puck"],
             "older man": ["hi-IN-Chirp3-HD-Charon", "hi-IN-Chirp3-HD-Fenrir"], "woman": ["hi-IN-Chirp3-HD-Kore"],
             "young woman": ["hi-IN-Chirp3-HD-Leda"], "older woman": ["hi-IN-Chirp3-HD-Aoede"]}


def enabled(channel: dict) -> bool:
    return str((channel.get("style") or {}).get("telling") or "") == "human_story"


def writer_template(base: str, channel: dict) -> str:
    """The writer prompt template for this channel: STRUCTURE in place of the fact-Short beat section when the channel
    opted in; the base prompt unchanged otherwise (or when its sections moved)."""
    if not enabled(channel) or _STEP3 not in base or _STEP4 not in base:
        return base
    a, b = base.index(_STEP3), base.index(_STEP4)
    return (base[:a] + STRUCTURE + base[b:]).replace(_BEAT_KEYS, _BEAT_KEYS_HUMAN, 1)


def speaker(beat: dict) -> str:
    """The speaking person of a beat ('' = the narrator)."""
    s = str(beat.get("speaker") or "").strip()
    return "" if s.lower() in ("", "narrator", "narration", "voiceover", "voice-over") else s


FAMILY = {"man": "m", "older man": "m", "young man": "m", "woman": "f", "older woman": "f", "young woman": "f"}


def _pick(table: dict, kind: str, taken: set, narrator: str) -> str | None:
    """A free voice of this kind, else of the same gender; all taken: share one rather than use the narrator's."""
    fam = FAMILY.get(kind, "m")
    kinds = [kind if kind in FAMILY else "man"] + [k for k, f in FAMILY.items() if f == fam and k != kind]
    for free_only in (True, False):
        for k in kinds:
            for v in table.get(k) or []:
                if v != narrator and (v not in taken or not free_only):
                    return v
    return None


def voices(script: dict, language: str, narrator: str, engine: str = "kokoro") -> dict[str, str]:
    """{speaker: voice} for every speaking person: never the narrator's voice, and two people never share one while
    another fits. engine: 'kokoro' (voice ids) or 'google' (Hindi Chirp 3 HD names)."""
    table = GOOGLE_HI if engine == "google" else KOKORO.get("hi" if language == "hi" else "en", KOKORO["en"])
    kinds = {str(k).strip(): str(v).strip().lower() for k, v in (script.get("cast_voices") or {}).items()}
    names = list(dict.fromkeys(speaker(b) for b in script.get("beats") or [] if speaker(b)))
    out, taken = {}, set()
    for n in names:
        v = _pick(table, kinds.get(n, "man"), taken, narrator)
        if v:
            out[n] = v
            taken.add(v)
    return out


def acted(script: dict) -> bool:
    """True when the script has spoken lines (the description then says it is a dramatized retelling)."""
    return any(speaker(b) for b in script.get("beats") or [])


COLD_OPEN_PROMPT = """Rewrite the FIRST line of a short story video. It is a question to the viewer; the storytelling
template wants a COLD OPEN instead: the person speaks in the first person, present tense, at the moment of the
greatest pressure, OR the narrator drops the viewer into that moment, mid-action.
Current first line: "{line}"
Second line (keep it as it is): "{line2}"
Rules: the same language and script, at most 10 words, no question mark, LITERALLY TRUE to the story (no legend told as
fact, no number, no new fact), keep these search words if the current line has them: {words}.
Return JSON only: {{"line": "...", "speaker": "narrator or the speaking person's name"}}"""


def cold_open(brain, script: dict, channel: dict, log=print) -> dict:
    """24 Nov R&D: the strong writer still opened the Haldighati draft with a question ("Why did Chetak wear an
    elephant trunk?") although STRUCTURE asks for a cold open. One targeted rewrite of line 1 for human-story
    channels; kept only when it is no question and at most 12 words. Never raises."""
    import copy
    import re
    beats = script.get("beats") or []
    if not enabled(channel) or brain is None or not beats:
        return script
    first = str(beats[0].get("narration") or "").strip()
    if not first.endswith("?"):
        return script
    words = [w for w in re.findall(r"\w+", str(script.get("search_phrase") or "")) if len(w) > 3 and w in first][:3]
    try:
        data, _ = brain.ask_json("writer", COLD_OPEN_PROMPT.format(
            line=first, line2=str(beats[1].get("narration") or "") if len(beats) > 1 else "",
            words=", ".join(words) or "none"), temperature=0.5)
    except Exception as e:  # noqa: BLE001 - the question stays; the judge still scores the hook
        log(f"Cold open: not rewritten ({type(e).__name__})")
        return script
    new = str((data if isinstance(data, dict) else {}).get("line") or "").strip()
    if not new or new.endswith("?") or "?" in new or len(new.split()) > 12 or any(w not in new for w in words):
        log("Cold open: the rewrite did not fit; the question stays")
        return script
    out = copy.deepcopy(script)
    out["beats"][0]["narration"] = new
    sp = str((data or {}).get("speaker") or "").strip()
    if sp and sp.lower() != "narrator" and sp in (out.get("cast_voices") or {}):
        out["beats"][0]["speaker"] = sp                           # the person speaks it, in their cast voice
    elif sp or "speaker" in out["beats"][0]:
        out["beats"][0]["speaker"] = "narrator"                   # an unknown speaker has no voice: the narrator
    if out.get("hook_text") and str(script.get("hook_text") or "").strip().endswith("?"):
        out["hook_text"] = new
    out["_fact_check"] = {}                                       # wording changed: checked again
    log(f"Cold open: '{first}' -> '{new}'")
    return out
