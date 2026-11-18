"""Emotional scores for the Hindi channels: music that follows the story instead of one flat loop.

Owner (13 Nov 2026): "for Hindi you have to learn the emotion driven audio, because that is what hooks the consumers
in India; make it more dramatic with sound, visuals, background music, and feel nostalgic and more devoted."

What the research says (docs/hindi_emotion_audio_2026-11-13.md):
- Indian drama tells the viewer how to feel through the music; quiet is used before a reveal and a hit lands on it.
- Devotional colour: tanpura drone, temple bells, shankh, damru, manjira, bansuri; music sits well under the voice.
- Nostalgia (old Bollywood): harmonium, santoor/sitar plucks in raga Yaman, light tabla, vinyl crackle, a warm old
  hall. Cricket: dhol that builds, stadium crowd swells, a heartbeat in the silence before the climax.
- Space matters: every instrument here is played in a room (our old beds had no reverb at all).

Everything is synthesised by our own code (plucked strings by Karplus-Strong, bells by inharmonic partials, a hummed
"Om" by formant filtering), so there are no licences and no Content ID claims.

The arc (intensity 0-1 over time): soft at the hook -> builds -> drops to near-silence 0.6 s before the climax ->
a hit and a swell on the climax and on each reveal -> settles at the end."""
from __future__ import annotations

import math

import numpy as np
from scipy.signal import fftconvolve, lfilter

SR = 48000
PALETTES = ("devotional", "dhol", "retro")
# Room per palette (reverb time T60 s, wet share): temple hall, open stadium, old cinema hall
ROOMS = {"devotional": (3.2, 0.34), "dhol": (1.6, 0.18), "retro": (1.3, 0.22)}


# ---------- building blocks ----------
def _t(n: int) -> np.ndarray:
    return np.arange(n) / SR


def _lowpass(x: np.ndarray, cutoff: float) -> np.ndarray:
    a = math.exp(-2 * math.pi * cutoff / SR)                     # one-pole: warm, cheap
    return lfilter([1 - a], [1, -a], x)


def _highpass(x: np.ndarray, cutoff: float) -> np.ndarray:
    return x - _lowpass(x, cutoff)


def pluck(freq: float, seconds: float, rng, bright: float = 0.6, decay: float = 0.996, buzz: float = 0.0) -> np.ndarray:
    """Karplus-Strong plucked string (tanpura, sitar, santoor). Computed one delay-line block at a time."""
    n = int(seconds * SR)
    p = max(2, int(SR / freq))
    y = np.zeros(n + p + 1)
    burst = rng.uniform(-1, 1, p)
    burst = bright * burst + (1 - bright) * np.convolve(burst, np.ones(4) / 4, mode="same")
    y[:p] = burst
    for s in range(p, n + p, p):
        e = min(s + p, n + p)
        prev = y[s - p:e - p]
        prev2 = y[s - p - 1:e - p - 1] if s - p - 1 >= 0 else np.concatenate([[0.0], y[s - p:e - p - 1]])
        y[s:e] = decay * 0.5 * (prev + prev2)
    out = y[:n]
    if buzz:                                                         # tanpura jawari: a bright, buzzing edge
        out = out + buzz * np.tanh(out * 6) * 0.25
    return out * np.minimum(1, (n - np.arange(n)) / (0.05 * SR))


def bell(freq: float = 440.0, seconds: float = 5.0, gain: float = 1.0) -> np.ndarray:
    """Temple bell (ghanta): inharmonic partials with slow beating, long ring."""
    n = int(seconds * SR)
    t = _t(n)
    out = np.zeros(n)
    for ratio, amp, dec in ((0.5, 0.5, 0.6), (1.0, 1.0, 0.9), (1.19, 0.6, 1.2), (1.51, 0.45, 1.5), (2.0, 0.4, 1.9),
                            (2.51, 0.3, 2.4), (2.66, 0.25, 2.6), (3.01, 0.2, 3.2), (4.17, 0.12, 4.0)):
        f = freq * ratio
        out += amp * np.sin(2 * np.pi * f * t) * (1 + 0.15 * np.sin(2 * np.pi * 1.3 * t)) * np.exp(-t * dec)
    strike = np.random.default_rng(int(freq)).uniform(-1, 1, int(0.01 * SR)) * np.linspace(1, 0, int(0.01 * SR))
    out[: len(strike)] += strike * 0.4
    return gain * out / (np.abs(out).max() + 1e-9)


