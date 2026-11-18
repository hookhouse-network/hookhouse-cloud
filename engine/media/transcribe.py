"""Speech to text with word timings (faster-whisper, MIT, runs offline)."""
from __future__ import annotations

import difflib
import re
from functools import lru_cache
from pathlib import Path

from .captions import Word


@lru_cache(maxsize=2)
def _model(size: str):
    from faster_whisper import WhisperModel
    return WhisperModel(size, device="cpu", compute_type="int8")


def load_16k(audio_or_video: Path):
    """Decode any audio/video to 16 kHz mono with ffmpeg (avoids PyAV version issues)."""
    import tempfile

    import soundfile as sf

    from . import ffmpeg
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "a16k.wav"
        ffmpeg.run(["-i", audio_or_video, "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", wav])
        audio, _ = sf.read(wav, dtype="float32")
    return audio


def transcribe(audio_or_video: Path, language: str | None = None, size: str = "small") -> list[Word]:
    segments, _info = _model(size).transcribe(load_16k(audio_or_video), language=language,
                                              word_timestamps=True, vad_filter=True)
    words = []
    for seg in segments:
        for w in seg.words or []:
            text = w.word.strip()
            if text:
                words.append(Word(text, float(w.start), float(w.end)))
    return words


def _norm(t: str) -> str:
    return re.sub(r"[^\w]", "", t.lower())


def align_script(script: str, heard: list[Word], total: float | None = None) -> list[Word]:
    """Give every word of the *script* a time, using what Whisper heard.
    Keeps the script's exact spelling (important for names and Hindi)."""
    script_words = script.split()
    if not script_words:
        return []
    if not heard:
        total = total or len(script_words) * 0.35
        step = total / len(script_words)
        return [Word(w, i * step, (i + 1) * step) for i, w in enumerate(script_words)]

    a = [_norm(w) for w in script_words]
    b = [_norm(w.text) for w in heard]
    times: list[tuple[float, float] | None] = [None] * len(script_words)
    for block in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_matching_blocks():
        for k in range(block.size):
            h = heard[block.b + k]
            times[block.a + k] = (h.start, h.end)

    # fill gaps by spreading time between known neighbours
    end_total = total or heard[-1].end
    i = 0
    while i < len(times):
        if times[i] is not None:
            i += 1
            continue
        j = i
        while j < len(times) and times[j] is None:
            j += 1
        left = times[i - 1][1] if i > 0 else (heard[0].start if heard else 0.0)
        right = times[j][0] if j < len(times) else end_total
        span = max(right - left, 0.12 * (j - i))
        step = span / (j - i)
        for k in range(i, j):
            times[k] = (left + (k - i) * step, left + (k - i + 1) * step)
        i = j
    return [Word(w, t[0], max(t[1], t[0] + 0.05)) for w, t in zip(script_words, times)]
