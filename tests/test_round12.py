"""Round 12 (13 Nov): ideas taken from reviewing SupoClip, written our own way and measured on our own footage.
- Clip openings: banter, one-word answers, mid-sentence starts and "But..." lines are skipped or ranked lower.
- Grounding: the model's times are re-anchored on the words it quoted.
- Moving pictures keep their pauses (a cut would make gameplay jump); stream clips get webcam-on-top layout."""
import json

import cv2
import numpy as np

from engine import clips
from engine import clipv3 as v
from engine.clips import Word


def W(text, n0=0.0, step=0.4):
    """Words from a sentence string, 0.4 s each, starting at n0."""
    out, t = [], n0
    for tok in text.split():
        out.append(Word(tok, round(t, 2), round(t + step - 0.05, 2)))
        t += step
    return out


POINT = "The Navy paid for my whole degree and I never paid a single dollar back."


def test_opening_skips_banter_and_one_word_answers():
    ws = W("No. No? Ah! " + POINT + " " + POINT)
    r = clips.review_opening(ws, 0.0, ws[-1].end, 5)
    assert r["issue"] == "fragment" and r["start"] == ws[3].start and r["skipped"] == "No. No? Ah!"
    ws = W("Catharsis. " + POINT + " " + POINT)
    assert clips.review_opening(ws, 0.0, ws[-1].end, 5)["start"] == ws[1].start


def test_opening_keeps_a_short_hook_and_clean_starts():
    ws = W("Here's why. " + POINT)
    assert clips.review_opening(ws, 0.0, ws[-1].end, 3)["issue"] is None
    ws = W(POINT + " " + POINT)
    assert clips.review_opening(ws, 0.0, ws[-1].end, 3) == {"start": None, "issue": None, "penalise": False,
                                                              "skipped": ""}


def test_dangling_lines_are_skipped_when_short_and_penalised_when_long():
    ws = W("But that's it. " + POINT + " " + POINT)
    r = clips.review_opening(ws, 0.0, ws[-1].end, 5)
    assert r["issue"] == "dangling" and r["start"] == ws[3].start and not r["penalise"]
    ws = W("So that's why the Navy paid for my whole degree and the housing too. " + POINT)
    r = clips.review_opening(ws, 0.0, ws[-1].end, 3)
    assert r["issue"] == "dangling" and r["start"] is None and r["penalise"]


def test_mid_sentence_start_moves_to_the_next_sentence():
    ws = W("Last year I finally told my boss the truth. " + POINT + " " + POINT)
    r = clips.review_opening(ws, ws[4].start, ws[-1].end, 5)              # clip starts at "told"
    assert r["issue"] == "mid-sentence" and r["start"] == ws[9].start
    assert r["skipped"] == "told my boss the truth."


def test_skipping_never_makes_a_clip_too_short():
    ws = W("No. No? Ah! " + POINT)
    r = clips.review_opening(ws, 0.0, ws[-1].end, 6.5)                    # only ~6.4 s would remain
    assert r["start"] is None and r["penalise"]


def test_ground_reanchors_on_the_quoted_words():
    ws = W(" ".join([POINT] * 12))                                         # 15 words a sentence, 6 s each
    m = {"first_words": "The Navy paid for my", "last_words": "a single dollar back."}
    s, e, grounded = clips.ground(ws, m, 41.0, 66.0)                      # model's times a little off
    assert grounded is True and s == 42.0 and abs(e - 65.95) < 0.01
    s, e, grounded = clips.ground(ws, {"first_words": "completely different words here"}, 41.0, 66.0)
    assert grounded is False and (s, e) == (41.0, 66.0)


def test_pick_moments_ranks_weak_openings_lower():
    ws = W(" ".join([POINT] * 10))

    class Brain:
        def ask_json(self, *a, **k):
            base = {"scores": {k2: 8 for k2 in clips.WEIGHTS}, "hook_options": ["x"]}
            moms = [dict(base, start=12.0, end=36.0, first_words="The Navy paid for my", id="clean"),
                    dict(base, start=48.0, end=72.0, first_words="nobody ever said these words", id="made_up")]
            return {"moments": moms}, type("R", (), {"provider": "test"})()
    out = clips.pick_moments(Brain(), ws, keep=2, min_len=20, max_len=55)
    by = {m["id"]: m for m in out}
    assert by["clean"]["virality"] == 80 and "opening" not in by["clean"]
    assert by["made_up"]["virality"] == 70 and by["made_up"]["opening"]["grounded"] is False
    assert out[0]["id"] == "clean"


