"""Storyboard: every shot SHOWS what the narrator is saying (owner, 15 Nov 2026: the videos were "text-to-image mostly"
and "missed the major objective"; make it "light, fast and accurate").

Old way: each beat searched photo/stock libraries by keyword and fell back to word cards (a story about a lake draining
into a salt mine showed a garden bridge and a card saying WHIRLPOOL). New way, per video:
1. plan()  - ONE writer call turns the script into a shot list: for each beat, what a camera would see at that moment
             (subject, action, place, era), the cast in it (fixed looks for the whole video) and the shot type:
             scene (drawn), real (a real photo of the exact named thing exists), number (one count-up card).
2. scene() - draws the shot (Cloudflare FLUX.1-schnell, then the Hugging Face FLUX.1-schnell Space; both Apache-2.0,
             free) in the channel's single look, then eyes() - a free Gemini vision check: does the picture show this
             moment, is there garbled text, anything from the wrong era? A failed picture is redrawn (max 2 more).
Light: one plan call, one picture + one check per shot, no library searches for drawn shots. Daily free quotas are
tracked (Cloudflare's 10,000 neurons end -> straight to the next source, no wasted calls)."""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
import os
import re
import time
from pathlib import Path

import requests
from engine.core.http import HTTP

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "cache" / "scenes"
QUOTA = ROOT / "data" / "state" / "image_quota.json"
ACTIONS = ("push_in", "pan_left", "pan_right", "drift_up")
TYPES = ("scene", "real", "number")
NO_TEXT = "no text, no letters, no words, no captions, no signs, no logos, no watermark"
EYES_MODEL = "gemini-3.5-flash-lite"
PASS = 7                                           # eyes score (0-10) a picture needs

PLAN_PROMPT = """You are the storyboard artist for a {channel} video ({fmt}). The narration is split into numbered beats.
For EVERY beat decide what the viewer SEES at that exact moment, so the story is clear even with the sound off.

Video: "{title}"
Language of narration: {lang}. Era/setting hint: {era}.
{rules}
Beats:
{beats}

Return JSON only:
{{"bible": {{"era": "time and place of the story, e.g. 'Louisiana, USA, November 1980'",
            "cast": {{"ID": "fixed look of each recurring person/creature/object, 15-25 words, same in every shot"}}}},
  "shots": [{{"i": 1, "type": "scene|real|number", "see": "...", "cast": ["ID"], "action": "push_in|pan_left|pan_right|drift_up"}}]}}

Rules for "see" (English, 18-40 words): one concrete filmable moment that matches what the beat SAYS happens - who,
doing what, where, camera angle (wide/close/aerial/low angle). Show the action itself (the drill piercing the mine, the
whirlpool swallowing the rig), not a symbol of it. Era-accurate clothes, buildings, tools. Never describe text, signs,
newspapers with readable words, logos or UI. For explanations show the mechanism (cutaway, cross-section, close-up of the
object). Vary the shots (wide, close, detail) - never the same framing twice in a row.
Rules for "type": "scene" for almost every beat. "real" ONLY when a well-known real photograph or object of exactly
this named subject surely exists (a famous ship, a landmark, a museum object). "number" for at most {max_numbers} beats
whose whole point is one striking number. One entry per beat, same order, i = beat number."""

RULES = {
    "no_faces": "Real sportspeople must never be recognisable: show them from behind, in silhouette, far away or as "
                "hands/feet/equipment close-ups; generic players only.",
    "myth": "Hindu epics: respectful, traditional iconography (e.g. Krishna blue-skinned with peacock feather, Karna with "
            "golden kavach armour and kundal earrings fused to his body); ancient Indian palaces, forests, chariots - "
            "never Mughal domes, minarets or modern objects; no invented rituals.",
    "kids": "",
}


# ---------------------------------------------------------------- plan
def enabled(channel: dict) -> bool:
    return bool(((channel.get("style") or {}).get("ai_style"))) and (channel.get("storyboard", True) is not False)


