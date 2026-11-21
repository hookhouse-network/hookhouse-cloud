"""Brain Snack v3 maker: picks a format and a fresh rule combination (never repeating a recent one),
renders it, and writes upload.json + script.json + cover.jpg like the other makers.

Formats (research: Report 1, Brain Snack specs):
  spiral    "Attempt Spiral"    escalating escape, 55-70 s
  multiply  "Multiply & Reveal" seamless loop, 15-20 s
  versus    "Snack Squad VS"    original-character battle with a running season table, 35-50 s
  ladder    "Brain Quiz Ladder" 10 timed questions, 45-65 s
  readfast  "Read it if you can" a fact revealed one word per bounce, speeding up, 20-35 s
"""
from __future__ import annotations

import json
import random
import time
from pathlib import Path

import cv2
import numpy as np

from ..config import ROOT
from ..media import ffmpeg
from ..media.mascot import Mascot
from . import audio as au
from .encode import FrameWriter, mux

HISTORY = ROOT / "data" / "snack_history.json"
FORMATS = ["spiral", "multiply", "versus", "ladder", "readfast", "colorsort"]
READY = {"spiral", "multiply", "versus", "ladder", "readfast"}
PC_FORMATS = {"colorsort"}          # HyperFrames formats (P3r, S3): only where HyperFrames is installed (the PC)


def ready_formats() -> set[str]:
    """Formats this machine can make now. HyperFrames formats need the CLI (the PC) and the settings switch
    `hyperframes_formats` (the off-switch); the cloud runner never picks them."""
    try:
        from ..config import settings
        from ..media import hyperframes
        on = settings().get("hyperframes_formats", True) and hyperframes.available()
    except Exception:  # noqa: BLE001 - unknown = the classic formats only
        on = False
    return READY | (PC_FORMATS if on else set())
MELODY_NAMES = {
    "mountain_king": "Grieg, In the Hall of the Mountain King (1875)",
    "ode_to_joy": "Beethoven, Ode to Joy (1824)",
    "fur_elise": "Beethoven, Für Elise (1810)",
    "twinkle": "Traditional, Twinkle Twinkle Little Star",
    "turkish_march": "Mozart, Rondo alla Turca (1783)",
    "morning_mood": "Grieg, Morning Mood (1875)",
    "habanera": "Bizet, Habanera (1875)",
    "bumblebee": "Rimsky-Korsakov, Flight of the Bumblebee (1900)",
}


def load_history() -> list[dict]:
    if HISTORY.exists():
        try:
            return json.loads(HISTORY.read_text(encoding="utf-8"))
        except ValueError:
            return []
    return []


def save_history(items: list[dict]) -> None:
    HISTORY.parent.mkdir(parents=True, exist_ok=True)
    HISTORY.write_text(json.dumps(items[-200:], indent=1, ensure_ascii=False), encoding="utf-8")


def _combo_key(spec: dict) -> str:
    keys = ("format", "rule", "shape", "melody", "instrument", "palette", "pair", "category")
    return "|".join(str(spec.get(k, "")) for k in keys)


def made_formats(channel_id: str = "brain_snack") -> list[str]:
    """The formats really made, oldest first, from the video folders (<YYYYmmdd_HHMMSS>_<format>) on this machine
    and in the week plans. 18 Nov: the PC helper made spiral, spiral, versus, ladder, spiral because its
    snack_history.json is replaced by the cloud's copy on every loop (the PC never sends state back), so the
    'never twice in a row' rule saw an empty history. Folder names survive on both machines."""
    names = set()
    folder = ROOT / "output" / channel_id
    if folder.exists():
        names |= {p.name for p in folder.iterdir() if p.is_dir()}
    for plan in sorted((ROOT / "data" / "weeks").glob("*/plan.json"))[-3:]:
        try:
            items = json.loads(plan.read_text(encoding="utf-8")).get("items", [])
        except (OSError, ValueError):
            continue
        names |= {Path(it["out_dir"]).name for it in items if it.get("channel") == channel_id and it.get("out_dir")}
    out = []
    for n in sorted(names):                                     # the name starts with the time it was made
        fmt = n.rsplit("_", 1)[-1]
        if fmt in FORMATS and n[:8].isdigit():
            out.append(fmt)
    return out


