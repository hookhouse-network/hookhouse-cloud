"""25 Nov (P7): the first GTA clips passed the campaign rules but the judge held them (hook 3.5, caption_hook 2.5:
nothing happens in the first 2 s; the explosion payoff only at the end). Stream clips now open with a 1.5 s flash of
the payoff, GTA's own subtitles (which still showed the muted swear words) are blurred, and captions sit clear of the
streamer's Kick badge."""
import numpy as np

from engine import clipv3


def _thumbs(start, dur, busy_at=None):
    out, rng = [], np.random.default_rng(1)
    for i in range(int(dur * 10)):
        t = start + i / 10
        base = np.full((36, 64), 100, np.float32)
        if busy_at and busy_at[0] <= t < busy_at[1]:
            base = rng.uniform(0, 255, (36, 64)).astype(np.float32)
        out.append((t, base))
    return out


def test_the_payoff_teaser_starts_just_before_the_loud_busy_moment():
    start, dur = 100.0, 30.0
    rms = np.full(int(dur * 10), 300.0)
    rms[200:215] = 6000.0                                  # the explosion + yelling at 20.0-21.5 s
    p0 = clipv3.payoff_start(rms, _thumbs(start, dur, (120.0, 121.5)), start, start + dur)
    assert p0 is not None and 119.0 <= p0 <= 120.0


def test_no_teaser_for_a_flat_or_short_clip():
    flat = np.full(300, 500.0)
    assert clipv3.payoff_start(flat, _thumbs(0, 30), 0, 30) is None
    assert clipv3.payoff_start(np.full(80, 500.0), _thumbs(0, 8), 0, 8) is None


def test_burned_in_subtitles_are_blurred_and_a_clean_picture_is_left_alone():
    game = np.full((1280, 1080, 3), 60, np.uint8)
    assert clipv3.blur_burned_subtitles(game) is game          # nothing to hide
    sub = game.copy()
    sub[1150:1175, 300:780] = 255                               # a white subtitle line, bottom middle
    out = clipv3.blur_burned_subtitles(sub)
    assert out[1150:1175, 300:780].mean() < 230 and out[:1000].mean() == sub[:1000].mean()


def test_stream_captions_sit_below_the_kick_badge():
    assert clipv3.STREAM_CAPTION_MIN_Y >= clipv3.CAM_PANE_H + 400


def test_the_teaser_starts_on_the_streamers_line_near_the_peak():
    """25 Nov: a remake was held for 'speech starts at 1.6s (the hook must land within 1.0s)': the flash had no words."""
    from engine.clips import Word
    start, dur = 100.0, 30.0
    rms = np.full(int(dur * 10), 300.0)
    rms[200:215] = 6000.0
    words = [Word("NO", 119.4, 119.7), Word("WAY", 119.7, 120.0), Word("later", 125.0, 125.3)]
    p0 = clipv3.payoff_start(rms, _thumbs(start, dur, (120.0, 121.5)), start, start + dur, words=words)
    assert abs(p0 - 119.2) < 0.01                  # 0.2 s before "NO"


def test_the_captions_file_starts_with_the_flash_words(tmp_path):
    from engine.clips import Word, write_clip_srt
    words = [Word("hello", 1.0, 1.4), Word("there", 1.4, 1.8), Word("BOOM", 20.2, 20.6), Word("wow", 20.6, 21.0)]
    p = write_clip_srt(words, 0.0, 30.0, tmp_path / "c.srt", offset=1.5, teaser=[20.0, 1.5])
    rows = p.read_text(encoding="utf-8").split("\n\n")
    assert rows[0].startswith("1\n00:00:00,200 --> ") and "BOOM wow" in rows[0]
    assert rows[1].startswith("2\n00:00:02,500") and "hello there" in rows[1]


def test_words_whisper_already_starred_are_muted_too():
    """25 Nov: a GTA remake was held for 'an unmuted racial slur (n****)': Whisper had starred it itself."""
    from engine import profanity
    from engine.clips import Word
    assert profanity.is_bad("n****") and profanity.is_bad("F***!") and profanity.is_bad("s***,")
    assert not profanity.is_bad("no") and not profanity.is_bad("5*") and not profanity.is_bad("damn")
    words, spans = profanity.clean([Word("you", 1.0, 1.2), Word("n****.", 1.2, 1.6)])
    assert spans and spans[0][0] < 1.2 < spans[0][1] and words[1].text.startswith("n*")


def test_a_silent_payoff_flashes_the_reaction_line_after_it():
    """26 Nov: Dom was quiet across the explosion (17.5-27.9 s); the remake was held for 'speech starts at 2.4s'."""
    from engine.clips import Word
    start, dur = 0.0, 31.0
    rms = np.full(int(dur * 10), 300.0)
    rms[200:215] = 6000.0                                   # the explosion at 20.0-21.5 s, nobody talks
    words = [Word("Try", 16.0, 16.3), Word("Now", 27.9, 28.1), Word("that", 28.1, 28.3), Word("was", 28.3, 28.5)]
    p0 = clipv3.payoff_start(rms, _thumbs(start, dur, (20.0, 21.5)), start, start + dur, words=words)
    assert abs(p0 - 27.7) < 0.01
