"""Round 14 (13 Nov): ideas from AutoClip's research note #1 ("what 158 short clips taught us", 9 Oct 2026).
- Clip titles: name the person + a concrete act or number; fake urgency removed; slogan titles flagged.
- Technical floor: no dead digital silence inside a video; no faded grey blacks on real footage.
- Weekly report: videos that were liked but stayed with existing fans."""
import time

import numpy as np

from engine import analytics, clips, quality
from engine.clips import Word
from engine.media import ffmpeg


def W(text, n0=0.0, step=0.4):
    out, t = [], n0
    for tok in text.split():
        out.append(Word(tok, round(t, 2), round(t + step - 0.05, 2)))
        t += step
    return out


def test_proper_nouns_come_from_mid_sentence_capitals_and_the_campaign():
    ws = W("So I told Kevin about it. Then we flew to Chicago and I said OK fine.")
    names = clips.proper_nouns(ws, "Diary Show")
    assert {"kevin", "chicago", "diary", "show"} <= names
    assert "so" not in names and "then" not in names and "ok" not in names and "i" not in names


def test_clean_title_removes_fake_urgency_and_flags_slogans():
    names = {"kevin", "hart"}
    assert clips.clean_title("BREAKING: Kevin Hart Walks Out", names) == ("Kevin Hart Walks Out", ["urgency_removed"])
    assert clips.clean_title("Respect Is Earned, Not Given", names) == ("Respect Is Earned, Not Given", ["vague"])
    assert clips.clean_title("He Turned Down $50M For One Reason", names)[1] == []        # a number is concrete
    assert clips.clean_title("Kevin Hart On Fame", names)[1] == []                        # names the person
    assert clips.clean_title("Live Like Kevin Hart", names) == ("Live Like Kevin Hart", [])
    assert clips.clean_title("Kevin Hart Was Just In Time (LIVE)", names)[0] == "Kevin Hart Was Just In Time"
    assert clips.clean_title("Respect Is Earned", None)[1] == []                          # no names known: no guess


def test_pick_moments_cleans_titles_and_keeps_flags():
    ws = W(" ".join(["Then Kevin paid for my whole degree and I never paid a single dollar back."] * 10))

    class Brain:
        def ask_json(self, *a, **k):
            base = {"scores": {k2: 8 for k2 in clips.WEIGHTS}, "hook_options": ["x"]}
            moms = [dict(base, start=0.0, end=24.0, first_words="Then Kevin paid for my", title="JUST IN: Kevin Paid It",
                         id="a"),
                    dict(base, start=30.0, end=54.0, first_words="Then Kevin paid for my", title="Generosity Wins",
                         id="b")]
            return {"moments": moms}, type("R", (), {"provider": "test"})()
    by = {m["id"]: m for m in clips.pick_moments(Brain(), ws, keep=2, min_len=20, max_len=55)}
    assert by["a"]["title"] == "Kevin Paid It" and by["a"]["title_flags"] == ["urgency_removed"]
    assert by["b"]["title"] == "Generosity Wins" and by["b"]["title_flags"] == ["vague"]


def test_silence_check_finds_dead_air_inside_but_not_at_the_edges(tmp_path):
    out = tmp_path / "a.mp4"
    ffmpeg.run(["-f", "lavfi", "-i", "sine=frequency=440:duration=1.5", "-f", "lavfi", "-i",
                "anullsrc=r=44100:cl=mono:d=1", "-f", "lavfi", "-i", "sine=frequency=440:duration=1.5",
                "-filter_complex", "[0:a]aresample=44100[a0];[2:a]aresample=44100[a2];[a0][1:a][a2]concat=n=3:v=0:a=1",
                "-c:a", "aac", str(out)])
    gaps = quality._silences(out, ffmpeg.duration(out))
    assert len(gaps) == 1 and 1.3 <= gaps[0][0] <= 1.7 and 2.3 <= gaps[0][1] <= 2.7
    tone = tmp_path / "b.mp4"
    ffmpeg.run(["-f", "lavfi", "-i", "sine=frequency=440:duration=3", "-c:a", "aac", str(tone)])
    assert quality._silences(tone, ffmpeg.duration(tone)) == []


def test_black_p1_spots_faded_blacks():
    rng = np.random.default_rng(3)
    deep = [np.repeat(rng.integers(0, 256, (60, 80, 1)), 3, axis=2).astype(np.uint8) for _ in range(5)]   # grey ramp
    faded = [(f.astype(float) * 0.6 + 60).astype(np.uint8) for f in deep]               # lifted to ~60
    assert quality.black_p1(deep) < 10
    assert quality.black_p1(faded) > quality.TARGETS["black_p1"]
    assert quality.washed_out(faded) and quality.washed_out(deep) is None
    bright_set = [np.clip(f.astype(int) * 0.8 + 50, 0, 255).astype(np.uint8) for f in deep]   # no black, real white
    assert quality.black_p1(bright_set) > 30 and quality.washed_out(bright_set) is None


def test_title_issues():
    assert quality.title_issues({}, {"title": "LIVE: The Captain's Last Words"})
    assert quality.title_issues({}, {"title": "Shark Tank Deal | BREAKING"})
    assert quality.title_issues({}, {"title": "Breaking down the Bermuda ending"}) == []  # normal words stay
    assert quality.title_issues({}, {"title": "Live Like Kobe Did"}) == []
    assert quality.title_issues({}, {"title": "The Captain's Last Words"}) == []
    assert quality.title_issues({}, {"title": "x", "title_flags": ["vague"]})[0][1].startswith("clip title")


def test_fan_only_flags_liked_but_unshared_videos(tmp_path):
    conn = analytics.connect(tmp_path / "a.db")
    now = time.time()
    for i, (views, likes) in enumerate([(10000, 300), (12000, 360), (9000, 270), (11000, 330), (10500, 315),
                                        (3000, 300), (4000, 40)]):
        analytics.record(conn, item_id=f"v{i}", channel="c", platform="youtube", hook=f"hook {i}",
                         posted_at=now - 86400 * 3, hours_after=48, views=views, likes=likes)
    fans = analytics.fan_only(conn, "c")
    assert [r["item_id"] for r in fans] == ["v5"]             # 3,000 views but a 10% like rate
    assert "FANS ONLY: 1 video" in analytics.weekly_report(conn, ["c"])
