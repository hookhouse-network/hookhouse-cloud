"""Emotional Hindi narration with Chatterbox Multilingual + its Hindi fine-tune (MIT, ResembleAI), as an opt-in voice
engine (channel yaml: voice: {engine: emotional, ...}).

Why: owner, 13 Nov 2026: "for Hindi you have to learn the emotion-driven audio, because that is what hooks the
consumers in India". Chatterbox has an emotion-intensity control (`exaggeration`); we set it per line from the
story: the hook and the reveals get more feeling, plain lines stay calm (one tone for everything is the strongest
"AI voice" tell; research note human_feel_hindi_voice_2026-11-12.md).

How: it runs in its own Python environment (~/cbx), one batch per video (the model takes ~20 s to load), all 8 CPU
threads. Measured 13 Nov on this PC: about 17 s of work per second of speech, so a 50 s Short takes ~14 min; long
videos stay on Kokoro unless `emotional_long: true`. The timbre is cloned from our own Kokoro clip (no third-party
voice). Chatterbox adds its inaudible Perth watermark (kept, as the licence intends).
Any failure falls back to Kokoro, so a video is never lost."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

from . import ffmpeg
from .say import normalise

HOME = Path.home()
CBX_PY = HOME / "cbx" / "Scripts" / "python.exe"
MODEL_DIR = HOME / "cbx_test" / "hi_model"
REF = HOME / "cbx_test" / "ref_omega.wav"
WORKER = Path(__file__).with_name("cbx_worker.py")
SR = 24000
# Emotion per story moment (Chatterbox: 0.5 = neutral; higher = more feeling; cfg lower = slower, steadier delivery)
EMOTION = {"hook": (0.75, 0.40), "reveal": (0.85, 0.35), "twist": (0.8, 0.38), "normal": (0.55, 0.45),
           "ending": (0.65, 0.42)}


def available() -> bool:
    return CBX_PY.exists() and MODEL_DIR.exists() and REF.exists() and (MODEL_DIR / "t3_mtl23ls_v2.safetensors").exists()


def emotion_for(i: int, n: int, moment: str) -> tuple[float, float]:
    if moment in ("reveal", "twist"):
        return EMOTION[moment]
    if i == 0:
        return EMOTION["hook"]
    if i == n - 1:
        return EMOTION["ending"]
    return EMOTION["normal"]


def batch(beats: list[dict], work: Path, language: str = "hi", log=print, timeout_s: int = 6 * 3600) -> list[Path]:
    """Generate every beat's raw emotional read (no pace change, no pauses). Returns the wav paths."""
    if not available():
        raise RuntimeError("emotional voice not installed (needs ~/cbx and the Hindi model)")
    lines, outs = [], []
    for i, b in enumerate(beats):
        out = (work / f"emo_{i:02d}.wav").resolve()
        ex, cfg = emotion_for(i, len(beats), b.get("moment", "normal"))
        lines.append({"text": normalise(b["narration"], language), "out": str(out), "exaggeration": ex, "cfg": cfg})
        outs.append(out)
    job = (work / "emo_job.json").resolve()
    job.write_text(json.dumps({"model_dir": str(MODEL_DIR), "ref": str(REF), "threads": 8, "language": language,
                               "lines": lines}, ensure_ascii=False), encoding="utf-8")
    log(f"  emotional voice: {len(lines)} lines (about {sum(len(x['text']) for x in lines) // 14 * 17 // 60} min)")
    proc = subprocess.run([str(CBX_PY), str(WORKER), str(job)], capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout_s)
    missing = [p for p in outs if not p.exists()]
    if proc.returncode != 0 or missing:
        tail = (proc.stderr or proc.stdout or "")[-400:]
        raise RuntimeError(f"emotional voice failed ({len(missing)} lines missing): {tail}")
    return outs


def _trim(audio: np.ndarray, keep_s: float = 0.04, threshold: float = 0.015) -> np.ndarray:
    loud = np.where(np.abs(audio) > threshold)[0]
    if not len(loud):
        return audio
    keep = int(SR * keep_s)
    return audio[max(loud[0] - keep, 0):min(loud[-1] + keep, len(audio))]


def line(raw: Path, out_wav: Path, speed: float = 1.0, pause_s: float = 0.0) -> float:
    """One beat ready for the mix: paced (pitch kept), trimmed, pause added. Returns seconds."""
    src = raw
    if abs(speed - 1.0) > 0.01:
        src = out_wav.with_name(out_wav.stem + "_tempo.wav")
        ffmpeg.run(["-i", str(raw), "-af", f"atempo={min(max(speed, 0.5), 2.0):.4f}", "-ar", str(SR), str(src)])
    audio, sr = sf.read(src, dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    audio = _trim(audio)
    if pause_s:
        audio = np.concatenate([audio, np.zeros(int(SR * pause_s), dtype=np.float32)])
    sf.write(out_wav, audio, SR)
    return len(audio) / SR


if __name__ == "__main__":       # quick manual check: python -m engine.media.emotional_voice
    print("available:", available(), sys.executable)
