"""AI voice with Kokoro-82M (Apache 2.0) — runs on our own machine, so it can't be
blocked or rate-limited. English (US) and Hindi voices."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np
import soundfile as sf

from . import ffmpeg

SR = 24000
LANG_CODES = {"en": "a", "en-us": "a", "en-gb": "b", "hi": "h"}


@lru_cache(maxsize=3)
def _pipeline(lang_code: str):
    from kokoro import KPipeline
    return KPipeline(lang_code=lang_code, repo_id="hexgrad/Kokoro-82M")


def _trim(audio: np.ndarray, keep_s: float = 0.04, threshold: float = 0.015) -> np.ndarray:
    """Cut silence at the start/end (keeps the pace tight, MrBeast-style)."""
    loud = np.where(np.abs(audio) > threshold)[0]
    if not len(loud):
        return audio
    keep = int(SR * keep_s)
    return audio[max(loud[0] - keep, 0):min(loud[-1] + keep, len(audio))]


def synthesize(text: str, out_wav: Path, voice_id: str, language: str = "en", speed: float = 1.05,
               pause_s: float = 0.0, trim: bool = False) -> float:
    """Write speech to out_wav. Returns duration in seconds. Numbers, money, units and names are first rewritten
    into the words a narrator says (say.normalise; captions keep the written form)."""
    from .say import normalise
    text = normalise(text, language)
    pipe = _pipeline(LANG_CODES.get(language, "a"))
    chunks = []
    for result in pipe(text, voice=voice_id, speed=speed, split_pattern=r"\n+"):
        audio = result.audio if hasattr(result, "audio") else result[2]
        if audio is not None:
            chunks.append(np.asarray(audio, dtype=np.float32))
    if not chunks:
        raise RuntimeError(f"Kokoro produced no audio for voice {voice_id}")
    audio = np.concatenate(chunks)
    if trim:
        audio = _trim(audio)
    if pause_s:
        audio = np.concatenate([audio, np.zeros(int(SR * pause_s), dtype=np.float32)])
    sf.write(out_wav, audio, SR)
    return len(audio) / SR


def to_48k(src: Path, dst: Path) -> Path:
    """Loudness-normalise and resample to 48 kHz stereo for the final mix."""
    ffmpeg.run(["-i", src, "-af", "loudnorm=I=-14:TP=-1.5:LRA=11", "-ar", "48000", "-ac", "2", dst])
    return dst
