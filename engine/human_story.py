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

RULES = """
STORY TELLING (this channel tells HUMAN stories; where these rules differ from the beat rules above, these win):
- Tell ONE real person's (or one animal's) story as a scene, not a list of facts: what they see, want, fear and
  decide. Facts stay true; the story is told through that person.
- Beat 1: the person speaks one line in the first person (present tense, at most 10 words), or the most intense
  moment in mid-action. A spoken line has "speaker": "<their name>".
- Narrator lines: 5-12 words, concrete pictures for the eye (light, weather, sounds, hands, faces), active verbs.
  Give the person ONE defining detail the pictures will show (a scar, a worn coat, a habit) and keep it.
- At the turning point, ONE short exchange: two lines by two different speakers, each at most 12 words. Historical,
  legendary or animal stories may act the scene in words faithful to the sources; a real person of the last 100
  years may only say words on record (then add "<name> said: <quote>" to claims). Never put acted lines in claims.
- One line just before the reveal that makes the viewer wait for it. The last line echoes the first line.
- EVERY beat has "speaker": "narrator" or the speaking person's name. Add "cast_voices": {"<name>": "man|woman|
  older man|older woman|young man|young woman"} for every speaking person.
"""

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


def rules_for(channel: dict) -> str:
    """The telling block for the writer prompt ('' for channels that keep their own telling)."""
    return RULES if enabled(channel) else ""


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
