"""Natural Hindi narration with AI4Bharat Indic Parler-TTS (Apache-2.0), free and on this PC, no card
(owner, 13 Nov 2026: "use the free Indic Parler-TTS, no card").

Why: the Kokoro Hindi voices (graded C by Kokoro itself) broke rhythm and mangled names (Whisper heard "Kapil Dev"
as "कापल देव"). Indic Parler-TTS was trained on Indian speech; you describe the delivery in words ("warm,
conversational, moderate pace, close clear recording") and pick a named speaker (AI4Bharat recommends Rohit and Divya
for Hindi), so every line keeps the same voice.
How: its own Python environment (~/parler: it needs transformers 4.46.1), one batch per video, all 8 CPU threads.
Needs: a free Hugging Face account that has pressed "Agree" on the model page (gated: auto-approved) and its read
token as HF_TOKEN in .env. Any failure falls back to Kokoro, so a video is never lost."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf

from . import ffmpeg
from .say import normalise

HOME = Path.home()
PY = HOME / "parler" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")    # PC (Windows) or cloud (Linux)
WORKER = Path(__file__).with_name("parler_worker.py")
# Owner, 14 Nov: after hearing v2 (emotion words + per-line pace evening + gap squeezing) and v3 (phrase-by-phrase,
# measured pitch shifts, our own pauses), "the v1 version is so far the best one". So this stays v1: whole lines,
# one calm description per channel, Parler's own timing. Don't re-add post-processed pace/pitch without a new listen test.
# How each Hindi channel's narrator speaks (Indic Parler-TTS description prompts; named speakers keep the voice fixed)
DESCRIPTIONS = {
    "itihaas_ke_raaz": "Rohit speaks in a deep, warm and expressive storytelling voice at a moderate pace, like "
                       "telling a story to a friend, with a very clear, close recording and no background noise.",
    "cricket_ke_kisse": "Rohit speaks in a lively, excited and conversational voice at a moderate pace, like "
                        "chatting with a friend about a match, with a very clear, close recording and no background noise.",
    "picture_abhi_baaki_hai": "Divya speaks in a warm, friendly and conversational voice at a moderate pace, like "
                              "sharing a secret with a friend, with a very clear, close recording and no background noise.",
}
DEFAULT_DESCRIPTION = DESCRIPTIONS["itihaas_ke_raaz"]


def token() -> str:
    return os.environ.get("HF_TOKEN", "").strip()


def available() -> bool:
    return PY.exists() and bool(token())


def description_for(channel: dict) -> str:
    return (channel.get("voice") or {}).get("parler") or DESCRIPTIONS.get(channel.get("id", ""), DEFAULT_DESCRIPTION)


def batch(beats: list[dict], work: Path, channel: dict, log=print, timeout_s: int = 4 * 3600) -> list[Path]:
    """Every beat's raw read (no pace change, no pauses). Returns the wav paths."""
    if not available():
        raise RuntimeError("Indic Parler-TTS not ready (needs ~/parler and HF_TOKEN)")
    outs, lines = [], []
    for i, b in enumerate(beats):
        out = (work / f"parler_{i:02d}.wav").resolve()
        lines.append({"text": normalise(b["narration"], "hi", engine="parler"), "out": str(out)})
        outs.append(out)
    job = (work / "parler_job.json").resolve()
    job.write_text(json.dumps({"description": description_for(channel), "threads": 8, "seed": 7, "lines": lines},
                              ensure_ascii=False), encoding="utf-8")
    log(f"  voice: Indic Parler-TTS ({len(lines)} lines)")
    env = dict(os.environ, HF_TOKEN=token(), PYTHONIOENCODING="utf-8")
    proc = subprocess.run([str(PY), str(WORKER), str(job)], capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout_s, env=env)
    missing = [p for p in outs if not p.exists()]
    if proc.returncode != 0 or missing:
        raise RuntimeError(f"Indic Parler-TTS failed ({len(missing)} lines missing): {(proc.stderr or proc.stdout)[-300:]}")
    return outs


def line(raw: Path, out_wav: Path, speed: float = 1.0, pause_s: float = 0.0, sr_out: int = 24000) -> float:
    """One beat ready for the mix (24 kHz like the other voices): paced (pitch kept), edges trimmed, pause added."""
    af = f"aresample={sr_out}" + (f",atempo={min(max(speed, 0.5), 2.0):.4f}" if abs(speed - 1.0) > 0.01 else "")
    tmp = out_wav.with_name(out_wav.stem + "_p.wav")
    ffmpeg.run(["-i", str(raw), "-af", af, "-ac", "1", str(tmp)])
    audio, sr = sf.read(tmp, dtype="float32")
    loud = np.where(np.abs(audio) > 0.012)[0]
    if len(loud):
        keep = int(sr * 0.03)
        audio = audio[max(loud[0] - keep, 0):min(loud[-1] + keep, len(audio))]
    if pause_s:
        audio = np.concatenate([audio, np.zeros(int(sr * pause_s), dtype=np.float32)])
    sf.write(out_wav, audio, sr)
    tmp.unlink(missing_ok=True)
    return len(audio) / sr
