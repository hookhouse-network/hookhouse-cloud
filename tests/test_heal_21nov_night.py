"""Heal round 21 Nov night: the gate holds found in the cloud memory (heal queue + weekly plan gate notes)."""
import numpy as np
import soundfile as sf

from engine import uniq


def test_clip_audio_never_has_dead_silence(tmp_path):
    """Stream Clips were held 3x: 'dead silence at 9.1s (2 gaps): sounds broken' (Kick's muted stretches)."""
    from engine import quality
    from engine.clipv3 import ROOM_TONE_AF
    from engine.media import ffmpeg
    sr = 48000
    t = np.arange(4 * sr) / sr
    a = (0.2 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    a[int(1.2 * sr):int(2.6 * sr)] = 0.0                      # 1.4 s of digital silence mid-clip
    src, out = tmp_path / "a.wav", tmp_path / "b.wav"
    sf.write(str(src), a, sr)
    assert quality._silences(src, 4.0)                          # the raw stream audio is "dead"
    ffmpeg.run(["-i", str(src), "-af", f"highpass=f=80,{ROOM_TONE_AF}", str(out)])
    assert quality._silences(out, 4.0) == []                    # room tone keeps it natural
    b, _ = sf.read(str(out), dtype="float32")
    quiet = b[int(1.5 * sr):int(2.3 * sr)]
    assert 0 < np.sqrt(np.mean(quiet ** 2)) < 0.004            # inaudible under speech (~-55 dBFS)


def test_freshest_title_avoids_near_repeats():
    """The Bloop long episode was held: 'title nearly repeats an earlier one' (one fixed template)."""
    past = {uniq._norm("Counting to 10 with Shiny Apples | Bloop & Friends Nursery Rhymes & Kids Songs")}
    options = ["Counting to 5 with Shiny Apples | Bloop & Friends Nursery Rhymes & Kids Songs",
               "How Many Soft Candy Canes? Count 1 to 5 with Bloop | Kids Songs for Toddlers"]
    assert uniq.freshest("bloop_and_friends", options, past=past)[0] == options[1]
    assert uniq.freshest("bloop_and_friends", options, past=set()) == options


def test_nasa_pictures_for_space_beats(monkeypatch):
    """P3b picture supply: real NASA pictures (public domain, credited) for space beats; third-party copyrighted
    items in NASA's library are skipped."""
    from engine import story
    from engine.media import visuals

    class Resp:
        def __init__(self, data):
            self.data = data

        def json(self):
            return self.data

    def get(url, params=None, timeout=None):
        if "search" in url:
            return Resp({"collection": {"items": [
                {"data": [{"nasa_id": "PIA1", "title": "Jupiter Great Red Spot", "center": "JPL",
                           "description": "Voyager view", "keywords": ["Jupiter"]}]},
                {"data": [{"nasa_id": "X2", "title": "Launch", "description": "Photo © Getty Images"}]}]}})
        return Resp({"collection": {"items": [{"href": "http://images-assets.nasa.gov/image/PIA1/PIA1~thumb.jpg"},
                                              {"href": "http://images-assets.nasa.gov/image/PIA1/PIA1~large.jpg"}]}})
    monkeypatch.setattr(visuals, "session", lambda: type("S", (), {"get": staticmethod(get)})())
    got = visuals.nasa_images("Jupiter storm", limit=3)
    assert len(got) == 1 and got[0].source == "nasa" and got[0].credit.startswith('"Jupiter Great Red Spot" (NASA')
    assert got[0].meta["url"].startswith("https://") and got[0].meta["url"].endswith("~large.jpg")
    assert story.SPACE_WORDS.search("Apollo rocket on the pad") and not story.SPACE_WORDS.search("NBA star dunks")


def test_wildlife_photos_check_the_licence_of_every_photo(monkeypatch):
    """P3b picture supply: real animal photos from iNaturalist via GBIF. GBIF's record licence filter lets through
    photos whose own licence is 'Copyright by the creator': each photo's licence is checked."""
    from engine.media import visuals
    calls = []

    class Resp:
        def __init__(self, data):
            self.data = data

        def json(self):
            return self.data

    def get(url, params=None, timeout=None):
        calls.append(url)
        if url.endswith("/species/search"):
            return Resp({"results": [{"nubKey": 5219243, "kingdom": "Animalia", "scientificName": "Vulpes vulpes"}]})
        media = [
            [{"license": "Copyright by the creator. See nabu.de", "identifier": "https://live.staticflickr.com/x.jpg"}],
            [{"license": "http://creativecommons.org/licenses/by-nc/4.0/",
              "identifier": "https://inaturalist-open-data.s3.amazonaws.com/photos/1/original.jpg"}],
            [{"license": "http://creativecommons.org/licenses/by/4.0/", "creator": "Ana",
              "identifier": "https://inaturalist-open-data.s3.amazonaws.com/photos/2/original.jpg"}],
            [{"license": "http://creativecommons.org/publicdomain/zero/1.0/", "creator": "Ben",
              "identifier": "https://inaturalist-open-data.s3.amazonaws.com/photos/3/original.jpg"}]]
        return Resp({"results": [{"key": k, "species": "Vulpes vulpes", "media": m} for k, m in enumerate(media)]})
    monkeypatch.setattr(visuals, "session", lambda: type("S", (), {"get": staticmethod(get)})())
    got = visuals.gbif_wildlife("red fox hunting in snow", limit=5)
    assert [v.license for v in got] == ["CC BY 4.0", "CC0"]                  # copyright + NC photos refused
    assert got[0].credit == "Photo: Ana (CC BY 4.0) via iNaturalist / GBIF"
    assert got[0].meta["url"].endswith("/photos/2/large.jpg")
    calls.clear()
    assert visuals.gbif_wildlife("old oil rig at sea") == [] and calls == []    # no animal named: no API call


def test_both_pace_passes_share_one_ceiling():
    """Story videos were held 'narration 139-148 wpm, target 180 (too slow)': the second pace pass capped at 1.12."""
    import inspect

    from engine import story
    assert abs(story.pace_speed(1.12, 180, 162) - 1.2444) < 1e-3                 # was cut back to 1.12 before
    assert story.pace_speed(1.2, 180, 150) == story.MAX_PACE_SPEED              # 1.44 -> the one ceiling
    assert story.pace_speed(1.0, 180, 150) == 1.2 and story.pace_speed(1.0, 150, 200) == 0.9
    src = inspect.getsource(story)
    assert "0.9, 1.12)" not in src                                              # no second, lower cap anywhere


def test_a_clip_never_borrows_another_clips_captions(tmp_path):
    """Hot Take HQ clip judged on another clip's words: srt_text fell back to the first .srt in the folder."""
    from engine import potential_gate as pg
    (tmp_path / "clip_01.srt").write_text("1\n00:00:00,100 --> 00:00:02,000\nCount the pens with me\n",
                                          encoding="utf-8")
    assert pg.srt_text(tmp_path, "clip_03") == ("", None)                      # its own words are unknown
    (tmp_path / "clip_03.srt").write_text("1\n00:00:00,300 --> 00:00:02,000\nHe walked out mid-show\n",
                                          encoding="utf-8")
    assert pg.srt_text(tmp_path, "clip_03")[0] == "He walked out mid-show"
    (tmp_path / "captions.srt").write_text("1\n00:00:00,200 --> 00:00:01,000\nStory words\n", encoding="utf-8")
    assert pg.srt_text(tmp_path, "video")[0] == "Story words"                 # a folder-wide file still works


STUCK = ("🛑 blocked: quality: score 86/100 (needs 100): dead silence at 3.1s (8 gap(s)): sounds broken, keep room "
         "tone; no captions file (search and sound-off viewers)")


def test_one_quality_finding_keeps_its_sub_issues():
    """The Stream Clips clip was never remade: '; ' inside the quality finding made it look unfixable."""
    from engine.content_gate import fixable_by_remake, split_problems
    probs = split_problems(STUCK.split("🛑 blocked: ", 1)[1])
    assert len(probs) == 1 and probs[0].startswith("quality:") and "no captions file" in probs[0]
    assert fixable_by_remake(probs)
    two = split_problems("names a protected franchise/character: avengers; quality: score 80/100: dull; dark")
    assert [p.split(":")[0] for p in two] == ["names a protected franchise/character", "quality"]
    assert not fixable_by_remake(split_problems("AI disclosure (ai_label) not set; quality: score 80/100"))


def test_an_all_blocked_video_is_remade_not_settled(monkeypatch):
    from engine import autopilot, publish_queue
    calls, settled = [], []
    monkeypatch.setattr(publish_queue, "queued", lambda *a, **k: [])
    monkeypatch.setattr(autopilot, "_redo_if_blocked", lambda s, it, why, log: calls.append(why) or True)
    monkeypatch.setattr(autopilot, "_update_state", lambda fn: settled.append(1))
    it = {"id": "1121_0500_stream_clips_short", "channel": "stream_clips", "status": "approved",
          "channel_name": "Stream Clips"}
    publish_queue._settle("s", it, [], [], [("youtube", STUCK)], [], None, lambda *_: None, lambda *_: None)
    assert calls == [STUCK] and settled == []                                  # remade, not dead-ended


def test_already_stuck_videos_are_rescued_once(monkeypatch, tmp_path):
    import json

    from engine import autopilot, publish
    it = {"id": "1121_0500_stream_clips_short", "channel": "stream_clips", "status": "approved", "made_at": 100.0}
    monkeypatch.setattr(autopilot, "items", lambda *a: [("s", it)])
    monkeypatch.setattr(autopilot, "_load", lambda: {"posted": {it["id"]: 200.0}})
    log = tmp_path / "publish_log.jsonl"
    log.write_text(json.dumps({"item_id": it["id"], "what": "BLOCKED by the content gate", "at": 150.0,
                               "result": {"error": STUCK}}) + "\n", encoding="utf-8")
    monkeypatch.setattr(publish, "LOG", log)
    calls = []
    monkeypatch.setattr(autopilot, "_redo_if_blocked", lambda s, x, why, log: calls.append((x["id"], why)) or True)
    assert autopilot._rescue_stuck(log=lambda *_: None) == 1 and calls == [(it["id"], STUCK)]
    it["youtube_id"] = "abc"                                                   # posted somewhere: never touched
    calls.clear()
    assert autopilot._rescue_stuck(log=lambda *_: None) == 0 and calls == []


def test_shot_rhythm_house_rule(tmp_path):
    """S9 Herk Edit Kit house rule: a story Short changes picture every 2-4 s; one shot held > 7 s is flagged."""
    from engine import quality
    from engine.media import ffmpeg

    def clip(name, colours):
        args, parts = [], []
        for i, (c, d) in enumerate(colours):
            args += ["-f", "lavfi", "-i", f"color={c}:s=320x568:d={d}:r=30"]
            parts.append(f"[{i}:v]")
        out = tmp_path / name
        ffmpeg.run([*args, "-filter_complex", "".join(parts) + f"concat=n={len(colours)}:v=1[v]", "-map", "[v]",
                    "-pix_fmt", "yuv420p", str(out)])
        return out
    slow = clip("slow.mp4", [("red", 10), ("blue", 2)])
    fast = clip("fast.mp4", [("red", 2), ("blue", 2), ("green", 2), ("yellow", 2), ("white", 2), ("purple", 2)])
    assert quality.rhythm_issues(slow, 12.0, "short") and "10 s" in quality.rhythm_issues(slow, 12.0, "short")[0][1]
    assert quality.rhythm_issues(fast, 12.0, "short") == []
    assert quality.rhythm_issues(slow, 12.0, "long") == []                    # Shorts only


def test_quiz_fits_the_short_length():
    """Brain Snack quiz: 10 questions = 60 s; the scorecard wants 8-45 s."""
    from engine.snack import ladder
    assert ladder.N_QUESTIONS == 7 and "7-question quiz" in ladder.QUIZ_PROMPT and "all 7" in ladder.QUIZ_PROMPT
