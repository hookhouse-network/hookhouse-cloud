"""Real background music that fits each video (owner, 18 Nov 2026: "currently the system uses the same kind of
background music ... not related to the video content; fun music, brain-rot sound effects, mystery music,
trending music ... according to the video content").

Before: every story video got one code-synthesised bed per channel look ("dark", "epic", "upbeat"), so every
Unsolved After Dark video sounded the same. Now:
1. mood_for(): each video gets a mood from its own script (the writer's "music_mood", else keywords in the title /
   summary, else the channel's default), from MOODS below.
2. track(): a real recorded track for that mood from our catalogue, never one the channel used in its last
   RECENT videos. Looped with a crossfade to the video's length; story._mix ducks it under the voice as before.
3. Catalogue: the Openverse audio API (official, free, no key; checked 18 Nov 2026) filtered to licences that
   allow commercial use: CC0 (no credit needed) first, CC BY (credit line added to the description). Sources:
   Freesound and Wikimedia Commons only. Jamendo is skipped on purpose: many of its tracks are registered with
   YouTube Content ID through Jamendo Licensing, which would put claims on our videos.
   Refreshed weekly per mood (a few API calls), kept in data/state/music_catalog.json (cloud memory); the files
   themselves are fetched from the source's CDN when a video needs them and cached in data/music_lib/.
No track found / offline: the old synthesised bed is used, so a video never fails because of music.
Trending commercial songs are NOT used: they are copyrighted (Content ID claims, muted audio, campaign rules
"no added music"); YouTube's own Shorts sounds can only be added in the YouTube app.
"""
from __future__ import annotations

import json
import random
import re
import time
from pathlib import Path

from ..config import ROOT

API = "https://api.openverse.org/v1/audio/"
CATALOG = ROOT / "data" / "state" / "music_catalog.json"
LIB = ROOT / "data" / "music_lib"
SOURCES = ("freesound", "wikimedia_audio")
REFRESH_D = 7
RECENT = 6
MIN_S, MAX_S = 25, 420
UA = {"User-Agent": "HookHouse-music/1.0"}

# mood -> (search words, synthesised fallback mood)
MOODS = {
    "mystery": (["mystery music", "suspense ambient", "dark mysterious"], "dark"),
    "suspense": (["thriller tension", "suspense build"], "dark"),
    "epic": (["epic orchestral", "cinematic trailer music"], "epic"),
    "emotional": (["emotional piano", "sad piano music"], "dark"),
    "hopeful": (["uplifting inspiring music", "hopeful piano"], "upbeat"),
    "playful": (["playful happy music", "ukulele happy"], "upbeat"),
    "quirky": (["quirky funny music", "silly comedy music", "funny cartoon music", "comedy loop", "goofy"], "upbeat"),
    "kids": (["children happy music", "cartoon music kids"], "upbeat"),
    "calm": (["calm ambient music", "relaxing peaceful"], "ocean"),
    "lofi": (["lofi chill beat", "chill hop"], "upbeat"),
    "energetic": (["energetic rock", "action drums music"], "epic"),
    "nostalgic": (["nostalgic retro music", "vintage old music"], "retro"),
    "wonder": (["space ambient music", "wonder discovery cinematic"], "cosmic"),
}
KEYWORDS = [
    (r"murder|vanish|disappear|missing|unsolved|haunt|ghost|secret|mystery|strange|creepy|cold case", "mystery"),
    (r"war|battle|empire|king|legend|final|champion|record|greatest|comeback|clutch", "epic"),
    (r"died|tragedy|lost|farewell|grief|sacrifice|tears|alone", "emotional"),
    (r"hope|rescue|survive|saved|miracle|kindness|dream", "hopeful"),
    (r"space|planet|galaxy|star|universe|cosmos|ocean|deep sea", "wonder"),
    (r"money|budget|save|invest|tips|hack|trick", "lofi"),
    (r"funny|weird|would you rather|quiz|rank|fail|silly|meme", "quirky"),
    (r"retro|90s|80s|old school|childhood|nostalgia|classic", "nostalgic"),
]
CHANNEL_DEFAULT = {"unsolved_after_dark": "mystery", "creepy_case_club": "mystery", "clutch_tales": "epic",
                   "ending_decoded": "suspense", "money_cheat_codes": "lofi", "brain_snack": "quirky",
                   "cosmos_unboxed": "wonder", "bloop_and_friends": "kids"}