def shankh(seconds: float = 2.6, freq: float = 290.0, seed: int = 0) -> np.ndarray:
    """Conch (shankh naad): a horn tone that swells, rises a little, wavers, with breath."""
    rng = np.random.default_rng(seed)
    n = int(seconds * SR)
    t = _t(n)
    env = np.minimum(1, t / 0.35) * np.minimum(1, (seconds - t) / 0.6).clip(0)
    f = freq * (1 + 0.03 * np.minimum(1, t / 0.8)) * (1 + 0.006 * np.sin(2 * np.pi * 5.2 * t))
    ph = 2 * np.pi * np.cumsum(f) / SR
    tone = sum(np.sin(h * ph) / h ** 0.9 for h in range(1, 12))
    breath = _lowpass(_highpass(rng.standard_normal(n), 600), 3000) * 0.18
    out = (np.tanh(tone * 0.8) + breath) * env
    return out / (np.abs(out).max() + 1e-9)


def om_hum(seconds: float, freq: float = 98.0, seed: int = 0) -> np.ndarray:
    """A low hummed "Om" choir (formant-filtered voices, slightly detuned): devotion at the climax."""
    rng = np.random.default_rng(seed)
    n = int(seconds * SR)
    t = _t(n)
    out = np.zeros(n)
    for detune in (-0.4, 0.0, 0.35):
        f = freq * 2 ** (detune / 12) * (1 + 0.004 * np.sin(2 * np.pi * (4.5 + rng.random()) * t))
        ph = 2 * np.pi * np.cumsum(f) / SR
        out += sum(np.sin(h * ph) / h for h in range(1, 30))            # saw-like glottal source
    o = sum(_lowpass(_highpass(out, lo), hi) * g for lo, hi, g in ((350, 650, 1.0), (650, 1000, 0.5)))   # "o"
    m = _lowpass(out, 320)                                               # "m": lips closed
    mix = np.clip((t - seconds * 0.55) / (seconds * 0.2), 0, 1)
    voice = o * (1 - mix) + m * mix * 1.4
    env = np.minimum(1, t / 0.8) * np.minimum(1, (seconds - t) / 1.2).clip(0)
    return voice * env / (np.abs(voice).max() + 1e-9)


def drum(f0: float, decay: float, seconds: float = 0.6, noise: float = 0.15, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n = int(seconds * SR)
    t = _t(n)
    f = f0 * (1 + 0.6 * np.exp(-t * 30))
    s = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * decay)
    return s + rng.uniform(-1, 1, n) * np.exp(-t * decay * 3) * noise


def manjira(seconds: float = 0.9) -> np.ndarray:
    n = int(seconds * SR)
    t = _t(n)
    return sum(np.sin(2 * np.pi * f * t) * a for f, a in ((2380, 1), (3120, 0.7), (4410, 0.5), (5650, 0.3))) * np.exp(-t * 5)


def crowd_bed(seconds: float, seed: int = 0) -> np.ndarray:
    """Stadium murmur that can swell into a roar (filtered noise with slow movement)."""
    rng = np.random.default_rng(seed)
    n = int(seconds * SR)
    x = _lowpass(_highpass(rng.standard_normal(n), 250), 2200)
    move = _lowpass(rng.standard_normal(n), 0.4)
    return x * (0.7 + 0.3 * move / (np.abs(move).max() + 1e-9))


def vinyl(seconds: float, seed: int = 0) -> np.ndarray:
    """Old record: soft hiss and sparse crackles (nostalgia)."""
    rng = np.random.default_rng(seed)
    n = int(seconds * SR)
    hiss = _lowpass(rng.standard_normal(n), 5000) * 0.05
    pops = np.zeros(n)
    idx = rng.integers(0, n, int(seconds * 9))
    pops[idx] = rng.uniform(0.3, 1.0, len(idx)) * rng.choice([-1, 1], len(idx))
    return hiss + _highpass(np.convolve(pops, np.exp(-np.arange(60) / 8), mode="same"), 900) * 0.5


