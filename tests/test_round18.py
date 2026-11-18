"""Round 18 (13 Nov): owner: "Hindi voice odd and breaking, wrong pauses, uneven pace, digits wrong; zoom in/out looks
awful in all channels." Fixes: punctuation-aware pauses, one steady pace, names in Devanagari for Kokoro, an optional
natural Google Hindi voice (free tier, capped), and a steady camera everywhere."""
import base64
import io
import json

import numpy as np
import soundfile as sf

from engine import story
from engine.media import compose, google_voice, parallax, say


def test_pauses_follow_the_punctuation():
    assert story.breath_after("कर्ण सब जानता था।") == 0.3
    assert story.breath_after("अंदाज़ा लगाइए?") == 0.3
    assert story.breath_after("और फिर…") == 0.45
    assert story.breath_after("Gavaskar zero,") == 0.12
    assert story.breath_after("और फिर कर्ण ने") < 0.12                    # the sentence goes on: barely a pause


def test_kokoro_hindi_gets_devanagari_names_and_no_mid_line_holes():
    say._dictionary.cache_clear()
    out = say.normalise("भारत 17 पर 5… Kapil Dev के 175, और TV पर कुछ नहीं।", "hi")
    assert "कपिल देव" in out and "टीवी" in out and "…" not in out
    assert say.normalise("और फिर…", "hi").endswith("…")                  # an ending '…' stays (a held moment)
    g = say.normalise("भारत 17 पर 5… Kapil Dev", "hi", engine="google")
    assert "…" in g                                                        # Google keeps the held pause


def test_camera_never_breathes_in_and_out():
    src = compose.Shot(0.0, 3.0, "image", None, "push_in", "full", "cut", [], [])
    r = compose.ShotRenderer.__new__(compose.ShotRenderer)
    r.s = src
    zs = [r._zoom_center(t)[0] for t in np.linspace(0, 3, 31)]
    steps = np.diff(zs)
    assert np.all(steps >= -1e-9) and zs[-1] - zs[0] <= 0.041              # one direction, gentle (<= 4%)
    assert np.std(steps[1:-1]) < 1e-6                                      # constant speed (no ease in/out)
    assert "pull" not in parallax.MOVES
    src_text = open(story.__file__, encoding="utf-8").read()
    assert 'moves = ["push_in", "pan_left", "push_in", "pan_right", "drift_up"]' in src_text


class _Resp:
    def __init__(self, sr=24000, seconds=0.5):
        buf = io.BytesIO()
        t = np.arange(int(sr * seconds)) / sr
        sf.write(buf, (0.3 * np.sin(2 * np.pi * 200 * t)).astype(np.float32), sr, format="WAV", subtype="PCM_16")
        self.status_code, self._b = 200, base64.b64encode(buf.getvalue()).decode()
        self.text = ""

    def json(self):
        return {"audioContent": self._b}


def test_google_voice_caches_counts_and_caps(tmp_path, monkeypatch):
    monkeypatch.setattr(google_voice, "CACHE", tmp_path / "cache")
    monkeypatch.setattr(google_voice, "USAGE", tmp_path / "usage.json")
    monkeypatch.setenv("GOOGLE_TTS_API_KEY", "AIza" + "x" * 35)
    calls = []

    class S:
        def post(self, url, params=None, json=None, timeout=0):
            calls.append(json)
            return _Resp()
    d = google_voice.synthesize("कर्ण ने खुद… कवच दे दिए।", tmp_path / "a.wav", "hi-IN-Chirp3-HD-Charon", 1.0, session=S())
    assert 0.4 < d < 0.6 and calls[0]["input"]["markup"].count("[pause]") == 1
    assert calls[0]["voice"] == {"languageCode": "hi-IN", "name": "hi-IN-Chirp3-HD-Charon"}
    google_voice.synthesize("कर्ण ने खुद… कवच दे दिए।", tmp_path / "b.wav", "hi-IN-Chirp3-HD-Charon", 1.0, session=S())
    assert len(calls) == 1                                                 # re-render: from the cache, no characters
    used = google_voice.month_used()
    assert used == len(calls[0]["input"]["markup"])
    (tmp_path / "usage.json").write_text(json.dumps({google_voice._month(): google_voice.SAFE_CHARS}), encoding="utf-8")
    assert not google_voice.available()                                   # the ₹0 safety cap
    try:
        google_voice.synthesize("नई लाइन", tmp_path / "c.wav", "hi-IN-Chirp3-HD-Charon", session=S())
        raise AssertionError("should stop at the cap")
    except RuntimeError as e:
        assert "cap" in str(e)


