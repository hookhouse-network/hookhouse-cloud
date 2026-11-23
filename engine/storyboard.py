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
# 23 Nov: in a burst of test calls 21 of 36 came back unchecked (Gemini: 503 "currently experiencing high demand"), and
# an unchecked picture counts as fine without anyone looking (match 0.85). A busy answer is now asked again twice.
EYES_BUSY = (429, 500, 502, 503, 504)
EYES_RETRY_S = (4, 12)
PASS = 7                                          # eyes score (0-10) a picture needs

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
    from .style_cards import visual_text            # S8 A16: one consistent look per channel (not random stock)
    look = visual_text(channel["id"])
    if look:
        out.append(look)
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


# 22 Nov: Cloudflare's free allocation did NOT come back at 00:00 UTC as its pricing page says: at 00:15 and 00:23 UTC
# FLUX still answered 4006 'used up your daily free allocation' (nothing else on the account had run since 20:32 UTC).
# Community reports and a cloudflare-docs issue (#34137) describe the same: 4006 for hours after the reset, the first
# success ~24 h after the last use (a rolling window, it seems). Blocking until the next 00:00 UTC then locked the
# pictures out for a whole day after one failed call. A blocked Cloudflare source is now re-tested at most once an
# hour by ONE tiny call to the first picture model (a 4006 answer costs nothing); a pass opens it again.
PROBE_S = 3600
CF_SOURCES = ("cloudflare", "cf_flux", "cf_klein", "cf_sdxl", "cf_dreamshaper")


def _write(path, q: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(q), encoding="utf-8")


def _block(source: str) -> None:
    """Free daily allowance used up: skip this source until 00:00 UTC (the documented reset); a Cloudflare source is
    re-tested hourly before that (_probe)."""
    from .core.where import in_runner
    path = QUOTA if in_runner() else QUOTA_PC
    q = _read(path)
    tomorrow = dt.datetime.now(dt.timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0) + dt.timedelta(days=1)
    q[source] = tomorrow.timestamp()
    q[f"at:{source}"] = time.time()                    # a later passing probe (ok:) outranks this block
    if source in CF_SOURCES:
        q[f"probe:{source}"] = time.time() + PROBE_S
    _write(path, q)


def _open(source: str) -> bool:
    q = _quota()
    if time.time() >= float(q.get(source, 0)):
        return True
    if float(q.get(f"ok:{source}", 0)) > float(q.get(f"at:{source}", 0)):
        return True                                    # a test call after the last block got a picture
    if source in CF_SOURCES and time.time() >= float(q.get(f"probe:{source}", 0)):
        return _probe()
    return False


def _probe() -> bool:
    """Does Cloudflare draw again? One tiny call to the first picture model (klein: a 256x256 picture, 1 tile, ~26
    neurons; FLUX-schnell: 1 step, 57.6 neurons); the result counts for every Cloudflare model (the free allocation
    is one per account). The next test is due an hour later either way."""
    from .core.where import in_runner
    path = QUOTA if in_runner() else QUOTA_PC
    now, ok = time.time(), False
    acct, token = os.environ.get("CLOUDFLARE_ACCOUNT_ID"), os.environ.get("CLOUDFLARE_API_TOKEN")
    if acct and token:
        try:
            short, model = cf_models()[0]
            r = _cf_post(short, model, "a red apple on a wooden table", 1, PROBE_SIZE, steps=1, timeout=60)
            ok = bool(((r.json() or {}).get("result") or {}).get("image"))
        except (requests.RequestException, ValueError, AttributeError) as e:
            print(f"picture quota test call: {type(e).__name__}")
    q = _read(path)
    for s in CF_SOURCES:
        q[f"probe:{s}"] = now + PROBE_S
        if ok:
            q[f"ok:{s}"] = now
    _write(path, q)
    print("AI pictures: Cloudflare draws again (test call passed)" if ok else
          "AI pictures: Cloudflare still says the free allowance is used up; next test in an hour", flush=True)
    return ok


class NoPictures(RuntimeError):
    """Both free picture sources are used up for today: make this video after the reset, never as word cards."""