def string_pad(freqs: list[float], seconds: float) -> np.ndarray:
    """Warm string ensemble (detuned saws, soft attack): the emotional swell."""
    n = int(seconds * SR)
    t = _t(n)
    out = np.zeros(n)
    for f in freqs:
        for d in (-0.08, 0.0, 0.07):
            ph = 2 * np.pi * f * 2 ** (d / 12) * t
            out += sum(np.sin(h * ph) / h for h in range(1, 10))
    out = _lowpass(out, 2400)
    env = np.minimum(1, t / (seconds * 0.35)) * np.minimum(1, (seconds - t) / (seconds * 0.4)).clip(0)
    return out * env / (np.abs(out).max() + 1e-9)


def room(x: np.ndarray, t60: float, wet: float, seed: int = 3) -> np.ndarray:
    """Convolution reverb with our own impulse response (decaying, darkening noise + early reflections)."""
    if wet <= 0:
        return x
    rng = np.random.default_rng(seed)
    n = int(t60 * SR)
    t = _t(n)
    ir = rng.standard_normal(n) * np.exp(-6.9 * t / t60)
    ir = _lowpass(ir, 5200)
    for d, g in ((0.011, 0.6), (0.019, 0.45), (0.029, 0.35), (0.041, 0.28)):
        ir[int(d * SR)] += g * 3
    ir /= np.sqrt(np.sum(ir ** 2)) + 1e-9
    w = fftconvolve(x, ir)[: len(x)]
    w *= (np.sqrt(np.mean(x ** 2)) + 1e-9) / (np.sqrt(np.mean(w ** 2)) + 1e-9)
    return (1 - wet) * x + wet * w


def projector(seconds: float = 1.6, seed: int = 0) -> np.ndarray:
    """An old film projector starting up: the shutter clatter speeds up to 24 frames a second over a motor hum."""
    rng = np.random.default_rng(seed)
    n = int(seconds * SR)
    t = _t(n)
    rate = 8 + 16 * np.minimum(1, t / (seconds * 0.6))                # 8 -> 24 clicks a second
    phase = np.cumsum(rate) / SR
    clicks = np.zeros(n)
    idx = np.nonzero(np.diff(np.floor(phase)) > 0)[0]
    clicks[idx] = 1.0
    clack = _highpass(np.convolve(clicks, rng.uniform(-1, 1, 240) * np.exp(-np.arange(240) / 40), mode="same"), 700)
    hum = sum(np.sin(2 * np.pi * f * t) * a for f, a in ((50, 0.3), (100, 0.2), (150, 0.08)))
    out = clack * 0.8 + hum * np.minimum(1, t / 0.4) * 0.5
    return out * np.minimum(1, (seconds - t) / 0.3).clip(0) / (np.abs(out).max() + 1e-9)


def _add(out: np.ndarray, snd: np.ndarray, at: float, gain: float) -> None:
    i0 = int(at * SR)
    if i0 >= len(out) or i0 < 0:
        return
    e = min(i0 + len(snd), len(out))
    out[i0:e] += snd[: e - i0] * gain


# ---------- the story arc ----------
def arc(seconds: float, climax: float | None, reveals: list[float]) -> np.ndarray:
    """Intensity 0-1 per sample: 0.35 at the start, building to 0.8, a near-silent drop in the 0.6 s before the
    climax, 1.0 on the climax and each reveal (fading back over 3 s), settling to 0.4 over the last 12%."""
    n = int(seconds * SR)
    t = _t(n)
    base = 0.35 + 0.45 * np.clip(t / max(seconds * 0.85, 1), 0, 1)
    tail = np.clip((t - seconds * 0.88) / max(seconds * 0.12, 0.5), 0, 1)
    out = base * (1 - tail) + 0.4 * tail
    for r in sorted(set(reveals + ([climax] if climax is not None else []))):
        # owner, 13 Nov: "not a soap opera, just emotion": the moment SWELLS in over ~0.45 s, never slams
        rise = np.clip((t - r) / 0.45, 0, 1)
        bump = 0.92 * rise * np.clip(1 - (t - r - 0.45) / 3.0, 0, 1) * (t >= r)
        out = np.maximum(out, bump)
    if climax is not None:
        drop = (t >= climax - 0.6) & (t < climax)
        out[drop] = 0.04
        back = (t >= climax) & (t < climax + 0.45)            # the music comes back in from the silence, softly
        out[back] = 0.04 + (out[back] - 0.04) * ((t[back] - climax) / 0.45)
    return out


