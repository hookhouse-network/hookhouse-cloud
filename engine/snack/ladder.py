"""Format 4, "Brain Quiz Ladder": 7 questions that get harder, a 2.5 s countdown ring, a ding on the reveal
and a ladder that fills with the answers. Hook and closing line are voiced with word-by-word captions.
Questions are written by the AI brain and double-checked by a second model; doubtful ones are dropped."""
from __future__ import annotations

import math
from pathlib import Path

import cv2
import numpy as np
import soundfile as sf

from ..media import stickers
from ..media.voice import synthesize, to_48k
from . import audio as au
from .canvas import W, H, bgr, blit, fit_size, pop_scale, rounded_rect, text_sprite, vertical_bg, wrap

CATEGORIES = {
    "space": ("#1B0B3A", "#3A0CA3", "stars"), "ocean": ("#012A4A", "#01497C", "bubbles"),
    "animals": ("#1B4332", "#2D6A4F", "sparkles"), "geography": ("#03045E", "#0077B6", "sparkles"),
    "human body": ("#590D22", "#A4133C", "bubbles"), "history": ("#3D2C1E", "#7F5539", "sparkles"),
    "science": ("#10002B", "#5A189A", "stars"), "food": ("#6A040F", "#C1121F", "sparkles"),
    "inventions": ("#14213D", "#3A506B", "stars"), "sports records": ("#0B3D20", "#1E6F3E", "sparkles"),
}
TIER = ["#FACC15"] * 3 + ["#22C55E"] * 3 + ["#EF4444"] * 3 + ["#D946EF"]

N_QUESTIONS = 7          # 21 Nov: 10 questions made a 60 s Short; the quality bar wants 8-45 s (watch-through)
QUIZ_PROMPT = """Write a 7-question quiz for the YouTube Shorts channel "Brain Snack" (teens and adults, United States).
Category: {category}. {topic_line}
Difficulty rises: questions 1-2 easy, 3-4 medium, 5-6 hard, 7 very hard.
Rules: each question is at most 9 words; each answer is 1-3 words; every answer must be 100% true and the only
correct answer (no trick questions, no opinions, nothing about living private people, no brands, no dates that
change). Use simple words. Write 9 questions so weak ones can be dropped.
Return JSON only: {{"hook": "max 7 words, e.g. Only 1% get all 7. Ready?", "questions": [{{"q": "...", "a": "...",
"emoji": "one emoji that fits"}}], "title_options": ["3 short titles"], "hashtags": ["#quiz", "..."]}}"""

CHECK_PROMPT = """Check this quiz. For each item, decide if the answer is definitely correct and the only reasonable
answer. Be strict.
{items}
Return JSON only: {{"bad": [indexes of wrong, doubtful or ambiguous items]}}"""


def write_quiz(brain, category: str, topic: str | None = None) -> dict:
    data, res = brain.ask_json("writer", QUIZ_PROMPT.format(
        category=category, topic_line=f"Theme idea: {topic}." if topic else ""), temperature=0.8)
    qs = [q for q in data.get("questions", []) if q.get("q") and q.get("a")]
    try:
        items = "\n".join(f"{i}. Q: {q['q']} A: {q['a']}" for i, q in enumerate(qs))
        verdict, _ = brain.ask_json("checker", CHECK_PROMPT.format(items=items), temperature=0.0)
        bad = {int(i) for i in verdict.get("bad", []) if str(i).isdigit() or isinstance(i, int)}
    except Exception:  # noqa: BLE001 - if the checker is down, keep the writer's list
        bad = set()
    data["questions"] = [q for i, q in enumerate(qs) if i not in bad][:N_QUESTIONS]
    data["_written_by"] = res.provider
    data["category"] = category
    if len(data["questions"]) < N_QUESTIONS - 1:
        raise RuntimeError("Not enough checked quiz questions")
    return data