def _rules(channel: dict) -> str:
    from .ip_guard import RULE                      # 20 Nov: no franchise characters / real faces, every channel
    out = [RULE]
    if channel["id"] in ("clutch_tales", "cricket_ke_kisse"):
        out.append(RULES["no_faces"])
    if channel["id"] == "itihaas_ke_raaz":
        out.append(RULES["myth"])
    return "\n".join(out)


def plan(brain, script: dict, channel: dict, fmt: str = "short", log=print, chunk: int = 40) -> bool:
    """Adds see/cast/shot/action to every beat and script['bible']. One writer call per 40 beats. False = no plan
    (the old picture search runs unchanged)."""
    beats = script.get("beats") or []
    if not beats or all(b.get("see") for b in beats):
        return bool(beats)
    style = channel.get("style") or {}
    bible = dict(script.get("bible") or {})
    t0 = time.time()
    for start in range(0, len(beats), chunk):
        part = beats[start:start + chunk]
        lines = "\n".join(f"{start + k + 1}. {b.get('narration', '')}" for k, b in enumerate(part))
        if bible:
            lines = f"(Keep this bible: {json.dumps(bible, ensure_ascii=False)})\n" + lines
        prompt = PLAN_PROMPT.format(channel=channel.get("name", channel["id"]), fmt=fmt, title=script.get("title", ""),
                                    lang=channel.get("language", "en"), era=style.get("visual_era") or "from the story",
                                    rules=_rules(channel), beats=lines,
                                    max_numbers=max(1, round(len(part) * (0.12 if fmt == "short" else 0.06))))
        try:
            data, _ = brain.ask_json("writer", prompt, temperature=0.4)
        except Exception as e:  # noqa: BLE001 - no plan = old behaviour
            log(f"  storyboard: writer failed ({e}); using the picture search")
            return False
        if not isinstance(data, dict):
            return False
        bible = {**(data.get("bible") or {}), **bible} if bible else dict(data.get("bible") or {})
        shots = {int(s.get("i", 0)): s for s in data.get("shots") or [] if isinstance(s, dict) and str(s.get("i", "")).isdigit()}
        for k, b in enumerate(part):
            s = shots.get(start + k + 1)
            if not s or not str(s.get("see", "")).strip():
                continue
            b["see"] = str(s["see"]).strip()
            b["cast"] = [c for c in (s.get("cast") or []) if isinstance(c, str)]
            b["shot"] = s.get("type") if s.get("type") in TYPES else "scene"
            b["action"] = s.get("action") if s.get("action") in ACTIONS else ""
    script["bible"] = bible
    done = sum(1 for b in beats if b.get("see"))
    for b in beats:
        if b.get("see"):
            b["_prompt"] = prompt_for(b, bible, style)
            b["_era"] = bible.get("era", "")
            if b["shot"] == "scene":
                b["visual"] = "scene"
            elif b["shot"] == "number" and (b.get("big_text") or re.search(r"\d", b.get("narration", ""))):
                b["visual"] = "text"
            elif b["shot"] == "real":
                b["visual"] = "photo"
    log(f"  storyboard: {done}/{len(beats)} shots planned in {time.time() - t0:.0f}s")
    return done >= len(beats) * 0.7


def prompt_for(beat: dict, bible: dict, style: dict) -> str:
    cast = bible.get("cast") or {}
    who = "; ".join(f"{c}: {cast[c]}" for c in beat.get("cast") or [] if c in cast)
    parts = [beat.get("see", ""), who, bible.get("era", ""), style.get("ai_style", ""), "vertical composition", NO_TEXT]
    return ", ".join(p for p in parts if p)


# ---------------------------------------------------------------- draw
# 20 Nov: the PC's data/state is replaced by the cloud's copy on every pull, so a block the PC hit was forgotten within
# minutes and every PC video ran ~20 minutes into the picture step and failed again, all night (the Cloudflare account
# is shared with the cloud's night book pages). The PC keeps its own marks here; both files count.
QUOTA_PC = ROOT / "data" / "pc" / "image_quota.json"


