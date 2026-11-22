"""23 Nov: Deep Blue Files 23 Nov was marked down for "one shot lasts 8 s" although its 17 beats (1-5 s) each had their
own picture: the cross-fade between two dark deep-sea pictures scores under the 0.2 cut threshold (at 0.1 the missed
cuts sit exactly on beat boundaries, 23.3 s and 30.7 s). Inside an over-long gap a weaker cut now counts too; a real
static shot (one picture, slow zoom) is still caught."""
from engine import quality


def test_a_weak_cut_inside_a_long_gap_counts(monkeypatch, tmp_path):
    strong = [3.2, 6.8, 10.5, 14.3, 19.5, 27.1, 34.7, 39.2, 41.8, 45.0, 52.0, 56.1, 59.1]   # the real 0.2 cuts
    weak = strong + [14.5, 15.0, 17.6, 23.3, 23.4, 30.7, 34.8, 48.2]                     # + the real 0.1 ones
    monkeypatch.setattr(quality, "cut_times", lambda v, threshold=0.3: strong if threshold >= 0.2 else weak)
    assert quality.longest_shot(tmp_path / "v.mp4", 60.0) == 7.0       # 45.0 -> 52.0 (not over 7 s: never rechecked)
    assert quality.rhythm_issues(tmp_path / "v.mp4", 60.0, "short") == []         # no false "8 s shot" any more
    monkeypatch.setattr(quality, "cut_times", lambda v, threshold=0.3: strong)        # nothing weaker found: as before
    assert quality.longest_shot(tmp_path / "v.mp4", 60.0) == 7.6


def test_weak_cuts_outside_long_gaps_and_at_their_edges_change_nothing(monkeypatch, tmp_path):
    strong = [3.0, 6.0, 9.0]
    weak = strong + [1.0, 4.5, 9.2, 16.8]          # 9.2 and 16.8 sit within 0.5 s of the long gap's ends
    monkeypatch.setattr(quality, "cut_times", lambda v, threshold=0.3: strong if threshold >= 0.2 else weak)
    assert quality.longest_shot(tmp_path / "v.mp4", 17.0) == 8.0                   # 9.0 -> 17.0: still one shot


def test_one_picture_with_a_slow_zoom_is_still_one_long_shot(tmp_path):
    from engine.media import ffmpeg
    still = tmp_path / "still.png"
    ffmpeg.run(["-f", "lavfi", "-i", "testsrc2=s=320x568:d=1", "-frames:v", "1", str(still)])
    out = tmp_path / "zoom.mp4"
    ffmpeg.run(["-loop", "1", "-i", str(still), "-vf",
                "zoompan=z='min(zoom+0.0008,1.25)':d=270:s=320x568:fps=30", "-t", "9", "-pix_fmt", "yuv420p", str(out)])
    assert quality.longest_shot(out, 9.0) >= 8.5
    assert quality.rhythm_issues(out, 9.0, "short")                                 # the house rule still fires
