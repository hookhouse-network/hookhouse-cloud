"""Sound polish (owner 18 Nov research): de-essed + presence voice chain, dynamic-EQ carve of the music's speech band,
quiet-intro skip, and the music's "button" ending on a beat right after the last word."""
import numpy as np
import soundfile as sf

from engine.media import sfx
from engine.media.music_library import intro_end

SR = 48000


def band_rms(x, lo, hi):
    from scipy.signal import butter, sosfiltfilt
    return float(np.sqrt(np.mean(sosfiltfilt(butter(2, [lo, hi], btype="bandpass", fs=SR, output="sos"), x) ** 2)))


def test_carve_dips_only_the_speech_band_while_talking():
    t = np.arange(SR * 4) / SR
    music = (0.3 * np.sin(2 * np.pi * 100 * t) + 0.3 * np.sin(2 * np.pi * 2000 * t)).astype(np.float32)
    voice = np.zeros_like(music)
    voice[SR:3 * SR] = 0.3 * np.sin(2 * np.pi * 200 * t[SR:3 * SR])       # talking from 1 s to 3 s
    out = sfx.carve_mid(music, voice, db=4.0)
    talk, quiet = slice(int(1.5 * SR), int(2.5 * SR)), slice(int(3.6 * SR), int(3.95 * SR))
    mid_drop = 20 * np.log10(band_rms(out[talk], 1500, 2500) / band_rms(music[talk], 1500, 2500))
    bass_drop = 20 * np.log10(band_rms(out[talk], 60, 150) / band_rms(music[talk], 60, 150))
    assert -5.0 < mid_drop < -2.5                     # the 2 kHz part steps aside ~4 dB
    assert bass_drop > -0.8                           # the bass stays
    assert abs(band_rms(out[quiet], 1500, 2500) / band_rms(music[quiet], 1500, 2500) - 1) < 0.1   # pauses: full


def test_duck_still_works_after_refactor():
    music = np.ones(SR * 2, np.float32) * 0.5
    voice = np.zeros(SR * 2, np.float32)
    voice[: SR] = 0.5
    out = sfx.duck_db(music, voice, db=6.0)
    assert out[int(0.8 * SR)] < 0.5 * 10 ** (-5 / 20) and abs(out[-10] - 0.5) < 0.02


def test_intro_skip():
    quiet = np.random.default_rng(1).normal(0, 0.005, SR * 6).astype(np.float32)
    body = np.random.default_rng(2).normal(0, 0.2, SR * 30).astype(np.float32)
    k = intro_end(np.concatenate([quiet, body]), SR)
    assert abs(k / SR - 6.0) <= 0.5
    assert intro_end(body, SR) == 0                   # starts strong: nothing skipped
    pickup = np.concatenate([quiet[: SR // 2], body])
    assert intro_end(pickup, SR) == 0                 # half a second is a pickup, kept


def click_bed(seconds, bpm=120):
    x = np.random.default_rng(0).normal(0, 0.01, int(SR * seconds)).astype(np.float32)
    k = np.arange(int(0.03 * SR))
    hit = (np.sin(2 * np.pi * 180 * k / SR) * np.exp(-k / (0.006 * SR))).astype(np.float32)
    for t in np.arange(0, seconds - 0.1, 60 / bpm):
        a = int(t * SR)
        x[a:a + len(hit)] += hit
    return x


def test_button_end_lands_after_last_word():
    from engine.story import button_end
    bed = click_bed(12.0)
    voice = np.zeros_like(bed)
    voice[: int(10.8 * SR)] = 0.2                     # last word ends at 10.8 s; beats every 0.5 s
    out = button_end(bed, voice, SR)
    assert np.abs(out[int(11.0 * SR):int(11.04 * SR)]).max() > 0.3      # the hit at 11.0 s is kept whole
    assert np.abs(out[int(11.6 * SR):]).max() < 1e-6                     # then silence: a clean button
    assert np.allclose(out[: int(10.9 * SR)], bed[: int(10.9 * SR)])     # nothing earlier is touched


def test_button_end_leaves_ambient_beds_alone():
    from engine.story import button_end
    t = np.arange(SR * 10) / SR
    pad = (0.3 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    assert np.array_equal(button_end(pad, np.zeros_like(pad), SR), pad)


def test_voice_chain_runs_in_ffmpeg(tmp_path):
    from engine.story import _process_voice
    t = np.arange(SR * 2) / SR
    src = tmp_path / "v.wav"
    sf.write(src, (0.2 * np.sin(2 * np.pi * 220 * t)).astype(np.float32), SR)
    out = _process_voice(src)
    assert out != src and out.exists()                # the new chain (deesser + presence EQ) did not fall back
