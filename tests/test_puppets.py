"""P3r step 4 (owner 21 Nov: "instead of just shapes, we can introduce some humans"): human friends as puppets.
Faces from DiceBear (licence checked every time), bodies/arms/motion from our code, wired into the kids Shorts."""
import subprocess

import cv2
import numpy as np
import pytest

from engine import kids
from engine.media import characters, puppet


def _fake_files(tmp_path):
    def files(cid, states, height):
        out = {}
        for s in states:
            img = np.zeros((height, height, 4), np.uint8)
            cv2.circle(img, (height // 2, height // 2), height // 3, (180, 160, 220, 255), -1)
            p = tmp_path / f"{cid}_{'_'.join(s)}.png"
            cv2.imwrite(str(p), img)
            out[s] = p
        return out
    return files


def test_licence_is_checked_on_every_generation(monkeypatch, tmp_path):
    monkeypatch.setattr(characters, "dicebear_dir", lambda: tmp_path)
    ch = characters.character("mia")
    ok = '{"license": "CC BY 4.0", "faces": {"smile_happy_happy": "<svg/>"}}'
    run = lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, stdout=ok, stderr="")  # noqa: E731
    assert characters._node_faces(ch, [("smile", "happy", "happy")], run=run) == {"smile_happy_happy": "<svg/>"}
    assert (tmp_path / characters.SCRIPT).read_text(encoding="utf-8") == characters.JS
    bad = '{"license": "Free for personal and commercial use", "faces": {}}'
    with pytest.raises(characters.CharacterError, match="not allowed"):
        characters._node_faces(ch, [("smile", "happy", "happy")],
                               run=lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, stdout=bad, stderr=""))
    with pytest.raises(characters.CharacterError, match="no character"):
        characters.character("nobody")


def test_bible_characters_are_fixed_and_kid_safe():
    b = characters.bible()
    assert "CC BY 4.0" in b["credit"] and "ToonHead" in b["credit"]
    for cid, ch in b["characters"].items():
        o = ch["options"]
        assert ch["style"] == "toonHead" and o["beardProbability"] == 0          # kids: never a beard
        for k in ("hair", "skinColor", "clothes", "clothesColor", "eyes", "eyebrows"):
            assert isinstance(o[k], list) and len(o[k]) == 1, (cid, k)          # fixed look in every episode
    assert len({ch["options"]["skinColor"][0] for ch in b["characters"].values()}) >= 3     # varied skin tones


def test_face_files_are_cached(monkeypatch, tmp_path):
    monkeypatch.setattr(characters, "CACHE", tmp_path)
    calls = []

    def node(ch, states):
        calls.append(len(states))
        return {characters.key(s): "<svg/>" for s in states}
    raster = lambda svgs, h: {k: b"\x89PNG" for k in svgs}  # noqa: E731
    states = [("smile", "happy", "happy"), ("laugh", "bow", "happy")]
    a = characters.face_files("leo", states, 100, node=node, raster=raster)
    b = characters.face_files("leo", states, 100, node=node, raster=raster)
    assert a == b and calls == [2] and all(p.exists() for p in a.values())


def test_puppet_poses(tmp_path):
    p = puppet.Puppet("mia", size=430, files=_fake_files(tmp_path))
    spr = p.draw(0.5)
    assert spr.shape == (p.H, p.W, 4) and p.H == int(0.8 * 430)
    assert spr[-12:, :, 3].max() == 255 and spr[0, 0, 3] == 0          # feet on the bottom edge, transparent corner
    blink = p.blinks[0] + 0.05
    assert p.face_state(blink)[1] == "humble" and p.face_state(blink + 0.3)[1] == "happy"
    assert p.face_state(1.0, viseme="round")[0] == "agape" and p.face_state(1.0, viseme="open")[0] == "laugh"
    assert p.face_state(1.0, mouth=0.0)[0] == "smile"
    assert p.face_state(p.blinks[0] + 0.5, action="cheer")[1] == "bow"            # joy: ^^ eyes
    assert p.face_state(1.0, action="question")[2] == "raised"
    assert p.draw(0.5) is spr                                                    # cached pose
    assert p.draw(0.5, hop=0.6).shape == spr.shape
    wave = [p.draw(2.0 + i / 12, action="wave") for i in range(6)]
    assert len({w.tobytes() for w in wave}) > 1                                  # the arm really moves
    gaps = np.diff(p.blinks[:20])
    assert gaps.min() >= 2.2 and gaps.max() <= 4.8 and gaps.std() > 0.2         # varied, never metronomic


def test_kids_friends_and_actions(monkeypatch):
    monkeypatch.setattr(kids, "puppets_on", lambda: True)
    pool = kids.friends()
    assert pool[0] in kids.HUMANS and sum(n in kids.HUMANS for n in pool) == len(kids.HUMANS)
    assert pool[1] not in kids.HUMANS                                           # humans take every other slot
    monkeypatch.setattr(kids, "puppets_on", lambda: False)
    assert not set(kids.friends()) & set(kids.HUMANS)                           # no puppets: toon friends only
    assert kids.is_puppet("Mia") and not kids.is_puppet("Bloop")
    cur = {"who": "Mia", "kind": "count", "start": 1.0}
    assert kids.puppet_action(cur, "Mia", "count", 0.2, 1.2, 1.9) == "count"
    assert kids.puppet_action(cur, "Bloop", "count", 0.2, 1.2, 1.9) is None
    assert kids.puppet_action(cur, "Mia", "wave", 0.2, 1.2, None) == "wave"
    assert kids.puppet_action(cur, "Mia", "answer", 0.5, 1.5, None) == "cheer"
    assert kids.puppet_action(None, "Mia", "", 0, 0, None) is None
    assert "CC BY 4.0" in kids.credits_line(("Bloop", "Mia")) and kids.credits_line(("Bloop", "Pip")) == ""