def _read(path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _quota() -> dict:
    q = _read(QUOTA)
    for k, v in _read(QUOTA_PC).items():
        q[k] = max(float(v), float(q.get(k, 0)))
    return q


def _block(source: str) -> None:
    """Free daily allowance used up: skip this source until 00:00 UTC (both reset daily)."""
    from .core.where import in_runner
    path = QUOTA if in_runner() else QUOTA_PC
    q = _read(path)
    tomorrow = dt.datetime.now(dt.timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0) + dt.timedelta(days=1)
    q[source] = tomorrow.timestamp()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(q), encoding="utf-8")


def _open(source: str) -> bool:
    return time.time() >= float(_quota().get(source, 0))


class NoPictures(RuntimeError):
    """Both free picture sources are used up for today: make this video after the reset, never as word cards."""


def images_blocked() -> bool:
    """True when neither free picture source can draw today (Cloudflare blocked and HF blocked or no token)."""
    cf = bool(os.environ.get("CLOUDFLARE_ACCOUNT_ID") and os.environ.get("CLOUDFLARE_API_TOKEN")) and _open("cloudflare")
    hf = bool(os.environ.get("HF_TOKEN")) and _open("hf")
    po = bool(os.environ.get("POLLINATIONS_KEY")) and _open("pollinations")
    return not (cf or hf or po)


def reset_at() -> float:
    """When the first blocked source opens again (epoch seconds)."""
    q = _quota()
    return min([float(v) for v in q.values()] or [time.time()])


# Cloudflare picture models, best first. FLUX-schnell (Apache 2.0) is the look we tuned for; the two Stable Diffusion
# models (CreativeML OpenRAIL: commercial use allowed) take over when FLUX's share of the free allocation is gone
# (17 Nov: tested, they still answered). Each model is blocked for the day separately.
CF_MODELS = [("flux", "@cf/black-forest-labs/flux-1-schnell"),
             ("sdxl", "@cf/bytedance/stable-diffusion-xl-lightning"),
             ("dreamshaper", "@cf/lykon/dreamshaper-8-lcm")]
DAILY_GONE = re.compile(r"4006|daily free allocation|neurons", re.I)


def _cloudflare(prompt: str, seed: int, size: tuple[int, int] = (1080, 1920)) -> bytes | None:
    acct, token = os.environ.get("CLOUDFLARE_ACCOUNT_ID"), os.environ.get("CLOUDFLARE_API_TOKEN")
    if not (acct and token) or not _open("cloudflare"):
        return None
    w, h = (768, 1344) if size[1] > size[0] else (1344, 768)
    gone = 0
    for short, model in CF_MODELS:
        if not _open(f"cf_{short}"):
            gone += 1
            continue
        # FLUX's schema allows only prompt + steps (no seed, no size): 4 steps is schnell's design and halves the
        # neurons per picture. The SD models take a size and a seed.
        body = {"prompt": prompt[:2048], "steps": 4} if short == "flux" else \
            {"prompt": prompt[:2048], "width": w, "height": h, "seed": seed % 2_000_000_000}
        for attempt in range(3):
            try:
                r = requests.post(f"https://api.cloudflare.com/client/v4/accounts/{acct}/ai/run/{model}",
                                  headers={"Authorization": f"Bearer {token}"}, json=body, timeout=120)
            except requests.RequestException:
                break
            if "image" in (r.headers.get("content-type") or ""):
                return r.content                       # the SD models answer with the picture itself
            try:
                j = r.json()
            except ValueError:
                break
            errs = str(j.get("errors"))
            if DAILY_GONE.search(errs):                # the real daily limit: this model is done until 00:00 UTC
                _block(f"cf_{short}")
                gone += 1
                break
            if r.status_code == 429:                   # 17 Nov: a per-minute limit used to block pictures for the
                time.sleep(15 * (attempt + 1))         # whole day; now it only waits a little
                continue
            img = (j.get("result") or {}).get("image")
            if img:
                return base64.b64decode(img)
            break
    if gone == len(CF_MODELS):
        _block("cloudflare")
    return None