TOPIC_FORMATS = {"readfast", "ladder"}          # the formats that are ABOUT a subject (fact / quiz)


def choose_format(history: list[dict], wanted: str | None = None, made: list[str] | None = None,
                  topic: str | None = None) -> str:
    if wanted:
        return wanted
    recent = (made if made is not None else []) or [h.get("format") for h in history[-3:]]
    recent = recent[-3:]
    ready = ready_formats()
    options = [f for f in FORMATS if f in ready and f not in recent[-2:]]     # never in the last two
    options = options or [f for f in FORMATS if f in ready and f not in recent[-1:]]
    # 18 Nov (owner: "you are giving the topics but you haven't generated the content according to that topics"):
    # the planned topic was dropped whenever a physics format came up. But the physics formats are the network's
    # best performers (spiral 1,088 + 1,065 views, versus 802; next best channel 172), so they alternate: after a
    # physics video, a planned topic gets a format that uses it (fact / quiz). A physics video leaves its topic in
    # the pool (make() doesn't record it as used).
    if topic and TOPIC_FORMATS & set(options) and (not recent or recent[-1] not in TOPIC_FORMATS):
        options = [f for f in options if f in TOPIC_FORMATS]
    weights = [0.5 if f in recent else 1.0 for f in options]
    return random.choices(options, weights=weights)[0]


def new_spec(fmt: str, history: list[dict], seed: int) -> dict:
    """A rule combination not used in the last 60 videos."""
    rng = random.Random(seed)
    used = {_combo_key(h) for h in history[-60:]}
    for _ in range(200):
        spec = {"format": fmt, "seed": rng.randrange(1, 10**6),
                "melody": rng.choice(list(au.MELODIES)), "instrument": rng.choice(list(au.INSTRUMENTS) + ["pluck"]),
                "transpose": rng.choice([0, 2, 5, -3])}
        if fmt == "spiral":
            spec.update(rule=rng.choice(["speed", "size", "boost"]), attempts=rng.choice([4, 5, 5, 6]),
                        hue_shift=round(rng.random(), 3))
        elif fmt == "multiply":
            from .multiply import SHAPES
            spec.update(shape=rng.choice(SHAPES))
            if spec["shape"] == "letter":
                spec["letter"] = rng.choice("ABCDEFGHKMNPRSWXYZ23456789?!")
        elif fmt == "versus":
            from .versus import pick_pair
            spec.update(pair="|".join(pick_pair(spec["seed"])))
        elif fmt == "ladder":
            from .ladder import CATEGORIES
            spec.update(category=rng.choice(list(CATEGORIES)))
        elif fmt == "colorsort":
            from .colorsort import LAYOUTS
            spec.update(layout=rng.randrange(len(LAYOUTS)), hue_shift=round(rng.random(), 3))
        if _combo_key(spec) not in used:
            return spec
    return spec


def _mascot_avatar(size: int = 104) -> np.ndarray:
    return Mascot(size=size).draw(0.0)


def render_spec(spec: dict, out_dir: Path, brain=None, channel: dict | None = None, log=print) -> dict:
    """Renders one video for `spec` into out_dir/video.mp4; returns format info."""
    work = out_dir / "work"
    work.mkdir(parents=True, exist_ok=True)
    silent = work / "anim.mp4"
    fmt = spec["format"]
    if fmt == "spiral":
        from . import spiral
        fps = 60
        with FrameWriter(silent, fps, (1080, 1920)) as w:
            info = spiral.render(spec, w, fps, _mascot_avatar(), log=log)
        mix = spiral.soundtrack(info, spec)
    elif fmt == "multiply":
        from . import multiply
        fps = 60
        with FrameWriter(silent, fps, (1080, 1920)) as w:
            info = multiply.render(spec, w, fps, log=log)
        mix = multiply.soundtrack(info, spec)
    elif fmt == "versus":
        from . import versus
        fps = 60
        with FrameWriter(silent, fps, (1080, 1920)) as w:
            info = versus.render(spec, w, fps, log=log)
        mix = versus.soundtrack(info, spec)
    elif fmt == "ladder":
        from . import ladder
        if brain is None:
            raise ValueError("The quiz format needs the AI brain to write questions")
        quiz = spec.get("quiz") or ladder.write_quiz(brain, spec["category"], spec.get("topic"))
        spec["quiz"] = quiz
        fps = 30
        with FrameWriter(silent, fps, (1080, 1920)) as w:
            info = ladder.render(spec, quiz, (channel or {}).get("voice") or {"id": "af_bella"}, work, w, fps, log=log)
        mix = ladder.soundtrack(info, spec)
        info.pop("voice", None)
    elif fmt == "readfast":
        from . import readfast
        if brain is None and not spec.get("fact"):
            raise ValueError("The read-fast format needs the AI brain to write a fact")
        fact = spec.get("fact") or readfast.write_fact(brain, spec.get("topic"))
        spec["fact"] = fact
        fps = 60
        with FrameWriter(silent, fps, (1080, 1920)) as w:
            info = readfast.render(spec, fact, w, fps, log=log)
        mix = readfast.soundtrack(info, spec)
    elif fmt == "colorsort":                         # HyperFrames (P3r step 3): writes work/anim.mp4 itself
        from . import colorsort
        fps = 30
        info = colorsort.render(spec, work, log=log)
        mix = colorsort.soundtrack(info, spec)
    else:
        raise ValueError(f"Format '{fmt}' is not built yet")
    final = out_dir / "video.mp4"
    mux(silent, au.to_stereo(mix), final, work)
    info["fps"] = fps
    return info