def images_blocked() -> bool:
    """True when no picture source can draw now: the free cloud ones are used up (or have no key) and the PC can't
    draw locally (22 Nov: engine/media/local_sd.py, PC only, idle + plugged in, capped)."""
    cf = bool(os.environ.get("CLOUDFLARE_ACCOUNT_ID") and os.environ.get("CLOUDFLARE_API_TOKEN")) and _open("cloudflare")
    hf = bool(os.environ.get("HF_TOKEN")) and _open("hf")
    po = bool(os.environ.get("POLLINATIONS_KEY")) and _open("pollinations")
    if cf or hf or po:
        return False
    from .media import local_sd
    return not local_sd.available()


def _local(prompt: str, seed: int, size: tuple[int, int]) -> bytes | None:
    from .media import local_sd
    return local_sd.draw(prompt, seed, size)


LOCAL_TRIES = 2          # draws per scene when they come from the PC (each ~2 CPU minutes; cloud pictures: 3)


def enlarge_small(path: Path) -> None:
    """A cached picture under 650 px on its short side can only be a PC picture drawn before 22 Nov 10:00 (512 px;
    every cloud model draws 768+): enlarge it in place, or the renderer frames it as a small dark card."""
    from PIL import Image
    try:
        with Image.open(path) as im:
            small = min(im.size) < 650
    except OSError as e:
        print(f"cached picture unreadable ({path.name}): {type(e).__name__}")
        return
    if small:
        import io
        from .media import local_sd
        big = Image.open(io.BytesIO(local_sd._enlarge(path.read_bytes()))).convert("RGB")
        big.save(path, quality=93)


def reset_at() -> float:
    """When the first blocked source opens again (epoch seconds): its reset, or its next test call (Cloudflare).
    Only blocks still running count: an old, expired mark (a retired model's) used to pull this into the past."""
    q, now = _quota(), time.time()
    return min([min(float(v), float(q.get(f"probe:{k}", v))) if k in CF_SOURCES else float(v)
                for k, v in q.items() if ":" not in k and float(v) > now] or [now])


# Cloudflare picture models. FLUX-schnell (Apache 2.0) is the look we tuned for. 22 Nov: the two Stable Diffusion
# backups (SDXL-Lightning, DreamShaper-8-LCM) were unbilled (0 neurons) and drew whenever FLUX's 10,000 free daily
# neurons were gone, but Cloudflare RETIRED both on 20 Nov (HTTP 410, code 5028 'Model has been deprecated'), the day
# our posting stopped; every call since failed quietly. The names cf_sdxl/cf_dreamshaper stay in CF_SOURCES for old
# quota files.
# 23 Nov, measured in Cloudflare's own usage records (GraphQL aiInferenceAdaptiveGroups, 20-23 Nov): a FLUX-schnell
# picture costs 172.8 neurons, not ~58. Its step price is charged per 512x512 tile: a 1024x1024 picture is 4 tiles x
# (4.8 + 4 steps x 9.6). So the 10,000 free daily neurons draw only ~57 pictures (4-5 Shorts), and a Short crops that
# square to ~576x1024. FLUX.2 [klein] 4B (Apache 2.0; in Cloudflare's catalog since 15 Jan 2026) costs 26.05 neurons
# per output tile with its 4 steps included, billed on the longer side. A 576x1024 vertical picture is 4 tiles, about
# 104 neurons (~96 pictures a day), drawn in the Short's own 9:16 shape. settings.yaml cf_picture_models sets the order.
CF_CATALOG = {"klein": "@cf/black-forest-labs/flux-2-klein-4b", "flux": "@cf/black-forest-labs/flux-1-schnell"}
CF_MODELS = [("flux", CF_CATALOG["flux"])]        # the default order when settings.yaml names none
KLEIN_SIZE = {"vertical": (576, 1024), "landscape": (1024, 576)}   # longer side 1024: 4 billed tiles
PROBE_SIZE = (256, 256)                           # klein's test call: 1 tile, ~26 neurons when it draws
DAILY_GONE = re.compile(r"4006|daily free allocation|neurons", re.I)
RETIRED = re.compile(r"5028|deprecated", re.I)
_CF_SAID: set = set()                             # odd Cloudflare answers already logged (once per model and code)