def _gate(intensity: np.ndarray, start: float, full: float) -> np.ndarray:
    return np.clip((intensity - start) / max(full - start, 1e-3), 0, 1)


# ---------- the three scores ----------
def _devotional(seconds: float, I: np.ndarray, climax, reveals, rng) -> np.ndarray:
    n = len(I)
    out = np.zeros(n)
    sa = 110.0
    for c in range(int(seconds / 4.0) + 1):                          # tanpura cycle: Pa Sa' Sa' Sa (always there)
        for k, f in enumerate((sa * 1.5, sa * 2, sa * 2, sa)):
            _add(out, pluck(f, 4.2, rng, bright=0.8, decay=0.9993, buzz=0.6), c * 4.0 + k, 0.22)
    beat = 60 / 72                                                    # slow pulse: frame drum, manjira on the off
    for k in range(int(seconds / beat) + 1):
        at = k * beat
        g = float(_gate(I[min(int(at * SR), n - 1):min(int(at * SR) + 1, n)], 0.4, 0.8).mean() or 0)
        if g > 0:
            _add(out, drum(68, 9, seed=k), at, 0.45 * g)
            if k % 2:
                _add(out, drum(140, 18, 0.3, 0.2, seed=k + 1), at, 0.2 * g)
        gm = float(_gate(I[min(int(at * SR), n - 1):min(int(at * SR) + 1, n)], 0.55, 0.9).mean() or 0)
        if gm > 0 and k % 2 == 1:
            _add(out, manjira(), at, 0.08 * gm)
    from .sfx import _melody                                        # bansuri phrases in raga Bhairavi (devotion)
    flute = _melody(seconds, sa, "bhairavi", rng, start=3.0, gap=5.0, gain=0.5)[:n]
    out[: len(flute)] += flute * (0.25 * (1 - _gate(I, 0.85, 1.0)))[: len(flute)]
    _add(out, shankh(2.8, seed=1), 0.05, 0.55)                       # the opening shankh
    for r in reveals:                                                 # damru roll into each reveal, bell on it
        for j, d in enumerate(np.cumsum(np.linspace(0.14, 0.045, 16))):
            _add(out, drum(380 if j % 2 else 300, 30, 0.2, 0.3, seed=j), r - 1.5 + d, 0.10 + 0.1 * j / 16)
        _add(out, bell(330.0, 6.0), r, 0.5)
    if climax is not None:
        _add(out, shankh(3.2, freq=260.0, seed=2), climax, 0.6)
        _add(out, bell(220.0, 7.0), climax, 0.55)
        _add(out, om_hum(min(8.0, max(3.0, seconds - climax)), seed=3), climax + 0.3, 0.35)
    return out


POST: dict[int, np.ndarray] = {}      # sounds that must stay audible inside the silent drop (filled per score)


def _dhol(seconds: float, I: np.ndarray, climax, reveals, rng) -> np.ndarray:
    n = len(I)
    out = crowd_bed(seconds, seed=int(rng.integers(1e6))) * 0.18 * (0.5 + 0.9 * I)
    beat = 60 / 112
    for k in range(int(seconds / (beat / 2)) + 1):                   # dha-dhin in eighths, denser as it builds
        at = k * beat / 2
        i = I[min(int(at * SR), n - 1)]
        if i < 0.1:
            continue
        if k % 4 in (0, 3):
            _add(out, drum(60, 8, seed=k), at, 0.35 + 0.35 * i)
        if k % 2 == 1 and i > 0.45:
            _add(out, drum(320, 22, 0.3, 0.35, seed=k), at, 0.12 + 0.18 * i)
        if i > 0.75 and k % 4 == 2:
            _add(out, drum(430, 26, 0.3, 0.4, seed=k), at, 0.16 * i)
    if climax is not None:                                           # heartbeat in the silence, roar on the climax
        from .sfx import heartbeat
        hb = heartbeat()
        post = POST.setdefault(id(I), np.zeros(n))
        _add(post, hb, climax - 1.4, 0.5)
        _add(post, hb, climax - 0.7, 0.55)
        tt = _t(int(4.5 * SR))
        roar = crowd_bed(4.5, seed=9) * np.minimum(1, tt / 0.6) * np.exp(-np.maximum(tt - 0.6, 0) * 0.5)   # swells in
        _add(out, roar, climax, 1.0)
        _add(out, drum(55, 7, 0.8, 0.2, seed=7), climax + 0.4, 0.35)          # a soft low drum, no slam
    for r in reveals:
        swell = crowd_bed(2.5, seed=int(r * 10)) * np.sin(np.linspace(0, np.pi, int(2.5 * SR)))
        _add(out, swell, r - 0.5, 0.5)
    return out


