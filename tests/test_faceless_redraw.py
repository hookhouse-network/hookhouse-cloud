"""24 Nov, Cricket Ke Kisse: 4 of 13 drawn scenes showed a face (sports rule: no real likeness), each became a word card
at once, and the quality gate held the video for "4/13 shots are word cards". One redraw with the faces hidden first."""
from engine import story


def test_a_face_gets_one_faceless_redraw(monkeypatch):
    asked = []
    monkeypatch.setattr("engine.storyboard.scene",
                        lambda beat, era, size, log=print, i=0, tries=3: asked.append((beat["_prompt"], tries)) or
                        {"kind": "image", "path": "new.jpg", "source": "ai_scene_hf"})
    monkeypatch.setattr(story, "_big_face", lambda path: False)
    got = story.faceless_redraw({"_prompt": "a bowler mid-delivery at Eden Gardens", "_era": "1984"}, (1080, 1920))
    assert got["path"] == "new.jpg"
    assert asked == [(f"a bowler mid-delivery at Eden Gardens{story.NO_FACE_SUFFIX}", 1)]


def test_still_a_face_or_no_picture_means_no_redraw(monkeypatch):
    monkeypatch.setattr("engine.storyboard.scene", lambda *a, **k: {"kind": "image", "path": "new.jpg"})
    monkeypatch.setattr(story, "_big_face", lambda path: True)
    assert story.faceless_redraw({"_prompt": "a batsman"}, (1080, 1920)) is None
    monkeypatch.setattr("engine.storyboard.scene", lambda *a, **k: None)
    assert story.faceless_redraw({"_prompt": "a batsman"}, (1080, 1920)) is None
    assert story.faceless_redraw({"narration": "no prompt"}, (1080, 1920)) is None
