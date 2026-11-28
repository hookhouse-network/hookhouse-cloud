"""Bloop & Friends (#10, Made for Kids): calm count-along story episodes (about 2-2.5 minutes).

Built from our research spec (research_notes/Viral faceless video formats 2026/kids_made_for_kids.md, part 7):
- Preschool (2-5), co-viewable, "vibrant pastel" colours, one ink outline, only a few big background shapes.
- Calm pacing: shots of 2.5 s or longer (most 4-8 s), slow push-ins only, no flashing, no fast cuts.
- A complete little story: greeting -> small problem -> counting solves it -> happy ending -> calm goodbye.
  Each episode gets a different situation, object and setting (YouTube calls "same situation, same outcome"
  inauthentic).
- Repetition with one new element each round: count to fill the spots, count again together, clap and count.
- Pauses after questions so the child can answer (serve and return), then the answer.
- On-screen text is only the learning target (the digits). The spoken number, the digit and the number of
  objects always match (checked in qa()).
- Our own characters, each with a different shape and voice; a public-domain melody (1761) in our own
  arrangement. Made for Kids, no calls to like/subscribe/comment, no AI label (non-realistic animation).
"""
from __future__ import annotations

import json
import math
import random
import re
import time
from math import gcd
from pathlib import Path

import cv2
import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

from .config import ROOT
from .media.mascot import Mascot
from .media.voice import synthesize
from .snack import audio as au
from .snack.canvas import blit, ease_out, pop_scale, rounded_rect, text_sprite
from .snack.encode import FrameWriter, mux

W, H, FPS = 1920, 1080, 30
CW, CH = 2304, 1296                       # drawing canvas; the virtual camera crops and scales it to W x H
FEET_Y = 1170                             # where the characters stand on the canvas
BEAT = 0.6                                # 100 BPM: the counting lands on the beat of the music
FLY = 0.65                                # seconds for an object to fly into its spot
DIGIT_Y = 215                             # where the big number (the learning target) appears


def _bgr_hex(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[4:6], 16), int(h[2:4], 16), int(h[0:2], 16)


INK = _bgr_hex("#2E3A59")
PAL = {k: _bgr_hex(v) for k, v in {
    "sky": "#8FD3F4", "sky2": "#E2F5FC", "grass": "#9BD770", "grass2": "#C2E8A0", "bush": "#86C65A",
    "sun": "#FFD45C", "coral": "#FF8A7A", "coral2": "#FFC4BA", "lavender": "#B9A7F2", "cream": "#FFF6E5",
    "cream2": "#F8E6CC", "base": "#EBD2B2", "wood": "#EFCB9F", "wood2": "#E4B988", "sea": "#57BEE0",
    "sea2": "#A6E0F0", "foam": "#E8F8FC", "sand": "#F6DFAA", "night": "#33318A", "night2": "#8B7BD6",
    "nhill": "#5E52BE", "nground": "#33A083", "moon": "#FFE27A", "wall": "#E9E0FF", "wall2": "#CDBDFF", "leaf": "#7CC35E", "leaf2": "#68AE4D",
    "trunk": "#B0835A", "white": "#FFFFFF", "teal": "#3FB8E0"}.items()}
DIGIT_COLORS = ["#FF6F61", "#2FA8DA", "#5DB53F", "#A974D6", "#F59B2B", "#E8579A", "#1FA89A", "#6C7BE0",
                "#E2574C", "#3C9BD6"]

# name: (body colour, shape, sprite size on the canvas, Kokoro voice, x position on the canvas)
CAST = {"Bloop": ("#3FB8E0", "drop", 440, "af_bella", 560),
        "Pip": ("#FFD45C", "sprout", 370, "bf_emma", 930),
        "Mo": ("#9BD770", "tall", 450, "am_puck", 1390),
        "Dee": ("#FF8A7A", "ears", 420, "af_sarah", 1770)}
NARRATOR = "af_heart"

# Layouts: the 16:9 episode, and the 9:16 Short (the same scene drawn lower on a taller canvas, key content
# kept above the bottom ~25% where the Shorts buttons and title sit).
LAYOUTS = {
    "long": {"W": 1920, "H": 1080, "CW": 2304, "CH": 1296, "DY": 0, "FEET_Y": 1170, "DIGIT_Y": 215,
             "DIGIT_SIZE": 230, "SLOT_R": 100, "OBJ": 170, "MED": (410, 1.4), "STAGE": (640, 1.1),
             "CAST_X": {"Bloop": 560, "Pip": 930, "Mo": 1390, "Dee": 1770}, "CAST_SCALE": 1.0},
    "short": {"W": 1080, "H": 1920, "CW": 1296, "CH": 2304, "DY": 480, "FEET_Y": 1650, "DIGIT_Y": 590,
              "DIGIT_SIZE": 210, "SLOT_R": 88, "OBJ": 150, "MED": (300, 1.3), "STAGE": (1270, 1.1),
              "CAST_X": {"Bloop": 175, "Pip": 440, "Mo": 735, "Dee": 1000}, "CAST_SCALE": 0.72,   # clear of the right-edge buttons
              "DUO_X": (300, 830), "DUO_SCALE": 1.15},     # the Short shows two characters, 1.6x bigger
}
_BASE_CAST = dict(CAST)
# Guest friends (owner 18 Nov: "varied characters ... we are not fixed to Bloop"): Bloop stays the host, and one of
# six friends visits each Short, three of them new faces with their own shape and voice.
GUESTS = {"Kiki": ("#B9A7F2", "pointy", 400, "bf_isabella", 0),
          "Hop": ("#FF9EC4", "bunny", 390, "am_eric", 0),
          "Zip": ("#FFB347", "antenna", 390, "am_michael", 0)}
FRIENDS = ["Pip", "Mo", "Dee", "Kiki", "Hop", "Zip"]


def toddlers_on() -> bool:
    """Owner 28 Nov ("totally change the animations ... like CoComelon", bright cartoon look): our own toddler cast
    (engine/media/toddler.py) replaces the DiceBear dolls. Pure code: no browser or DiceBear needed."""
    try:
        from .config import settings
        return bool(settings().get("kids_toddlers", False))
    except Exception as e:  # noqa: BLE001
        print(f"kids: toddlers off ({type(e).__name__}: {e})")
        return False


def _humans() -> dict:
    """Human friends (owner 21 Nov: "instead of just shapes, we can introduce some humans"). Since 28 Nov our own
    CoComelon-style toddlers (kids_toddlers); before, puppets with DiceBear Toon Head faces (CC BY 4.0, credited) on
    bodies our own code draws (engine/media/puppet.py; config/characters.yaml)."""
    if toddlers_on():
        from .media.toddler import TODDLERS
        return {t["name"]: ("#" + t["top"], f"toddler:{cid}", 560, t["voice"], 0) for cid, t in TODDLERS.items()}
    try:
        from .media import characters
        # size 520 (21 Nov live render: at 430 Mia read as a background extra next to Bloop's 440 blob)
        return {str(c["name"]): ("#" + str(c.get("colour") or "2563EB"), f"puppet:{cid}", int(c.get("size") or 520),
                                 str(c.get("voice") or NARRATOR), 0)
                for cid, c in (characters.bible().get("characters") or {}).items()}
    except Exception as e:  # noqa: BLE001 - no character bible: the toon cast only (said, never silent)
        print(f"kids: human friends unavailable ({type(e).__name__}: {e}); toon friends only")
        return {}


HUMANS = _humans()
GUESTS.update(HUMANS)


def puppets_on() -> bool:
    """Human puppets need DiceBear + a browser on this machine (the PC) and the settings switch kids_puppets."""
    if toddlers_on():
        return bool(HUMANS)                      # our own drawn toddlers: always available
    try:
        from .config import settings
        from .media import characters
        return bool(HUMANS) and settings().get("kids_puppets", True) and characters.available()
    except Exception as e:  # noqa: BLE001 - puppets off, toon friends instead (said, never silent)
        print(f"kids: puppets off ({type(e).__name__}: {e})")
        return False


def friends() -> list[str]:
    """The Short's rotating friend: humans take every other slot where puppets can be made, else the toon friends."""
    if not puppets_on():
        return list(FRIENDS)
    toons, humans = ["Pip", "Kiki", "Hop", "Zip", "Mo", "Dee"], list(HUMANS)
    out = []
    for i in range(max(len(toons), len(humans))):
        out += ([humans[i]] if i < len(humans) else []) + ([toons[i]] if i < len(toons) else [])
    return out


def is_puppet(name: str) -> bool:
    """A human friend with arms (waves, claps, cheers, points): a DiceBear puppet or one of our toddlers."""
    spec = {**_BASE_CAST, **GUESTS}.get(name)
    return bool(spec) and str(spec[1]).startswith(("puppet:", "toddler:"))


def needs_credit(name: str) -> bool:
    spec = {**_BASE_CAST, **GUESTS}.get(name)
    return bool(spec) and str(spec[1]).startswith("puppet:")    # DiceBear faces (CC BY 4.0); toddlers are ours


def puppet_action(cur: dict | None, name: str, kind: str, age: float, tt: float, count_until: float | None) -> str | None:
    """What a puppet's arms do on this line: everyone waves/claps/cheers together; the speaker points while counting
    and raises the brows on a question."""
    if not cur:
        return None
    if kind == "wave":
        return "wave"
    if kind == "clap":
        return "clap"
    if kind in ("answer", "praise") and age < 1.2:
        return "cheer"
    if cur.get("who") == name:
        if kind == "count" and count_until is not None and tt < count_until:
            return "count"
        if kind == "question":
            return "question"
    return None


def use_layout(fmt: str, duo: tuple[str, str] | None = None, swap: dict[str, str] | None = None) -> None:
    """Switch the drawing layout for this process (one render at a time). duo: only these two characters, bigger
    (the Short)."""
    lay = LAYOUTS[fmt]
    g = globals()
    for k in ("W", "H", "CW", "CH", "DY", "FEET_Y", "DIGIT_Y", "DIGIT_SIZE", "SLOT_R", "OBJ", "MED", "STAGE"):
        g[k] = lay[k]
    if duo and lay.get("DUO_X"):
        spec = {**_BASE_CAST, **GUESTS}
        g["CAST"] = {name: (spec[name][0], spec[name][1], int(spec[name][2] * lay["DUO_SCALE"]), spec[name][3],
                            lay["DUO_X"][i]) for i, name in enumerate(duo)}
        return
    g["CAST"] = {name: (col, shape, int(size * lay["CAST_SCALE"]), voice, lay["CAST_X"][name])
                 for name, (col, shape, size, voice, _x) in _BASE_CAST.items()}
    if swap:                                  # long episodes: human friends stand where the swapped toons stood
        g["CAST"] = {swap.get(name, name): ((*HUMANS[swap[name]][:2], int(HUMANS[swap[name]][2] * lay["CAST_SCALE"]),
                                              HUMANS[swap[name]][3], spec[4]) if name in swap else spec)
                     for name, spec in g["CAST"].items()}


def human_cast_lines(lines: list[dict], seed: int) -> tuple[list[dict], dict[str, str]]:
    """Long episodes (owner 21 Nov: "introduce some humans"): Mo and Dee hand their parts to two human friends that
    rotate from episode to episode; their names in every line follow, so the words match who is on screen."""
    humans = list(HUMANS)
    if len(humans) < 2:
        return lines, {}
    swap = {"Mo": humans[seed % len(humans)], "Dee": humans[(seed + 1) % len(humans)]}
    rx = re.compile(r"\b(Mo|Dee)\b")
    out = [dict(ln, who=swap.get(ln["who"], ln["who"]), say=rx.sub(lambda m: swap[m.group(1)], ln["say"]))
           for ln in lines]
    return out, swap


