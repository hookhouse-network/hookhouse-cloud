"""22 Nov (Brain Snack, the best channel, held by the potential judge since 21 Nov): the openings and the remake path.
- A physics game overwrote the item's topic with its own title (twice: the kept planned topic too), and every remake got
  that title + the angle + the judge's notes about the previous, different format as its theme: a food quiz came out
  as "Venus vs. Birthday: Food Edition" with a hook copied from the judge's example (clarity 4/10).
- The quiz took a random category AND the idea; the first ~3 s of a quiz were an empty backdrop; multiply opened with a
  small "1 bounce = 2 balls" for 1.2 s (hook 4-6/10).
- Physics formats had 3 fixed titles each, so they soon "nearly repeat an earlier one" (0.85 rule)."""
import numpy as np
import pytest

from engine import uniq, weekly
from engine.snack import ladder, maker, multiply

VENUS = "On Venus, your birthday comes around before the day is even over"


def test_snack_theme_is_the_planned_idea_never_the_judges_notes():
    item = {"topic": "1 bounce = 2 balls inside a blob (wait for the reveal) 🧠", "planned_topic": VENUS,
            "angle": "a day on Venus is longer than its year", "status": "redo",
            "gate_note": "potential: below 8/10 on hook 4. Fix: e.g. 'Did you know a day on Venus is longer?'"}
    theme = weekly.snack_theme(item)
    assert theme.startswith(VENUS) and "(angle: a day on Venus" in theme
    assert "quality check" not in theme and "potential" not in theme and "1 bounce" not in theme
    item["note"] = "make it about Mars"                                  # the owner's own change request stays
    assert weekly.snack_theme(item).endswith("The owner asked for this change: make it about Mars")
    assert weekly.snack_theme({"topic": "Octopus hearts"}) == "Octopus hearts"


def test_make_item_keeps_the_planned_idea_once(monkeypatch, tmp_path):
    monkeypatch.setattr("engine.config.channel", lambda cid: {"id": cid, "name": "Brain Snack", "type": "brainrot"})
    monkeypatch.setattr(weekly, "clip_slot", lambda ch, it: False)
    monkeypatch.setattr("engine.training_data.record", lambda it: None)
    seen, results = [], iter([{"used_topic": False, "title": "Which try reaches the center? 😭"},
                              {"used_topic": False, "title": "1 bounce = 2 balls inside a blob 🧠"},
                              {"used_topic": True, "title": "Space quiz 🧠"}])

    def fake_make(brain, ch, topic=None, memory=None, log=print, **_kw):
        seen.append(topic)
        return tmp_path, next(results)
    monkeypatch.setattr(maker, "make", fake_make)
    item = {"id": "s1", "channel": "brain_snack", "kind": "short", "topic": VENUS, "angle": "A", "status": "planned"}
    weekly.make_item({"items": [item]}, item, brain=object(), log=lambda *a: None)
    assert item["planned_topic"] == VENUS and item["topic"].startswith("Which try")
    item.update(status="redo", gate_note="potential: below 8/10 on hook 4 (readfast word flash too fast)")
    weekly.make_item({"items": [item]}, item, brain=object(), log=lambda *a: None)
    assert item["planned_topic"] == VENUS and item["topic"].startswith("1 bounce")       # kept once, not overwritten
    weekly.make_item({"items": [item]}, item, brain=object(), log=lambda *a: None)
    assert item["topic"] == VENUS                                        # a quiz made from the idea shows the idea
    assert seen == [f"{VENUS} (angle: A)"] * 3                           # never a physics title or the judge's notes


def test_a_planned_idea_picks_its_quiz_category():
    assert ladder.category_for(VENUS) == "space"
    assert ladder.category_for("Butter vs Heavy Cream: Which whips faster into Thanksgiving pie topping?") == "food"
    assert ladder.category_for("The Year Without a Summer: 1816 When Snow Ruined July Crops") == "science"
    assert ladder.category_for("Why octopuses have three hearts") == "ocean"
    assert ladder.category_for("Black Friday camping outside a store or a loading screen?") is None
    assert ladder.category_for(None) is None
    assert set(ladder.CATEGORY_WORDS) == set(ladder.CATEGORIES)          # every category can be matched


def test_an_idea_no_quiz_carries_goes_to_a_fact_video(monkeypatch):
    monkeypatch.setattr(maker, "ready_formats", lambda: set(maker.READY))
    odd = "Black Friday camping outside a store or a loading screen?"
    assert {maker.choose_format([], made=["spiral"], topic=odd) for _ in range(40)} == {"readfast"}
    assert {maker.choose_format([], made=["spiral"], topic=VENUS) for _ in range(80)} == {"ladder", "readfast"}


def _fake_make_env(monkeypatch, tmp_path, captured):
    monkeypatch.setattr(maker, "ROOT", tmp_path)
    monkeypatch.setattr(maker, "HISTORY", tmp_path / "hist.json")
    monkeypatch.setattr(maker.ffmpeg, "duration", lambda p: 30.0)
    monkeypatch.setattr(uniq, "used_titles", lambda cid: set())
    monkeypatch.setattr("engine.weekly.past_topics", lambda cid: [])

    def fake_render(spec, out_dir, brain=None, channel=None, log=print):
        captured.append(dict(spec))
        spec.setdefault("quiz", {"hook": "Only 1% get all 7. Ready?", "title_options": ["Space quiz: 7 levels 🧠"],
                                 "questions": [{"q": "Which planet is hottest?", "a": "Venus"}]})
        (out_dir / "video.mp4").write_bytes(b"x")
        return {"total": 30.0, "ai_voice": True}
    monkeypatch.setattr(maker, "render_spec", fake_render)