def cf_models() -> list[tuple[str, str]]:
    """The Cloudflare picture models to try, best first: settings.yaml cf_picture_models (names from CF_CATALOG);
    unknown names are skipped, and an empty or broken setting keeps CF_MODELS."""
    from .config import settings
    try:
        order = [str(m).strip() for m in (settings().get("cf_picture_models") or [])]
    except Exception:  # noqa: BLE001 - a broken setting never stops the pictures
        order = []
    return [(m, CF_CATALOG[m]) for m in dict.fromkeys(order) if m in CF_CATALOG] or list(CF_MODELS)


def _cf_post(short: str, model: str, prompt: str, seed: int, size: tuple[int, int], steps: int = 4,
             timeout: int = 120):
    """One Cloudflare picture request in the model's own format. FLUX.2 [klein] takes multipart form data even for a
    prompt alone (Cloudflare changelog, 15 Jan 2026), with a size and a seed; FLUX-schnell takes JSON with only
    prompt + steps (its schema has no seed and no size)."""
    acct, token = os.environ.get("CLOUDFLARE_ACCOUNT_ID"), os.environ.get("CLOUDFLARE_API_TOKEN")
    url = f"https://api.cloudflare.com/client/v4/accounts/{acct}/ai/run/{model}"
    head = {"Authorization": f"Bearer {token}"}
    if short == "klein":
        form = {"prompt": (None, prompt[:2048]), "width": (None, str(size[0])), "height": (None, str(size[1])),
                "seed": (None, str(seed % 2_000_000_000))}
        return requests.post(url, headers=head, files=form, timeout=timeout)
    return requests.post(url, headers=head, json={"prompt": prompt[:2048], "steps": steps}, timeout=timeout)


def _full_size(data: bytes, short: str) -> bytes:
    """A klein picture is 576 px on its short side; the renderer shows anything under 650 px as a small framed card
    (story._v3_frame), so it is enlarged once to 1080 px (Lanczos + a light sharpen, like the PC's own pictures).
    A FLUX-schnell square is kept as it is."""
    if short != "klein":
        return data
    from .media import local_sd
    return local_sd._enlarge(data)


def _retired(model: str, status: int, errs: str) -> None:
    """A Cloudflare model answered 'deprecated' (410/5028): say it loudly and queue a code fix. 20 Nov the two backup
    models were retired and nothing noticed for two days."""
    msg = (f"Cloudflare retired the picture model {model} (HTTP {status}: {errs[:160]}); pick another in CF_CATALOG "
           "(settings.yaml cf_picture_models)")
    print(f"AI pictures: {msg}")
    try:
        from . import heal
        heal.report("pictures", msg)
    except Exception as e:  # noqa: BLE001 - the heal queue never stops a picture
        print(f"heal queue: {type(e).__name__}: {e}")