TITLES = {
    "spiral": {
        "speed": ["Which try reaches the center? 😭", "It starts faster every try… 🧠", "Wait for the last try 😳"],
        "size": ["The ball shrinks every try… which one makes it? 😭", "Smaller ball, better chance? 🧠",
                 "Wait for the tiny ball 😳"],
        "boost": ["Every break makes it faster 😳", "Which try finally breaks through? 🧠",
                  "The boost grows every try… 😭"],
    },
}


SHAPE_NAMES = {"heart": "heart", "star": "star", "blob": "blob", "brain": "brain", "donut": "donut",
               "rocket": "rocket", "bolt": "lightning bolt", "drop": "water drop"}


def titles_for(spec: dict) -> list[str]:
    fmt = spec["format"]
    if fmt == "multiply":
        name = SHAPE_NAMES.get(spec.get("shape"), f"letter {spec.get('letter', '')}".strip())
        return [f"1 bounce = 2 balls inside a {name} (wait for the reveal) 🧠",
                f"Filling a {name} with multiplying balls 😳", "Watch it hit 100%… 🤯"]
    if fmt == "ladder":
        quiz = spec.get("quiz") or {}
        n = len(quiz.get("questions", [])) or 10
        return (quiz.get("title_options") or [])[:2] + [f"Only 1% get all {n} 🧠"]
    if fmt == "readfast":
        return ["If you can read this, your brain is fast 🧠", "Read it before it speeds up 😳",
                "What word did you lose it at? 👇"]
    if fmt == "versus":
        a, b = spec["pair"].split("|")
        return [f"{a} vs {b}: who wins? 🔴🔵", f"{a} gets stronger every hit… 😳", f"{b} vs {a}, rematch time 🏆"]
    if fmt == "colorsort":
        return ["Wait for the last tile 😳", "Watch it sort itself into a rainbow 🌈", "The last swap is so satisfying 😌"]
    return TITLES.get(fmt, {}).get(spec.get("rule"), ["Satisfying physics 🧠"])


# 19 Nov review (Brain Snack Instagram: 1.6% likes, 0 shares; every caption asked "Which rule next?", even on facts).
# Per format: a real question viewers can answer + a friendly send challenge. Mosseri (Jan 2025): watch time, likes
# per reach and sends per reach weigh most; sends most for reaching non-followers. Meta demotes chain-letter bait
# ("share with 10 friends", "comment YES"), so these stay questions/challenges tied to the video.
CTA = {
    "readfast": ("What word did you lose it at? 👇", "Send it to a friend and see who reads further 👀"),
    "ladder": ("What did you score? Be honest 👇", "Send it to the friend who thinks they know everything 🧠"),
    "versus": ("Who were you rooting for, and why? 👇", "Send it to the friend who'd pick the other side 🔴🔵"),
    "spiral": ("Which try did you think would make it? 👇", "Send it to someone who needs 30 calm seconds 😌"),
    "multiply": ("Did you guess when it would fill up? 👇", "Send it to someone who needs 30 calm seconds 😌"),
    "colorsort": ("Which colour did you watch the whole time? 👇", "Send it to someone who needs 15 calm seconds 😌"),
}
MADE_WITH = {   # the description's "how it was made" line (true per format)
    "colorsort": "Drawn and animated from scratch in code, no AI. Every note is played by a swap.",
}
CTA_DEFAULT = ("Which rule should we try next? 👇", "Send it to someone who'd love this 🧠")