def test_google_voice_is_off_without_a_key(monkeypatch):
    monkeypatch.delenv("GOOGLE_TTS_API_KEY", raising=False)
    assert not google_voice.available()
    assert google_voice.voice_for({"id": "itihaas_ke_raaz"}).startswith("hi-IN-Chirp3-HD")


def test_setup_checks_the_google_voice_key():
    from engine import setup_steps

    class S:
        def get(self, url, params=None, timeout=0, **k):
            r = type("R", (), {})()
            r.status_code = 200
            r.json = lambda: {"voices": [{"name": "hi-IN-Chirp3-HD-Charon"}, {"name": "hi-IN-Standard-A"}]}
            return r
    ok, msg = setup_steps.check_google_tts_key("AIza" + "y" * 35, S())
    assert ok and "1 natural Hindi" in msg
    assert not setup_steps.check_google_tts_key("nope")[0]


def test_parler_is_off_without_a_token(monkeypatch):
    from engine.media import parler_voice
    monkeypatch.delenv("HF_TOKEN", raising=False)
    assert not parler_voice.available()
    assert "Divya" in parler_voice.description_for({"id": "picture_abhi_baaki_hai"})
    assert "Rohit" in parler_voice.description_for({"id": "itihaas_ke_raaz"})


def test_parler_batch_sends_devanagari_lines_with_one_voice(monkeypatch, tmp_path):
    from engine.media import parler_voice
    monkeypatch.setattr(parler_voice, "available", lambda: True)
    monkeypatch.setenv("HF_TOKEN", "hf_" + "a" * 34)
    sent = {}

    def fake_run(cmd, **k):
        job = json.loads(open(cmd[-1], encoding="utf-8").read())
        sent.update(job, env_token=k["env"].get("HF_TOKEN"))
        for ln in job["lines"]:
            sf.write(ln["out"], np.zeros(4410, np.float32), 44100)
        return type("P", (), {"returncode": 0, "stdout": "DONE", "stderr": ""})()
    monkeypatch.setattr(parler_voice.subprocess, "run", fake_run)
    beats = [{"narration": "Kapil Dev के 175… और TV पर कुछ नहीं।"}, {"narration": "₹15,000 की फिल्म"}]
    outs = parler_voice.batch(beats, tmp_path, {"id": "cricket_ke_kisse"}, log=lambda m: None)
    assert len(outs) == 2 and sent["env_token"].startswith("hf_")
    assert "कपिल देव" in sent["lines"][0]["text"] and "टीवी" in sent["lines"][0]["text"]
    assert sent["lines"][1]["text"] == "पंद्रह हज़ार रुपये की फिल्म"      # round 20: numbers as words
    assert "Rohit" in sent["description"] and sent["seed"] == 7                 # one speaker, one seed: same voice


def test_parler_line_resamples_paces_and_pauses(tmp_path):
    from engine.media import parler_voice
    t = np.arange(44100) / 44100
    sf.write(tmp_path / "raw.wav", (0.3 * np.sin(2 * np.pi * 220 * t)).astype(np.float32), 44100)
    d = parler_voice.line(tmp_path / "raw.wav", tmp_path / "out.wav", 1.0, 0.3)
    info = sf.info(tmp_path / "out.wav")
    assert info.samplerate == 24000 and 1.25 <= d <= 1.4


def test_setup_checks_the_hugging_face_token():
    from engine import setup_steps

    class S:
        def __init__(self, gated_ok):
            self.gated_ok = gated_ok

        def get(self, url, timeout=0, **k):
            r = type("R", (), {})()
            r.status_code = 200 if ("whoami" in url or self.gated_ok) else 403
            r.json = lambda: {"name": "hookhouse"}
            return r
    tok = "hf_" + "b" * 34
    assert setup_steps.check_hf_token(tok, S(True))[0]
    ok, msg = setup_steps.check_hf_token(tok, S(False))
    assert not ok and "Agree" in msg
    assert not setup_steps.check_hf_token("nope")[0]
