"""Format 5, "Read it if you can": a true fact is revealed one word per bounce while the ball speeds up
(word time falls from 450 ms to 140 ms). The ball's path is solved so every bounce lands exactly on the
next word. It ends with "What word did you lose it at?" (a comment prompt) and loops. 20-35 s."""
from __future__ import annotations

import math
import re

import cv2
import numpy as np

from . import audio as au
from .canvas import W, H, add_glow, blit, hue_bgr, radial_bg, text_sprite

CX, CY, R = 540, 960, 450
FACT_PROMPT = """Write one surprising, TRUE fact for the YouTube Shorts channel "Brain Snack" (teens and adults).
{topic_line}
Rules: 28-40 words, simple words, no names of living private people, no brands. It must be checkable on Wikipedia.
"hook" = the words on screen at 0:00, 3-7 words: the most surprising part of THIS fact as a teaser statement or a
direct question that makes a stranger need the rest (the fact itself delivers the payoff); plain words, never "did you
know", "guess" or "read it if you can".
Return JSON only: {{"fact": "...", "hook": "...", "claims": ["the fact's key claim(s)"],
"sources": ["Wikipedia article titles"], "title_options": ["3 short titles"], "hashtags": ["#facts", "..."]}}"""
DARE = "READ IT IF YOU CAN"
_WEAK_HOOK = re.compile(r"\bdid you know\b|\bguess\b|\bread (?:it|this) if\b|\bif you can\b", re.I)


def hook_of(fact: dict) -> str:
    """The fact's own teaser for the 0:00 card (24 Nov: the fixed "READ IT IF YOU CAN" card is what the judge called
    the vague, templated opening of the held Brain Snack videos; the 23 Nov review's best Instagram Shorts were the
    ones whose subject showed first, e.g. 'The Day of Two Noons'). "" = no usable hook (the dare card stays)."""
    hook = re.sub(r"\s+", " ", str((fact or {}).get("hook") or "")).strip().strip('"')
    n = len(hook.split())
    if not 2 <= n <= 8 or len(hook) > 48 or _WEAK_HOOK.search(hook):
        return ""
    return hook


def wrap(text: str, width: int = 12) -> str:
    """Greedy word wrap for a big card (lines of at most `width` characters where the words allow)."""
    lines: list[str] = []
    for w in text.split():
        if lines and len(lines[-1]) + 1 + len(w) <= width:
            lines[-1] += " " + w
        else:
            lines.append(w)
    return "\n".join(lines)


def write_fact(brain, topic: str | None = None) -> dict:
    from ..story import fact_check
    for _ in range(2):
        data, res = brain.ask_json("writer", FACT_PROMPT.format(
            topic_line=f"Topic idea: {topic}" if topic else "Pick any fascinating topic."), temperature=0.9)
        fact = (data.get("fact") or "").strip()
        if 20 <= len(fact.split()) <= 48:
            verdict = fact_check(brain, {"claims": data.get("claims") or [fact], "sources": data.get("sources") or []})
            data["_fact_check"], data["_written_by"] = verdict, res.provider
            if verdict.get("ok") or not verdict.get("checked"):
                return data
    raise RuntimeError("Could not write a checked fact")


def schedule(n_words: int, start: float = 0.45, end: float = 0.14) -> list[float]:
    """Word durations shrinking geometrically from start to end."""
    if n_words <= 1:
        return [start]
    k = (end / start) ** (1 / (n_words - 1))
    return [start * k ** i for i in range(n_words)]


def bounce_points(n: int, rng) -> list[tuple[float, float]]:
    """Points on the circle; each next point is roughly across, so paths cross the middle."""
    pts, a = [], rng.uniform(0, 2 * math.pi)
    for _ in range(n + 1):
        pts.append((CX + (R - 22) * math.cos(a), CY + (R - 22) * math.sin(a)))
        a += math.pi + rng.uniform(-0.9, 0.9)
    return pts