def cta_for(fmt: str) -> tuple[str, str]:
    return CTA.get(fmt, CTA_DEFAULT)


def write_meta(channel: dict, spec: dict, info: dict, out_dir: Path) -> dict:
    fmt = spec["format"]
    from .. import uniq
    titles = uniq.pick(channel["id"], titles_for(spec))       # 17 Nov: never the same title twice on a channel
    melody = MELODY_NAMES.get(spec.get("melody"), "")
    made = MADE_WITH.get(fmt) or ("Simulated and rendered from scratch with our own physics engine. "
                                  "Every note is played by a collision"
                                  + (f" (melody: {melody}, public domain)." if melody else "."))
    desc = (f"{titles[0]}\n"                     # searchable first line (title words), then how it was made
            + made
            + "\n\n" + "\n".join(cta_for(fmt))
            + (f"\n\n{channel['catchphrase']}" if channel.get("catchphrase") else "")
            + "\n\n" + " ".join(channel.get("hashtags", [])))
    meta = {"channel": channel["id"], "format": "short", "snack_format": fmt, "title": titles[0],
            "title_options": titles, "hook_text": titles[0], "description": desc,
            "instagram_caption": f"{titles[0]}\n\n" + "\n".join(cta_for(fmt)) + "\n\n"
                                 + " ".join(channel.get("hashtags", [])),
            "duration_s": round(ffmpeg.duration(out_dir / "video.mp4"), 2), "made_for_kids": False,
            "ai_label": bool(info.get("ai_voice")), "ai_used": bool(info.get("ai_voice")),   # explicit for the gate
            "yt_synthetic": False, "spec": spec,
            "fact_check": (spec.get("fact") or {}).get("_fact_check")}
    (out_dir / "upload.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    return meta


def save_cover(video: Path, at_s: float, dest: Path) -> None:
    cap = cv2.VideoCapture(str(video))
    cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, at_s) * 1000)
    ok, frame = cap.read()
    cap.release()
    if ok:
        cv2.imwrite(str(dest), frame, [cv2.IMWRITE_JPEG_QUALITY, 92])


def make(brain, channel: dict, topic: str | None = None, fmt: str | None = None, memory=None, log=print,
         seed: int | None = None) -> tuple[Path, dict]:
    history = load_history()
    seed = seed if seed is not None else int(time.time()) % 1_000_000
    fmt = choose_format(history, fmt, made=made_formats(channel["id"]), topic=topic)
    spec = new_spec(fmt, history, seed)
    used = bool(topic) and fmt in TOPIC_FORMATS          # physics formats don't use (or use up) the planned topic
    if used:
        spec["topic"] = topic
    out_dir = ROOT / "output" / channel["id"] / f"{time.strftime('%Y%m%d_%H%M%S')}_{fmt}"
    out_dir.mkdir(parents=True, exist_ok=True)
    log(f"Brain Snack v3: format '{fmt}', spec {spec}")
    info = render_spec(spec, out_dir, brain=brain, channel=channel, log=log)
    (out_dir / "script.json").write_text(json.dumps({"title": fmt, "topic": topic if used else None, "spec": spec},
                                                    indent=2, ensure_ascii=False), encoding="utf-8")
    meta = write_meta(channel, spec, info, out_dir)
    meta["used_topic"] = used
    save_cover(out_dir / "video.mp4", info.get("cover_at", max(0.0, info["total"] - 1.2)), out_dir / "cover.jpg")
    try:
        from ..reels import snack_reel
        snack_reel(out_dir, meta, channel)              # Instagram version (never byte-identical)
    except Exception as e:  # noqa: BLE001
        log(f"Reel variant failed: {e}")
    history.append({**{k: spec.get(k) for k in ("format", "rule", "shape", "melody", "instrument", "palette",
                                                 "pair", "category")}, "at": time.time(), "dir": out_dir.name})
    save_history(history)
    return out_dir, meta