def test_the_quiz_is_about_the_ideas_category(monkeypatch, tmp_path):
    captured = []
    _fake_make_env(monkeypatch, tmp_path, captured)
    ch = {"id": "brain_snack", "name": "Brain Snack", "hashtags": ["#shorts"]}
    _out, meta = maker.make(object(), ch, topic=VENUS, fmt="ladder", log=lambda *a: None, seed=5)
    assert captured[0]["category"] == "space" and captured[0]["topic"] == VENUS and meta["used_topic"] is True
    assert meta["hook_text"] == "Only 1% get all 7. Ready?"              # what the viewer meets, not the title
    _out, meta = maker.make(object(), ch, topic="Black Friday camping or a loading screen?", fmt="ladder",
                            log=lambda *a: None, seed=6)
    assert "topic" not in captured[1] and meta["used_topic"] is False   # quiz by its own category; idea kept


def test_the_judge_reads_what_is_on_screen_at_0_00():
    assert maker.screen_hook({"format": "spiral", "rule": "speed"}).endswith("Which try reaches the center?")
    assert maker.screen_hook({"format": "multiply", "shape": "heart"}) == "1 BOUNCE = 2 BALLS Can it fill the heart?"
    assert maker.screen_hook({"format": "versus", "pair": "Lava|Ice"}) == "WHO WINS? Lava or Ice? Comment now"
    assert maker.screen_hook({"format": "ladder", "quiz": {"hook": "Can you climb all 7?"}}) == "Can you climb all 7?"
    assert maker.screen_hook({"format": "readfast"}) == "READ IT IF YOU CAN"
    assert maker.screen_hook({"format": "colorsort"}) == "Watch it sort itself"
    assert multiply.hook_lines({"shape": "bolt"}) == ("1 BOUNCE = 2 BALLS", "Can it fill the lightning bolt?")
    assert multiply.hook_lines({"shape": "letter", "letter": "B"})[1] == "Can it fill the letter B?"
    shown = maker.describe({"format": "multiply", "shape": "heart"}, {"total": 18, "t_fill": 12.4, "balls": 2048})
    assert shown.startswith('0:00 Big words on screen: "1 BOUNCE = 2 BALLS" and "Can it fill the heart?"')
    quiz = {"format": "ladder", "category": "space",
            "quiz": {"hook": "Only 1% get all 7. Ready?", "questions": [{"q": "Which planet is hottest?"}]}}
    assert maker.describe(quiz, {"total": 40}).startswith(
        '0:00 The first question card ("Which planet is hottest?") is already on screen while a voice dares you')


class Brain:
    def __init__(self, titles):
        self.titles, self.prompts = titles, []

    def ask_json(self, role, prompt, temperature=0.0):
        self.prompts.append(prompt)
        return {"titles": self.titles}, None


def test_physics_titles_are_written_for_the_video_and_never_near_repeats(monkeypatch):
    past = {uniq._norm("1 bounce = 2 balls inside a blob (wait for the reveal) 🧠")}
    monkeypatch.setattr(uniq, "used_titles", lambda cid: set(past))
    monkeypatch.setattr("engine.weekly.past_topics", lambda cid: [])
    brain = Brain(["Can one ball fill a whole heart? 💗", "Super Mario fills the heart 🍄", "x",
                   "Guess the second it hits 100% 👇", "Can one ball fill a whole heart? 💗"])
    spec = {"format": "multiply", "shape": "heart"}
    got = maker.ai_titles(brain, spec, "0:00 Big words ...", "brain_snack")
    assert got == ["Can one ball fill a whole heart? 💗", "Guess the second it hits 100% 👇"]   # franchise/short/dupe out
    assert "1 bounce 2 balls inside a blob wait for the reveal" in brain.prompts[0]           # told what is taken
    order = maker.order_titles("brain_snack", got + maker.titles_for(spec))
    assert order[:2] == got                                              # the writer's order among clearly new ones
    assert order.index("1 bounce = 2 balls inside a heart (wait for the reveal) 🧠") > 1     # a 0.9 match goes last
    assert maker.ai_titles(brain, {"format": "readfast"}, "", "brain_snack") == []          # fact/quiz: own titles
    assert maker.ai_titles(None, spec, "", "brain_snack") == []

    class Down:
        def ask_json(self, *a, **k):
            raise TimeoutError("busy")
    assert maker.ai_titles(Down(), spec, "", "brain_snack", log=lambda *a: None) == []        # fixed titles then
    scores = uniq.repeat_scores("brain_snack", ["1 bounce = 2 balls inside a heart (wait for the reveal)"])
    assert list(scores.values())[0] >= 0.85


class Frames:
    def __init__(self):
        self.frames = []

    def write(self, f):
        self.frames.append(f.copy())


def test_the_first_quiz_card_is_on_screen_from_the_start(monkeypatch, tmp_path):
    monkeypatch.setattr(ladder, "_voice_line", lambda text, path, voice: (np.zeros(4800, np.float32), 0.6))
    quiz = {"category": "space", "hook": "Only 1% get all 2. Ready?",
            "questions": [{"q": "Which planet is hottest?", "a": "Venus"}, {"q": "Closest star?", "a": "The Sun"}]}
    w = Frames()
    info = ladder.render({"seed": 3}, quiz, {"id": "af_bella"}, tmp_path, w, fps=5, log=lambda *a: None)
    first = info["items"][0]
    assert first["start"] == 0.0 and first["voice_at"] > 1.0              # card first, its voice after the dare
    assert info["cover_at"] == pytest.approx(first["voice_at"] + 0.6)
    assert w.frames[0][650, 420].min() > 240 and w.frames[3][650, 420].min() > 240   # whole white card from frame 0
    assert info["items"][1]["start"] == info["items"][1]["voice_at"]