POLLINATIONS_MODEL = "zimage"          # Tongyi Z-Image Turbo (Apache 2.0: commercial use allowed); flat-rate, cheap


def _pollinations(prompt: str, seed: int, size: tuple[int, int]) -> bytes | None:
    """Third free picture source (17 Nov: Cloudflare's 10,000 daily neurons cover only ~10 Shorts for 14 channels).
    A free Pollinations account key (POLLINATIONS_KEY, no card). 402 = the free pollen is used up for today."""
    key = os.environ.get("POLLINATIONS_KEY")
    if not key or not _open("pollinations"):
        return None
    from urllib.parse import quote
    w, h = (1080, 1920) if size[1] > size[0] else (1920, 1080)     # Z-Image: up to 2.36 MP, so full HD directly
    for attempt in range(2):
        try:
            r = HTTP.get(f"https://gen.pollinations.ai/image/{quote(prompt[:1500])}", timeout=180,
                             params={"model": POLLINATIONS_MODEL, "width": w, "height": h, "seed": seed, "nologo": "true"},
                             headers={"Authorization": f"Bearer {key}"})
        except requests.RequestException:
            return None
        if r.status_code in (401, 402, 403):
            _block("pollinations")
            return None
        if r.status_code == 429:
            time.sleep(10 * (attempt + 1))
            continue
        if r.ok and r.headers.get("content-type", "").startswith("image/"):
            return r.content
        return None
    return None


def _hf(prompt: str, seed: int, size: tuple[int, int]) -> bytes | None:
    token = os.environ.get("HF_TOKEN")
    if not token or not _open("hf"):
        return None
    try:
        from gradio_client import Client
        w, h = (768, 1344) if size[1] > size[0] else (1344, 768)
        out = Client("black-forest-labs/FLUX.1-schnell", hf_token=token, verbose=False).predict(
            prompt=prompt[:1500], seed=seed, randomize_seed=False, width=w, height=h, num_inference_steps=4,
            api_name="/infer")
        path = out[0] if isinstance(out, (list, tuple)) else out
        return Path(path).read_bytes()
    except Exception as e:  # noqa: BLE001 - quota/outage: skip HF for the day only on a quota message
        if re.search(r"quota|exceeded|ZeroGPU", str(e), re.I):
            _block("hf")
        return None


def draw(prompt: str, seed: int, size: tuple[int, int], variant: int = 0) -> tuple[Path, str] | None:
    from .ip_guard import scrub                     # 20 Nov: never draw a copyrighted character (strike risk)
    prompt, _ = scrub(prompt)
    if variant:                                    # Cloudflare takes no seed: a redraw changes the composition words
        prompt = f"{prompt}, {('different camera angle', 'closer framing', 'wider framing')[variant % 3]}"
    key = hashlib.md5(f"{prompt}|{seed}|{size}".encode()).hexdigest()
    dest = CACHE / f"{key}.jpg"
    if dest.exists():
        return dest, "cache"
    for name, fn in (("cloudflare", lambda: _cloudflare(prompt, seed, size)),
                     ("pollinations", lambda: _pollinations(prompt, seed, size)), ("hf", lambda: _hf(prompt, seed, size))):
        data = fn()
        if data:
            from PIL import Image
            import io
            dest.parent.mkdir(parents=True, exist_ok=True)
            Image.open(io.BytesIO(data)).convert("RGB").save(dest, quality=93)
            return dest, name
    return None


