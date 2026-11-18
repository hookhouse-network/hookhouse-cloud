"""Round 16 (13 Nov): emotion-driven Hindi channels (owner: "learn the emotion-driven audio... more dramatic with
sound, visuals, background music, and feel nostalgic and more devoted").
- Emotional scores that follow the story (build, silence before the climax, hit, settle), played in a room.
- Nostalgic / devotional picture looks: old film, golden glow, warm light leak.
- Opt-in emotional Hindi voice (Chatterbox Hindi) with emotion per line and a Kokoro fallback."""
import json

import numpy as np
import pytest
import soundfile as sf

from engine.media import compose
from engine.media import emotion_music as em
from engine.media import emotional_voice as ev


def _db(x, a, b):
    seg = x[int(a * em.SR):int(b * em.SR)]
    return 20 * np.log10(np.sqrt(np.mean(seg ** 2)) + 1e-9)


def test_arc_builds_drops_hits_and_settles():
    I = em.arc(50.0, 36.0, [18.0])
    at = lambda t: I[int(t * em.SR)]                                           # noqa: E731
    assert abs(at(0.1) - 0.35) < 0.02 and at(30) > at(5)                      # soft start, builds
    assert at(35.7) < 0.05                                                     # silence just before the climax
    assert at(36.05) < 0.5 and at(36.5) > 0.9 and at(18.5) > 0.9             # swells in (never slams), then peaks
    assert max(I) <= 0.93
    assert 0.35 < at(49.9) < 0.45                                              # settles at the end


@pytest.mark.parametrize("palette", em.PALETTES)
def test_scores_follow_the_story(palette):
    x = em.score(40.0, palette, climax=28.0, reveals=[14.0], seed=2)
    assert len(x) == int(40.0 * em.SR) and np.abs(x).max() <= 0.71
    assert _db(x, 28.0, 31.0) - _db(x, 27.5, 27.95) > 10                      # the hit lands out of the quiet
    if palette != "dhol":                                                      # cricket keeps a heartbeat in it
        assert _db(x, 27.5, 27.95) < _db(x, 20, 26) - 20                      # real silence before the climax


def test_score_without_moments_still_works():
    x = em.score(12.0, "retro", climax=None, reveals=[], seed=1)
    assert np.isfinite(x).all() and np.abs(x).max() > 0.1


def test_room_reverb_keeps_length_and_level():
    rng = np.random.default_rng(0)
    dry = np.zeros(em.SR * 2)
    dry[1000] = 1.0
    wet = em.room(dry, 1.5, 0.4)
    assert len(wet) == len(dry)
    assert np.abs(wet[int(0.5 * em.SR):]).max() > 1e-4                       # a tail after the click
    noise = rng.standard_normal(em.SR)
    assert abs(np.sqrt(np.mean(em.room(noise, 1.0, 0.3) ** 2)) - np.sqrt(np.mean(noise ** 2))) < 0.35


def test_instruments_make_sound():
    rng = np.random.default_rng(3)
    for snd in (em.pluck(110, 1.0, rng, buzz=0.6), em.bell(330, 2.0), em.shankh(1.5), em.om_hum(2.0),
                em.projector(1.0), em.vinyl(1.0), em.string_pad([220.0, 277.2], 2.0), em.manjira()):
        assert np.isfinite(snd).all() and np.abs(snd).max() > 0.05


def test_hindi_palettes_hand_the_moments_to_the_score():
    from engine import story
    assert story.SFX_PALETTE["itihaas_ke_raaz"]["open"] is None and story.SFX_PALETTE["itihaas_ke_raaz"]["reveal"] is None
    assert story.SFX_PALETTE["cricket_ke_kisse"]["reveal"] is None
    assert story.SFX_PALETTE["picture_abhi_baaki_hai"]["open"][0] == "projector"
    assert "projector" in story.SFX_BANK


def test_mix_uses_the_emotional_score(monkeypatch, tmp_path):
    from engine import story
    sr = 48000
    t = np.arange(int(6 * sr)) / sr
    v = (0.2 * np.sin(2 * np.pi * 180 * t) * (np.sin(2 * np.pi * 0.7 * t) > 0)).astype(np.float32)
    sf.write(tmp_path / "voice.wav", v, sr)
    seen = {}
    real = em.score

    def spy(seconds, palette, climax=None, reveals=None, seed=0):
        seen.update(palette=palette, climax=climax, reveals=reveals)
        return real(seconds, palette, climax=climax, reveals=reveals, seed=seed)
    monkeypatch.setattr(em, "score", spy)
    out = story._mix(tmp_path / "voice.wav", [], "devotional", tmp_path / "mix.wav", drops=[4.0],
                     swells=[(2.0, 3.0), (4.0, 5.0)], mix=story.MIX["itihaas_ke_raaz"])
    assert out.exists() and seen == {"palette": "devotional", "climax": 4.0, "reveals": [2.0, 4.0]}