def duo_lines(lines: list[dict], seed: int) -> tuple[list[dict], tuple[str, str]]:
    """The Short's two characters: Bloop + a friend that changes from Short to Short (FRIENDS, incl. the guests);
    the others' lines go to the friend, and a name said in a line becomes the friend's, so the words match who is
    on screen (the counting stays exactly the same)."""
    pool = friends()
    friend = pool[seed % len(pool)]
    others = [n for n in _BASE_CAST if n not in ("Bloop", friend)]
    rx = re.compile(r"\b(" + "|".join(others) + r")\b")
    rx_all = re.compile(r"\b(" + "|".join(others + [friend]) + r")\b")
    out = []
    for ln in lines:
        orig = ln["who"]
        ln = dict(ln, who=friend) if orig in _BASE_CAST and orig not in ("Bloop", friend) else dict(ln)
        if orig == friend:                                   # its own line: the others it spoke to -> Bloop
            ln["say"] = rx.sub("Bloop", ln["say"])
        elif ln["who"] == friend:                            # a line taken over from Mo/Dee/...: now said to Bloop
            ln["say"] = rx_all.sub("Bloop", ln["say"])
        else:                                                # Bloop / the narrator: the others -> the friend
            ln["say"] = rx.sub(friend, ln["say"])
        out.append(ln)
    return out, ("Bloop", friend)


use_layout("long")

OBJECTS ={"apple": ("garden", "park"), "star": ("night", "room"), "balloon": ("park", "room"),
           "duck": ("park",), "flower": ("garden",), "ball": ("park", "room"), "fish": ("beach",),
           "cupcake": ("room",),
           # 18 Nov (owner: nature, real world, not repetitive): more things to count all year
           "strawberry": ("garden", "park"), "butterfly": ("garden", "park"), "leaf": ("park", "garden"),
           "car": ("room", "park"), "cookie": ("room",), "carrot": ("garden",)}
# Christmas season (owner 17 Nov 2026: product research #1 = Christmas coloring pages; videos follow the research).
# Drawn by engine/christmas_book.xmas_object; used 15 Nov - 31 Dec, then the planner goes back to the year-round set.
XMAS_OBJECTS = {"present": ("room",), "ornament": ("room", "night"), "bell": ("room",), "snowman": ("night",),
                "stocking": ("room",), "candy cane": ("room",)}
XMAS_ART = {"present": "gift", "ornament": "ornament", "bell": "bell", "snowman": "snowman", "stocking": "stocking",
            "candy cane": "candy_cane"}
XMAS_SITUATIONS = ["decorating the Christmas tree", "wrapping presents for friends", "a snowy Christmas morning",
                   "getting ready for Santa", "a Christmas party with friends", "hanging stockings by the fire"]
OBJECTS.update(XMAS_OBJECTS)
PLURAL = {"fish": "fish", "snowman": "snowmen", "strawberry": "strawberries", "butterfly": "butterflies",
          "leaf": "leaves"}


def christmas_season(when=None) -> bool:
    from datetime import date
    d = when or date.today()
    return (d.month == 11 and d.day >= 15) or d.month == 12
SITUATIONS = ["getting ready for a party", "a picnic", "getting ready for bed", "a rainy day inside",
              "cheering up a friend", "a treasure hunt", "a sunny morning", "a surprise for a friend",
              "tidying up after play", "putting on a little show"]
NUM = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"]
# Kids 2.0 (owner 21 Nov: "too static, stalling, idle ... boring"): the waits were long silent holds. Shorter, still
# Dora-style (ask -> pause -> answer), and the picture keeps moving during every pause.
GAPS = {"story": 0.4, "wave": 0.45, "count": 1.4, "together": 1.2, "clap": 1.0, "question": 1.8, "answer": 0.9,
        "callout": 1.5, "praise": 0.5}
FIRST_WORD_S = 0.3        # potential gate: speech within 0.6 s (it started after 2 s of music, so every video was held)
# Talking WITH the child (owner, 13 Nov: "like someone is talking through you to make you engage and helping...
# motherly vibes and comfort"; research: Ms Rachel's speech-therapy techniques = repetition, pausing for the child,
# parentese, short simple language). A callout asks the child to say or do something, waits, then praises.
PRAISE = ["Yay! You did it!", "Wonderful!", "I knew you could!", "Great job, friend!", "Super!", "You're a great helper!"]
# The colour each object is drawn in (draw_object), so the colour lesson always matches the picture
OBJECT_COLOUR = {"apple": "red", "star": "yellow", "balloon": "purple", "duck": "yellow", "flower": "pink",
                 "fish": "orange", "cupcake": "pink", "strawberry": "red", "butterfly": "blue", "leaf": "green",
                 "car": "blue", "cookie": "brown", "carrot": "orange"}
BANNED = re.compile(r"subscrib|\bcomment|\btap\b|\bclick|\bbell\b|\blink\b|like (this|the|our) video|hit (the )?like",
                    re.I)

# 24 Nov: the Short opens on the "problem" lines and the child was first asked something in line 4 ("Do we have
# enough, friend?"); both judged versions of 1125_0500 scored human_feel 5 with the same fix: open with a direct
# challenge to the child (Dora's ask-the-viewer-for-help). The problem part now starts with the narrator asking for
# help, in the writer's own words (an example line would come back word for word in every episode).
STORY_PROMPT = """Write the story parts of a FUNNY, lively episode of "Bloop & Friends", a Made-for-Kids show for ages 2-5.
(Owner 21 Nov: the old episodes were "too static, stalling, idle, unfunny, uncatchy, boring". Make kids giggle.)
Characters (our own): Bloop (blue water-drop, curious, a bit clumsy: says "Oopsie-doodle!" when things go wrong),
Pip (small yellow, bouncy, loves to sing), Mo (tall green, gentle, slow and surprised), Dee (coral, round ears, clever
helper). An off-screen narrator talks to the child like a playful favourite teacher: excited, warm, asks the child to
help ("Can you help? Point to it!"), cheers when they do. The friends talk TO the child too.
Situation: {situation}. Setting: {setting}. Learning target: counting from 1 to {n}.
The problem: there are {n} empty round spots and each needs one {obj}; the {objs} keep rolling, bouncing or hiding
in silly ways, so the friends must count to know if they have enough. The counting itself is added automatically,
so do NOT write any counting lines.
What makes it fun (use all of these): the VERY FIRST line is a surprise or a silly mishap that grabs attention at
once (no slow hello first); gentle slapstick (slipping, bonking softly, a {obj} bouncing off Mo's head); a running gag
that comes back 2-3 times; one short catchy chant everyone repeats ("{objs}, {objs}, one by one!"); a funny surprise
twist before the happy ending. Quick back-and-forth between characters.
Rules: 3-8 simple words per line, happy and kind, never mean. No scary, sad or violent moments, no brands, no famous
songs or characters. Never ask the child to like, subscribe, comment or tap anything.
Return JSON only:
{{"adjective": "one fun adjective for the {objs}, e.g. bouncy",
"intro": [2-3 lines: line 1 is the surprise/mishap (e.g. Bloop: "Oopsie-doodle! The {objs} are bouncing away!"),
  then a quick excited hello to the child],
"problem": [4-6 lines: line 1 is the narrator asking the child for help right away, a direct challenge in your own
  words (the Short starts here), then the {objs} misbehave, the {n} empty spots, "do we have enough?", the chant,
  "let's count!"],
"after_count": [2-4 lines: a big happy cheer, the running gag comes back, every spot has one {obj}],
"ending": [3-4 lines: the funny twist, then the happy ending and the lesson (counting tells us how many)],
"goodbye": [1-2 short, upbeat lines with the chant or catchphrase (the narrator: proud of the child)],
"description": "2 plain sentences for parents about what the child learns"}}
Every line is {{"who": "Bloop|Pip|Mo|Dee|narrator", "say": "..."}}."""

FALLBACK = {
    "adjective": "little",
    "intro": [{"who": "narrator", "say": "Hello, my little friend! I'm so happy you're here."},
              {"who": "Bloop", "say": "Hi! I am Bloop!"},
              {"who": "Pip", "say": "Hello! I am Pip!"}, {"who": "Mo", "say": "Hi, friend. I am Mo."},
              {"who": "Dee", "say": "And I am Dee!"}],
    "problem": [{"who": "Bloop", "say": "Look! Some empty spots!"}, {"who": "Dee", "say": "Each spot needs one {obj}."},
                {"who": "Mo", "say": "Do we have enough {objs}?"}, {"who": "Pip", "say": "Let's count and see!"}],
    "after_count": [{"who": "Dee", "say": "Every spot has one {obj}!"}, {"who": "Pip", "say": "Hooray! We have enough!"}],
    "ending": [{"who": "Mo", "say": "Counting helped us today."}, {"who": "Bloop", "say": "Now we know how many!"},
               {"who": "narrator", "say": "You counted so well, friend."}],
    "goodbye": [{"who": "Bloop", "say": "Bye-bye, friend!"}, {"who": "narrator", "say": "See you next time!"}],
    "description": "Your child counts objects one by one with Bloop and friends. They practise saying each number "
                   "and matching it to one object.",
}


# ---------- script ----------

def _clean(lines, section: str, kind: str = "story") -> list[dict]:
    out = []
    for ln in lines or []:
        if not isinstance(ln, dict):
            continue
        say = re.sub(r"\s+", " ", str(ln.get("say", ""))).strip()
        who = ln.get("who") if ln.get("who") in CAST else "narrator"
        if say and not BANNED.search(say):
            out.append({"who": who, "say": say, "kind": kind, "section": section})
    return out


ADJ_DEFAULT = {"apple": "red", "star": "shiny", "balloon": "bright", "duck": "yellow", "flower": "pretty",
               "ball": "bouncy", "fish": "orange", "cupcake": "yummy", "strawberry": "juicy", "butterfly": "pretty",
               "leaf": "green", "car": "shiny", "cookie": "crunchy", "carrot": "crunchy"}
ADJ_OK = {"shiny", "bright", "bouncy", "yummy", "red", "yellow", "orange", "pretty", "happy", "sparkly", "juicy",
          "colorful", "colourful", "fluffy", "soft", "round", "sweet", "golden", "sunny", "cheerful", "twinkly",
          "lovely", "rosy", "crunchy", "splashy", "friendly", "jolly", "glowing", "gentle", "pink", "blue", "green"}


def _adjective(story: dict, obj: str = "") -> str:
    """The writer's adjective if it is a gentle, title-safe word, else a fixed one for the object."""
    words = re.sub(r"[^a-z\- ]", "", str(story.get("adjective") or "").lower()).split()
    return words[0] if words and words[0] in ADJ_OK else ADJ_DEFAULT.get(obj, "happy")


def _nar(say: str, kind: str, section: str) -> dict:
    return {"who": "narrator", "say": say, "kind": kind, "section": section}


def build_lines(story: dict, n: int, obj: str, seed: int = 0) -> list[dict]:
    """Story parts from the writer + counting rounds built by code (so the numbers are always right), with the
    child invited in: help us? say the word, what colour?, praise after every answer (varied, never the same)."""
    objs = PLURAL.get(obj, obj + "s")
    adj = _adjective(story, obj)
    order = list(CAST)
    praise = [PRAISE[(seed + k) % len(PRAISE)] for k in range(len(PRAISE))]
    lines = _clean(story.get("intro"), "intro")
    lines += [_nar("Will you help us today? Say, yes!", "callout", "help"),
              _nar("Yay! Thank you, friend!", "praise", "help")]
    lines += _clean(story.get("problem"), "problem")
    lines += [_nar(f"Can you say, {obj}?", "callout", "say"), _nar(f"{obj.capitalize()}! {praise[0]}", "praise", "say")]
    lines += [{"who": order[(k - 1) % 4], "say": f"{NUM[k].capitalize()} {adj} {obj if k == 1 else objs}!",
               "kind": "count", "n": k, "section": "count"} for k in range(1, n + 1)]
    lines += [{"who": "narrator", "say": f"How many {objs} did we count?", "kind": "question", "section": "count"},
              {"who": "narrator", "say": f"{NUM[n].capitalize()}! We counted {NUM[n]} {objs}!", "kind": "answer",
               "n": n, "section": "count"}]
    lines += _clean(story.get("after_count"), "after_count")
    colour = OBJECT_COLOUR.get(obj)
    if colour:                                                  # a second learning target: colours
        lines += [_nar(f"What colour are the {objs}?", "question", "colour"),
                  _nar(f"{colour.capitalize()}! The {objs} are {colour}! {praise[1]}", "praise", "colour")]
    lines += [{"who": "narrator", "say": "Let's count them again, all together!", "kind": "story",
               "section": "together"}]
    lines += [{"who": "all", "say": f"{NUM[k].capitalize()}!", "kind": "together", "n": k, "section": "together"}
              for k in range(1, n + 1)]
    lines += [{"who": "Pip", "say": "Now let's clap and count!", "kind": "story", "section": "clap"}]
    lines += [{"who": "all", "say": f"{NUM[k].capitalize()}!", "kind": "clap", "n": k, "section": "clap"}
              for k in range(1, n + 1)]
    lines += [{"who": "narrator", "say": f"Can you show me {NUM[n]} fingers?", "kind": "question",
               "section": "fingers"},
              {"who": "narrator", "say": f"{praise[2]} {NUM[n].capitalize()} fingers!", "kind": "answer", "n": n,
               "section": "fingers"}]
    lines += _clean(story.get("ending"), "ending")
    lines += [{"who": "narrator", "say": f"Today we counted to {NUM[n]}!", "kind": "answer", "n": n,
               "section": "ending"},
              _nar("You did so well today. I'm proud of you.", "praise", "ending")]
    lines += _clean(story.get("goodbye"), "goodbye", "wave")
    return lines