def test_long_episodes_get_two_rotating_human_friends():
    lines = [{"who": "Mo", "say": "Hi Dee! Hi Pip!", "kind": "story", "section": "intro"},
             {"who": "Dee", "say": "Mo, look at the moon.", "kind": "story", "section": "intro"},
             {"who": "Bloop", "say": "Momo the moose!", "kind": "story", "section": "intro"}]
    out, swap = kids.human_cast_lines(lines, seed=1)
    a, b = swap["Mo"], swap["Dee"]
    assert a != b and {a, b} <= set(kids.HUMANS)
    assert out[0] == dict(lines[0], who=a, say=f"Hi {b}! Hi Pip!") and out[1]["say"] == f"{a}, look at the moon."
    assert out[2]["say"] == "Momo the moose!"                              # only whole names change
    assert kids.human_cast_lines(lines, seed=2)[1] != swap                  # rotates from episode to episode
    kids.use_layout("long", swap=swap)
    try:
        cast = dict(kids.CAST)
    finally:
        kids.use_layout("long")
    assert set(cast) == {"Bloop", "Pip", a, b} and cast[a][1] == f"puppet:{a.lower()}"
    assert cast[a][4] == kids.LAYOUTS["long"]["CAST_X"]["Mo"] and cast[b][4] == kids.LAYOUTS["long"]["CAST_X"]["Dee"]
    assert set(kids.CAST) == {"Bloop", "Pip", "Mo", "Dee"}                 # the base cast is back afterwards
    assert "CC BY 4.0" in kids.credits_line(tuple(cast))


def test_chorus_lines_with_any_friend_never_crash():
    kids.use_layout("short", duo=("Bloop", "Mia"))
    try:
        part = np.ones(100, np.float32)
        lines = [{"start": 0.0, "_parts": {"Bloop": part, "Mia": part}}]
        tracks = kids.voice_tracks(lines, 1.0)
        assert tracks["Mia"].max() > 0
    finally:
        kids.use_layout("long")


def test_kid_voices_are_lifted(monkeypatch, tmp_path):
    pitch = kids.kid_pitch()
    assert pitch and all(1.5 <= s <= 4 for s in pitch.values())            # a child, never a chipmunk
    assert not any(v.startswith("am_") for v in pitch)                     # boys: a lifted female voice
    calls = []

    def fake_synth(text, path, voice, lang, speed=1.0, trim=True):
        import soundfile as sf
        sf.write(str(path), np.zeros(2400, np.float32) + 0.01, 24000)
    monkeypatch.setattr(kids, "synthesize", fake_synth)
    monkeypatch.setattr(kids, "pitch_up", lambda src, st: calls.append((src.name, st)) or src)
    v = kids.Voices(tmp_path, 1.0, pitch={"af_nicole": 3.0})
    v.say("Hi Bloop!", "af_nicole")
    v.say("Hi Mia!", "af_bella")                                          # Bloop: natural voice
    assert calls == [("v_000.wav", 3.0)]


def test_pitch_up_keeps_the_length(tmp_path):
    import soundfile as sf
    sr = 24000
    t = np.arange(sr) / sr
    sf.write(str(tmp_path / "a.wav"), (0.3 * np.sin(2 * np.pi * 180 * t)).astype(np.float32), sr)
    out = kids.pitch_up(tmp_path / "a.wav", 3.0)
    b, sr2 = sf.read(str(out), dtype="float32")
    assert sr2 == sr and abs(len(b) - sr) < sr * 0.03
    spec = np.abs(np.fft.rfft(b * np.hanning(len(b))))
    peak = np.argmax(spec) * sr2 / len(b)
    assert 205 < peak < 222                                               # 180 Hz * 2^(3/12) = 214 Hz
    assert kids.pitch_up(tmp_path / "a.wav", 0) == tmp_path / "a.wav"


def test_duo_with_a_human_friend(monkeypatch, tmp_path):
    monkeypatch.setattr(kids, "puppets_on", lambda: True)
    lines = [{"who": "Bloop", "say": "Hi Pip and Mo!", "kind": "story", "section": "intro"},
             {"who": "Pip", "say": "Hi Bloop!", "kind": "story", "section": "intro"}]
    out, duo = kids.duo_lines(lines, seed=0)
    assert duo == ("Bloop", kids.friends()[0]) and duo[1] in kids.HUMANS
    assert out[1]["who"] == duo[1] and duo[1] in out[0]["say"]
    made = []
    monkeypatch.setattr("engine.media.puppet.Puppet",
                        lambda cid, size, seed=0: made.append((cid, size)) or object())
    kids.use_layout("short", duo=duo)
    try:
        cast = kids.make_cast(seed=3)
    finally:
        kids.use_layout("long")
    assert set(cast) == {"Bloop", duo[1]} and made and made[0][0] == duo[1].lower()