# ---------------------------------------------------------------- eyes
def eyes(path: Path, narration: str, see: str, era: str = "") -> dict:
    """Free Gemini vision check. {"score": 0-10, "text": bool, "wrong": str, "ok": bool}. No key/limit -> ok with
    score -1 (unchecked) so a video is never blocked by the checker itself."""
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return {"score": -1, "text": False, "wrong": "", "ok": True}
    from PIL import Image
    import io
    im = Image.open(path).convert("RGB")
    im.thumbnail((512, 512))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=85)
    q = (f'Narration at this moment: "{narration}"\nIntended shot: "{see}"\nStory era/place: {era or "unknown"}\n'
         'Rate how well the picture shows this moment for a viewer (0-10). Report any visible letters/text/garbled '
         'writing, and anything clearly wrong (wrong era, wrong place, extra limbs, wrong object). JSON only: '
         '{"shows": "8 words", "score": 0, "text": false, "wrong": "none"}')
    try:
        r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{EYES_MODEL}:generateContent",
                          headers={"x-goog-api-key": key}, timeout=60,
                          json={"contents": [{"parts": [{"inline_data": {"mime_type": "image/jpeg",
                                                                         "data": base64.b64encode(buf.getvalue()).decode()}},
                                                        {"text": q}]}],
                                "generationConfig": {"responseMimeType": "application/json", "temperature": 0}})
        j = json.loads(r.json()["candidates"][0]["content"]["parts"][0]["text"])
        if isinstance(j, list):                    # sometimes [{...}]
            j = next((x for x in j if isinstance(x, dict)), {})
        score = int(float(j.get("score") or 0))
    except Exception:  # noqa: BLE001 - checker down / odd answer: don't block
        return {"score": -1, "text": False, "wrong": "", "ok": True}
    wrong = str(j.get("wrong") or "").strip()
    wrong = "" if wrong.lower() in ("none", "no", "n/a", "") else wrong
    text = bool(j.get("text"))
    return {"score": score, "text": text, "wrong": wrong, "shows": j.get("shows", ""),
            "ok": score >= PASS and not text and (not wrong or score >= 8)}   # light: nitpicks on a good shot pass


# ---------------------------------------------------------------- one shot
def scene(beat: dict, era: str, size: tuple[int, int], log=print, i: int = 0, tries: int = 3,
          seed: int | None = None) -> dict | None:
    """Draw + check one beat's shot. Returns a story visual dict, or None when no free source is left today."""
    prompt = beat.get("_prompt")
    if not prompt:
        return None
    best, base = None, seed if seed is not None else (int(hashlib.md5(prompt.encode()).hexdigest()[:6], 16) % 100000)
    for t in range(tries):
        got = draw(prompt, base + t * 977, size, variant=t)
        if not got:
            break
        path, src = got
        verdict = eyes(path, beat.get("narration", ""), beat.get("see", ""), era)
        if best is None or verdict["score"] > best[1]["score"]:
            best = (path, verdict, src)
        if verdict["ok"]:
            break
        why = "text in picture" if verdict["text"] else (verdict["wrong"] or f"score {verdict['score']}")
        log(f"  beat {i + 1}: redraw ({why})")
    if not best:
        return None
    path, verdict, src = best
    return {"kind": "image", "path": path, "frame": "full", "credit": "AI-generated image",
            "source": f"ai_scene_{src}", "match": max(0.0, verdict["score"]) / 10 if verdict["score"] >= 0 else 0.85,
            "eyes": verdict}


def check_photo(vis: dict, beat: dict, era: str) -> bool:
    """A library photo/clip found for a storyboard beat must also pass the eyes check (keyword matches showed a garden
    bridge for 'saltwater')."""
    path = vis.get("path")
    if not path or not beat.get("see"):
        return True
    p = Path(str(path))
    if p.suffix.lower() in (".mp4", ".mov", ".webm"):
        import subprocess
        frame = p.with_suffix(".eyes.jpg")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "0.5", "-i", str(p), "-frames:v", "1", str(frame)],
                       check=False)
        if not frame.exists():
            return True
        p = frame
    v = eyes(p, beat.get("narration", ""), beat.get("see", ""), era)
    return v["ok"] or v["score"] < 0
