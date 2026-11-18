"""Brain Snack (channel #9) v2 — Cocomelon techniques for a teen/adult audience.

Bright shifting colours, an original talking mascot (lip-synced), escalating physics
(balls escape 3 spinning rings and every escape spawns 2 more — the count keeps rising),
particle bursts, bounce notes that play a melody, a live counter, punchy captions, emoji.
Every frame and sound is made by our own code. Not "Made for Kids": topics are for 13+.
"""
from __future__ import annotations

import colorsys
import json
import math
import os
import re
import subprocess
import time
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
import soundfile as sf
from PIL import Image, ImageDraw, ImageFont

from .config import ROOT
from .media import ffmpeg, sfx, stickers
from .media.captions import HookStyle, build_ass
from .media.fonts import FONTS_DIR, ensure_fonts, font_file
from .media.mascot import Mascot, mouth_track
from .media.transcribe import align_script, transcribe
from .media.voice import synthesize, to_48k

W, H, FPS = 1080, 1920, 30

SCRIPT_PROMPT = """Write a 35-45 second "{kind}" Short for the channel "{channel}" ({niche}).
Audience: United States, ages 13-35 (NOT a kids' video). Fast, surprising, fun, 100% true facts only.
Topic idea: {topic}

Use these attention techniques:
- First line = the most surprising fact or a question, under 2 seconds. No greetings.
- Short sentences (5-10 words). A tiny catchphrase the mascot repeats ("Snack fact!") 2-3 times.
- Escalate: each fact more surprising than the last. Count them ("Fact number 3...").
- End with a question that makes people comment, then loop back to the first line.
What has worked before:
{memory}
Return ONLY JSON:
{{"title": "under 60 chars", "hook_text": "max 6 words", "hook_options": ["3 options"],
  "sentences": ["one sentence per item, 12-16 sentences, 95-115 words total"],
  "emoji": ["one emoji per sentence or empty string"],
  "emphasis": ["key words to pop (numbers, surprising words)"],
  "caption": "Shorts/Instagram caption ending with a question", "hashtags": ["3-5"]}}"""

# Twinkle Twinkle Little Star — a traditional melody (public domain). Bounce notes play it.
MELODY = [0, 0, 7, 7, 9, 9, 7, 5, 5, 4, 4, 2, 2, 0, 7, 7, 5, 5, 4, 4, 2, 7, 7, 5, 5, 4, 4, 2]
BRIGHT = [("#4FC3F7", "#FFF176"), ("#81C784", "#FFF59D"), ("#F48FB1", "#FFE082"), ("#9575CD", "#80DEEA"),
          ("#FFB74D", "#F06292")]