# The music the video switches to at its climax (owner 18 Nov: "music according to video's vibe, transition music"):
# the story's turn gets its own, stronger track instead of one bed from start to end.
CLIMAX = {"mystery": "suspense", "suspense": "epic", "emotional": "hopeful", "hopeful": "epic", "wonder": "epic",
          "calm": "wonder", "nostalgic": "emotional", "lofi": "energetic", "playful": "energetic",
          "quirky": "energetic", "epic": "energetic", "energetic": "epic"}


def climax_mood(mood: str) -> str | None:
    """The mood the music turns into at the climax (None: keep one track, e.g. kids videos)."""
    return CLIMAX.get(mood)


# ---------------- choosing the mood ----------------
def mood_for(channel: dict, script: dict | None = None, fallback: str = "") -> str:
    script = script or {}
    m = str(script.get("music_mood") or "").lower().strip()
    if m in MOODS:
        return m
    text = " ".join(str(script.get(k) or "") for k in ("title", "summary", "hook_text", "search_phrase")).lower()
    for rx, mood in KEYWORDS:
        if re.search(rx, text):
            return mood
    if channel.get("id") in CHANNEL_DEFAULT:
        return CHANNEL_DEFAULT[channel["id"]]
    return {"dark": "mystery", "epic": "epic", "upbeat": "playful", "cosmic": "wonder", "ocean": "calm",
            "wild": "wonder"}.get(fallback, "mystery")


# ---------------- catalogue ----------------
def _load() -> dict:
    try:
        return json.loads(CATALOG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"moods": {}, "used": {}}


def _save(c: dict) -> None:
    CATALOG.parent.mkdir(parents=True, exist_ok=True)
    CATALOG.write_text(json.dumps(c, indent=1, ensure_ascii=False), encoding="utf-8")


def _search(q: str, session, licence: str) -> list[dict]:
    r = session.get(API, headers=UA, timeout=30, params={
        "q": q, "license": licence, "license_type": "commercial", "source": ",".join(SOURCES), "page_size": 20})
    if r.status_code == 429:
        raise RuntimeError("Openverse rate limit")
    r.raise_for_status()
    out = []
    for it in r.json().get("results") or []:
        dur = (it.get("duration") or 0) / 1000
        tags = " ".join(t.get("name", "") for t in it.get("tags") or []).lower()
        title = (it.get("title") or "").lower()
        if not (MIN_S <= dur <= MAX_S) or re.search(r"vocal|voice|speech|sing|lyrics|sfx|effect", f"{title} {tags}"):
            continue
        out.append({"id": it["id"], "title": it.get("title", ""), "creator": it.get("creator") or "unknown",
                    "license": it.get("license"), "license_version": it.get("license_version") or "",
                    "url": it.get("url"), "page": it.get("foreign_landing_url") or "", "seconds": round(dur),
                    "source": it.get("source")})
    return out


def refresh(moods=None, session=None, log=print, force: bool = False) -> int:
    """Weekly: fill each mood with up to 12 commercial-use tracks (CC0 first)."""
    import requests
    session = session or requests
    c = _load()
    n = 0
    for mood in moods or MOODS:
        rec = c["moods"].get(mood) or {}
        if not force and time.time() - rec.get("at", 0) < REFRESH_D * 86400 and rec.get("tracks"):
            continue
        tracks: dict[str, dict] = {}
        try:
            for licence in ("cc0", "by"):
                for q in MOODS[mood][0]:
                    for t in _search(q, session, licence):
                        tracks.setdefault(t["id"], t)
                    if len(tracks) >= 12:
                        break
                if len(tracks) >= 12:
                    break
        except Exception as e:  # noqa: BLE001 - keep last week's list
            log(f"music {mood}: {e}")
            continue
        if tracks:
            c["moods"][mood] = {"at": time.time(), "tracks": list(tracks.values())[:12]}
            n += len(tracks)
    _save(c)
    log(f"music catalogue: {n} tracks refreshed")
    return n


