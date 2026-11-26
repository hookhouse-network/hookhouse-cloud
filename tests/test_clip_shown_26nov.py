"""26 Nov (P7): the potential judge read only a clip's captions (starred swearing) and held every GTA clip for
caption_hook 2-3 ('replace the weak audio-only transcript with a visual hook'). The clip record now says what it shows."""
import json

from engine import clip_shown, potential_gate
from engine.clips import Word


def test_the_facts_name_layout_headline_flash_and_end_line():
    m = {"stream": True, "title": "Dom lands it", "teaser": [20.0, 1.5], "start": 100.0}
    words = [Word("NO", 120.2, 120.4), Word("WAY", 120.4, 120.7), Word("later", 125.0, 125.2)]
    s = clip_shown.facts(m, {"headline_box": True, "end_text": "Watch live: kick.com/x"}, words)
    assert "face cam on top" in s and '"Dom lands it"' in s and 'he says: "NO WAY"' in s and "kick.com/x" in s


def test_no_key_means_facts_only(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert clip_shown.frames(None, 30.0) == []


def test_the_judge_reads_shown_before_said(tmp_path):
    (tmp_path / "clip_01.srt").write_text("1\n00:00:00,200 --> 00:00:01,500\nNO WAY\n", encoding="utf-8")
    (tmp_path / "clips.json").write_text(json.dumps([{"file": "clip_01.mp4", "shown": "Layout: face cam on top."}]),
                                         encoding="utf-8")
    text = potential_gate.script_text({"out_dir": str(tmp_path), "file": "clip_01.mp4"}, {})
    assert text.startswith("SHOWN: Layout: face cam on top.\nSAID: ") and "NO WAY" in text


def test_the_title_writer_sees_the_frames():
    """26 Nov: headlines were generic ('Streamer reacts to risky landing'): the writer had only the transcript."""
    from engine import clips
    got = {}

    class Res:
        provider = "test"

    class Brain:
        def ask_json(self, task, prompt, system="", temperature=0.5):
            got["p"] = prompt
            return {"title": "Dom crashes the plane", "hook_options": ["Will he land it?"]}, Res()
    m = clips.whole_clip_moment(Brain(), [], 30.0, seen=["0.7s: a plane wing", "46.0s: mission failed screen"])
    assert "What the picture shows (frames, in order): 0.7s: a plane wing; 46.0s: mission failed screen" in got["p"]
    assert m[0]["whole_clip"] and clips.whole_clip_moment(Brain(), [], 30.0) and "picture shows" not in got["p"]


def test_the_title_writer_is_told_not_to_reveal_the_ending():
    """26 Nov: the first frame-written headline gave the crash away; the campaign gate held it as a spoiled payoff."""
    from engine import clips
    assert "never the outcome" in clips.WHOLE_PROMPT and "do not describe the ending" in clips.WHOLE_PROMPT


def test_the_brief_name_is_mandatory_in_clip_titles():
    """26 Nov: 4 of 4 GTA headlines ignored the brief's 'Dasgas Dom ...' pattern ('Motorbike ride leads to ...')."""
    from engine import clips
    camp = {"hook_ideas": ["Dasgas Dom reacts to ...", "Dasgas Dom finds a GTA 6 glitch", "Dasgas Dom fails ..."]}
    assert clips.brief_name(camp) == "Dasgas Dom"
    assert clips.brief_name({"hook_ideas": ["He reacts", "Watch this"]}) == "" and clips.brief_name(None) == ""
    got = {}

    class Res:
        provider = "test"

    class Brain:
        def __init__(self, title):
            self.title = title

        def ask_json(self, task, prompt, system="", temperature=0.5):
            got["p"] = prompt
            return {"title": self.title}, Res()
    m = clips.whole_clip_moment(Brain("Motorbike ride goes wrong"), [], 30.0, campaign=camp)
    assert 'MUST start with "Dasgas Dom"' in got["p"] and "no_brief_name" in m[0]["title_flags"]
    m = clips.whole_clip_moment(Brain("Dasgas Dom tries a motorbike jump"), [], 30.0, campaign=camp)
    assert "no_brief_name" not in (m[0].get("title_flags") or [])