def _thumbs(kind, n=40, seed=1):
    rng = np.random.default_rng(seed)
    base = rng.uniform(0, 255, (36, 64)).astype(np.float32)
    out = []
    for i in range(n):
        if kind == "still":                     # a podcast camera: compression noise only
            f = base + rng.normal(0, 0.4, base.shape)
        else:                                   # a game camera: the picture slides every sample
            f = np.roll(base, i * 3, axis=1)
        out.append((i / 10, f.astype(np.float32)))
    return out


def test_moving_picture_uses_the_measured_threshold():
    assert not v.moving_picture(_thumbs("still")) and v.moving_picture(_thumbs("moving"))
    assert v.MOVING_MEDIAN == 1.0                                          # measured 13 Nov: 0.30 vs 1.39+


def _scene(face, kind="moving", share=0.9, n=40, extra=True):
    rng = np.random.default_rng(3)
    faces = []
    for i in range(n):
        fs = [face] if i < share * n else []
        if extra:                               # faces inside the game wander around
            fs.append((float(rng.uniform(0.3, 0.7)), float(rng.uniform(0.2, 0.8)), 0.06, 0.12, 0.4))
        faces.append((i / 10, fs))
    return v.Scene([], (1920, 1080), faces, _thumbs(kind, n))


def test_find_webcam_needs_a_small_steady_side_face_over_a_moving_game():
    cam = (0.91, 0.10, 0.035, 0.086, 0.088)
    found = v.find_webcam(_scene(cam))
    assert found and abs(found["face"][0] - 0.91) < 0.01 and found["share"] >= 0.9
    assert v.find_webcam(_scene(cam, kind="still")) is None                # a studio: the middle doesn't move
    assert v.find_webcam(_scene((0.68, 0.31, 0.15, 0.385, 0.3))) is None   # a normal interview face (too big)
    assert v.find_webcam(_scene((0.5, 0.1, 0.035, 0.086, 0.09))) is None   # not at the side
    assert v.find_webcam(_scene(cam, share=0.3)) is None                   # comes and goes


def _stream_video(path, border: bool):
    """640x360, 3 s at 10 fps: a changing 'game' and a still 'webcam' at x 460-630, y 10-110."""
    rng = np.random.default_rng(5)
    cam = rng.integers(60, 200, (100, 170, 3), dtype=np.uint8)
    cam = cv2.GaussianBlur(cam, (0, 0), 3)
    vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 10, (640, 360))
    for i in range(30):
        game = rng.integers(0, 255, (45, 80, 3), dtype=np.uint8)
        frame = cv2.resize(game, (640, 360), interpolation=cv2.INTER_NEAREST)
        noise = rng.normal(0, 2, cam.shape)
        frame[10:110, 460:630] = np.clip(cam + noise, 0, 255).astype(np.uint8)
        if border:
            cv2.rectangle(frame, (459, 9), (630, 110), (255, 255, 255), 2)
        vw.write(frame)
    vw.release()


def test_webcam_rect_finds_the_inset(tmp_path):
    face = (545 / 640, 55 / 360, 0.04, 0.09, 50 / 360)
    for border in (True, False):
        p = tmp_path / f"s{border}.mp4"
        _stream_video(p, border)
        rect, found = v.webcam_rect(p, 0.0, 2.9, face, (640, 360))
        assert found, border
        for got, want in zip(rect, (460, 10, 630, 110)):
            assert abs(got - want) <= 6, (border, rect)


def test_stream_crops_fit_the_panes_and_dodge_the_webcam():
    cam, game = v.stream_crops((1422, 24, 1893, 285), (0.911, 0.099, 0.035, 0.086, 0.088), (1920, 1080))
    assert abs(cam[2] / cam[3] - 1080 / 640) < 0.01 and abs(game[2] / game[3] - 1080 / 1280) < 0.01
    assert 1422 <= cam[0] and cam[0] + cam[2] <= 1893 and 24 <= cam[1] and cam[1] + cam[3] <= 285
    assert game[0] + game[2] <= 1422 and game[3] == 1080                   # the game pane leaves the webcam out
    cam, game = v.stream_crops((0, 756, 576, 1080), (0.15, 0.85, 0.05, 0.11, 0.82), (1920, 1080))
    assert game[0] >= 576 and game[0] - (1920 - game[2]) / 2 <= 0.12 * 1920 + 1


def test_stream_captions_sit_under_the_seam(tmp_path):
    ws = [Word("clutch", 0.0, 0.4), Word("moment", 0.4, 0.9)]
    text = v.build_captions(ws, [{"t0": 0.0, "t1": 2.0, "layout": "S", "speaker": 0}], tmp_path / "c.ass").read_text(
        encoding="utf-8")
    assert f"\\pos(540,{v.CAM_PANE_H + 210})" in text and v.STREAM_CAPTION_Y == 850
    plan = json.dumps({"seam": v.CAM_PANE_H, "game": v.GAME_PANE_H})
    assert json.loads(plan)["game"] == 1280