def _cloudflare(prompt: str, seed: int, size: tuple[int, int] = (1080, 1920)) -> bytes | None:
    acct, token = os.environ.get("CLOUDFLARE_ACCOUNT_ID"), os.environ.get("CLOUDFLARE_API_TOKEN")
    if not (acct and token) or not _open("cloudflare"):
        return None
    models = cf_models()
    gone = 0
    for short, model in models:
        if not _open(f"cf_{short}"):
            gone += 1
            continue
        # FLUX-schnell: prompt + 4 steps (schnell's design), always a 1024x1024 square. klein: the frame's own shape.
        want = KLEIN_SIZE["vertical" if size[1] > size[0] else "landscape"] if short == "klein" else (1024, 1024)
        for attempt in range(3):
            try:
                r = _cf_post(short, model, prompt, seed, want)
            except requests.RequestException:
                break
            if "image" in (r.headers.get("content-type") or ""):
                return _full_size(r.content, short)    # a model that answers with the picture itself
            try:
                j = r.json()
            except ValueError:
                break
            errs = str(j.get("errors"))
            if DAILY_GONE.search(errs):                # the real daily limit: this model is done until 00:00 UTC
                _block(f"cf_{short}")
                gone += 1
                break
            if r.status_code == 410 or RETIRED.search(errs):
                _retired(model, r.status_code, errs)   # skipped for the day; the heal queue asks for a code fix
                _block(f"cf_{short}")
                gone += 1
                break
            if r.status_code == 429:                   # 17 Nov: a per-minute limit used to block pictures for the
                time.sleep(15 * (attempt + 1))         # whole day; now it only waits a little
                continue
            img = (j.get("result") or {}).get("image")
            if img:
                return _full_size(base64.b64decode(img), short)
            said = (short, r.status_code)              # any other answer: the next model draws; said once, never silent
            if said not in _CF_SAID:
                _CF_SAID.add(said)
                print(f"AI pictures: Cloudflare {short} gave no picture (HTTP {r.status_code}: {errs[:160]}); "
                      "trying the next model", flush=True)
            break
    if gone == len(models):
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
        enlarge_small(dest)
        return dest, "cache"
    for name, fn in (("cloudflare", lambda: _cloudflare(prompt, seed, size)),
                     ("pollinations", lambda: _pollinations(prompt, seed, size)), ("hf", lambda: _hf(prompt, seed, size)),
                     ("local_sd", lambda: _local(prompt, seed, size))):       # last: the PC's own, slow and capped
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
    body = {"contents": [{"parts": [{"inline_data": {"mime_type": "image/jpeg",
                                                     "data": base64.b64encode(buf.getvalue()).decode()}},
                                    {"text": q}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0}}
    r = None
    for wait in (0,) + EYES_RETRY_S:
        if wait:
            time.sleep(wait)
        try:
            r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{EYES_MODEL}:generateContent",
                              headers={"x-goog-api-key": key}, timeout=60, json=body)
        except requests.RequestException:
            r = None
            continue
        code = getattr(r, "status_code", 200)
        if code not in EYES_BUSY or "PerDay" in str(getattr(r, "text", "")):   # a used-up daily quota: waiting won't help
            break
    try:
        if r is None or getattr(r, "status_code", 200) != 200:
            raise RuntimeError(f"eyes check unavailable ({getattr(r, 'status_code', 'no answer')})")
        j = json.loads(r.json()["candidates"][0]["content"]["parts"][0]["text"])
        if isinstance(j, list):                    # sometimes [{...}]
            j = next((x for x in j if isinstance(x, dict)), {})
        score = int(float(j.get("score") or 0))
    except Exception as e:  # noqa: BLE001 - checker down / odd answer: don't block (said, never silent)
        print(f"  eyes check skipped: {str(e)[:80] or type(e).__name__}; the picture is kept unchecked", flush=True)
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
        if src == "local_sd" and t + 1 >= LOCAL_TRIES:   # 22 Nov: ~2 CPU minutes a local picture: keep the best
            break
        why = "text in picture" if verdict["text"] else (verdict["wrong"] or f"score {verdict['score']}")
        log(f"  beat {i + 1}: redraw ({why})")
    if not best:
        return None
    path, verdict, src = best
    return {"kind": "image", "path": path, "frame": "full", "credit": "AI-generated image",
            "source": f"ai_scene_{src}", "match": max(0.0, verdict["score"]) / 10 if verdict["score"] >= 0 else 0.85,
            "eyes": verdict}


# ---------------------------------------------------------------- P3b asset bank (pictures of the last version)
# 22 Nov: a remake (gate redo) writes a new script, so every shot prompt changed and every picture was drawn again:
# Itihaas 22 Nov 12:30 was drawn three times the same morning, and the redos the potential gate then held took
# Cloudflare's free allowance and the PC's 60 local pictures. The last version's pictures of the same video are now
# offered first. Word overlap only ranks them (the same moment is written differently each time: "Kautsa bowing before
# his guru" vs "Rishi Kouts bowing before Raja Raghu" overlap 0.16); the eyes check decides, against the NEW narration.
REUSE_MIN = 0.15             # word overlap an old picture's shot needs before the eyes check looks at it
REUSE_BLIND = 0.5            # overlap that is enough on its own when the eyes check is off (no key / down)
_SHOT_STOP = {"a", "an", "the", "of", "in", "on", "at", "with", "and", "or", "to", "from", "by", "for", "is", "are",
              "his", "her", "their", "its", "close", "up", "close-up", "shot", "wide", "view", "scene", "showing",
              "shows", "while", "as", "into", "over", "under", "behind", "front", "background", "foreground",
              "dramatic", "cinematic", "angle", "low", "high", "medium", "aerial", "camera", "frame", "framing",
              "toward", "towards", "through", "extreme", "macro", "real", "photo"}


def _shot_words(see: str) -> set[str]:
    return {re.sub(r"(?<=[a-z]{3})s$", "", w.lower()) for w in re.findall(r"[A-Za-z][A-Za-z'-]{2,}", see or "")} \
        - _SHOT_STOP


def shot_overlap(a: str, b: str) -> float:
    """0-1: shared content words of two shot descriptions (Jaccard; camera words and plurals ignored)."""
    wa, wb = _shot_words(a), _shot_words(b)
    return len(wa & wb) / len(wa | wb) if wa and wb else 0.0


def same_shot(a, b) -> bool:
    """The very same shot description (a retry of the same script), spacing and case aside."""
    na, nb = (" ".join(str(x or "").lower().split()) for x in (a, b))
    return bool(na) and na == nb


SAME_SHOT_MATCH = 0.7          # a stored eyes score (match) this good is trusted again for the very same shot


def _stored_match(s: dict) -> float:
    try:
        return float(s.get("match") or 0)
    except (TypeError, ValueError):
        return 0.0


def reuse(beat: dict, bank: list[dict], era: str = "", log=print, i: int = 0) -> dict | None:
    """The best picture of the video's last version for this beat, if the eyes check says it shows THIS moment (one
    check per beat). A reused picture leaves the bank (never twice in one video). The caller keeps the opening shot
    new (the hook is what a remake must change) unless the bank holds the very same shot. The very same shot with a
    good stored eyes score needs no new check (22 Nov: a retry of the same script after the picture limit)."""
    see = str(beat.get("see") or "")
    if not see or not bank:
        return None
    cands = []
    for s in bank:
        p = Path(str(s.get("path") or ""))
        if s.get("kind", "image") != "image" or not str(s.get("source") or "").startswith("ai_scene") or not p.is_file():
            continue
        cands.append((shot_overlap(see, str(s.get("see") or "")), s, p))
    if not cands:
        return None
    sim, s, p = max(cands, key=lambda c: (same_shot(see, c[1].get("see")), c[0]))
    if sim < REUSE_MIN:
        return None
    if same_shot(see, s.get("see")) and _stored_match(s) >= SAME_SHOT_MATCH:
        bank.remove(s)
        log(f"  beat {i + 1}: the same shot's picture from the stopped try reused (stored match {_stored_match(s):.2f})")
        return {"kind": "image", "path": p, "frame": "full", "credit": "AI-generated image", "source": "ai_scene_reuse",
                "match": _stored_match(s), "eyes": {"score": round(_stored_match(s) * 10), "ok": True, "stored": True}}
    verdict = eyes(p, beat.get("narration", ""), see, era)
    if not (verdict["ok"] and (verdict["score"] >= 0 or sim >= REUSE_BLIND)):
        log(f"  beat {i + 1}: last version's closest picture doesn't fit (overlap {sim:.2f}, eyes {verdict['score']});"
            " drawing a new one")
        return None
    bank.remove(s)
    log(f"  beat {i + 1}: picture from the last version reused (overlap {sim:.2f}, eyes {verdict['score']})")
    return {"kind": "image", "path": p, "frame": "full", "credit": "AI-generated image", "source": "ai_scene_reuse",
            "match": max(0.0, verdict["score"]) / 10 if verdict["score"] >= 0 else 0.85, "eyes": verdict}


UNCHECKED = {"score": -1, "text": False, "wrong": "", "ok": True}


def photo_verdict(vis: dict, beat: dict, era: str) -> dict:
    """The eyes verdict for a photo/clip/AI picture found for a storyboard beat (score -1 = not checked: no picture,
    no intended shot, or the checker is off)."""
    path = vis.get("path")
    if not path or not beat.get("see"):
        return dict(UNCHECKED)
    p = Path(str(path))
    if p.suffix.lower() in (".mp4", ".mov", ".webm"):
        import subprocess
        frame = p.with_suffix(".eyes.jpg")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "0.5", "-i", str(p), "-frames:v", "1", str(frame)],
                       check=False)
        if not frame.exists():
            return dict(UNCHECKED)
        p = frame
    return eyes(p, beat.get("narration", ""), beat.get("see", ""), era)


def check_photo(vis: dict, beat: dict, era: str) -> bool:
    """A library photo/clip found for a storyboard beat must also pass the eyes check (keyword matches showed a garden
    bridge for 'saltwater')."""
    v = photo_verdict(vis, beat, era)
    return v["ok"] or v["score"] < 0
