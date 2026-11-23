"""24 Nov: three held videos for today (Cosmos, Brain Snack, Clutch Tales) were judged 'obviously AI-made' (human_feel
5, bar 6). Counting phrases across our 29 English scripts since 18 Nov: a line opening "Guess how/what..." in 16,
"You see," in 6 and "It started" in 6: all three were the writer prompt's own examples. The prompt no longer gives
them; the humanize step marks them so the line is restated plainly before the voice is made."""
from engine import content_tuning, humanize, story


def _ids(text: str) -> set:
    return {t["id"] for t in humanize.tells(text)}


def test_formula_lines_from_our_scripts_are_tells():
    for line in ("Guess how many seasons he punished offenses in Denver.",       # Clutch Tales 1124
                 "Guess why the signal took so long to return.",                 # Cosmos 1124
                 "You see, every returning spacecraft hits a wall of air.",
                 "It started with a fishing line.",
                 "It all started in 1518.",
                 "Did you know Apollo 13 was silent for twice the expected time?",
                 "Which brings us right back to the question."):
        assert "template_line" in _ids(line), line


def test_the_trailing_wonder_line_is_a_closer():
    # 24 Nov prompt A/B: a Wild Instinct draft ended on "Which makes you wonder..."
    assert "closer" in _ids("Which makes you wonder...")
    assert "closer" not in _ids("The tern makes you look twice at a map.")


def test_the_same_words_inside_a_sentence_are_not_a_template():
    for line in ("Nobody could guess how deep it went.",
                 "The engines started at dawn.",
                 "Then you see the crack in the hull.",
                 "Forty times farther than the Sun, for one photo."):
        assert "template_line" not in _ids(line), line


def test_the_writer_prompt_no_longer_gives_the_formula_lines_to_copy():
    p = story.WRITER_PROMPT
    assert "Guess how deep it went" not in p
    assert '"You see," /' not in p and '"It started..." backstory' not in p
    assert 'Never a line that starts with "Guess"' in p


def test_the_like_rate_advice_asks_for_no_guess_line():
    s = {"stayed": 90, "plateaued": 0, "avg_pct": 95, "like_rate": 0.5, "views": 900, "videos": 3, "zero": 0}
    advice = " ".join(change for _said, change in content_tuning._findings(s))
    assert "guess" not in advice.lower() and "without telling them to comment" in advice


def test_the_humanize_step_rewrites_a_guess_line():
    class Brain:
        def __init__(self):
            self.prompts = []

        def ask_json(self, task, prompt, temperature=0.5):
            self.prompts.append(prompt)
            return {"lines": ["Fourteen seasons in Denver.", "He played on for fourteen seasons in Denver."]}, None
    b = Brain()
    lines, changed = humanize.rewrite_lines(b, ["Fourteen seasons in Denver.",
                                                "Guess how many seasons he punished offenses in Denver."])
    assert changed == 1 and lines[1].startswith("He played")
    assert "template line from a script formula" in b.prompts[0]