def render(spec: dict, fact: dict, writer, fps: int, log=print) -> dict:
    rng = np.random.default_rng(spec["seed"])
    words = fact["fact"].split()
    durs = schedule(len(words))
    hook = hook_of(fact)
    lead = 1.9 if hook else 1.4                        # the fact's teaser (or the dare) card first
    times = [lead]
    for d in durs:
        times.append(times[-1] + d)
    pts = bounce_points(len(words), rng)
    end_hold, outro = 0.5, 2.0
    total = times[-1] + end_hold + outro
    log(f"Readfast: {len(words)} words, {total:.1f}s")
    bg = radial_bg("#3B1E8A", "#0E0B2A")   # vivid violet: colour from frame 1 (was near-black)
    cv2.circle(bg, (CX, CY), R, (200, 200, 200), 4, cv2.LINE_AA)
    trail = np.zeros((H, W, 3), np.uint8)
    mask = np.zeros((H, W), np.uint8)
    cv2.circle(mask, (CX, CY), R - 2, 255, -1)
    dare = None
    if hook:                                           # the teaser big, the dare small under it
        card = wrap(hook.upper())
        longest = max(len(ln) for ln in card.split("\n"))
        intro = text_sprite(card, "Poppins Black", 120 if longest <= 10 else max(78, int(120 * 10 / longest)),
                            fill="#FFE600", stroke=10)
        dare = text_sprite(DARE.lower(), "Poppins ExtraBold", 54, stroke=6)
    else:
        intro = text_sprite("READ IT IF\nYOU CAN", "Poppins Black", 120, fill="#FFE600", stroke=10)
    end1 = text_sprite("What word did you\nlose it at?", "Poppins Black", 74, stroke=8)
    # 22 Nov S6: was "Send it to a friend: who reads further?". Instagram does not recommend posts that ask for
    # shares; a second try is an honest invite (and rewatches add watch time, its first ranking signal).
    end2 = text_sprite("Try again:\nyou'll read further", "Poppins ExtraBold", 54, fill="#FFE600", stroke=6)
    events = []
    prev = None
    hue0 = rng.random()
    n_frames = int(total * fps)
    for fi in range(n_frames):
        t = fi / fps
        frame = bg.copy()
        if t < lead:
            pos = pts[0]
        elif t < times[-1]:
            k = int(np.searchsorted(times, t, side="right") - 1)
            k = min(max(k, 0), len(words) - 1)
            p = (t - times[k]) / durs[k]
            (x0, y0), (x1, y1) = pts[k], pts[k + 1]
            pos = (x0 + (x1 - x0) * p, y0 + (y1 - y0) * p)
        else:
            pos = pts[-1]
        if prev is not None and lead <= t <= times[-1] + 0.05:
            hue = (hue0 + t * 0.12) % 1.0
            cv2.line(trail, (int(prev[0]), int(prev[1])), (int(pos[0]), int(pos[1])), hue_bgr(hue, 0.9, 0.85), 44,
                     cv2.LINE_AA)
            trail[mask == 0] = 0
        prev = pos
        cv2.addWeighted(frame, 1.0, trail, 0.55, 0, dst=frame)
        layer = np.zeros_like(frame)
        cv2.circle(layer, (int(pos[0]), int(pos[1])), 30, hue_bgr((hue0 + t * 0.12) % 1.0, 0.6, 1.0), -1, cv2.LINE_AA)
        add_glow(frame, layer, passes=((8, 0.6), (26, 0.3)))
        cv2.circle(frame, (int(pos[0]), int(pos[1])), 22, (255, 255, 255), -1, cv2.LINE_AA)
        if t < lead:
            blit(frame, intro, W / 2, CY, scale=1.0)   # full size from frame 1, steady (no pulsing)
            if dare is not None:
                blit(frame, dare, W / 2, max(CY + intro.shape[0] / 2 + 70, CY + R + 70), scale=1.0)  # under the ring
        elif t < times[-1] + end_hold:
            k = min(int(np.searchsorted(times, t, side="right") - 1), len(words) - 1)
            word = words[k].strip()
            size = 120 if len(word) <= 9 else max(70, int(120 * 9 / len(word)))
            blit(frame, text_sprite(word, "Poppins Black", size, stroke=10), CX, CY)
        else:
            blit(frame, end1, W / 2, CY, scale=min(1.0, 0.7 + (t - times[-1] - end_hold) * 3))
            if t >= times[-1] + end_hold + 0.4:
                blit(frame, end2, W / 2, CY + R + 150, scale=1.0)
        writer.write(frame)
    for i, tt in enumerate(times[:-1]):
        events.append((tt, i))
    # the cover (Instagram grid, Shorts shelf): the teaser card when there is one, not a single flashing word
    return {"total": total, "bounces": events, "end": times[-1],
            "cover_at": lead / 2 if hook else times[len(times) // 3], "words": len(words)}


def soundtrack(info: dict, spec: dict) -> np.ndarray:
    total = info["total"]
    melody = au.MELODIES[spec["melody"]]
    events = [(t, melody[i % len(melody)], 0.6) for t, i in info["bounces"]]
    mix = au.render_notes(events, total, spec["instrument"], min_gap=0.05, dur=0.5, transpose=spec.get("transpose", 0))
    au.place(mix, au.success(), info["end"] + 0.1, 0.6)
    mix += au.pad(total, root=48, vol=0.04)[: len(mix)]
    return mix