def credit(t: dict) -> str:
    """Description line (CC BY needs title, author, source and licence; CC0 is credited as a courtesy)."""
    lic = "CC0" if t["license"] == "cc0" else f"CC BY {t.get('license_version') or ''}".strip()
    return f"Music: \"{t['title']}\" by {t['creator']} ({lic}) {t.get('page') or t.get('url')}"


def _fetch(t: dict, session) -> Path | None:
    LIB.mkdir(parents=True, exist_ok=True)
    ext = Path(t["url"].split("?")[0]).suffix or ".mp3"
    p = LIB / f"{t['id']}{ext}"
    if p.exists() and p.stat().st_size > 20_000:
        return p
    r = session.get(t["url"], headers=UA, timeout=60)
    if not r.ok or len(r.content) < 20_000:
        return None
    p.write_bytes(r.content)
    return p


def track(mood: str, channel_id: str, session=None, log=print, rng=None) -> tuple[Path, dict] | None:
    """A file + its catalogue entry for this mood that the channel hasn't used lately, or None."""
    import requests
    session = session or requests
    rng = rng or random.Random()
    c = _load()
    if not (c["moods"].get(mood) or {}).get("tracks"):
        try:
            refresh([mood], session=session, log=log)
            c = _load()
        except Exception as e:  # noqa: BLE001
            log(f"music: {e}")
    tracks = list((c["moods"].get(mood) or {}).get("tracks") or [])
    recent = c.setdefault("used", {}).get(channel_id, [])
    fresh = [t for t in tracks if t["id"] not in recent] or tracks
    rng.shuffle(fresh)
    fresh.sort(key=lambda t: t["license"] != "cc0")            # CC0 first, the shuffle keeps variety inside
    for t in fresh[:4]:
        try:
            p = _fetch(t, session)
        except Exception:  # noqa: BLE001
            p = None
        if p:
            c["used"][channel_id] = ([t["id"]] + recent)[:RECENT]
            _save(c)
            return p, t
    return None


def intro_end(x, sr: int, win: float = 0.5, frac: float = 0.5, max_s: float = 20.0) -> int:
    """Sample where the music gets going: the first half-second whose level reaches half the track's typical level
    (owner 18 Nov: the first 3 s of a Short decide the swipe; a quiet 8 s intro under the hook wastes them).
    0 when the track starts strong (under 1 s of quiet is a pickup, kept) or never builds within `max_s`."""
    import numpy as np
    w = int(win * sr)
    m = len(x) // w
    if m < 4:
        return 0
    rms = np.sqrt((x[: m * w].reshape(m, w) ** 2).mean(axis=1))
    body = float(np.median(rms))
    if body <= 1e-6:
        return 0
    for k in range(min(m, int(max_s / win))):
        if rms[k] >= frac * body:
            return k * w if k >= 2 else 0
    return 0


def bed(path: Path, seconds: float, sr: int = 48000, skip_intro: bool = True):
    """Decode, skip a quiet intro, loop with a 2 s crossfade to `seconds`, fade in/out. Mono float32."""
    import subprocess
    import numpy as np
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    x = np.frombuffer(raw, dtype=np.float32).copy()
    if len(x) < sr * 5:
        raise ValueError("track too short")
    skip = intro_end(x, sr) if skip_intro else 0
    if len(x) - skip >= sr * 5:
        x = x[skip:]
    n, xf = int(seconds * sr), int(2 * sr)
    out = x[:n] if len(x) >= n else x.copy()
    while len(out) < n:
        ramp = np.linspace(0, 1, xf, dtype=np.float32)
        out[-xf:] = out[-xf:] * (1 - ramp) + x[:xf] * ramp
        out = np.concatenate([out, x[xf:]])
    out = out[:n]
    f = int(min(1.0, seconds / 4) * sr)
    out[:f] *= np.linspace(0, 1, f, dtype=np.float32)
    out[-f:] *= np.linspace(1, 0, f, dtype=np.float32)
    return out / (np.abs(out).max() + 1e-9) * 0.7