def _bgr(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return b, g, r


def _gradient(top, bottom, w, h):
    k = np.linspace(0, 1, h, dtype=np.float32)[:, None, None]
    return (np.array(top, np.float32) * (1 - k) + np.array(bottom, np.float32) * k).repeat(w, axis=1)


@lru_cache(maxsize=64)
def _digit_sprite(text: str, size: int = 92) -> np.ndarray:
    """Counter text drawn with the Luckiest Guy font (Latin digits render fine in Pillow)."""
    font = ImageFont.truetype(str(font_file("Luckiest Guy")), size)
    w = int(font.getlength(text)) + 40
    img = Image.new("RGBA", (w, size + 40), (0, 0, 0, 0))
    ImageDraw.Draw(img).text((20, 14), text, font=font, fill="white", stroke_width=8, stroke_fill="black")
    a = np.array(img)
    return cv2.cvtColor(a, cv2.COLOR_RGBA2BGRA)


def _blend(dst, sprite, x, y):
    h, w = sprite.shape[:2]
    x0, y0, x1, y1 = max(x, 0), max(y, 0), min(x + w, dst.shape[1]), min(y + h, dst.shape[0])
    if x0 >= x1 or y0 >= y1:
        return
    sp = sprite[y0 - y:y1 - y, x0 - x:x1 - x]
    a = sp[..., 3:4].astype(np.float32) / 255
    roi = dst[y0:y1, x0:x1]
    roi[:] = (sp[..., :3] * a + roi * (1 - a)).astype(np.uint8)


class Sim:
    """Balls inside 3 spinning rings. Escaping all rings = +1 and 2 new balls appear."""

    def __init__(self, seed: int = 0, cx: int = W // 2, cy: int = int(H * 0.5)):
        self.rng = np.random.default_rng(seed)
        self.cx, self.cy = cx, cy
        # tuned so escapes start within seconds and then snowball (see pick_seed)
        self.rings = [{"r": 250, "gap": math.radians(90), "spin": 0.07},
                      {"r": 350, "gap": math.radians(76), "spin": -0.055},
                      {"r": 450, "gap": math.radians(64), "spin": 0.04}]
        self.balls, self.particles = [], []
        self.escaped, self.bounces, self.escapes = 0, [], []
        self.colors = [(80, 230, 255), (255, 120, 255), (120, 255, 140), (255, 210, 90), (90, 160, 255)]
        for _ in range(2):
            self._spawn()

    def _spawn(self):
        if len(self.balls) >= 36:
            return
        ang = self.rng.uniform(0, 2 * math.pi)
        self.balls.append({"p": np.array([self.cx + 40 * math.cos(ang), self.cy + 40 * math.sin(ang)]),
                           "v": self.rng.uniform(-13, 13, 2), "r": int(self.rng.integers(24, 34)), "layer": 0,
                           "c": self.colors[len(self.balls) % len(self.colors)]})

    def step(self, f: int):
        g = 0.5
        center = np.array([self.cx, self.cy], float)
        for b in list(self.balls):
            b["v"][1] += g
            b["p"] += b["v"]
            if b["layer"] >= len(self.rings):
                if not (-100 < b["p"][0] < W + 100 and b["p"][1] < H + 100):
                    b["gone"] = True
                continue
            ring = self.rings[b["layer"]]
            d = b["p"] - center
            dist = np.linalg.norm(d) + 1e-9
            if dist + b["r"] >= ring["r"]:
                ang = (math.atan2(d[1], d[0]) - f * ring["spin"]) % (2 * math.pi)
                if ang < ring["gap"]:
                    b["layer"] += 1
                    if b["layer"] == len(self.rings):          # fully escaped!
                        self.escaped += 1
                        self.escapes.append(f / FPS)
                        self._burst(b["p"], b["c"])
                        self._spawn()
                        self._spawn()
                else:
                    n = d / dist
                    b["v"] = (b["v"] - 2 * np.dot(b["v"], n) * n) * 1.015
                    sp = np.linalg.norm(b["v"])
                    if sp > 24:
                        b["v"] *= 24 / sp
                    b["p"] = center + n * (ring["r"] - b["r"] - 1)
                    self.bounces.append(f / FPS)
        # rebuild the lists (list.remove compares dicts holding numpy arrays, which fails)
        self.balls = [b for b in self.balls if not b.get("gone")]
        for p in self.particles:
            p["p"] += p["v"]
            p["v"][1] += 0.35
            p["life"] -= 1
        self.particles = [p for p in self.particles if p["life"] > 0]

    def _burst(self, pos, color):
        for _ in range(28):
            a = self.rng.uniform(0, 2 * math.pi)
            s = self.rng.uniform(4, 14)
            self.particles.append({"p": np.array(pos, float), "v": np.array([math.cos(a) * s, math.sin(a) * s]),
                                   "life": int(self.rng.integers(14, 30)), "c": color})


def pick_seed(seconds: float, base: int = 0, tries: int = 40) -> int:
    """Pre-run the physics (fast, no drawing) and keep the most exciting start:
    first escape as early as possible (the hook), then as many escapes as possible."""
    best, best_score = base, -1e9
    for seed in range(base, base + tries):
        sim = Sim(seed)
        for f in range(int(seconds * FPS)):
            sim.step(f)
        first = sim.escapes[0] if sim.escapes else 99
        score = sim.escaped - 6 * max(first - 2.5, 0)
        if score > best_score:
            best, best_score = seed, score
    return best


def render_frames(seconds: float, sim: Sim, mouth: np.ndarray, palette_idx: int = 0):
    """Yields BGR frames."""
    trail = np.zeros((H // 2, W // 2, 3), np.float32)
    mascot = Mascot(300, "#FF7AB8", "#B0306A")
    bg_cache, sprites = {}, {}
    total = int(seconds * FPS)
    last_escape = -10.0
    for f in range(total):
        t = f / FPS
        sim.step(f)
        # background: bright gradient that slowly changes colour
        key = int(t / 0.25)
        if key not in bg_cache:
            top, bottom = BRIGHT[(palette_idx + int(t / 6)) % len(BRIGHT)]
            hue_shift = (t % 6) / 6 * 0.08
            def shift(c):
                b, g, r = _bgr(c)
                h, l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
                r2, g2, b2 = colorsys.hls_to_rgb((h + hue_shift) % 1, l, min(1, s * 1.1))
                return int(b2 * 255), int(g2 * 255), int(r2 * 255)
            bg_cache = {key: _gradient(shift(top), shift(bottom), W, H).astype(np.uint8)}
        frame = bg_cache[key].copy()
        # glowing trails (half resolution for speed)
        trail *= 0.9
        for b in sim.balls:
            cv2.circle(trail, (int(b["p"][0] / 2), int(b["p"][1] / 2)), b["r"] // 2, [c / 255 for c in b["c"]], -1,
                       cv2.LINE_AA)
        small = cv2.GaussianBlur(trail, (0, 0), 5)
        mask = np.clip(np.maximum(np.maximum(small[..., 0], small[..., 1]), small[..., 2]), 0, 0.6)
        keep = cv2.resize(((1 - mask) * 255).astype(np.uint8), (W, H))
        glow = cv2.resize(np.clip(small * 255, 0, 255).astype(np.uint8), (W, H))
        frame = cv2.add(cv2.multiply(frame, cv2.cvtColor(keep, cv2.COLOR_GRAY2BGR), scale=1 / 255), glow)
        # rings (white with a dark outline so they read on bright colours)
        for ring in sim.rings:
            start = math.degrees(f * ring["spin"] + ring["gap"])
            end = start + 360 - math.degrees(ring["gap"])
            cv2.ellipse(frame, (sim.cx, sim.cy), (ring["r"], ring["r"]), 0, start, end, (60, 40, 40), 26, cv2.LINE_AA)
            cv2.ellipse(frame, (sim.cx, sim.cy), (ring["r"], ring["r"]), 0, start, end, (255, 255, 255), 16, cv2.LINE_AA)
        for p in sim.particles:
            cv2.circle(frame, (int(p["p"][0]), int(p["p"][1])), max(2, p["life"] // 5), p["c"], -1, cv2.LINE_AA)
        for b in sim.balls:
            c = (int(b["p"][0]), int(b["p"][1]))
            cv2.circle(frame, c, b["r"] + 4, (40, 30, 30), -1, cv2.LINE_AA)
            cv2.circle(frame, c, b["r"], b["c"], -1, cv2.LINE_AA)
            cv2.circle(frame, (c[0] - b["r"] // 3, c[1] - b["r"] // 3), max(2, b["r"] // 4), (255, 255, 255), -1,
                       cv2.LINE_AA)
        # counter, top right — pops when it changes
        if sim.escapes and sim.escapes[-1] > last_escape:
            last_escape = sim.escapes[-1]
        pop = max(0.0, 1 - (t - last_escape) / 0.25)
        key_s = (sim.escaped, int(78 * (1 + 0.25 * pop)) // 4 * 4)
        if key_s not in sprites:
            sprites[key_s] = _digit_sprite(f"ESCAPED: {key_s[0]}", key_s[1])
        spr = sprites[key_s]
        _blend(frame, spr, W - spr.shape[1] - 30, 340)    # below the hook strips (y 70-330)
        # mascot, bottom left: talks with the voice, hops on every escape
        m = float(mouth[f]) if f < len(mouth) else 0.0
        hop = max(0.0, 1 - (t - last_escape) / 0.4) if t - last_escape < 0.4 else 0.0
        sprite = mascot.draw(t, m, hop=hop, look=math.sin(t * 0.7))
        _blend(frame, sprite, 30, H - sprite.shape[0] - 380)
        # camera punch on escapes
        if pop > 0:
            z = 1 + 0.05 * pop
            M = cv2.getRotationMatrix2D((sim.cx, sim.cy), 0, z)
            frame = cv2.warpAffine(frame, M, (W, H), borderMode=cv2.BORDER_REFLECT)
        yield frame


def notes(times: list[float], total_s: float, sr: int = 48000) -> np.ndarray:
    """Each bounce plays the next note of the melody (C major, bright marimba-like tone)."""
    out = np.zeros(int(total_s * sr) + sr)
    n = int(0.22 * sr)
    t = np.arange(n) / sr
    last = -1.0
    k = 0
    for at in times:
        if at - last < 0.09:          # skip near-simultaneous bounces
            continue
        last = at
        f = 523.25 * 2 ** (MELODY[k % len(MELODY)] / 12)
        k += 1
        tone = (np.sin(2 * np.pi * f * t) + 0.3 * np.sin(4 * np.pi * f * t)) * np.exp(-t * 16)
        s = int(at * sr)
        out[s:s + n] += tone * 0.16
    return out[: int(total_s * sr)]


def write_script(brain, channel: dict, topic: str, kind: str = "fast facts", memory=None) -> dict:
    mem = memory.context_block(topic, channel["id"]) if memory else ""
    script, result = brain.ask_json("writer", SCRIPT_PROMPT.format(
        kind=kind, channel=channel["name"], niche=channel["niche"], topic=topic,
        memory=mem or "(no history yet)"), temperature=0.9)
    script["_written_by"] = result.provider
    return script


def render(channel: dict, script: dict, out_dir: Path, seed: int = 0, log=print) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    work = out_dir / "work"
    work.mkdir(exist_ok=True)
    ensure_fonts()
    style, voice = channel.get("style", {}), channel["voice"]
    sentences = script.get("sentences") or [x.strip() for x in
                                             re.split(r"(?<=[.!?])\s+", script.get("narration", "")) if x.strip()]
    emojis = script.get("emoji", [])

    log("Voice")
    parts, starts, t0 = [], [], 0.2
    for i, s in enumerate(sentences):
        wav = work / f"v_{i:02d}.wav"
        d = synthesize(s, wav, voice["id"], "en", speed=voice.get("speed", 1.12), pause_s=0.08, trim=True)
        starts.append(t0)
        t0 += d
        parts.append(sf.read(wav, dtype="float32")[0])
    narration = work / "narration.wav"
    sf.write(narration, np.concatenate([np.zeros(int(24000 * 0.2), np.float32)] + parts), 24000)
    total = t0 + 0.8
    text = " ".join(sentences)
    words = align_script(text, transcribe(narration, language="en"), total)

    log("Animation")
    sim = Sim(pick_seed(total, seed))
    mouth = mouth_track(narration)
    stick = []
    for i, e in enumerate(emojis[:len(starts)]):
        png = stickers.emoji_png(e) if e else None
        if png:
            stick.append((starts[i] + 0.1, min(starts[i] + 1.3, total), stickers.load_rgba(png, 260)))

    accent = style.get("highlight_color", "#00E5FF")
    ass = build_ass(words, work / "captions.ass", font="Luckiest Guy", language="en", caption_color="#FFFFFF",
                    highlight_color="#FFE600", emphasis_color="#FF4FD8",
                    emphasis_words=set(script.get("emphasis", [])), glow_color="#FF4FD8",
                    hook=script.get("hook_text"), hook_style=HookStyle(lines_bg=["#FFFFFF", "#FF4FD8"],
                    lines_fg=["#000000", "#FFFFFF"], font="Luckiest Guy", size=104, y=70, until=3.0),
                    caption_margin_v=250, font_size=112, max_words=2)
    fonts_rel = os.path.relpath(FONTS_DIR, work).replace("\\", "/")

    log("Audio")
    v48 = to_48k(narration, work / "narration_48k.wav")
    voice_audio, sr = sf.read(v48, dtype="float32")

    # frames first (the sim decides when bounces happen), then audio, then mux
    silent = work / "anim.mp4"
    cmd = [ffmpeg.ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24",
           "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", *ffmpeg.H264_FAST, str(silent)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    for fi, frame in enumerate(render_frames(total, sim, mouth, seed % len(BRIGHT))):
        t = fi / FPS
        for s0, s1, spr in stick:
            if s0 <= t <= s1:
                d = t - s0
                sc = max(0.05, min(1.15, d / 0.1) - max(0, min(0.15, (d - 0.1))))
                sz = max(4, int(260 * sc))
                _blend(frame, cv2.resize(spr, (sz, sz)), W - sz - 60, H - sz - 460 + int(8 * math.sin(d * 6)))
        proc.stdin.write(frame.tobytes())
    proc.stdin.close()
    if proc.wait() != 0:
        raise RuntimeError(proc.stderr.read().decode("utf-8", "replace")[-1500:])

    n = len(voice_audio)
    mix = voice_audio.copy()
    mix += notes(sim.bounces, n / sr, sr)[:n, None]
    music_line = "Animation and music made by us."
    raw_bed = None
    try:                     # owner 18 Nov: varied real music (quirky / lofi / playful), not the same synth loop
        from .media import music_library
        got = music_library.track(("quirky", "lofi", "playful")[seed % 3], channel["id"], log=log)
        if got:
            raw_bed = music_library.bed(got[0], n / sr, sr=sr)
            music_line = "Animation made by us. " + music_library.credit(got[1])
    except Exception as e:  # noqa: BLE001
        log(f"Music library: {e} (synthesised bed instead)")
    if raw_bed is None:
        raw_bed = sfx.music_bed(n / sr, "upbeat", seed=seed)
    bed = sfx.duck(raw_bed, voice_audio, 0.5)
    mix[: len(bed)] += bed[:, None] * 0.12
    for at in sim.escapes:
        s = int(at * sr)
        d = sfx.ding(0.6, base=1046)
        e = min(s + len(d), n)
        if s < n:
            mix[s:e] += d[: e - s, None] * 0.3
    for s0, _s1, _ in stick:
        s = int(s0 * sr)
        p = sfx.pop()
        if s < n:
            mix[s:s + len(p)] += p[: n - s, None] * 0.4
    mix *= 0.98 / max(np.abs(mix).max(), 0.98)
    sf.write(work / "mix.wav", mix, sr)

    final = out_dir / "video.mp4"
    ffmpeg.run(["-i", "anim.mp4", "-i", "mix.wav", "-vf", f"subtitles=captions.ass:fontsdir={fonts_rel}",
                "-map", "0:v", "-map", "1:a", *ffmpeg.H264, *ffmpeg.AAC, "-shortest", "-movflags", "+faststart",
                str(final.resolve())], cwd=work)
    meta = {"channel": channel["id"], "format": "short", "title": script.get("title"),
            "hook_text": script.get("hook_text"), "hook_options": script.get("hook_options", []),
            "description": f"{script.get('caption', '')}\n\nNarration uses an AI voice. {music_line}\n\n"
                           + " ".join(dict.fromkeys(channel.get("hashtags", []) + script.get("hashtags", []))),
            "instagram_caption": script.get("caption", ""), "duration_s": round(ffmpeg.duration(final), 2),
            "made_for_kids": False, "ai_label": True, "yt_synthetic": False,   # cartoon animation: YouTube label not needed "written_by": script.get("_written_by"),
            "escaped_count": sim.escaped}
    (out_dir / "upload.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    return meta


def make(brain, channel: dict, topic: str | None = None, script: dict | None = None, memory=None,
         log=print) -> tuple[Path, dict]:
    if script is None:
        script = write_script(brain, channel, topic or "mind-blowing facts", memory=memory)
    out_dir = ROOT / "output" / channel["id"] / time.strftime("%Y%m%d_%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "script.json").write_text(json.dumps(script, indent=2, ensure_ascii=False), encoding="utf-8")
    return out_dir, render(channel, script, out_dir, seed=int(time.time()) % 10_000, log=log)
