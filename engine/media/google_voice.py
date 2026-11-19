"""Natural Hindi narration with Google Cloud Text-to-Speech "Chirp 3: HD" voices (owner, 13 Nov 2026: "in Hindi your
voice is too odd and breaking... make them more human and conversational").

Why this one (research 13 Nov, docs/hindi_voice_fix_2026-11-13.md):
- Chirp 3 HD supports hi-IN and is built for natural, conversational speech (Google's docs: "smooth flow",
  "realistic pauses", "conversational tone"); it reads numbers, rupees and English words inside Hindi correctly.
- Free tier: 1 million Chirp 3 HD characters a month (Google's pricing page), about 10x what our three Hindi channels
  use, so we stay at ₹0. A monthly counter stops at 900,000 and falls back to Kokoro, so it can never bill.
- Commercial use of the generated audio is allowed under Google Cloud's terms; videos keep the "altered or
  synthetic content" label.
Needs: Text-to-Speech API enabled in the owner's existing Google Cloud project (billing switched on for identity;
nothing is charged inside the free tier) and GOOGLE_TTS_API_KEY in .env (an API key restricted to Text-to-Speech).
Every line is cached by its text, so re-rendering a video never spends characters twice."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import time
from pathlib import Path

import numpy as np
import requests
import soundfile as sf

from ..config import ROOT
from engine.core.http import HTTP

API = "https://texttospeech.googleapis.com/v1/text:synthesize"
SR = 24000
FREE_CHARS = 1_000_000
SAFE_CHARS = 900_000                     # stop well before the free tier ends (₹0 rule)
USAGE = ROOT / "data" / "state" / "google_tts_usage.json"
CACHE = ROOT / "data" / "cache" / "google_tts"
# Default voices per channel (the owner can change them in the channel file: voice: {google: ...})
DEFAULTS = {"itihaas_ke_raaz": "hi-IN-Chirp3-HD-Charon", "cricket_ke_kisse": "hi-IN-Chirp3-HD-Puck",
            "picture_abhi_baaki_hai": "hi-IN-Chirp3-HD-Aoede"}


def key() -> str:
    return os.environ.get("GOOGLE_TTS_API_KEY", "").strip()


def available() -> bool:
    return bool(key()) and month_used() < SAFE_CHARS


def _month() -> str:
    return time.strftime("%Y-%m")


def month_used() -> int:
    try:
        data = json.loads(USAGE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    return int(data.get(_month(), 0))


def _add_usage(n: int) -> None:
    try:
        data = json.loads(USAGE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    data[_month()] = int(data.get(_month(), 0)) + n
    USAGE.parent.mkdir(parents=True, exist_ok=True)
    USAGE.write_text(json.dumps(data), encoding="utf-8")


def markup(text: str) -> str:
    """Chirp 3 HD reads punctuation as a human would; '…' becomes Google's own [pause] tag (a held moment)."""
    t = text.replace("…", "... ").replace("  ", " ").strip()
    return t.replace("... ", "[pause] ") if t.count("...") <= 2 else t


def synthesize(text: str, out_wav: Path, voice_name: str, speed: float = 1.0, session=HTTP) -> float:
    """Write one line to out_wav (24 kHz mono). Returns seconds. Raises when not configured or over the safe cap."""
    if not key():
        raise RuntimeError("GOOGLE_TTS_API_KEY is not set")
    body_text = markup(text)
    rate = round(min(max(speed, 0.5), 1.5), 3)
    h = hashlib.sha256(f"{voice_name}|{rate}|{body_text}".encode()).hexdigest()[:24]
    cached = CACHE / f"{h}.wav"
    if not cached.exists():
        if month_used() + len(body_text) > SAFE_CHARS:
            raise RuntimeError("Google TTS: monthly free-tier safety cap reached; using Kokoro")
        lang = "-".join(voice_name.split("-")[:2])
        r = session.post(API, params={"key": key()}, timeout=90, json={
            "input": {"markup": body_text},
            "voice": {"languageCode": lang, "name": voice_name},
            "audioConfig": {"audioEncoding": "LINEAR16", "sampleRateHertz": SR, "speakingRate": rate}})
        if r.status_code != 200:
            raise RuntimeError(f"Google TTS {r.status_code}: {r.text[:200]}")
        _add_usage(len(body_text))
        CACHE.mkdir(parents=True, exist_ok=True)
        cached.write_bytes(base64.b64decode(r.json()["audioContent"]))
    audio, sr = sf.read(cached, dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    loud = np.where(np.abs(audio) > 0.012)[0]                       # trim only the silence at the edges
    if len(loud):
        keep = int(sr * 0.03)
        audio = audio[max(loud[0] - keep, 0):min(loud[-1] + keep, len(audio))]
    sf.write(out_wav, audio, sr)
    return len(audio) / sr


def voice_for(channel: dict) -> str:
    return (channel.get("voice") or {}).get("google") or DEFAULTS.get(channel.get("id", ""), "hi-IN-Chirp3-HD-Charon")