def qa(lines: list[dict], n: int, rounds_needed: int = 3) -> dict:
    """Spoken number == digit == objects: every round counts 1..n exactly, in order."""
    rounds: dict[str, list[int]] = {}
    for ln in lines:
        if ln["kind"] in ("count", "together", "clap"):
            rounds.setdefault(ln["kind"], []).append(int(ln["n"]))
            if NUM[int(ln["n"])] not in ln["say"].lower():
                return {"counts_ok": False, "why": f"line does not say its number: {ln['say']}"}
    ok = len(rounds) == rounds_needed and all(v == list(range(1, n + 1)) for v in rounds.values())
    return {"counts_ok": ok, "rounds": len(rounds), "count_to": n}


def plan_topics(n_items: int, seed: int, kinds: list[str] | None = None) -> list[dict]:
    """Week-planner topics for Bloop & Friends: each one a different counting lesson, object and situation
    (YouTube's 'same situation, same outcome' rule), written so plan_episode() can read them back."""
    rng = random.Random(seed)
    xmas = christmas_season()
    objs = list(XMAS_OBJECTS) if xmas else [o for o in OBJECTS if o not in XMAS_OBJECTS]
    rng.shuffle(objs)
    sits = list(XMAS_SITUATIONS if xmas else SITUATIONS)
    rng.shuffle(sits)
    out = []
    for i in range(n_items):
        short = bool(kinds and i < len(kinds) and kinds[i] != "long")
        obj = objs[i % len(objs)]
        n = rng.choice([4, 5, 5, 6]) if short else rng.choice([5, 6, 7, 8, 10])
        if "beach" in OBJECTS[obj]:
            n = min(n, 5)
        sit = sits[i % len(sits)]
        out.append({"topic": f"count from 1 to {n} with {PLURAL.get(obj, obj + 's')}: {sit}",
                    "angle": f"Bloop and friends count {PLURAL.get(obj, obj + 's')} ({sit})",
                    "why": "one learning target, a new situation and object each time"})
    return out


def plan_episode(brain, seed: int, lesson: str | None = None, max_n: int = 10) -> dict:
    rng = random.Random(seed)
    obj = (next((o for o in sorted(OBJECTS, key=len, reverse=True) if lesson and o in lesson.lower()), None)
           or rng.choice([o for o in OBJECTS if o not in XMAS_OBJECTS]))
    scene = rng.choice(OBJECTS[obj])
    n = rng.choice([5, 5, 6, 7, 8, 10])
    m = re.search(r"\b(?:to|till|until)\s+(\d+)", lesson or "")
    if m:
        n = max(3, min(10, int(m.group(1))))
    if scene == "beach":
        n = min(n, 5)                                         # one row of fish in the sea
    if not m:
        n = min(n, max_n)
    situation = (next((x for x in SITUATIONS + XMAS_SITUATIONS if lesson and x.lower() in lesson.lower()), None)
                 or rng.choice(XMAS_SITUATIONS if obj in XMAS_OBJECTS else SITUATIONS))
    objs = PLURAL.get(obj, obj + "s")
    try:
        prompt = STORY_PROMPT.format(situation=situation, setting=scene, n=n, obj=obj, objs=objs)
        try:                               # S6: the channel's running experiment + the rules its numbers proved
            from .scorecard import writer_rule
            extra = writer_rule("bloop_and_friends")
        except Exception as e:  # noqa: BLE001 - the story is still written (said, never silent)
            print(f"kids: experiment rule unavailable ({type(e).__name__}: {e})")
            extra = ""
        if extra:
            prompt += "\n" + extra
        story, res = brain.ask_json("writer", prompt, temperature=0.7)
        writer = res.provider
    except Exception:                                       # no writer today: a safe template, still correct
        story = json.loads(json.dumps(FALLBACK).replace("{obj}", obj).replace("{objs}", objs))
        writer = "template"
    lines = build_lines(story, n, obj, seed=seed)
    return {"object": obj, "scene": scene, "count_to": n, "situation": situation, "adjective": _adjective(story, obj),
            "lines": lines, "description": str(story.get("description", "")), "_written_by": writer}


# ---------- voices ----------

def kid_pitch() -> dict[str, float]:
    """voice id -> semitones up for the human friends (S10, 21 Nov: Kokoro's adult voices made 5-year-olds sound like
    grown-ups); config/characters.yaml `pitch`, default +2."""
    try:
        from .media import characters
        return {str(c.get("voice")): float(c.get("pitch", 2.0))
                for c in (characters.bible().get("characters") or {}).values() if c.get("voice")}
    except Exception as e:  # noqa: BLE001 - no bible: natural voices (said, never silent)
        print(f"kids: kid voices unchanged ({type(e).__name__}: {e})")
        return {}


def pitch_up(src: Path, semitones: float) -> Path:
    """A younger-sounding copy of a voice line: resample up (pitch + speed), then slow back to the same length.
    ffmpeg asetrate + atempo (no extra library); formants rise a little too, which reads as a child's voice."""
    import soundfile as _sf
    from .media import ffmpeg as ff
    if not semitones:
        return src
    sr = _sf.info(str(src)).samplerate
    f = 2 ** (semitones / 12)
    dst = src.with_name(src.stem + "_kid.wav")
    ff.run(["-i", str(src), "-af", f"asetrate={int(sr * f)},aresample={sr},atempo={1 / f:.5f}", str(dst)])
    return dst


