"""In-house beat tracking and cut-on-the-beat (owner 18 Nov: music/transitions are what keep the audience).

Editors cut on the music's beat: a cut that lands on a kick or snare feels intentional, one just off it feels sloppy.
librosa is not installed (and pulls numba), so this is a small numpy version of the classic method:
spectral-flux onset envelope -> tempo from its autocorrelation (70-180 BPM, a soft prior around 115) -> the beat
grid phase that collects the most onset energy -> each beat refined to the nearest onset peak.
Ambient beds with no steady pulse return no beats (then nothing is moved)."""
from __future__ import annotations

import numpy as np

HOP, NFFT, TARGET_SR = 512, 1024, 22050
MIN_FLUX = 5.0          # strongest attack (summed log-magnitude rise) below this = no pulse to cut on


def onset_envelope(x: np.ndarray, sr: int) -> tuple[np.ndarray, float]:
    """Spectral flux (log magnitude, positive differences). Returns (envelope, frames per second)."""
    x = np.asarray(x, dtype=np.float32)
    if x.ndim > 1:
        x = x.mean(axis=1)
    step = max(1, int(round(sr / TARGET_SR)))
    x, sr2 = x[::step], sr / step
    if len(x) < NFFT * 4:
        return np.zeros(0, dtype=np.float32), sr2 / HOP
    n = 1 + (len(x) - NFFT) // HOP
    idx = np.arange(NFFT)[None, :] + HOP * np.arange(n)[:, None]
    mag = np.abs(np.fft.rfft(x[idx] * np.hanning(NFFT).astype(np.float32), axis=1))
    logm = np.log1p(100.0 * mag)
    flux = np.maximum(np.diff(logm, axis=0), 0).sum(axis=1)
    flux = np.concatenate([[0.0], flux])
    flux -= np.convolve(flux, np.ones(16) / 16, mode="same")       # remove the slow loudness trend
    flux = np.maximum(flux, 0)
    if flux.max() < MIN_FLUX * NFFT / 1024:                        # a smooth pad: no attacks at all
        return np.zeros(len(flux), dtype=np.float32), sr2 / HOP
    return (flux / (flux.max() + 1e-9)).astype(np.float32), sr2 / HOP


def tempo(env: np.ndarray, fps: float, lo: float = 70, hi: float = 180) -> tuple[float, float]:
    """(BPM, confidence 0..1). Confidence = autocorrelation peak over the median: low for ambient pads."""
    if len(env) < fps * 4:
        return 0.0, 0.0
    e = env - env.mean()
    ac = np.correlate(e, e, mode="full")[len(e) - 1:]
    if ac[0] <= 0:
        return 0.0, 0.0
    ac = ac / ac[0]
    lags = np.arange(int(fps * 60 / hi), int(fps * 60 / lo) + 1)
    lags = lags[lags < len(ac)]
    if not len(lags):
        return 0.0, 0.0
    bpm = 60 * fps / lags
    prior = np.exp(-0.5 * (np.log2(bpm / 115.0) / 0.9) ** 2)       # soft preference for common tempos
    score = ac[lags] * prior
    k = int(np.argmax(score))
    floor = float(np.median(np.abs(ac[lags]))) + 1e-6
    conf = float(np.clip((ac[lags][k] - floor) / (1 - floor), 0, 1))
    lag = float(lags[k])
    if 0 < k < len(lags) - 1:                                       # sub-frame peak (parabolic fit)
        y0, y1, y2 = ac[lags[k] - 1], ac[lags[k]], ac[lags[k] + 1]
        den = y0 - 2 * y1 + y2
        if den < 0:
            lag += float(np.clip(0.5 * (y0 - y2) / den, -0.5, 0.5))
    return float(60 * fps / lag), conf


def beat_times(x: np.ndarray, sr: int, min_conf: float = 0.12) -> list[float]:
    """Beat times in seconds, or [] when the music has no steady pulse."""
    env, fps = onset_envelope(x, sr)
    bpm, conf = tempo(env, fps)
    if not bpm or conf < min_conf:
        return []
    period = 60 * fps / bpm
    best, phase = -1.0, 0.0
    for ph in np.arange(0, period, 0.5):                            # grid phase with the most onset energy
        pos = np.arange(ph, len(env), period).astype(int)
        s = float(env[pos].sum())
        if s > best:
            best, phase = s, ph
    out, w, p = [], max(1, int(round(period * 0.12))), phase
    while p < len(env):                                             # follow the beat: each one from the last hit
        a, b = max(0, int(round(p)) - w), min(len(env), int(round(p)) + w + 1)
        if b <= a:
            break
        q = a + int(np.argmax(env[a:b]))
        q = q if env[q] > 0.1 else int(round(p))                    # no hit here: keep the grid position
        out.append(round(q / fps + NFFT / 2 / (fps * HOP), 3))     # frame centre, not its start
        p = 0.5 * (q + p) + period                                  # half trust the hit, half the steady tempo
    return sorted(set(out))


def snap_cuts(cuts: list[float], beats: list[float], window: float = 0.15, min_shot: float = 0.6,
              keep: list[float] | None = None) -> dict[float, float]:
    """{old cut: new cut} for the cuts that move onto a beat within +-window seconds. Cuts listed in `keep` (the
    climax) stay put; every shot keeps at least `min_shot` seconds; cut order never changes."""
    if not beats or not cuts:
        return {}
    b = np.asarray(sorted(beats))
    keep = keep or []
    srt = sorted(cuts)
    moved: dict[float, float] = {}
    for k, c in enumerate(srt):
        if any(abs(c - kk) < 1e-3 for kk in keep):
            continue
        j = int(np.argmin(np.abs(b - c)))
        nb = float(b[j])
        if abs(nb - c) > window or abs(nb - c) < 0.01:
            continue
        prev = moved.get(srt[k - 1], srt[k - 1]) if k else None
        nxt = srt[k + 1] if k + 1 < len(srt) else None
        if prev is not None and nb - prev < min_shot:
            continue
        if nxt is not None and nxt - nb < min_shot:
            continue
        moved[c] = round(nb, 3)
    return moved


def remap(t: float, moved: dict[float, float], tol: float = 0.12) -> float:
    """Move a time that sat on (or within `tol` after/before) a moved cut by the same amount."""
    for old, new in moved.items():
        if abs(t - old) <= tol:
            return t + (new - old)
    return t