def _retro(seconds: float, I: np.ndarray, climax, reveals, rng) -> np.ndarray:
    n = len(I)
    out = np.zeros(n)
    chords = [[0, 4, 7], [5, 9, 12], [7, 11, 14], [5, 9, 12]]        # I - IV - V - IV, harmonium-like reeds
    bar = 2.4
    for b in range(int(seconds / bar) + 1):
        m = int(bar * SR)
        tt = _t(m)
        seg = np.zeros(m)
        for st in chords[b % 4]:
            f = 220 * 2 ** (st / 12)
            seg += sum(np.sin(2 * np.pi * f * h * tt) / h ** 1.3 for h in range(1, 6))
        seg *= np.minimum(1, tt / 0.15) * np.minimum(1, (bar - tt) / 0.2)
        _add(out, seg, b * bar, 0.05)
    yaman = [0, 2, 4, 6, 7, 9, 11, 12]                               # santoor-like plucks in Yaman (nostalgia)
    step = 0.3
    for k in range(int(seconds / step)):
        at = k * step
        if rng.random() < 0.55:
            deg = yaman[int(rng.integers(0, len(yaman)))]
            _add(out, pluck(440 * 2 ** (deg / 12), 1.2, rng, bright=0.9, decay=0.995), at, 0.18)
    beat = 60 / 96                                                    # light tabla (keherwa feel)
    for k in range(int(seconds / beat) + 1):
        at = k * beat
        i = I[min(int(at * SR), n - 1)]
        if i > 0.3:
            _add(out, drum(90 if k % 2 == 0 else 260, 12 if k % 2 == 0 else 26, seed=k), at, 0.22 * i)
    out += vinyl(seconds, seed=int(rng.integers(1e6)))[:n] * 0.35   # the old record, throughout
    for r in reveals + ([climax] if climax is not None else []):    # strings swell on the reveals (filmi emotion)
        _add(out, string_pad([220.0, 277.2, 329.6], 4.0), r - 0.3, 0.35)
    return out


def score(seconds: float, palette: str, climax: float | None = None, reveals: list[float] | None = None,
          seed: int = 0) -> np.ndarray:
    """The whole background score (mono, -1..1) for one video."""
    if palette not in PALETTES:
        raise ValueError(f"unknown palette {palette}")
    rng = np.random.default_rng(seed)
    reveals = sorted(r for r in (reveals or []) if 0 < r < seconds and r != climax)
    I = arc(seconds, climax, reveals)
    raw = {"devotional": _devotional, "dhol": _dhol, "retro": _retro}[palette](seconds, I, climax, reveals, rng)
    raw = raw[: len(I)]
    t60, wet = ROOMS[palette]
    out = room(raw, t60, wet, seed=seed + 5)
    level = (0.25 + 0.75 * I) * np.where(I < 0.05, 0.06, 1.0)        # the arc shapes the loudness; real silence
    out = out * _lowpass(level, 8.0)                                  # in the drop before the climax
    post = POST.pop(id(I), None)
    if post is not None:
        out = out + room(post[: len(out)], t60, wet * 0.6, seed=seed + 6) * 0.6
    t = _t(len(out))
    out *= np.minimum(1, t / 0.4) * np.minimum(1, (seconds - t) / 1.5).clip(0)
    return 0.7 * out / (np.abs(out).max() + 1e-9)
