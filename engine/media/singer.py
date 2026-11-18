"""Singing with free tools (owner, 12 Nov 2026: Bloop songs for Spotify and the music apps need real sung vocals).

Kokoro (Apache 2.0) says each word; the WORLD vocoder (pyworld, MIT; WORLD itself modified-BSD) moves it onto the
melody: the pitch follows the note (small glides between notes, gentle vibrato on long notes), the voiced part (the
vowel) is stretched to the note length while consonants keep their natural speed, and the voice's own formants are
kept (no chipmunk sound). One syllable per note; a word can span several notes ("sev-en").
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

from .voice import SR as KSR, synthesize

FP = 5.0                       # WORLD frame period (ms)


def note_hz(m: float) -> float:
    return 440.0 * 2 ** ((m - 69) / 12)


def _word_audio(word: str, voice: str, cache: Path, speed: float = 0.95) -> np.ndarray:
    cache.mkdir(parents=True, exist_ok=True)
    f = cache / f"{voice}_{hashlib.sha1(word.lower().encode()).hexdigest()[:10]}.wav"
    if not f.exists():
        synthesize(word, f, voice, "en", speed=speed, trim=True)
    x, _ = sf.read(f, dtype="float64")
    return x if x.ndim == 1 else x.mean(axis=1)


def _time_map(voiced: np.ndarray, n_tgt: int) -> np.ndarray:
    """Source frame position for every target frame: unvoiced frames (consonants) keep their speed, voiced frames
    (the vowel) stretch to fill the note."""
    n_src = len(voiced)
    n_v = int(voiced.sum())
    n_u = n_src - n_v
    if n_v == 0 or n_tgt - n_u < 0.5 * n_v:
        return np.linspace(0, n_src - 1, n_tgt)
    k = (n_tgt - n_u) / n_v
    w = np.where(voiced, k, 1.0)
    cum = np.concatenate([[0.0], np.cumsum(w)])[:-1]
    return np.interp(np.arange(n_tgt) * (cum[-1] + w[-1]) / n_tgt, cum, np.arange(n_src))


def _rows(a: np.ndarray, pos: np.ndarray) -> np.ndarray:
    i0 = np.floor(pos).astype(int)
    i1 = np.minimum(i0 + 1, len(a) - 1)
    f = (pos - i0)[:, None]
    return a[i0] * (1 - f) + a[i1] * f


def retune(x: np.ndarray, notes: list[tuple[float, float]], beat_s: float, legato: float = 0.92,
           vibrato_cents: float = 28.0, formant: float = 1.0) -> np.ndarray:
    """Sing one word over its notes [(midi, beats), ...]. Returns audio at Kokoro's sample rate."""
    import pyworld as pw
    f0, t = pw.harvest(x, KSR, frame_period=FP)
    sp = pw.cheaptrick(x, f0, t, KSR)
    ap = pw.d4c(x, f0, t, KSR)
    total_s = sum(b for _, b in notes) * beat_s * legato
    n_tgt = max(4, int(total_s * 1000 / FP))
    pos = _time_map(f0 > 0, n_tgt)
    sp2 = np.exp(_rows(np.log(np.maximum(sp, 1e-12)), pos))
    ap2 = np.clip(_rows(ap, pos), 0, 1)
    voiced = np.interp(pos, np.arange(len(f0)), (f0 > 0).astype(float)) > 0.5
    if formant != 1.0:                                     # optional: brighter, younger timbre
        bins = np.arange(sp2.shape[1])
        sp2 = np.stack([np.interp(bins / formant, bins, row) for row in sp2])
    # target pitch: note by note (in proportion to their beats), 30 ms glides, vibrato after 150 ms on long notes
    tt = np.arange(n_tgt) * FP / 1000
    edges = np.cumsum([0.0] + [b for _, b in notes]) / sum(b for _, b in notes) * total_s
    cents = np.zeros(n_tgt)
    midi = np.zeros(n_tgt)
    for (m, _b), a, b in zip(notes, edges[:-1], edges[1:]):
        sel = (tt >= a) & (tt < b)
        midi[sel] = m
        if b - a > 0.42:
            age = np.clip(tt[sel] - a - 0.15, 0, None)
            cents[sel] = vibrato_cents * np.minimum(1, age / 0.2) * np.sin(2 * np.pi * 5.5 * age)
    midi[midi == 0] = notes[-1][0]
    glide = max(1, int(30 / FP))
    midi = np.convolve(np.pad(midi, (glide, glide), mode="edge"), np.ones(2 * glide + 1) / (2 * glide + 1), "valid")
    f0_t = note_hz(midi + cents / 100.0)
    f0_2 = np.where(voiced, f0_t, 0.0)
    y = pw.synthesize(np.ascontiguousarray(f0_2), np.ascontiguousarray(sp2), np.ascontiguousarray(ap2), KSR, FP)
    n_fade_in, n_fade_out = int(0.008 * KSR), int(0.03 * KSR)
    y[:n_fade_in] *= np.linspace(0, 1, n_fade_in)
    y[-n_fade_out:] *= np.linspace(1, 0, n_fade_out)
    return y


def sing(lyrics: list[tuple[str, float, float]], bpm: float, voice: str, cache: Path, out_sr: int = 48000,
         transpose: int = 0, formant: float = 1.0) -> np.ndarray:
    """lyrics: [(syllable, midi, beats)]; a syllable starting with "-" continues the previous word ("sev", "-en");
    "" is a rest. Returns the dry vocal at out_sr, starting at beat 0."""
    beat = 60.0 / bpm
    words: list[tuple[str, list[tuple[float, float]], float]] = []
    t = 0.0
    for syl, m, b in lyrics:
        if syl.startswith("-") and words:
            w, ns, start = words[-1]
            words[-1] = (w + syl[1:], ns + [(m + transpose, b)], start)
        else:
            words.append((syl, [(m + transpose, b)], t))
        t += b * beat
    out = np.zeros(int((t + 1.0) * KSR))
    for w, ns, start in words:
        if not w.strip():
            continue
        x = _word_audio(w, voice, cache)
        y = retune(x, ns, beat, formant=formant)
        y = y / (np.sqrt(np.mean(y ** 2)) + 1e-9) * 0.08          # every word equally loud
        a = int(start * KSR)
        out[a:a + len(y)] += y[: len(out) - a]
    if out_sr != KSR:
        g = np.gcd(out_sr, KSR)
        out = resample_poly(out, out_sr // g, KSR // g)
    return out.astype(np.float32)


def pitch_error_cents(vocal: np.ndarray, sr: int, lyrics: list[tuple[str, float, float]], bpm: float,
                      transpose: int = 0) -> float:
    """Median distance (cents) between the sung pitch and the written notes, over voiced frames: a quality check."""
    import pyworld as pw
    x = vocal.astype(np.float64)
    f0, t = pw.harvest(x, sr, frame_period=10.0)
    beat = 60.0 / bpm
    target = np.zeros(len(t))
    pos = 0.0
    for syl, m, b in lyrics:
        a, e = pos, pos + b * beat * 0.85
        target[(t >= a + 0.06) & (t < e)] = note_hz(m + transpose) if syl.strip() else 0
        pos += b * beat
    ok = (f0 > 0) & (target > 0)
    if not ok.any():
        return float("inf")
    return float(np.median(np.abs(1200 * np.log2(f0[ok] / target[ok]))))
