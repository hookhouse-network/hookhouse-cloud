"""23 Nov: in a week of videos, 9 of 9 beats the writer planned as an animated chart (map, depth dive, size scale,
compare, timeline) were overwritten by the storyboard: 4 became AI pictures, 4 word cards (they count against the
20% word-card limit), 1 a stock photo; none reached the screen. A chart beat now stays a chart (its shot prompt is
kept, so a chart that fails its checks is drawn instead), and a video may show up to three, each of its own type."""
from pathlib import Path

from engine import story, storyboard

CH = {"id": "deep_blue_files", "name": "Deep Blue Files", "language": "en", "style": {"ai_style": "photoreal"}}
DEPTH = {"type": "depth", "title": "Barreleye depth", "items": [{"label": "Hunting zone", "value": 2000,
                                                                 "text": "2,000 feet"}]}


class Brain:
    def __init__(self, types):
        self.types = types

    def ask_json(self, task, prompt, temperature=0.4):
        return {"bible": {"era": "deep ocean, today"},
                "shots": [{"i": k + 1, "see": f"shot {k + 1}", "cast": [], "type": t, "action": ""}
                          for k, t in enumerate(self.types)]}, None


def _script():
    return {"title": "Barreleye", "beats": [
        {"narration": "Meet the barreleye fish.", "visual": "ai"},
        {"narration": "It hunts 2,000 feet down.", "visual": "chart", "chart": DEPTH},
        {"narration": "Its eyes rotate upward.", "visual": "ai"},
        {"narration": "It was filmed alive in 2004.", "visual": "photo"}]}


def test_the_writers_chart_survives_the_storyboard():
    sc = _script()
    assert storyboard.plan(Brain(["scene", "number", "scene", "real"]), sc, CH, log=lambda *a: None)
    b = sc["beats"]
    assert b[1]["visual"] == "chart" and b[1]["chart"] == DEPTH
    assert b[1]["_prompt"]                                   # a failed chart is drawn from its own shot instead
    assert [b[0]["visual"], b[2]["visual"], b[3]["visual"]] == ["scene", "scene", "photo"]   # the rest as before


def test_up_to_three_charts_each_of_its_own_type(tmp_path, monkeypatch):
    from engine.media import html_scene
    made = []
    monkeypatch.setattr(html_scene, "chart_video", lambda ch, chart, size, s, out, **k: made.append(chart["type"]) or out)
    monkeypatch.setattr(html_scene, "check_chart", lambda chart, said: (chart, ""))
    used = set()

    def chart(kind):
        return {"visual": "chart", "narration": "n", "chart": {"type": kind, "items": []}}
    assert story._chart_visual(chart("compare"), 3.0, tmp_path, 0, used, (360, 640), CH)["source"] == "chart"
    assert story._chart_visual(chart("compare"), 3.0, tmp_path, 1, used, (360, 640), CH) is None   # same type twice
    assert story._chart_visual(chart("timeline"), 3.0, tmp_path, 2, used, (360, 640), CH) is not None
    assert story._chart_visual(chart("scale"), 3.0, tmp_path, 3, used, (360, 640), CH) is not None
    assert story._chart_visual(chart("depth"), 3.0, tmp_path, 4, used, (360, 640), CH) is None     # a fourth
    assert made == ["compare", "timeline", "scale"]


def test_the_writer_may_plan_up_to_three_charts():
    src = Path(story.__file__).read_text(encoding="utf-8")
    assert '"chart" up to 3 times' in src and '"chart" at most once' not in src
