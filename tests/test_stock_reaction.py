"""23 Nov: the writer prompt's example reaction line ("Honestly, this is the part I can't get over.") came back word
for word in 10 of 33 recent scripts across channels (15 had "Honestly"); a Deep Blue script opened with "This isn't a
glass sculpture; it's a living animal". The same line in every video reads as a template (S10 'obviously AI-made').
The prompt no longer gives a sentence to copy, and both shapes are AI tells that the humanize step rewrites."""
from engine import humanize, story


def _ids(text: str) -> set:
    return {t["id"] for t in humanize.tells(text)}


def test_the_stock_reaction_line_is_a_tell():
    assert "stock_reaction" in _ids("Honestly, this is the part I can't get over.")
    assert "stock_reaction" in _ids("I still can't get over that.")


def test_this_isnt_x_its_y_is_a_tell():
    assert "not_x_but_y" in _ids("This isn't a glass sculpture; it's a living animal with its brain exposed.")


def test_plain_story_lines_are_not_tells():
    for line in ("The eyes actually rotate to look upward for silhouettes of prey.",
                 "It wasn't the engine, it was the fuel line.",          # a spoken correction with a comma stays
                 # (24 Nov: "Guess how ..." lines are a template now: tests/test_template_lines.py)
                 "Forty times farther than the Sun, for one photo."):
        assert not _ids(line), line


def test_the_writer_prompt_gives_no_reaction_sentence_to_copy():
    assert "can't get over" not in story.WRITER_PROMPT
    assert "concrete detail of THIS story" in story.WRITER_PROMPT


def test_the_rewrite_step_marks_the_stock_line_for_the_writer():
    class Brain:
        def __init__(self):
            self.prompts = []

        def ask_json(self, task, prompt, temperature=0.5):
            self.prompts.append(prompt)
            return {"lines": ["The eyes rotate.", "Forty times farther than the Sun, for one photo."]}, None
    b = Brain()
    lines, changed = humanize.rewrite_lines(b, ["The eyes rotate.", "Honestly, this is the part I can't get over."])
    assert changed == 1 and lines[1] == "Forty times farther than the Sun, for one photo."
    assert "stock reaction line" in b.prompts[0]