def _frame():
    rng = np.random.default_rng(1)
    f = np.full((320, 180, 3), 90, np.uint8)
    f[40:120, 40:140] = 240                                                     # a bright area (a diya, a sky)
    return f + rng.integers(0, 6, f.shape).astype(np.uint8)


def test_glow_brightens_highlights_warmly():
    fin = compose.Finisher(compose.Look(size=(180, 320), glow=0.6, vignette=0, grain=0), 5.0)
    src = _frame()
    out = fin._glow(src.copy())
    around = (slice(122, 150), slice(40, 140))                                 # just outside the bright area
    d = out[around].astype(int) - src[around].astype(int)
    assert d[..., 2].mean() > d[..., 0].mean() > 0                             # red (warm) rises more than blue
    assert out.shape == src.shape and out.dtype == np.uint8


def test_leak_is_soft_with_no_hard_edges():
    fin = compose.Finisher(compose.Look(size=(180, 320), leak=0.5, vignette=0, grain=0), 5.0)
    src = np.full((320, 180, 3), 60, np.uint8)
    diff = fin._leak(src.copy(), 3.0).astype(int) - src
    assert diff.max() > 10                                                     # visible
    assert np.abs(np.diff(diff[..., 2], axis=0)).max() <= 3                   # smooth: no box edge
    assert np.abs(np.diff(diff[..., 2], axis=1)).max() <= 3


def test_film_adds_reel_marks_and_stays_the_same_size():
    fin = compose.Finisher(compose.Look(size=(180, 320), film=0.8, vignette=0, grain=0), 5.0)
    src = _frame()
    outs = [fin._film(src.copy(), i / 30, i) for i in range(12)]
    assert all(o.shape == src.shape for o in outs)
    assert sum(int((o != src).any()) for o in outs) >= 10                      # flicker / dust / scratches


def test_hindi_looks_reach_the_compositor():
    from engine import story
    look, _ = story.channel_look({"id": "picture_abhi_baaki_hai", "style": {}}, (1080, 1920))
    assert look.film > 0 and look.leak > 0
    look, _ = story.channel_look({"id": "itihaas_ke_raaz", "style": {}}, (1080, 1920))
    assert look.glow > 0 and look.particles > 0
    look, _ = story.channel_look({"id": "unsolved_after_dark", "style": {}}, (1080, 1920))
    assert look.film == look.glow == look.leak == 0                            # English channels unchanged


def test_emotion_follows_the_moment():
    assert ev.emotion_for(0, 10, "normal") == ev.EMOTION["hook"]
    assert ev.emotion_for(4, 10, "reveal") == ev.EMOTION["reveal"]
    assert ev.emotion_for(9, 10, "normal") == ev.EMOTION["ending"]
    assert ev.emotion_for(4, 10, "normal")[0] < ev.emotion_for(4, 10, "reveal")[0]


def test_batch_sends_normalised_lines_with_emotion(monkeypatch, tmp_path):
    monkeypatch.setattr(ev, "available", lambda: True)
    sent = {}

    def fake_run(cmd, **k):
        job = json.loads(open(cmd[-1], encoding="utf-8").read())
        sent.update(job)
        for ln in job["lines"]:
            sf.write(ln["out"], np.zeros(2400, np.float32), 24000)
        return type("P", (), {"returncode": 0, "stdout": "DONE", "stderr": ""})()
    monkeypatch.setattr(ev.subprocess, "run", fake_run)
    beats = [{"narration": "₹15,000 की फिल्म", "moment": "normal"}, {"narration": "1983 में", "moment": "reveal"}]
    outs = ev.batch(beats, tmp_path, "hi", log=lambda m: None)
    assert len(outs) == 2 and all(p.exists() for p in outs)
    assert sent["lines"][0]["text"] == "15000 रुपये की फिल्म"                  # say-it-right applies here too
    assert sent["lines"][1]["exaggeration"] == ev.EMOTION["reveal"][0]


def test_batch_refuses_when_not_installed(monkeypatch, tmp_path):
    monkeypatch.setattr(ev, "available", lambda: False)
    with pytest.raises(RuntimeError):
        ev.batch([{"narration": "x"}], tmp_path)


def test_line_paces_trims_and_pauses(tmp_path):
    a = np.concatenate([np.zeros(2400), 0.3 * np.sin(np.arange(24000) / 5), np.zeros(4800)]).astype(np.float32)
    sf.write(tmp_path / "raw.wav", a, 24000)
    d1 = ev.line(tmp_path / "raw.wav", tmp_path / "a.wav", 1.0, 0.5)
    d2 = ev.line(tmp_path / "raw.wav", tmp_path / "b.wav", 1.25, 0.0)
    assert 1.45 <= d1 <= 1.6                                                   # 1 s speech + 0.5 s pause, trimmed
    assert 0.75 <= d2 <= 0.9                                                   # faster read