def _voice_line(text: str, path: Path, voice: dict) -> tuple[np.ndarray, float]:
    synthesize(text, path, voice["id"], "en", speed=voice.get("speed", 1.08), trim=True)
    p48 = to_48k(path, path.with_name(path.stem + "_48.wav"))
    audio, _ = sf.read(p48, dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    return audio, len(audio) / au.SR


def _particles(kind: str, n: int, rng) -> np.ndarray:
    return np.stack([rng.uniform(0, W, n), rng.uniform(0, H, n), rng.uniform(0.3, 1.0, n), rng.uniform(0, 6.28, n)], 1)


def render(spec: dict, quiz: dict, voice: dict, work: Path, writer, fps: int, log=print) -> dict:
    cat = quiz["category"]
    top, bottom, pkind = CATEGORIES.get(cat, CATEGORIES["science"])
    rng = np.random.default_rng(spec["seed"])
    qs = quiz["questions"]
    hook_text = quiz.get("hook") or f"Only 1% get all {len(qs)}. Ready?"
    cta_text = "Comment your score!"
    # voice lines and timeline
    hook_a, hook_d = _voice_line(hook_text, work / "q_hook.wav", voice)
    t = 0.2
    timeline = {"hook": (t, hook_d)}
    t += hook_d + 0.35
    items = []
    for i, q in enumerate(qs):
        qa, qd = _voice_line(q["q"], work / f"q_{i:02d}.wav", voice)
        start = t
        timer_start = start + qd + 0.15
        reveal = timer_start + 2.5
        items.append({"q": q, "audio": qa, "start": start, "timer": timer_start, "reveal": reveal, "end": reveal + 0.75})
        t = reveal + 0.75
    cta_a, cta_d = _voice_line(cta_text, work / "q_cta.wav", voice)
    timeline["cta"] = (t, cta_d)
    total = t + cta_d + 0.6
    log(f"Ladder: {cat}, {len(qs)} questions, {total:.1f}s")
    bg_a, bg_b = vertical_bg(top, bottom), vertical_bg(bottom, top)
    parts = _particles(pkind, 70, rng)
    pill_txt = f"BRAIN SNACK QUIZ · {cat.upper()}"
    pill_size = fit_size(pill_txt, "Poppins Black", 760, 50)
    pill = text_sprite(pill_txt, "Poppins Black", pill_size, stroke=0, shadow=0)
    emojis = {}
    for i, it in enumerate(items):
        png = stickers.emoji_png(it["q"].get("emoji") or "") if it["q"].get("emoji") else None
        emojis[i] = stickers.load_rgba(png, 230) if png else None
    hook_words, cta_words = hook_text.split(), cta_text.split()
    caption_cols = ["#FFE600", "#00E5FF", "#FFFFFF"]
    n_frames = int(total * fps)
    for fi in range(n_frames):
        tv = fi / fps
        mix_k = min(1.0, max(0.0, (tv - total * 0.45) / 1.5))    # backdrop hue changes at the halfway point
        frame = cv2.addWeighted(bg_a, 1 - mix_k, bg_b, mix_k, 0) if 0 < mix_k < 1 else (bg_b if mix_k >= 1 else bg_a).copy()
        for x, y, z, ph in parts:                                 # slow parallax particles
            yy = (y - tv * 40 * z) % H
            xx = x + 12 * math.sin(tv * 0.8 + ph)
            r = int(2 + 3 * z)
            col = (255, 255, 255) if pkind == "stars" else (255, 230, 200)
            if pkind == "bubbles":
                cv2.circle(frame, (int(xx), int(yy)), r * 3, col, 2, cv2.LINE_AA)
            else:
                cv2.circle(frame, (int(xx), int(yy)), r, col, -1, cv2.LINE_AA)
        rounded_rect(frame, W / 2 - 410, 95, W / 2 + 410, 195, 50, bgr("#E11D48"))
        blit(frame, pill, W / 2, 145)
        # ladder
        for k in range(len(items)):
            y = 520 + k * 86
            blit(frame, text_sprite(str(k + 1), "Poppins Black", 52, fill=TIER[k], stroke=5), 90, y)
            it = items[k]
            if tv >= it["reveal"]:
                ans = it["q"]["a"]
                size = fit_size(ans, "Poppins Black", 245, 44, 30, 4)
                blit(frame, text_sprite(ans, "Poppins Black", size, stroke=4), 122, y - size * 0.62, anchor="top-left")
        cur = next((it for it in items if it["start"] <= tv < it["end"]), None)
        if cur is not None:
            i = items.index(cur)
            age = tv - cur["start"]
            sc = pop_scale(age, 0.24, 1.08)
            if sc > 0.02:
                card = np.full((640, 640, 3), 255, np.uint8)
                cv2.rectangle(card, (0, 0), (639, 639), (30, 30, 30), 8)
                if emojis.get(i) is not None:
                    blit(card, emojis[i], 320, 190)
                q_size = 54
                lines = wrap(cur["q"]["q"], "Poppins Black", q_size, 570)
                while len(lines) > 3 and q_size > 36:
                    q_size -= 4
                    lines = wrap(cur["q"]["q"], "Poppins Black", q_size, 570)
                blit(card, text_sprite("\n".join(lines), "Poppins Black", q_size, fill="#111111", stroke=0, shadow=0),
                     320, 420)
                if tv >= cur["reveal"]:
                    a_size = fit_size(cur["q"]["a"], "Poppins Black", 560, 72, 40)
                    rounded_rect(card, 36, 520, 604, 615, 30, bgr("#22C55E"))
                    blit(card, text_sprite(cur["q"]["a"], "Poppins Black", a_size, stroke=6), 320, 567)
                if abs(sc - 1) > 0.01:
                    card = cv2.resize(card, (int(640 * sc), int(640 * sc)))
                ch, cw = card.shape[:2]
                cx, cy = 700, 930
                y0, x0 = int(cy - ch / 2), int(cx - cw / 2)
                frame[max(0, y0):y0 + ch, max(0, x0):x0 + cw] = card[max(0, -y0):, max(0, -x0):][:H - max(0, y0), :W - max(0, x0)]
                # countdown ring above the card
                if cur["timer"] <= tv < cur["reveal"]:
                    p = (tv - cur["timer"]) / 2.5
                    col = (94, 197, 34) if p < 0.5 else (21, 204, 250) if p < 0.8 else (68, 68, 239)
                    cv2.ellipse(frame, (700, 515), (64, 64), -90, 0, 360 * (1 - p), col, 18, cv2.LINE_AA)
                    blit(frame, text_sprite(str(max(1, math.ceil(2.5 - (tv - cur['timer'])))), "Poppins Black", 64,
                                            stroke=6), 700, 515)
                if cur["reveal"] <= tv < cur["reveal"] + 0.15:
                    over = np.full_like(frame, bgr("#22C55E"))
                    cv2.addWeighted(frame, 0.6, over, 0.4, 0, dst=frame)
        # voiced hook / CTA captions: one word at a time
        for key, words in (("hook", hook_words), ("cta", cta_words)):
            s0, d = timeline[key]
            if s0 <= tv < s0 + d + 0.2:
                wi = min(len(words) - 1, int((tv - s0) / max(d, 0.1) * len(words)))
                w_age = (tv - s0) - wi * d / len(words)
                blit(frame, text_sprite(words[wi].upper(), "Poppins Black", 112, fill=caption_cols[wi % 3], stroke=10),
                     W / 2, 400, scale=1.0 + 0.15 * max(0.0, 1 - w_age / 0.11))
        writer.write(frame)
    voice_track = np.zeros(int(total * au.SR) + au.SR, np.float32)
    au.place(voice_track, hook_a, timeline["hook"][0])
    for it in items:
        au.place(voice_track, it["audio"], it["start"])
    au.place(voice_track, cta_a, timeline["cta"][0])
    return {"total": total, "items": [{k: v for k, v in it.items() if k != "audio"} for it in items],
            "voice": voice_track[: int(total * au.SR)], "ai_voice": True, "cover_at": items[0]["start"] + 0.6}


def soundtrack(info: dict, spec: dict) -> np.ndarray:
    total = info["total"]
    mix = info["voice"].copy()
    bed = au.drum_loop(total, 100, vol=0.05)
    mix[: len(bed)] += bed
    mix += au.pad(total, root=50, vol=0.035)[: len(mix)]
    for it in info["items"]:
        for k in range(3):                                   # ticks in the final second
            au.place(mix, au.tick(), it["reveal"] - 1.0 + k * 0.33, 0.5)
        au.place(mix, au.ding(1046), it["reveal"], 0.45)
    return mix
