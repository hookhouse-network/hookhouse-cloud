"""Tests for the v2 look (fast, no internet or models needed)."""
import numpy as np

from engine.media import compose, sfx
from engine.media.captions import _count_steps, _text_width, fit_big
from engine.media.footage import Footage, usable
from engine.media.mascot import Mascot
from engine.story import normalize_script


def _img(v, w=108, h=192):
    return np.full((h, w, 3), v, np.uint8)


def test_transitions_keep_frame_size_and_reach_the_new_shot():
    prev, new = _img(0), _img(200)
    rng = np.random.default_rng(0)
    for kind in ("zoom", "flash", "swipe", "glitch", "cut"):
        for p in (0.0, 0.3, 0.7, 1.0):
            out = compose.transition(kind, prev, new, p, rng)
            assert out.shape == new.shape and out.dtype == np.uint8
    assert abs(int(compose.transition("swipe", prev, new, 1.0, rng).mean()) - 200) <= 2
    assert compose.transition("flash", prev, new, 0.0, rng).mean() > 250       # starts white


def test_grader_and_finisher_run_on_a_frame():
    look = compose.Look(size=(108, 192), grain=4.0)
    frame = compose.Grader(look)(_img(120))
    out = compose.Finisher(look, total=10)(frame, 5.0, 0)
    assert out.shape == (192, 108, 3)
    bar = out[-8:, :, :]
    assert bar[:, :50].mean() != bar[:, -5:].mean()                            # progress bar half filled


def test_footage_filter_skips_talking_heads_and_logos():
    def f(title):
        return Footage("u", "nasa", title, "", "", title)
    assert not usable(f("Vice President Remarks at Kennedy Space Center"))
    assert not usable(f("Press Conference: Artemis Update"))
    assert usable(f("Saturn V Launch B-Roll"))


def test_music_bed_length_and_ducking():
    bed = sfx.music_bed(3.0, "dark")
    assert len(bed) == 3 * sfx.SR and np.abs(bed).max() <= 0.71
    voice = np.zeros(3 * sfx.SR, np.float32)
    voice[sfx.SR:2 * sfx.SR] = 0.5
    ducked = sfx.duck(bed, voice, 0.6)
    assert np.abs(ducked[sfx.SR + 2000:2 * sfx.SR - 2000]).mean() < np.abs(bed[sfx.SR + 2000:2 * sfx.SR - 2000]).mean()


def test_mascot_poses_are_cached():
    m = Mascot(64)
    a = m.draw(1.0, 0.5)
    b = m.draw(1.0, 0.5)
    assert a is b and a.shape == (64, 64, 4)


def test_count_up_ends_on_the_real_number():
    steps = list(_count_steps("183 RUNS", 0.0, 2.0))
    assert steps[-1][2] == "183 RUNS" and steps[0][2] != "183 RUNS"
    assert list(_count_steps("NO NUMBER", 0, 1)) == [(0, 1, "NO NUMBER")]


def test_old_scripts_are_converted_to_beats():
    s = normalize_script({"scenes": [{"narration": "Hi.", "visual_type": "ai", "visual_query": "fog"}]})
    assert s["beats"][0]["visual"] == "ai" and s["beats"][0]["query"] == "fog"


def test_big_text_always_fits_the_screen():
    for text in ("SHERLOCK HOLMES", "HE WAS ASTONISHED", "NEVER \"MARIE\"", "1872"):
        rows, size = fit_big(text, "Bebas Neue", 307, 830)
        assert len(rows) <= 2 and all(_text_width(r, "Bebas Neue", size) <= 831 for r in rows)
    assert fit_big("1872", "Bebas Neue", 307, 830) == (["1872"], 307)      # short text keeps full size


def test_brainsnack_sim_survives_escapes_and_particles():
    from engine.brainrot import Sim
    sim = Sim(22)
    for f in range(30 * 20):          # 20 s: escapes, bursts, balls leaving the screen
        sim.step(f)
    assert sim.escaped >= 1 and len(sim.balls) <= 36


def test_rate_limit_pause_fails_fast(monkeypatch):
    import time
    import pytest
    from engine.media import visuals

    class R:
        status_code, headers = 429, {"Retry-After": "600"}
    calls = []
    class FakeSession:
        def get(self, *a, **k):
            calls.append(1)
            return R()
    monkeypatch.setattr(visuals, "session", lambda: FakeSession())
    visuals._PAUSED_UNTIL.clear()
    with pytest.raises(visuals.RateLimited):
        visuals._get("https://example.org/a.jpg")
    t = time.time()
    with pytest.raises(visuals.RateLimited):
        visuals._get("https://example.org/b.jpg")       # paused host: no request, no sleeping
    assert len(calls) == 1 and time.time() - t < 0.5
    visuals._PAUSED_UNTIL.clear()


def test_captions_stop_before_big_text(tmp_path):
    from engine.media.captions import BigText, Word, build_ass, _ts
    words = [Word("kapil", 2.6, 2.9), Word("dev", 2.9, 3.4), Word("won", 4.5, 4.8)]
    text = build_ass(words, tmp_path / "b.ass", big_texts=[BigText(3.0, 4.0, "175")]).read_text(encoding="utf-8")
    cap_ends = [l.split(",")[2] for l in text.splitlines() if l.startswith("Dialogue") and ",Caption," in l]
    assert cap_ends and all(e <= _ts(3.0) or e > _ts(4.0) for e in cap_ends)


def test_fact_check_only_blocks_contradictions(monkeypatch):
    from engine import story

    class R:
        provider = "fake"

    class FakeBrain:
        def __init__(self, answer):
            self.answer = answer

        def ask_json(self, task, prompt, temperature=0.0):
            return self.answer, R()

    monkeypatch.setattr(story, "wikipedia_summaries", lambda titles, focus="", **kw: "reference text")
    script = {"claims": ["A court ordered the film destroyed in Germany"], "sources": ["Nosferatu"]}
    soft = story.fact_check(FakeBrain({"contradicted": [], "unsupported": ["court nationality not stated"]}), script)
    assert soft["ok"] is True and soft["warnings"] == ["court nationality not stated"]
    hard = story.fact_check(FakeBrain({"contradicted": ["year is 1922 not 1923"], "unsupported": []}), script)
    assert hard["ok"] is False and hard["problems"] == ["year is 1922 not 1923"]
    old = story.fact_check(FakeBrain({"ok": False, "problems": ["wrong"]}), script)
    assert old["ok"] is False
