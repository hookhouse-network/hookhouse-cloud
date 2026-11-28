"""28 Nov (P3b data story): when the free pictures are used up, a channel allowed to (data_story: true, settings
switch on) writes its Short with charts on most beats; the renderer then allows up to DATA_CHARTS_MAX charts and a
repeated type. Off by default; other channels keep waiting for pictures."""
from engine import story, storyboard


def _switch(monkeypatch, on="on", blocked=True):
    monkeypatch.setattr("engine.config.settings", lambda: {"data_story": on})
    monkeypatch.setattr(storyboard, "images_blocked", lambda: blocked)


def test_data_story_needs_the_channel_the_switch_and_no_pictures(monkeypatch):
    _switch(monkeypatch)
    assert story.data_story_on({"data_story": True})
    assert not story.data_story_on({})                                   # channel not allowed
    _switch(monkeypatch, on="off")
    assert not story.data_story_on({"data_story": True})                 # switch off (the default)
    _switch(monkeypatch, blocked=False)
    assert not story.data_story_on({"data_story": True})                 # pictures available: normal video


def test_the_renderer_allows_more_charts_and_repeats_in_a_data_story(monkeypatch, tmp_path):
    from engine.media import html_scene
    monkeypatch.setattr(html_scene, "check_chart", lambda chart, said: (chart, ""))
    monkeypatch.setattr(html_scene, "chart_video", lambda ch, chart, size, s, out: out)
    beat = {"chart": {"type": "compare", "items": []}, "narration": "x"}
    normal, data = set(), {story.DATA_MARK}
    got = [story._chart_visual(beat, 3.0, tmp_path, i, normal, (1080, 1920), {"id": "c"}) for i in range(3)]
    assert got[0] and got[1] is None                                     # normal: one chart per type
    got = [story._chart_visual(beat, 3.0, tmp_path, i, data, (1080, 1920), {"id": "c"}) for i in range(10)]
    assert sum(1 for g in got if g) == story.DATA_CHARTS_MAX             # data story: repeats, up to the cap
    assert all(g["source"] == "chart" for g in got if g)                 # charts are not word cards


def test_the_writer_rule_states_rules_only():
    r = story.DATA_STORY_RULE
    assert "chart" in r and "at least 9" in r and "Nov" not in r   # prompt text: rules, no history


def test_scheduler_lets_a_data_story_channel_through(monkeypatch):
    from engine.cloud import runner
    monkeypatch.setattr("engine.config.settings", lambda: {"data_story": "on"})
    monkeypatch.setattr("engine.config.channel", lambda cid: {"data_story": cid == "cosmos_unboxed"})
    assert runner._data_story("cosmos_unboxed") and not runner._data_story("itihaas_ke_raaz")
    monkeypatch.setattr("engine.config.settings", lambda: {"data_story": "off"})
    assert not runner._data_story("cosmos_unboxed")


def test_a_scale_charts_named_unit_and_number_words_count_as_said():
    from engine.media import html_scene as hs
    chart = {"type": "scale", "items": [{"label": "Sun", "value": 1, "text": "1x"},
                                        {"label": "Sirius", "value": 2, "text": "2x"}]}
    ok, why = hs.check_chart(chart, "Sirius is about twice as wide as the Sun.")
    assert ok and not why
    bad, why = hs.check_chart(chart, "First, Sirius, shining bright.")       # the Sun not named, 2 never said
    assert bad is None and "never said" in why
    assert hs.check_chart({"type": "compare", "items": [{"label": "A", "value": 1, "text": "1"},
                                                        {"label": "B", "value": 3, "text": "3"}]},
                          "A and B: three.")[0] is None                       # the unit rule is for scale only


def test_digits_inside_a_spoken_name_are_part_of_the_name():
    from engine.media import html_scene as hs
    chart = {"type": "scale", "items": [{"label": "Sun", "value": 1, "text": "1x"},
                                        {"label": "Stephenson 2-18", "value": 50, "text": "50x"}]}
    ok, _ = hs.check_chart(chart, "Stephenson 2-18 is about 50 times wider than the Sun.")
    assert ok
    assert hs.check_chart(chart, "This giant is about 50 times wider than the Sun.")[0] is None   # name not said


def test_numbers_said_in_words_count_as_said():
    from engine.media import html_scene as hs
    s = hs._spoken("Mount Everest rises five and a half miles; the blast was fifteen kilotons, "
                   "about three thousand metres down, twenty-one times, two point five billion years.")
    for n in (5.5, 15, 3000, 21, 2.5e9):
        assert n in s, n
    chart = {"type": "compare", "items": [{"label": "Hiroshima", "value": 15, "text": "15 kilotons"},
                                          {"label": "Tsar Bomba", "value": 50000, "text": "50,000 kilotons"}]}
    assert hs.check_chart(chart, "Hiroshima was fifteen kilotons; Tsar Bomba fifty thousand.")[0]
    assert hs.check_chart(chart, "Hiroshima was big; Tsar Bomba was bigger.")[0] is None


def test_failing_charts_go_back_to_the_writer_before_drawing():
    from engine import story

    class Brain:
        def __init__(self):
            self.calls = 0

        def ask_json(self, task, prompt, temperature=0.4):
            self.calls += 1
            assert "Asteroid" in prompt and "never said" in prompt
            return {"beats": [{"i": 1, "narration": "The asteroid was 6 miles wide, Everest is 5.5 miles tall."}]}, None
    script = {"beats": [
        {"narration": "A rock fell.", "visual": "photo"},
        {"narration": "It was huge.", "visual": "chart", "chart": {"type": "scale", "items": [
            {"label": "Everest", "value": 5.5, "text": "5.5 miles"}, {"label": "Asteroid", "value": 6, "text": "6 miles"}]}}]}
    assert story.chart_problems(script)
    b = Brain()
    out = story.repair_charts(b, script, log=lambda *a: None)
    assert b.calls == 1 and story.chart_problems(out) == []
    assert "6 miles" in out["beats"][1]["narration"]


def test_two_date_timelines_are_fine():
    from engine.media import html_scene as hs
    ok, _ = hs.check_chart({"type": "timeline", "items": [{"label": "1985", "text": "found"},
                                                         {"label": "2024", "text": "today"}]}, "Found in 1985; in 2024 it rests.")
    assert ok


def test_a_resumed_data_story_is_repaired_too():
    import inspect
    from engine import story
    src = inspect.getsource(story.make)
    assert 'script.get("data_story")' in src and "repair_charts(brain, script, log)" in src
