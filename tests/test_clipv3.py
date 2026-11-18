"""Tests for the v3 podcast clip logic (no video needed)."""
from engine.clips import Word
from engine.clipv3 import TimeMap, build_captions, build_segments, make_shots, plan_punches


def _words(spec):
    """spec: list of (text, start, end)."""
    return [Word(t, s, e) for t, s, e in spec]


def test_long_pauses_are_tightened_but_speech_is_kept():
    ws = _words([("one", 0.0, 0.4), ("two", 0.5, 0.9), ("three", 2.5, 3.0), ("four", 3.1, 3.5)])
    segs = build_segments(ws, 0.0, 4.0)
    assert len(segs) == 2                                    # the 1.6 s pause was cut
    tm = TimeMap(segs)
    assert tm.duration < 3.5 - 1.0
    for w in ws:                                             # every word survives, in order
        assert 0 <= tm.to_out(w.start) < tm.to_out(w.end) <= tm.duration + 1e-6
    assert abs(tm.to_src(tm.to_out(2.7)) - 2.7) < 1e-6


def test_backchannels_do_not_cause_cuts_and_real_turns_do():
    ws = _words([("I", 0.0, 0.2), ("think", 0.2, 0.5), ("this", 0.5, 0.8), ("matters", 0.8, 1.6),
                 ("yeah", 1.7, 1.9),                                     # listener: backchannel
                 ("because", 2.0, 2.4), ("it", 2.4, 2.5), ("changed", 2.5, 3.0), ("everything", 3.0, 3.8),
                 ("No", 4.0, 4.3), ("I", 4.3, 4.4), ("disagree", 4.4, 5.0), ("completely", 5.0, 5.8),
                 ("with", 5.8, 6.0), ("that", 6.0, 6.4)])
    spk = [0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1]
    shots = make_shots(ws, spk, 2, 7.0)
    assert [s["speaker"] for s in shots] == [0, 1]
    assert shots[0]["t0"] == 0.0 and shots[-1]["t1"] == 7.0
    assert all(s["t1"] - s["t0"] >= 1.5 for s in shots)


def test_punch_ins_respect_spacing_and_limits():
    ws = _words([(f"w{i}", i * 0.5, i * 0.5 + 0.4) for i in range(80)])
    shots = [{"t0": 0.0, "t1": 40.0, "layout": "A", "speaker": 0}]
    punches = plan_punches(ws, {f"w{i}" for i in range(0, 80, 2)}, shots, 40.0)
    starts = [a for a, _ in punches]
    assert all(b - a >= 8.0 for a, b in zip(starts, starts[1:]))
    assert all(b - a >= 2.0 for a, b in punches)
    assert sum(1 for a in starts if a < 30) <= 3


def test_captions_are_short_chunks_with_one_accent(tmp_path):
    ws = _words([("This", 0.0, 0.3), ("is", 0.3, 0.4), ("the", 0.4, 0.5), ("craziest", 0.5, 1.0),
                 ("thing", 1.0, 1.3), ("ever.", 1.3, 1.8)])
    shots = [{"t0": 0.0, "t1": 2.0, "layout": "A", "speaker": 0}]
    path = build_captions(ws, shots, tmp_path / "c.ass")
    events = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.startswith("Dialogue")]
    assert len(events) == len(ws)                            # one event per spoken word (moving highlight)
    for ev in events:
        text = ev.split(",,", 2)[-1]
        assert text.count("\\1c&H003D6AFF") == 1             # exactly one accent word
        assert "\\pos(540,1150)" in ev    # research: 60% height, below the chin, above Meta's bottom-35% UI line


def test_hyphen_pieces_join_the_previous_word(tmp_path):
    ws = _words([("meet", 0.0, 0.3), ("-and", 0.3, 0.5), ("-greet", 0.5, 0.9), ("today.", 0.9, 1.4)])
    shots = [{"t0": 0.0, "t1": 2.0, "layout": "A", "speaker": 0}]
    text = build_captions(ws, shots, tmp_path / "c.ass").read_text(encoding="utf-8")
    assert "meet-and-greet" in text and " -and" not in text
