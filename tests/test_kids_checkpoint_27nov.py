"""27 Nov (P3 checkpoints): a stopped kids episode resumes from its kept plan (the AI planning call is not repeated,
same seed); a fresh plan is handed to on_plan before the slow render starts."""
import pytest

from engine import kids


class Stop(Exception):
    pass


def _stop_after_plan(monkeypatch):
    monkeypatch.setattr(kids, "use_layout", lambda *a, **k: None)
    monkeypatch.setattr(kids, "puppets_on", lambda: False)
    monkeypatch.setattr(kids, "qa", lambda *a, **k: (_ for _ in ()).throw(Stop()))      # stop before the render


def test_a_fresh_plan_is_kept_before_the_render(monkeypatch):
    _stop_after_plan(monkeypatch)
    monkeypatch.setattr(kids, "plan_episode", lambda brain, seed, topic, max_n=10: {"lines": [{"t": "one"}],
                                                                                    "count_to": 3, "object": "apple"})
    kept = []
    with pytest.raises(Stop):
        kids.make(None, {"id": "bloop_and_friends"}, seed=42, on_plan=kept.append)
    assert kept and kept[0]["seed"] == 42 and kept[0]["lines"] == [{"t": "one"}]


def test_a_kept_plan_skips_the_ai_call(monkeypatch):
    _stop_after_plan(monkeypatch)
    monkeypatch.setattr(kids, "plan_episode", lambda *a, **k: pytest.fail("the AI planning call must not repeat"))
    seen = {}
    monkeypatch.setattr(kids, "qa", lambda lines, n, rounds_needed=3: seen.update(lines=lines) or
                        (_ for _ in ()).throw(Stop()))
    with pytest.raises(Stop):
        kids.make(None, {"id": "bloop_and_friends"}, planned={"lines": [{"t": "kept"}], "count_to": 3,
                                                              "object": "apple", "seed": 7})
    assert seen["lines"] == [{"t": "kept"}]


def test_brain_snack_keeps_the_ai_words_when_the_render_stops(monkeypatch, tmp_path):
    from engine.snack import maker
    monkeypatch.setattr(maker, "ROOT", tmp_path)
    monkeypatch.setattr(maker, "load_history", lambda: [])

    def render(spec, out_dir, brain=None, channel=None, log=print):
        spec["quiz"] = spec.get("quiz") or {"q": "written by the AI"}
        raise Stop()
    monkeypatch.setattr(maker, "render_spec", render)
    kept = []
    with pytest.raises(Stop):
        maker.make(None, {"id": "brain_snack"}, fmt="ladder", topic=None, on_plan=lambda sp: kept.append(dict(sp)))
    assert kept[0]["format"] == "ladder" and "quiz" not in kept[0]      # before the render
    assert kept[-1]["quiz"] == {"q": "written by the AI"}               # the AI's words kept after the stop
    monkeypatch.setattr(maker, "choose_format", lambda *a, **k: pytest.fail("a kept spec is not re-chosen"))
    seen = {}
    monkeypatch.setattr(maker, "render_spec", lambda spec, *a, **k: seen.update(spec) or (_ for _ in ()).throw(Stop()))
    with pytest.raises(Stop):
        maker.make(None, {"id": "brain_snack"}, planned=kept[-1])
    assert seen["quiz"] == {"q": "written by the AI"}


def test_a_kept_plan_is_resumed_at_most_twice(monkeypatch, tmp_path):
    from engine import weekly
    monkeypatch.setattr(weekly, "CHECKPOINTS", tmp_path)
    item = {"id": "1127_0900_brain_snack_short", "channel": "brain_snack"}
    weekly.save_checkpoint(item, {"format": "ladder"})
    assert weekly.checkpoint(item) and weekly.checkpoint(item)
    assert weekly.checkpoint(item) is None


def test_a_footage_transcript_is_kept_for_the_next_try(monkeypatch, tmp_path):
    from engine import clips
    from engine.media.captions import Word
    monkeypatch.setattr(clips, "TRANSCRIPTS", tmp_path)
    assert clips.kept_words("kick:abc", "whole", 600.0) is None
    clips.keep_words("kick:abc", "whole", 600.0, [Word("hello", 1.0, 1.4)])
    got = clips.kept_words("kick:abc", "whole", 600.4)
    assert got and got[0].text == "hello" and got[0].start == 1.0
    assert clips.kept_words("kick:abc", "whole", 900.0) is None        # another length: transcribed fresh
    assert clips.kept_words("kick:abc", "hotspots7", 600.0) is None    # another way of transcribing


def test_saving_the_same_script_again_keeps_the_resume_count(monkeypatch, tmp_path):
    """28 Nov: the story maker re-saves the resumed script; that reset the count, so a script whose charts kept
    failing (Cosmos, 3 tries) was resumed for ever instead of written fresh on the third try."""
    from engine import weekly
    monkeypatch.setattr(weekly, "CHECKPOINTS", tmp_path)
    item = {"id": "1122_0500_cosmos_unboxed_short", "channel": "cosmos_unboxed"}
    weekly.save_checkpoint(item, {"beats": [1]})
    assert weekly.checkpoint(item)
    weekly.save_checkpoint(item, {"beats": [1]})          # the resumed try saves it again
    assert weekly.checkpoint(item)
    weekly.save_checkpoint(item, {"beats": [1]})
    assert weekly.checkpoint(item) is None                 # third try: a fresh script
    weekly.save_checkpoint(item, {"beats": [2]})           # a new script starts its own count
    assert weekly.checkpoint(item)