class Voices:
    """Kokoro voice per character (cached, levelled to the same loudness, 48 kHz); human friends a little higher."""

    def __init__(self, work: Path, speed: float = 0.92, pitch: dict[str, float] | None = None):
        self.work, self.speed, self.cache, self.bad = work, speed, {}, set()
        self.pitch = kid_pitch() if pitch is None else pitch

    def say(self, text: str, voice: str) -> np.ndarray:
        key = (text, voice)
        if key in self.cache:
            return self.cache[key]
        path = self.work / f"v_{len(self.cache):03d}.wav"
        v = NARRATOR if voice in self.bad else voice
        try:
            synthesize(text, path, v, "en-gb" if v.startswith("b") else "en", speed=self.speed, trim=True)
        except Exception:                                   # voice not available: use the narrator's
            self.bad.add(voice)
            synthesize(text, path, NARRATOR, "en", speed=self.speed, trim=True)
        if voice not in self.bad and self.pitch.get(voice):
            try:
                path = pitch_up(path, self.pitch[voice])
            except Exception as e:  # noqa: BLE001 - the natural voice still works (said, never silent)
                print(f"kids: pitch lift skipped for {voice} ({type(e).__name__}: {e})")
        a, sr = sf.read(path, dtype="float32")
        a = a.mean(axis=1) if a.ndim > 1 else a
        g = gcd(au.SR, sr)
        a = resample_poly(a, au.SR // g, sr // g).astype(np.float32)
        a = np.clip(a * (0.1 / (np.sqrt(np.mean(a ** 2)) + 1e-9)), -0.98, 0.98)
        self.cache[key] = a
        return a


def build_timeline(lines: list[dict], voices: Voices, tail: float = 2.5) -> float:
    """Adds start/end/hold (s) and the voice clips to every line. Returns the total length."""
    t, prev = FIRST_WORD_S, None                             # the hook is spoken at once (was 2 s of music first)
    for ln in lines:
        if ln["who"] == "all":                               # everyone says it together (a little chorus)
            parts = {name: voices.say(ln["say"], spec[3]) for name, spec in CAST.items()}
            parts["narrator"] = voices.say(ln["say"], NARRATOR)
        else:
            parts = {ln["who"]: voices.say(ln["say"], NARRATOR if ln["who"] == "narrator" else CAST[ln["who"]][3])}
        dur = max(len(a) for a in parts.values()) / au.SR + 0.04
        if prev and prev["section"] != ln["section"]:
            t += 0.5
        if ln["kind"] in ("count", "together", "clap"):
            t = math.ceil(t / BEAT - 1e-6) * BEAT
        ln.update(start=round(t, 3), end=round(t + dur, 3), hold=round(t + dur + GAPS[ln["kind"]], 3))
        ln["_parts"] = parts
        t, prev = ln["hold"], ln
    return t + tail                                          # calm instrumental goodbye


def voice_tracks(lines: list[dict], total: float) -> dict[str, np.ndarray]:
    n = int(total * au.SR) + au.SR
    tracks = {name: np.zeros(n, np.float32) for name in [*CAST, "narrator"]}
    offsets = {"Bloop": 0.0, "Pip": 0.018, "Mo": 0.035, "Dee": 0.012, "narrator": 0.026}
    for ln in lines:
        chorus = len(ln["_parts"]) > 1
        for who, clip in ln["_parts"].items():
            au.place(tracks[who], clip * (0.5 if chorus else 1.0),
                     ln["start"] + (offsets.get(who, 0.022) if chorus else 0.0))     # guests + humans: no KeyError
    return {k: v[: int(total * au.SR)] for k, v in tracks.items()}


def _mouth(track: np.ndarray) -> np.ndarray:
    hop = au.SR // FPS
    n = len(track) // hop
    rms = np.sqrt(np.mean(track[: n * hop].reshape(n, hop) ** 2, axis=1))
    loud = rms[rms > 1e-4]
    ref = np.percentile(loud, 95) if len(loud) else 1.0
    m = np.clip((rms / (ref + 1e-9) - 0.08) * 1.4, 0, 1)
    return np.convolve(m, np.ones(2) / 2, mode="same")


# ---------- drawing ----------

def _vgrad(top, bot, h: int, w: int) -> np.ndarray:
    t = np.linspace(0, 1, h, dtype=np.float32)[:, None, None]
    g = np.array(top, np.float32) * (1 - t) + np.array(bot, np.float32) * t
    return np.repeat(g, w, axis=1).astype(np.uint8)


def _paint(img: np.ndarray, color, draw, alpha: float = 1.0, blur: float = 0.0) -> None:
    """Draws a shape (anti-aliased mask) onto img in one colour, optionally soft (blur) or see-through."""
    m = np.zeros(img.shape[:2], np.uint8)
    draw(m)
    if blur:
        m = cv2.GaussianBlur(m, (0, 0), blur)
    a = (m.astype(np.float32) / 255 * alpha)[..., None]
    img[:] = (img.astype(np.float32) * (1 - a) + np.array(color, np.float32) * a).astype(np.uint8)


def _hill(y0: int, amp: float, period: float, phase: float):
    pts = [(x, int(y0 + amp * math.sin(x / period + phase))) for x in range(0, CW + 41, 40)]
    poly = np.array([(0, CH), *pts, (CW, CH)], np.int32)
    return lambda m: cv2.fillPoly(m, [poly], 255, cv2.LINE_AA)


def _sun(img, c, r, color=None) -> None:
    color = color or PAL["sun"]
    _paint(img, color, lambda m: cv2.circle(m, c, int(r * 1.7), 255, -1, cv2.LINE_AA), alpha=0.35, blur=r * 0.5)
    _paint(img, color, lambda m: cv2.circle(m, c, r, 255, -1, cv2.LINE_AA))


def _tree(img, x: int, base: int, s: int) -> None:
    _paint(img, PAL["trunk"], lambda m: cv2.rectangle(m, (x - s // 14, base - int(s * 0.6)), (x + s // 14, base), 255, -1))
    blobs = [(0, -0.78, 0.36), (-0.26, -0.62, 0.27), (0.27, -0.64, 0.29), (0.05, -0.55, 0.3)]
    _paint(img, PAL["leaf2"], lambda m: [cv2.circle(m, (x + int(dx * s), base + int(dy * s) + s // 30), int(r * s), 255,
                                                    -1, cv2.LINE_AA) for dx, dy, r in blobs])
    _paint(img, PAL["leaf"], lambda m: [cv2.circle(m, (x + int(dx * s), base + int(dy * s)), int(r * s * 0.94), 255,
                                                   -1, cv2.LINE_AA) for dx, dy, r in blobs])


def _cloud_sprite(w: int) -> np.ndarray:
    h, S = int(w * 0.55), 2
    m = np.zeros((h * S, w * S), np.uint8)
    for px, py, pr in [(0.27, 0.62, 0.2), (0.47, 0.45, 0.27), (0.7, 0.55, 0.22), (0.5, 0.68, 0.22)]:
        cv2.circle(m, (int(px * w * S), int(py * h * S)), int(pr * w * S), 255, -1, cv2.LINE_AA)
    cv2.rectangle(m, (int(0.25 * w * S), int(0.6 * h * S)), (int(0.75 * w * S), int(0.82 * h * S)), 255, -1)
    m = cv2.resize(m, (w, h), interpolation=cv2.INTER_AREA)
    spr = np.zeros((h, w, 4), np.uint8)
    shade = np.linspace(255, 232, h, dtype=np.float32)[:, None]
    spr[..., 0] = 255
    spr[..., 1] = np.clip(shade + 8, 0, 255).astype(np.uint8)
    spr[..., 2] = shade.astype(np.uint8)
    spr[..., 3] = (m.astype(np.float32) * 0.95).astype(np.uint8)
    return spr


def scene_plate(scene: str, rng) -> tuple[np.ndarray, dict]:
    """The still background (drawn once) + what moves in it (clouds, waves). For the tall Short canvas the
    normal scene is drawn, then the sky (or wall) continues upward and the ground downward."""
    if not DY:
        return _scene_plate(scene, rng)
    g = globals()
    saved = (g["CH"], g["FEET_Y"])
    g["CH"], g["FEET_Y"] = 1296, 1170
    try:
        sub, extras = _scene_plate(scene, rng, sun=False)
    finally:
        g["CH"], g["FEET_Y"] = saved
    img = np.empty((CH, CW, 3), np.uint8)
    img[:DY] = sub[0]
    img[DY:DY + sub.shape[0]] = sub
    ground = {"room": "wood2", "night": "nground", "beach": "sand"}.get(scene, "grass")
    img[DY + sub.shape[0]:] = PAL[ground]                                 # floor / ground continues down
    if scene == "night":
        for _ in range(25):
            x, y, r = int(rng.uniform(20, CW - 20)), int(rng.uniform(20, DY)), int(rng.choice([2, 3]))
            _paint(img, PAL["white"], lambda m, x=x, y=y, r=r: cv2.circle(m, (x, y), r, 255, -1, cv2.LINE_AA), alpha=0.75)
        _sun(img, (CW - 230, 250), 85, PAL["moon"])                       # moon high in the tall sky
    elif scene != "room":
        _sun(img, (CW - 230, 250), 100)
    extras["dy"], extras["cloud_dy"] = DY, 0                              # clouds stay in the top sky
    return img, extras


def _scene_plate(scene: str, rng, sun: bool = True) -> tuple[np.ndarray, dict]:
    extras: dict = {"clouds": [], "waves": False}
    if scene == "room":
        img = _vgrad(PAL["wall"], PAL["wall2"], CH, CW)          # lavender nursery wall (was beige: colourfulness 46)
        img[880:] = _vgrad(PAL["wood"], PAL["wood2"], CH - 880, CW)
        img[862:892] = PAL["base"]
        x0, y0, x1, y1 = (CW - 470, 90, CW - 130, 330) if CW > 1500 else (CW - 380, 60, CW - 90, 270)  # window
        img[y0:y1, x0:x1] = _vgrad(PAL["sky"], PAL["sky2"], y1 - y0, x1 - x0)
        blit(img, _cloud_sprite(170), x0 + 110, y0 + 80)
        for r in ((x0, y0, x1, y0 + 18), (x0, y1 - 18, x1, y1), (x0, y0, x0 + 18, y1), (x1 - 18, y0, x1, y1),
                  ((x0 + x1) // 2 - 7, y0, (x0 + x1) // 2 + 7, y1), (x0, (y0 + y1) // 2 - 7, x1, (y0 + y1) // 2 + 7)):
            cv2.rectangle(img, r[:2], r[2:], PAL["white"], -1)
        cv2.rectangle(img, (x0 - 30, y1), (x1 + 30, y1 + 26), PAL["base"], -1)
        cv2.line(img, (x0 - 110, y0 - 30), (x1 + 110, y0 - 30), PAL["trunk"], 10, cv2.LINE_AA)
        for cx in (x0 - 45, x1 + 45):                                         # curtains
            _paint(img, PAL["coral"], lambda m, cx=cx: cv2.ellipse(m, (cx, y0 + 105), (50, 140 if CW > 1500 else 120), 0, 0, 360, 255, -1,
                                                                       cv2.LINE_AA))
        cv2.rectangle(img, (150, 250), (560, 274), PAL["trunk"], -1)        # shelf with toy blocks
        for (bx, by, col) in ((190, 180, "coral"), (275, 180, "teal"), (232, 110, "sun")):
            rounded_rect(img, bx, by, bx + 72, by + 70, 12, PAL[col])
        _paint(img, PAL["coral2"], lambda m: cv2.ellipse(m, (CW // 2, FEET_Y + 25), (880, 105), 0, 0, 360, 255, -1,
                                                         cv2.LINE_AA))
        cv2.ellipse(img, (CW // 2, FEET_Y + 25), (800, 82), 0, 0, 360, PAL["cream"], 8, cv2.LINE_AA)
    elif scene == "night":
        img = _vgrad(PAL["night"], PAL["night2"], CH, CW)
        for _ in range(60):
            x, y, r = int(rng.uniform(20, CW - 20)), int(rng.uniform(20, 760)), int(rng.choice([2, 2, 3, 4]))
            _paint(img, PAL["white"], lambda m, x=x, y=y, r=r: cv2.circle(m, (x, y), r, 255, -1, cv2.LINE_AA), alpha=0.75)
        if sun:
            _sun(img, (CW - 330, 215), 95, PAL["moon"])
        _paint(img, PAL["nhill"], _hill(790, 45, 360, rng.uniform(0, 6)))
        _paint(img, PAL["nground"], _hill(905, 28, 520, rng.uniform(0, 6)))
    else:
        img = _vgrad(PAL["sky"], PAL["sky2"], CH, CW)
        if sun:
            _sun(img, (CW - 330, 215), 112)
        extras["clouds"] = [(_cloud_sprite(int(w)), x, y, sp) for w, x, y, sp in
                            ((300, 300, 170, 7.0), (220, 1150, 120, 5.0), (260, 1900, 290, 9.0))]
        if scene == "beach":
            img[520:880] = _vgrad(PAL["sea2"], PAL["sea"], 360, CW)
            _paint(img, PAL["sand"], _hill(880, 22, 600, rng.uniform(0, 6)))
            pole_x = CW - 230
            if CW > 1500:                                                     # no room for it in the Short
                cv2.line(img, (pole_x, 560), (pole_x + 30, 1000), PAL["trunk"], 14, cv2.LINE_AA)
                for i in range(6):
                    col = PAL["coral"] if i % 2 == 0 else PAL["white"]
                    _paint(img, col, lambda m, i=i: cv2.ellipse(m, (pole_x, 600), (240, 130), 0, 180 + i * 30,
                                                                180 + (i + 1) * 30, 255, -1, cv2.LINE_AA))
            extras["waves"] = True
        else:
            _paint(img, PAL["grass2"], _hill(770, 50, 380, rng.uniform(0, 6)))
            if scene == "garden":
                for x in range(-20, CW + 120, 120):                          # white picket fence
                    poly = np.array([(x - 24, 905), (x - 24, 730), (x, 700), (x + 24, 730), (x + 24, 905)], np.int32)
                    _paint(img, PAL["white"], lambda m, poly=poly: cv2.fillPoly(m, [poly], 255, cv2.LINE_AA))
                cv2.rectangle(img, (0, 762), (CW, 786), PAL["white"], -1)
                cv2.rectangle(img, (0, 842), (CW, 866), PAL["white"], -1)
            else:
                for x, s in (((190, 520), (CW - 200, 470)) if CW > 1500 else ((70, 300), (CW - 70, 280))):
                    _tree(img, x, 880, s)
            _paint(img, PAL["grass"], _hill(890, 26, 520, rng.uniform(0, 6)))
            if scene == "garden":
                for x in range(60, CW, 230):                                  # flower bushes along the fence
                    _paint(img, PAL["bush"], lambda m, x=x: cv2.ellipse(m, (x, 905), (110, 60), 0, 180, 360, 255, -1,
                                                                        cv2.LINE_AA))
                    for k, col in enumerate(("coral", "lavender", "sun")):
                        cx, cy = x - 55 + k * 55, 868 + (k % 2) * 14
                        _paint(img, PAL[col], lambda m, cx=cx, cy=cy: cv2.circle(m, (cx, cy), 16, 255, -1, cv2.LINE_AA))
    return img, extras


def draw_extras(canvas: np.ndarray, extras: dict, t: float) -> None:
    dy = extras.get("dy", 0)
    for spr, x0, y, speed in extras["clouds"]:
        span = CW + spr.shape[1] * 2
        x = (x0 + speed * t) % span - spr.shape[1]
        blit(canvas, spr, x, y + extras.get("cloud_dy", dy))
    if extras["waves"]:
        for k in range(3):
            y = dy + 560 + k * 105
            pts = np.array([(x, int(y + 6 * math.sin(x / 70 + t * 1.4 + k * 1.7))) for x in range(0, CW + 30, 30)],
                           np.int32)
            cv2.polylines(canvas, [pts], False, PAL["foam"], 5, cv2.LINE_AA)


def draw_object(kind: str, size: int, color=None) -> np.ndarray:
    """BGRA sprite of a simple, friendly object (drawn at 2x then shrunk for smooth edges), ink outline."""
    if kind in XMAS_ART:                                   # Christmas set: the colouring-book art, in colour
        from .christmas_book import xmas_object
        return xmas_object(XMAS_ART[kind], size)
    S = size * 2
    im = np.zeros((S, S, 4), np.uint8)
    c = color or {"apple": (80, 80, 235), "star": (70, 212, 255), "balloon": (210, 120, 180), "duck": (80, 220, 255),
                  "flower": (200, 140, 255), "ball": (225, 150, 70), "fish": (60, 160, 250),
                  "cupcake": (200, 170, 255), "strawberry": (70, 60, 230), "butterfly": (235, 170, 70),
                  "leaf": (90, 190, 110), "car": (220, 150, 60), "cookie": (90, 170, 225), "carrot": (40, 140, 250)}[kind]
    col = tuple(int(v) for v in c) + (255,)
    m = S // 2
    if kind == "apple":
        cv2.circle(im, (m, m + S // 16), int(S * 0.36), col, -1, cv2.LINE_AA)
        cv2.line(im, (m, m - S // 4), (m + S // 16, m - S // 2 + S // 10), (40, 80, 110, 255), S // 18, cv2.LINE_AA)
        cv2.ellipse(im, (m + S // 7, m - S // 3), (S // 9, S // 18), -30, 0, 360, (80, 180, 80, 255), -1, cv2.LINE_AA)
    elif kind == "star":
        ang = np.linspace(-np.pi / 2, 1.5 * np.pi, 11)[:-1]
        rad = np.where(np.arange(10) % 2 == 0, S * 0.45, S * 0.21)
        pts = np.stack([m + rad * np.cos(ang), m + 0.04 * S + rad * np.sin(ang)], 1).astype(np.int32)
        cv2.fillPoly(im, [pts], col, cv2.LINE_AA)
    elif kind == "balloon":
        cv2.ellipse(im, (m, int(S * 0.4)), (int(S * 0.3), int(S * 0.36)), 0, 0, 360, col, -1, cv2.LINE_AA)
        cv2.line(im, (m, int(S * 0.76)), (m - S // 12, S - 4), (*INK, 255), 4, cv2.LINE_AA)
    elif kind == "duck":
        cv2.ellipse(im, (m, int(S * 0.62)), (int(S * 0.36), int(S * 0.22)), 0, 0, 360, col, -1, cv2.LINE_AA)
        cv2.circle(im, (m + S // 6, int(S * 0.36)), int(S * 0.16), col, -1, cv2.LINE_AA)
        cv2.ellipse(im, (m + S // 3, int(S * 0.38)), (S // 9, S // 20), 0, 0, 360, (40, 150, 250, 255), -1, cv2.LINE_AA)
        cv2.circle(im, (m + S // 5, int(S * 0.33)), S // 40, (*INK, 255), -1, cv2.LINE_AA)
    elif kind == "flower":
        for k in range(6):
            a = k * np.pi / 3
            cv2.circle(im, (int(m + S * 0.22 * math.cos(a)), int(m + S * 0.22 * math.sin(a))), int(S * 0.16), col, -1,
                       cv2.LINE_AA)
        cv2.circle(im, (m, m), int(S * 0.14), (70, 212, 255, 255), -1, cv2.LINE_AA)
    elif kind == "ball":                                        # beach ball: coloured wedges + white hub
        r = int(S * 0.4)
        wedges = [(80, 80, 235), (255, 255, 255), (70, 212, 255), (255, 255, 255), (225, 150, 70), (255, 255, 255)]
        for k, wc in enumerate(wedges):
            cv2.ellipse(im, (m, m), (r, r), -90, k * 60, (k + 1) * 60, (*wc, 255), -1, cv2.LINE_AA)
        cv2.circle(im, (m, m), S // 14, (255, 255, 255, 255), -1, cv2.LINE_AA)
        cv2.circle(im, (m, m), S // 14, (*INK, 255), 3, cv2.LINE_AA)
    elif kind == "fish":
        cv2.ellipse(im, (int(S * 0.45), m), (int(S * 0.3), int(S * 0.2)), 0, 0, 360, col, -1, cv2.LINE_AA)
        tail = np.array([[int(S * 0.72), m], [int(S * 0.92), int(S * 0.3)], [int(S * 0.92), int(S * 0.7)]], np.int32)
        cv2.fillPoly(im, [tail], col, cv2.LINE_AA)
        cv2.circle(im, (int(S * 0.3), int(S * 0.45)), S // 30, (*INK, 255), -1, cv2.LINE_AA)
    elif kind == "strawberry":                                  # round top, pointed bottom, seeds, leaves
        body = np.array([(int(S * 0.16), int(S * 0.38)), (int(S * 0.84), int(S * 0.38)), (m, int(S * 0.92))], np.int32)
        cv2.fillPoly(im, [body], col, cv2.LINE_AA)
        for sx in (0.33, 0.67):
            cv2.circle(im, (int(S * sx), int(S * 0.42)), int(S * 0.18), col, -1, cv2.LINE_AA)
        for k in range(9):
            x = int(S * (0.32 + 0.18 * (k % 3) + 0.04 * (k // 3 % 2)))
            y = int(S * (0.42 + 0.13 * (k // 3)))
            if abs(x - m) < (S * 0.92 - y) * 0.55:
                cv2.ellipse(im, (x, y), (S // 70, S // 45), 0, 0, 360, (90, 220, 255, 255), -1, cv2.LINE_AA)
        for a in (-50, -15, 15, 50):
            cv2.ellipse(im, (m + int(S * 0.0035 * a), int(S * 0.26)), (S // 9, S // 26), a, 0, 360,
                        (90, 175, 80, 255), -1, cv2.LINE_AA)
    elif kind == "butterfly":                                   # four wings, little body, antennae
        for sx in (-1, 1):
            cv2.ellipse(im, (m + sx * int(S * 0.2), int(S * 0.38)), (int(S * 0.2), int(S * 0.17)), sx * 25, 0, 360, col,
                        -1, cv2.LINE_AA)
            cv2.ellipse(im, (m + sx * int(S * 0.16), int(S * 0.64)), (int(S * 0.14), int(S * 0.12)), -sx * 20, 0, 360,
                        tuple(int(v * 0.85) for v in c) + (255,), -1, cv2.LINE_AA)
            cv2.circle(im, (m + sx * int(S * 0.22), int(S * 0.37)), S // 16, (255, 255, 255, 255), -1, cv2.LINE_AA)
            cv2.line(im, (m, int(S * 0.3)), (m + sx * int(S * 0.12), int(S * 0.1)), (*INK, 255), S // 60, cv2.LINE_AA)
            cv2.circle(im, (m + sx * int(S * 0.12), int(S * 0.1)), S // 45, (*INK, 255), -1, cv2.LINE_AA)
        cv2.ellipse(im, (m, int(S * 0.5)), (S // 22, int(S * 0.22)), 0, 0, 360, (*INK, 255), -1, cv2.LINE_AA)
    elif kind == "leaf":                                        # a big leaf with a middle vein and a stem
        cv2.ellipse(im, (m, m), (int(S * 0.38), int(S * 0.22)), -35, 0, 360, col, -1, cv2.LINE_AA)
        p0 = (m - int(S * 0.3), m + int(S * 0.21))
        p1 = (m + int(S * 0.3), m - int(S * 0.21))
        cv2.line(im, p0, p1, (60, 140, 70, 255), S // 50, cv2.LINE_AA)
        cv2.line(im, p0, (p0[0] - S // 10, p0[1] + S // 14), (60, 110, 140, 255), S // 35, cv2.LINE_AA)
    elif kind == "car":                                         # a little toy car: body, cabin, windows, wheels
        cv2.rectangle(im, (int(S * 0.08), int(S * 0.45)), (int(S * 0.92), int(S * 0.7)), col, -1, cv2.LINE_AA)
        cab = np.array([(int(S * 0.26), int(S * 0.46)), (int(S * 0.36), int(S * 0.24)), (int(S * 0.66), int(S * 0.24)),
                        (int(S * 0.78), int(S * 0.46))], np.int32)
        cv2.fillPoly(im, [cab], col, cv2.LINE_AA)
        for x0, x1 in ((0.33, 0.49), (0.53, 0.7)):
            win = np.array([(int(S * x0), int(S * 0.44)), (int(S * (x0 + 0.05)), int(S * 0.29)),
                            (int(S * (x1 - 0.03)), int(S * 0.29)), (int(S * x1), int(S * 0.44))], np.int32)
            cv2.fillPoly(im, [win], (250, 235, 200, 255), cv2.LINE_AA)
        for x in (0.27, 0.73):
            cv2.circle(im, (int(S * x), int(S * 0.72)), int(S * 0.11), (*INK, 255), -1, cv2.LINE_AA)
            cv2.circle(im, (int(S * x), int(S * 0.72)), int(S * 0.045), (220, 220, 220, 255), -1, cv2.LINE_AA)
    elif kind == "cookie":                                      # round cookie with chocolate chips
        cv2.circle(im, (m, m), int(S * 0.4), col, -1, cv2.LINE_AA)
        for cx, cy in ((0.36, 0.36), (0.6, 0.32), (0.66, 0.56), (0.42, 0.62), (0.5, 0.47), (0.3, 0.52), (0.56, 0.72)):
            cv2.ellipse(im, (int(S * cx), int(S * cy)), (S // 22, S // 28), 30, 0, 360, (40, 70, 110, 255), -1,
                        cv2.LINE_AA)
    elif kind == "carrot":                                      # long orange carrot with green leaves
        body = np.array([(int(S * 0.3), int(S * 0.3)), (int(S * 0.7), int(S * 0.3)), (int(S * 0.52), int(S * 0.95)),
                         (int(S * 0.48), int(S * 0.95))], np.int32)
        cv2.fillPoly(im, [body], col, cv2.LINE_AA)
        cv2.ellipse(im, (m, int(S * 0.31)), (int(S * 0.2), int(S * 0.06)), 0, 0, 360, col, -1, cv2.LINE_AA)
        for k, y in enumerate((0.45, 0.6, 0.75)):
            x = m + (S // 12 if k % 2 else -S // 12)
            cv2.line(im, (x - S // 20, int(S * y)), (x + S // 20, int(S * y) - S // 60), (30, 110, 210, 255), S // 70,
                     cv2.LINE_AA)
        for a in (-30, 0, 30):
            cv2.ellipse(im, (m + int(S * 0.003 * a), int(S * 0.17)), (S // 26, S // 8), a, 0, 360, (90, 175, 80, 255), -1,
                        cv2.LINE_AA)
    else:  # cupcake: striped paper cup + swirl of frosting + cherry
        cup = np.array([(int(S * 0.24), int(S * 0.52)), (int(S * 0.76), int(S * 0.52)), (int(S * 0.68), int(S * 0.88)),
                        (int(S * 0.32), int(S * 0.88))], np.int32)
        cv2.fillPoly(im, [cup], (120, 175, 240, 255), cv2.LINE_AA)
        for k in range(1, 5):
            x = int(S * (0.24 + k * 0.104))
            cv2.line(im, (x, int(S * 0.54)), (int(m + (x - m) * 0.82), int(S * 0.86)), (95, 145, 215, 255), S // 40,
                     cv2.LINE_AA)
        for cx, cy, r in ((0.34, 0.5, 0.15), (0.66, 0.5, 0.15), (0.5, 0.45, 0.19), (0.5, 0.31, 0.13)):
            cv2.circle(im, (int(S * cx), int(S * cy)), int(S * r), col, -1, cv2.LINE_AA)
        cv2.circle(im, (m, int(S * 0.17)), int(S * 0.06), (80, 80, 235, 255), -1, cv2.LINE_AA)
    a = im[..., 3].copy()
    edge = cv2.dilate(a, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))) - a     # ink outline
    im[edge > 0] = (*INK, 255)
    im[..., 3] = np.maximum(a, edge)
    if kind in ("apple", "balloon", "ball", "fish", "duck", "cupcake", "star", "strawberry", "car"):  # soft shine
        sh = np.zeros((S, S), np.uint8)
        cv2.ellipse(sh, (int(m - S * 0.13), int(m - S * 0.12)), (S // 14, S // 24), -35, 0, 360, 255, -1, cv2.LINE_AA)
        w = (sh.astype(np.float32) / 255 * 0.7)[..., None]
        im[..., :3] = (im[..., :3] * (1 - w) + 255 * w).astype(np.uint8)
    return cv2.resize(im, (size, size), interpolation=cv2.INTER_AREA)


def _slot_sprite(r: int, night: bool) -> np.ndarray:
    S = 2
    size = (r * 2 + 24) * S
    im = np.zeros((size, size, 4), np.uint8)
    c = size // 2
    cv2.circle(im, (c, c), r * S, (255, 255, 255, 60 if night else 130), -1, cv2.LINE_AA)
    ring = (255, 255, 255, 230) if night else (*INK, 150)
    for i in range(0, 24, 2):
        cv2.ellipse(im, (c, c), (r * S, r * S), 0, i * 15, i * 15 + 9, ring, 6 * S, cv2.LINE_AA)
    return cv2.resize(im, (size // S, size // S), interpolation=cv2.INTER_AREA)


def _sparkle_sprite(s: int = 46) -> np.ndarray:
    S = s * 2
    im = np.zeros((S, S, 4), np.uint8)
    c = S // 2
    pts = []
    for k in range(8):
        a = k * np.pi / 4 - np.pi / 2
        r = S * 0.48 if k % 2 == 0 else S * 0.13
        pts.append((c + r * math.cos(a), c + r * math.sin(a)))
    cv2.fillPoly(im, [np.array(pts, np.int32)], (184, 244, 255, 255), cv2.LINE_AA)
    cv2.circle(im, (c, c), S // 9, (255, 255, 255, 255), -1, cv2.LINE_AA)
    return cv2.resize(im, (s, s), interpolation=cv2.INTER_AREA)


def slot_xy(n: int, scene: str = "") -> list[tuple[int, int]]:
    if CW < CH:                                           # tall Short: rows of up to 5
        rows = [n] if n <= 5 else [(n + 1) // 2, n // 2]
        ys = ([DY + 650] if scene == "beach" else [DY + 470]) if n <= 5 else \
            ([DY + 570, DY + 780] if scene == "beach" else [DY + 400, DY + 630])
        out = []
        for cnt, y in zip(rows, ys):
            gap = min(230, (CW - 240) // max(1, cnt))
            out += [(int(CW / 2 - gap * (cnt - 1) / 2 + i * gap), y) for i in range(cnt)]
        return out
    if n <= 5:
        gap, y = min(250, 1560 // n), (650 if scene == "beach" else 470)     # fish sit in the sea
        return [(int(CW / 2 - gap * (n - 1) / 2 + i * gap), y) for i in range(n)]
    top, gap = (n + 1) // 2, 270
    out = [(int(CW / 2 - gap * (top - 1) / 2 + i * gap), 420) for i in range(top)]
    bot = n - top
    return out + [(int(CW / 2 - gap * (bot - 1) / 2 + i * gap), 640) for i in range(bot)]


def _digit(k: int, size: int = 250) -> np.ndarray:
    return text_sprite(str(k), "Luckiest Guy", size, fill=DIGIT_COLORS[(k - 1) % len(DIGIT_COLORS)],
                       stroke=max(3, size // 18), stroke_fill="#FFFFFF", shadow=max(1, size // 30))


# ---------- camera ----------

def _solo_frame(who: str, z: float) -> tuple[float, float]:
    """A close shot of one speaker in which no other character is cut by the frame edge: zoom in until only the
    speaker is in shot (a clean close-up), or out until the whole group fits."""
    # real half-widths of the toon bodies (mascot.py: tall 0.29, sprout 0.33, others 0.35 of the sprite) + outline,
    # breathing and the ears/tip
    half = {n: spec[2] * {"tall": 0.32, "sprout": 0.36, "drop": 0.38, "ears": 0.41}.get(spec[1], 0.40)
            for n, spec in CAST.items()}
    x = CAST[who][4]
    ka, kb = x - half[who], x + half[who]
    left = max([CAST[n][4] + half[n] for n in CAST if n != who and CAST[n][4] < x] + [0.0])
    right = min([CAST[n][4] - half[n] for n in CAST if n != who and CAST[n][4] > x] + [float(CW)])
    w = min(CW / z, right - left)
    if w >= (kb - ka) and CW / w <= 2.4:                         # solo close-up fits
        cx = min(max(x, left + w / 2), right - w / 2)
        return cx, CW / w
    order = sorted(CAST, key=lambda n: CAST[n][4])                # two-shot: the speaker + one neighbour, both whole
    i = order.index(who)
    for j in (i - 1, i + 1):
        if not 0 <= j < len(order):
            continue
        pair = sorted((who, order[j]), key=lambda n: CAST[n][4])
        pa, pb = CAST[pair[0]][4] - half[pair[0]], CAST[pair[1]][4] + half[pair[1]]
        lo = max([CAST[n][4] + half[n] for n in CAST if n not in pair and CAST[n][4] < CAST[pair[0]][4]] + [0.0])
        hi = min([CAST[n][4] - half[n] for n in CAST if n not in pair and CAST[n][4] > CAST[pair[1]][4]] + [float(CW)])
        w2 = min(hi - lo, (pb - pa) + 60)
        if w2 >= pb - pa and CW / w2 <= 2.6:
            return min(max((pa + pb) / 2, lo + w2 / 2), hi - w2 / 2), CW / w2
    a = min(CAST[n][4] - half[n] for n in CAST)                 # otherwise frame the whole group
    b = max(CAST[n][4] + half[n] for n in CAST)
    w = min(float(CW), (b - a) + 80)
    return (a + b) / 2, CW / w


def plan_shots(lines: list[dict], total: float, slots) -> list[tuple[float, float, tuple]]:
    """Calm camera: wide, medium on a speaker, or close on the counting spots. Cuts only on line starts,
    never sooner than 4 s (2.5 s at a new section). Each shot slowly pushes in."""
    # close-up: the number + every spot, zoomed so the characters' heads stay out of the bottom edge
    top, bottom = DIGIT_Y - 140, max(y for _, y in slots) + SLOT_R + 60
    width = max(x for x, _ in slots) - min(x for x, _ in slots) + 2 * SLOT_R + 140
    z = min(1.7 if CW > CH else 1.25, CW / width, CH / (bottom - top))
    wide, stage = (CW / 2, CH / 2, 1.0), (CW / 2, STAGE[0], STAGE[1])
    close = (CW / 2, (top + bottom) / 2, z)
    slots_on = next((ln["start"] for ln in lines if ln["section"] == "problem"), 0.0)

    def framing(ln):
        k, sec, who = ln["kind"], ln["section"], ln["who"]
        if k == "count":
            return stage
        if k == "together" or (sec == "count" and k in ("question", "answer")):
            return close
        if sec in ("clap", "fingers") or k == "wave" or sec == "intro" and who == "narrator":
            return wide
        if who in CAST and CW > CH:                       # 16:9 episode: classic medium shot on the speaker
            return (CAST[who][4], FEET_Y - MED[0], MED[1])
        if who in CAST:                                     # the Short: a clean close-up (nobody cut in half)
            cx, z = _solo_frame(who, MED[1])
            cy = FEET_Y - int(CAST[who][2] * 0.62) if z > MED[1] + 0.3 else FEET_Y - MED[0]   # close: on the face
            return (cx, cy, z)
        return stage if ln["start"] >= slots_on else wide

    shots, cur, t0, sec0 = [], wide, 0.0, "intro"
    for ln in lines:
        f = framing(ln)
        if f != cur:
            dur = ln["start"] - t0
            if dur >= 4.0 or (dur >= 2.5 and ln["section"] != sec0):
                shots.append((t0, ln["start"], cur))
                cur, t0, sec0 = f, ln["start"], ln["section"]
    shots.append((t0, total, cur))
    return shots


def camera(canvas: np.ndarray, shots, t: float) -> np.ndarray:
    i = next((k for k, s in enumerate(shots) if s[0] <= t < s[1]), len(shots) - 1)
    t0, t1, (cx, cy, z) = shots[i]
    u = min(1.0, max(0.0, (t - t0) / max(1e-6, t1 - t0)))
    # steady camera (owner 13 Nov): constant speed, a 2.5% push; only the very last shot drifts back out
    zz = z * (1 + 0.025 * u) if i < len(shots) - 1 else max(1.0, z * 1.04 - 0.04 * z * u)
    w, h = CW / zz, CH / zz
    cx, cy = min(max(cx, w / 2), CW - w / 2), min(max(cy, h / 2), CH - h / 2)
    s = W / w
    M = np.float32([[s, 0, -(cx - w / 2) * s], [0, s, -(cy - h / 2) * s]])
    return cv2.warpAffine(canvas, M, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)


# ---------- sound ----------

# Twinkle, Twinkle (melody 1761, public domain), our own arrangement: (MIDI note, beats), A-B-A.
_A = [(60, 1), (60, 1), (67, 1), (67, 1), (69, 1), (69, 1), (67, 2), (65, 1), (65, 1), (64, 1), (64, 1), (62, 1),
      (62, 1), (60, 2)]
_B = [(67, 1), (67, 1), (65, 1), (65, 1), (64, 1), (64, 1), (62, 2)] * 2
TUNE = _A + _B + _A
CHORDS = [48, 48, 53, 48, 53, 48, 55, 48] + [48, 53, 48, 55] * 2 + [48, 48, 53, 48, 53, 48, 55, 48]   # per 2 beats


def _pad_chord(root: int, dur: float) -> np.ndarray:
    n = int(dur * au.SR)
    t = np.arange(n, dtype=np.float32) / au.SR
    sig = sum(np.sin(2 * np.pi * au.midi_hz(root + 12 + s) * t) for s in (0, 4, 7)).astype(np.float32)
    env = np.minimum(1.0, t / 0.25) * np.minimum(1.0, (dur - t) / 0.35)
    return sig * env * 0.045


def _clap(seed: int = 0) -> np.ndarray:
    n = int(0.2 * au.SR)
    noise = np.random.default_rng(seed).uniform(-1, 1, n).astype(np.float32)
    noise = noise - np.concatenate([[0], noise[:-1]])                     # brighter (high-passed) noise
    t = np.arange(n, dtype=np.float32) / au.SR
    env = sum(np.exp(-np.maximum(0, t - d) * 180) * (t >= d) for d in (0.0, 0.009, 0.018)) + 0.3 * np.exp(-t * 28)
    return noise * env.astype(np.float32) * 0.35


# Public-domain nursery melodies (all 18th-19th century), rotated per episode so videos don't sound alike and
# parents hear the tunes they grew up with (nostalgia). (MIDI note, beats); half beats allowed.
TUNES = {
    "twinkle": TUNE,                                                               # melody 1761
    "mary": [(64, 1), (62, 1), (60, 1), (62, 1), (64, 1), (64, 1), (64, 2), (62, 1), (62, 1), (62, 2), (64, 1),
             (67, 1), (67, 2), (64, 1), (62, 1), (60, 1), (62, 1), (64, 1), (64, 1), (64, 1), (64, 1), (62, 1),
             (62, 1), (64, 1), (62, 1), (60, 4)],                                  # Mary Had a Little Lamb, 1830
    "frere": [(60, 1), (62, 1), (64, 1), (60, 1)] * 2 + [(64, 1), (65, 1), (67, 2)] * 2
             + [(67, .5), (69, .5), (67, .5), (65, .5), (64, 1), (60, 1)] * 2 + [(60, 1), (55, 1), (60, 2)] * 2,  # Frere Jacques
    "london": [(67, 1.5), (69, .5), (67, 1), (65, 1), (64, 1), (65, 1), (67, 2), (62, 1), (64, 1), (65, 2), (64, 1),
               (65, 1), (67, 2), (67, 1.5), (69, .5), (67, 1), (65, 1), (64, 1), (65, 1), (67, 2), (62, 2), (67, 2),
               (64, 1), (60, 3)],                                                  # London Bridge (traditional)
    "row": [(60, 1.5), (60, 1.5), (60, 1), (62, .5), (64, 1.5), (64, 1), (62, .5), (64, 1), (65, .5), (67, 3),
            (72, .5), (72, .5), (72, .5), (67, .5), (67, .5), (67, .5), (64, .5), (64, .5), (64, .5), (60, .5),
            (60, .5), (60, .5), (67, 1), (65, .5), (64, 1), (62, .5), (60, 3)],    # Row, Row, Row Your Boat, 1852
}
_TRIADS = {48: (0, 4, 7), 53: (5, 9, 0), 55: (7, 11, 2)}                         # C, F, G (pitch classes)


def harmonise(tune: list[tuple[int, float]], window: float = 2.0) -> list[int]:
    """One chord root (C/F/G) per 2 beats: the triad that holds the most melody time in that window."""
    events, t = [], 0.0
    for note, beats in tune:
        events.append((t, t + beats, note % 12))
        t += beats
    roots, w = [], 0.0
    while w < t - 1e-6:
        score = {r: sum(max(0.0, min(e, w + window) - max(s0, w)) for s0, e, pc in events if pc in tri)
                 for r, tri in _TRIADS.items()}
        roots.append(max(score, key=lambda r: (score[r], r == 48)))
        w += window
    return roots


def pick_tune(seed: int) -> str:
    return list(TUNES)[seed % len(TUNES)]


def music_bed(total: float, clap_ranges: list[tuple[float, float]], seed: int = 0) -> np.ndarray:
    """Cosy, nostalgic bed: a music-box melody (a classic nursery tune), gentle ukulele strums, a soft pad and bass,
    in a small warm room (owner, 13 Nov: fun, nostalgic, motherly comfort)."""
    end = total - 2.5
    name = pick_tune(seed)
    tune = TUNES[name]
    chords = harmonise(tune)
    loop_beats = sum(b for _, b in tune)
    melody, bass, strum, beat_t, k = [], [], [], 0.0, 0
    pad = np.zeros(int(total * au.SR) + au.SR, np.float32)
    while beat_t < end:
        note, beats = tune[k % len(tune)]
        melody.append((beat_t, note + 12, 0.55))
        beat_t += beats * BEAT
        k += 1
    t, k = 0.0, 0
    per_loop = len(chords)
    while t < end:
        root = chords[k % per_loop]
        bass.append((t, root, 0.6))
        au.place(pad, _pad_chord(root, 2 * BEAT + 0.15), t)
        for j, st in enumerate(_TRIADS[root]):                                # ukulele: a soft down-strum
            strum.append((t + j * 0.025, 60 + st, 0.35))
            strum.append((t + BEAT + j * 0.025, 60 + st, 0.25))
        t += 2 * BEAT
        k += 1
    bed = au.render_notes(melody, total, "celesta", min_gap=0.05, dur=1.1) * 0.85     # music box
    bed += au.render_notes(bass, total, "pluck", min_gap=0.05, dur=1.1) * 0.5
    bed += au.render_notes(strum, total, "pluck", min_gap=0.0, dur=0.8) * 0.28
    bed += pad[: len(bed)]
    for a, b in clap_ranges:                                                 # soft shaker in the clap round
        t = math.ceil(a / BEAT) * BEAT + BEAT / 2
        while t < b:
            au.place(bed, _clap(int(t * 10))[: int(0.06 * au.SR)] * 0.25, t)
            t += BEAT
    au.place(bed, au.chord([60, 64, 67, 72], 2.4, "bell", 0.5) * 0.5, end)  # final soft chord
    from .media.emotion_music import room
    bed = room(bed.astype(np.float64), 0.9, 0.18, seed=seed).astype(np.float32)   # a small, warm nursery room
    fade = int(2.0 * au.SR)
    bed[-fade:] *= np.linspace(1, 0, fade, dtype=np.float32)
    _ = loop_beats
    return bed


def _duck(voice: np.ndarray) -> np.ndarray:
    k = int(0.2 * au.SR)
    c = np.concatenate([[0.0], np.cumsum(np.abs(voice), dtype=np.float64)])
    ma = (c[k:] - c[:-k]) / k
    ma = np.concatenate([np.full(k // 2, ma[0]), ma, np.full(len(voice) - len(ma) - k // 2, ma[-1])])
    return (1.0 - 0.45 * np.clip(ma / 0.03, 0, 1)).astype(np.float32)


# ---------- render ----------

def make_cast(seed: int = 0) -> dict:
    """The drawn cast for this layout: toon Mascots, and Puppets for the human friends (puppet:<id>)."""
    cast = {}
    for k, (name, (col, shape, sz, _v, _x)) in enumerate(CAST.items()):
        if str(shape).startswith("toddler:"):
            from .media.toddler import Toddler
            cast[name] = Toddler(str(shape).split(":", 1)[1], size=sz, seed=seed + k)
        elif str(shape).startswith("puppet:"):
            from .media.puppet import Puppet
            cast[name] = Puppet(str(shape).split(":", 1)[1], size=sz, seed=seed)
        else:
            cast[name] = Mascot(size=sz, body=col, outline="#2E3A59", seed=k, shape=shape)
    return cast


def credits_line(names) -> str:
    """CC BY 4.0 credit when a human friend (Toon Head face) is on screen."""
    if not any(needs_credit(n) for n in names or ()):
        return ""
    try:
        from .media import characters
        return characters.credit()
    except Exception:  # noqa: BLE001
        return "Characters' faces: ToonHead by Johan Melin (CC BY 4.0), made with DiceBear."


def render(episode: dict, out_dir: Path, seed: int = 0, log=print, speed: float = 1.0,
           tail: float = 2.5) -> dict:                  # Kids 2.0: natural voice speed (was 0.92), short loop ending
    work = out_dir / "work"
    work.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    lines, n = episode["lines"], int(episode["count_to"])
    voices = Voices(work, speed)
    total = build_timeline(lines, voices, tail)
    tracks = voice_tracks(lines, total)
    voice_mix = sum(tracks.values())
    mouths = {name: _mouth(tracks[name]) for name in CAST}
    from .media.mascot import viseme_track               # lip-sync: the classic mouth shapes, from the known words
    shapes = {name: viseme_track([(ln["start"], ln["end"], ln["say"]) for ln in lines if ln["who"] in (name, "all")],
                                 tracks[name], au.SR, FPS) for name in CAST}
    if voices.bad:
        log(f"Kids: voices not available, narrator used instead: {sorted(voices.bad)}")
    log(f"Kids: {len(lines)} lines, {total:.0f}s, count to {n} with {episode['object']}s in the {episode['scene']}")

    plate, extras = scene_plate(episode["scene"], rng)
    night = episode["scene"] == "night"
    slots = slot_xy(n, episode["scene"])
    slot_spr, obj, sparkle = _slot_sprite(SLOT_R, night), draw_object(episode["object"], OBJ), _sparkle_sprite()
    br = int(SLOT_R * 0.34)                                                 # digit badge radius
    cast = make_cast(seed)
    shots = plan_shots(lines, total, slots)
    slots_on = next((ln["start"] for ln in lines if ln["section"] == "problem"), 3.0)
    if CW < CH:
        slots_on = -1.5                                  # the Short: the empty spots are already there in frame 1 (the hook)
    count_line = {int(ln["n"]): ln for ln in lines if ln["kind"] == "count"}
    land = {k: ln["start"] + FLY for k, ln in count_line.items()}
    bursts = [(land[k], *slots[k - 1]) for k in range(1, n + 1)]
    bursts += [(ln["start"], CW / 2, DIGIT_Y) for ln in lines if ln["kind"] in ("answer", "praise")]
    head = {name: (spec[4], FEET_Y - int(spec[2] * 0.62)) for name, spec in CAST.items()}

    silent = work / "anim.mp4"
    with FrameWriter(silent, FPS, (W, H)) as wr:
        tail_from = max((ln["hold"] for ln in lines), default=total)   # the closing jingle starts here
        for fi in range(int(total * FPS)):
            tt = fi / FPS
            canvas = plate.copy()
            draw_extras(canvas, extras, tt)
            cur = next((ln for ln in lines if ln["start"] <= tt < ln["hold"]), None)
            kind = cur["kind"] if cur else ""
            age = tt - cur["start"] if cur else 0.0
            # the empty spots pop in one by one when the problem starts
            if tt >= slots_on:
                for k, (x, y) in enumerate(slots):
                    s = pop_scale(tt - slots_on - 0.12 * k, 0.3, 1.1)
                    if s > 0.01:
                        blit(canvas, slot_spr, x, y, scale=s)
            # objects: fly from the speaker into their spot, then stay (bounce when counted again)
            for k in range(1, n + 1):
                ln = count_line[k]
                if tt < ln["start"]:
                    continue
                (x1, y1), (x0, y0) = slots[k - 1], head[ln["who"]]
                u = (tt - ln["start"]) / FLY
                if u < 1:
                    e = ease_out(u)
                    blit(canvas, obj, x0 + (x1 - x0) * e, y0 + (y1 - y0) * e - 230 * math.sin(math.pi * e),
                         scale=0.55 + 0.45 * e)
                    continue
                sc = pop_scale(tt - land[k], 0.25, 1.15) if tt - land[k] < 0.25 else 1.0
                if cur and kind in ("together", "clap") and int(cur.get("n", 0)) == k and age < 0.5:
                    sc *= 1 + 0.22 * math.sin(math.pi * age / 0.5)
                    ring = 1 - age / 0.5
                    cv2.circle(canvas, (x1, y1), int(SLOT_R * (1 + 0.6 * (1 - ring))), (255, 255, 255), max(1, int(8 * ring)),
                               cv2.LINE_AA)
                if cur and kind == "answer" and 0 <= age - 0.07 * k < 0.45:
                    sc *= 1 + 0.15 * math.sin(math.pi * (age - 0.07 * k) / 0.45)
                blit(canvas, obj, x1, y1, scale=sc)
                bx, by = x1 + int(SLOT_R * 0.74), y1 + int(SLOT_R * 0.74)   # small digit badge on the spot
                cv2.circle(canvas, (bx, by), br, (255, 255, 255), -1, cv2.LINE_AA)
                cv2.circle(canvas, (bx, by), br, INK, 4, cv2.LINE_AA)
                blit(canvas, _digit(k, int(SLOT_R / 2)), bx, by + 3)
            # sparkles
            for (b0, bx, by) in bursts:
                a = tt - b0
                if 0 <= a < 0.8:
                    for p in range(10):
                        ang = p * 2 * math.pi / 10 + b0
                        r = 60 + 170 * ease_out(a / 0.8)
                        blit(canvas, sparkle, bx + r * math.cos(ang), by + r * math.sin(ang),
                             scale=0.6 + 0.5 * (1 - a / 0.8), alpha=1 - a / 0.8)
            # the learning target: the big digit
            if cur and kind in ("count", "together", "clap", "answer"):
                t_in = land[int(cur["n"])] if kind == "count" else cur["start"]
                if tt >= t_in:
                    blit(canvas, _digit(int(cur["n"]), DIGIT_SIZE), CW / 2, DIGIT_Y, scale=pop_scale(tt - t_in, 0.3, 1.12))
            if cur and kind == "question" and tt >= cur["end"] - 0.2:          # pause for the child to answer
                p = 1 + 0.04 * math.sin((tt - cur["end"]) * 2 * math.pi / 1.6)
                bw, bh = int(170 * p), int(150 * p)
                tri = np.array([(CW // 2 - 30, DIGIT_Y + bh // 2 - 6), (CW // 2 + 10, DIGIT_Y + bh // 2 - 6),
                                (CW // 2 - 40, DIGIT_Y + bh // 2 + 40)], np.int32)
                cv2.fillPoly(canvas, [tri], INK, cv2.LINE_AA)
                rounded_rect(canvas, CW // 2 - bw // 2, DIGIT_Y - bh // 2, CW // 2 + bw // 2, DIGIT_Y + bh // 2, 40,
                             (255, 255, 255), border=6, border_color=INK)
                blit(canvas, text_sprite("?", "Luckiest Guy", 130, fill="#FF6F61", stroke=0, shadow=0), CW / 2,
                     DIGIT_Y + 7)
            # characters
            speaker = cur["who"] if cur and cur["start"] <= tt < cur["end"] else None
            for name, m in cast.items():
                col, shape, sz, _v, x = CAST[name]
                mo = float(mouths[name][min(fi, len(mouths[name]) - 1)])
                hop, dx = 0.0, 0.0
                if cur:
                    if cur["who"] == name and kind in ("story", "wave", "count") and age < 0.4:
                        hop = 0.5 * math.sin(math.pi * age / 0.4)
                    elif kind == "clap" and age < 0.45:
                        hop = math.sin(math.pi * age / 0.45)
                    elif kind == "answer" and age < 0.9:
                        hop = 0.7 * abs(math.sin(2 * math.pi * age / 0.9))
                    if kind == "wave":
                        dx = 14 * math.sin(2 * math.pi * 0.6 * tt + x)
                elif tt >= tail_from:                    # 28 Nov: the cast bops to the closing jingle (a frozen
                    beat = 2 * math.pi * 1.1 * (tt - tail_from) + x / 160.0   # 2.9 s end read as 'held end card')
                    hop = 0.5 * abs(math.sin(beat))
                    dx = 12 * math.sin(beat / 2)
                if speaker in CAST and speaker != name:
                    look = 0.9 if CAST[speaker][4] > x else -0.9
                elif cur and kind == "count" and tt < land[int(cur["n"])] + 0.3:
                    look = 0.9 if slots[int(cur["n"]) - 1][0] > x else -0.9
                else:
                    look = 0.25 * math.sin(tt * 0.5 + x)
                vis = shapes[name][min(fi, len(shapes[name]) - 1)] if shapes[name] else ""
                if is_puppet(name):                        # human friend: arms wave / clap / point / cheer
                    until = land[int(cur["n"])] + 0.3 if cur and kind == "count" else None
                    spr = m.draw(tt, mouth=mo, hop=hop, look=look, viseme=vis,
                                 action=puppet_action(cur, name, kind, age, tt, until))
                else:
                    spr = m.draw(tt, mouth=mo, hop=hop, look=look, viseme=vis)
                blit(canvas, spr, x + dx, FEET_Y - sz * 0.40 - 30 * hop)
            frame = camera(canvas, shots, tt)
            if CW < CH:
                pass                                       # the Short: full brightness from frame 1, no black end (it loops)
            elif tt < 0.5:
                frame = (frame.astype(np.float32) * (tt / 0.5)).astype(np.uint8)
            elif tt > total - 1.0:
                frame = (frame.astype(np.float32) * max(0.0, (total - tt) / 1.0)).astype(np.uint8)
            wr.write(frame)

    # sound: voices + our arrangement of a public-domain melody (ducked under speech) + gentle effects
    claps = [ln for ln in lines if ln["kind"] == "clap"]
    clap_ranges = [(claps[0]["start"], claps[-1]["hold"])] if claps else []
    bed = music_bed(total, clap_ranges, seed=seed)
    L = min(len(bed), len(voice_mix))
    mix = voice_mix[:L] + bed[:L] * _duck(voice_mix[:L]) * 0.34
    scale = [0, 2, 4, 5, 7, 9, 11, 12, 14, 16]
    for k in range(1, n + 1):
        au.place(mix, au.whoosh(0.4) * 0.1, count_line[k]["start"])
        au.place(mix, au.tone(au.midi_hz(72 + scale[k - 1]), 0.4, "celesta", 0.7), land[k], 0.3)
        au.place(mix, au.tone(au.midi_hz(96), 0.3, "bell", 0.5), land[k] + 0.03, 0.12)
    for ln in lines:
        if ln["kind"] == "together":
            au.place(mix, au.tone(au.midi_hz(72 + scale[int(ln["n"]) - 1]), 0.4, "celesta", 0.5), ln["start"], 0.18)
        elif ln["kind"] == "clap":
            au.place(mix, _clap(int(ln["n"])), ln["start"], 0.9)
        elif ln["kind"] == "answer":
            au.place(mix, au.chord([72, 76, 79], 1.4, "bell", 0.6), ln["start"], 0.25)
        elif ln["kind"] in ("question", "callout"):          # "your turn" chime, then a real pause for the child
            au.place(mix, au.tone(au.midi_hz(76), 0.4, "glass", 0.5), ln["end"], 0.18)
            au.place(mix, au.tone(au.midi_hz(81), 0.5, "glass", 0.5), ln["end"] + 0.18, 0.18)
        elif ln["kind"] == "praise":                           # a warm little "yay" chord
            au.place(mix, au.chord([67, 72, 76], 1.2, "celesta", 0.6), ln["start"], 0.22)
    try:                       # sonic logo: a sung "Count with Bloop!" in the quiet tail (brand recall, every video)
        from .songs import jingle
        jg = jingle()
        au.place(mix, jg * 0.85, max(0.0, total - len(jg) / au.SR - 0.15))
    except Exception as e:  # noqa: BLE001 - the video is fine without it
        log(f"Kids: jingle skipped ({e})")
    final = out_dir / "video.mp4"
    mux(silent, au.to_stereo(mix), final, work)
    return {"total": total, "lines": len(lines), "shots": len(shots),
            "avg_shot_s": round(total / max(1, len(shots)), 1), "voices_missing": sorted(voices.bad)}


# ---------- thumbnail, captions, metadata ----------

def make_thumbnail(episode: dict, dest: Path, seed: int = 0) -> Path:
    """Bloop's face big + the episode's object + 2-3 words (research: face + one key object, clean, bright)."""
    plate, _ = scene_plate(episode["scene"], np.random.default_rng(seed))
    img = cv2.resize(plate, (1280, 720), interpolation=cv2.INTER_AREA)
    n = int(episode["count_to"])
    obj = draw_object(episode["object"], 118)
    shown = min(n, 5)
    for k in range(shown):
        x = 700 + k * (520 / max(1, shown - 1) if shown > 1 else 0)
        blit(img, obj, x, 470 - 40 * math.sin(math.pi * k / max(1, shown - 1)))
    bloop = Mascot(size=600, body=CAST["Bloop"][0], outline="#2E3A59", seed=1, shape="drop").draw(0.2, look=0.6)
    blit(img, bloop, 300, 450)
    title = text_sprite(f"COUNT TO {n}!", "Luckiest Guy", 120, fill="#FFFFFF", stroke=12, stroke_fill="#2E3A59",
                        shadow=10)
    if title.shape[1] > 700:
        title = cv2.resize(title, (700, int(title.shape[0] * 700 / title.shape[1])), interpolation=cv2.INTER_AREA)
    blit(img, title, 905, 150)
    rounded_rect(img, 880, 640, 1250, 700, 24, PAL["teal"])
    blit(img, text_sprite("Bloop & Friends", "Luckiest Guy", 40, fill="#FFFFFF", stroke=0, shadow=0), 1065, 673)
    cv2.imwrite(str(dest), img, [cv2.IMWRITE_JPEG_QUALITY, 92])
    return dest


def write_srt(lines: list[dict], dest: Path) -> Path:
    def ts(s):
        ms = int(round(s * 1000))
        return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"
    rows = [f"{i}\n{ts(ln['start'])} --> {ts(max(ln['end'], ln['start'] + 1.0))}\n{ln['say']}\n"
            for i, ln in enumerate(lines, 1)]
    dest.write_text("\n".join(rows), encoding="utf-8")
    return dest


def short_lines(lines: list[dict]) -> list[dict]:
    """The Short (research: a complete mini-scene, 30-60 s, same calm pace): hello, the problem, one counting
    round, the question and answer, one happy line and goodbye."""
    keep = {"intro": 0, "problem": 99, "count": 99, "after_count": 1, "goodbye": 1}   # opens on the problem (hook)
    seen: dict[str, int] = {}
    out = []
    for ln in lines:
        sec = ln["section"]
        if seen.get(sec, 0) < keep.get(sec, 0):
            seen[sec] = seen.get(sec, 0) + 1
            out.append(ln)
    return out


def make(brain, channel: dict, topic: str | None = None, memory=None, log=print, seed: int | None = None,
         fmt: str = "long", planned: dict | None = None, on_plan=None) -> tuple[Path, dict]:
    """fmt="long": the 16:9 episode (2-2.5 min). fmt="short": a 9:16 mini-episode (30-60 s).
    27 Nov (P3 checkpoints): planned = the kept plan of a stopped try (its AI call is not repeated; same seed, so the
    same cast and pictures); on_plan(plan) is called once a fresh plan is written, so a crash later resumes from it."""
    if planned and planned.get("lines"):
        seed = int(planned.get("seed") or 0) if seed is None else seed
    seed = seed if seed is not None else int(time.time()) % 1_000_000
    short = fmt == "short"
    use_layout("short" if short else "long")
    try:
        if planned and planned.get("lines"):
            episode = json.loads(json.dumps(planned))           # a copy: the kept plan stays as it was
            log("   Resuming the last try's episode plan (its AI call is not repeated)")
        else:
            episode = plan_episode(brain, seed, topic, max_n=6 if short else 10)
            episode["seed"] = seed
            if on_plan:
                on_plan(episode)
        duo = None
        if short:
            episode["lines"], duo = duo_lines(short_lines(episode["lines"]), seed)
            use_layout("short", duo=duo)
            episode["friend"] = duo[1]
        elif puppets_on():                                   # long episode: two human friends join Bloop and Pip
            episode["lines"], swap = human_cast_lines(episode["lines"], seed)
            if swap:
                use_layout("long", swap=swap)
                episode["friends"] = sorted(swap.values())
        check = qa(episode["lines"], episode["count_to"], rounds_needed=1 if short else 3)
        if not check["counts_ok"]:
            raise RuntimeError(f"Kids QA failed: {check}")
        out_dir = ROOT / "output" / channel["id"] / (time.strftime("%Y%m%d_%H%M%S") + ("_short" if short else ""))
        out_dir.mkdir(parents=True, exist_ok=True)
        info = render(episode, out_dir, seed=seed, log=log, tail=3.0 if short else 3.5,   # just the sung jingle
                      speed=float((channel.get("voice") or {}).get("speed", 1.0)))
        script = {k: v for k, v in episode.items()}
        script["lines"] = [{k: v for k, v in ln.items() if not k.startswith("_")} for ln in episode["lines"]]
        (out_dir / "script.json").write_text(json.dumps(script, indent=2, ensure_ascii=False), encoding="utf-8")
        write_srt(script["lines"], out_dir / "captions.srt")
        n, objs = episode["count_to"], PLURAL.get(episode["object"], episode["object"] + "s")
        adj = episode.get("adjective", "").title()
        o = objs.title()
        if short:
            options = [f"Count to {n} with Bloop & {duo[1]}! {adj} {o} #shorts",
                       f"{adj} {o}! Can You Count to {n} with {duo[1]}? #shorts",
                       f"How Many {o}? Count with Bloop & {duo[1]} #shorts"]
        else:                                    # Cocomelon pattern: topic first, then the brand + what parents search
            options = [f"Counting to {n} with {adj} {o} | Bloop & Friends Nursery Rhymes & Kids Songs",
                       f"How Many {adj} {o}? Count 1 to {n} with Bloop | Kids Songs for Toddlers",
                       f"{adj} {o} Counting Song (1 to {n}) | Bloop & Friends Learning Videos",
                       f"Let's Count {n} {o} in the {str(episode.get('scene', 'park')).title()}! | Bloop & Friends"]
        from . import uniq                       # 21 Nov: one fixed template was held as "title nearly repeats"
        titles = [t.replace("  ", " ") for t in uniq.freshest(channel["id"], options)]
        title = titles[0]
        credit = credits_line(duo or tuple(CAST))            # CC BY 4.0: Toon Head faces on the human friends
        meta = {"channel": channel["id"], "format": "short" if short else "long", "title": title,
                "title_options": titles,                     # the gate's repair_title can switch to another one
                "description": (f"{episode.get('description', '').strip()}\n\nLearning goal: counting from 1 to {n}, "
                                "one object for each number.\n\nAn original Bloop & Friends story. Music: our own "
                                "arrangement of a traditional public-domain melody. "
                                + (f"Script and animation © Bloop & Friends. {credit} " if credit else
                                   "Characters, script and animation © Bloop & Friends. ")
                                + "Character voices: AI voices reading our script."
                                + (f"\n\n{channel['catchphrase']} 🎵" if channel.get("catchphrase") else "")),
                "made_for_kids": True, "comments": False, "ai_label": False, "duration_s": round(info["total"], 1),
                "hashtags": channel.get("hashtags", []), "written_by": episode.get("_written_by"),
                "tags": [f"counting to {n}", f"count to {n}", "counting for toddlers", "nursery rhymes for toddlers",
                         "kids songs", "preschool learning", "learn numbers", f"{objs} for kids", "Bloop and Friends"],
                "captions_file": "captions.srt", "qa": {**check, "avg_shot_s": info["avg_shot_s"],
                                                         "voices_missing": info["voices_missing"]}}
        (out_dir / "upload.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
        from .snack.maker import save_cover
        if short:
            save_cover(out_dir / "video.mp4", min(info["total"] * 0.6, 30), out_dir / "cover_vertical.jpg")
        else:
            make_thumbnail(episode, out_dir / "thumbnail_1.jpg", seed)
            save_cover(out_dir / "video.mp4", min(info["total"] / 2, 40), out_dir / "cover.jpg")
        return out_dir, meta
    finally:
        use_layout("long")
