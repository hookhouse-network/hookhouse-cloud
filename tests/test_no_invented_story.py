"""24 Nov, the Money Cheat Codes remake: the judge's fix "Inject a personal or relatable anecdote" made the writer invent
one for the faceless narrator ("Back in 2008, I bought a high-end laptop that bricked within a week of the crash"), and
neither the writer nor the fact-check knew today's date ("the week ending November 22, 2024", "corrected" to 2025, in
2026)."""
from engine import humanize, story, weekly

FAKE = "Back in 2008, I bought a high-end laptop that bricked within a week of the crash."


def test_a_narrators_invented_experience_is_found():
    for line in (FAKE, "My dad lost everything in that crash.", "When I was a kid, every laptop had one of these chips.",
                 "I remember the day the stock fell."):
        assert humanize.personal_claims(line), line
    for line in ("I think this is the wildest part.", "You probably owned one of these laptops.",
                 "Nvidia lost a third of its value in a day.", "If you bought a laptop in 2008, it may have died."):
        assert not humanize.personal_claims(line), line


class _Writer:
    def __init__(self, new_lines):
        self.new, self.prompts = new_lines, []

    def ask_json(self, task, prompt, temperature=0.5):
        self.prompts.append(prompt)
        return {"lines": list(self.new)}, None


def test_humanize_rewrites_the_narrators_invented_story():
    script = {"title": "Nvidia's 2008 crash", "search_phrase": "Nvidia 2008 crash",
              "beats": [{"narration": "Nvidia stock just fell 14 percent this week."}, {"narration": FAKE}]}
    fixed = "If you bought a laptop in 2008, it may have died within weeks of the crash."
    w = _Writer(["Nvidia stock just fell 14 percent this week.", fixed, "Nvidia's 2008 crash"])
    out = humanize.humanize_script(w, script, log=lambda *a: None)
    assert out["beats"][1]["narration"] == fixed and humanize.PERSONAL_LABEL in w.prompts[0]


def test_a_characters_acted_line_may_say_my_father():
    script = {"title": "The fort", "beats": [{"narration": "My father built this fort with his own hands.",
                                              "speaker": "Prince Amar"},
                                             {"narration": "The walls still stand today.", "speaker": "narrator"}]}
    w = _Writer([])
    assert humanize.humanize_script(w, script, log=lambda *a: None) is script and w.prompts == []


def test_the_writer_is_told_never_to_invent_a_personal_story():
    assert "personal experience" in story.WRITER_PROMPT and "I bought" in story.NO_INVENTED_STORY
    item = {"status": "redo", "gate_note": "potential: hook 5. Fix: Inject a personal or relatable anecdote"}
    assert story.NO_INVENTED_STORY in weekly.redo_text(item, {"id": "money_cheat_codes", "type": "story"})


def test_this_weeks_news_is_dated_for_the_writer_and_the_fact_check(monkeypatch):
    from datetime import date
    line = weekly.now_line({"news": "Nvidia stock plunges 14%"})
    assert f"Today is {date.today():%d %B %Y}" in line and "never with a date or a year" in line
    assert story.news_in_brief(line) == "Nvidia stock plunges 14%"
    monkeypatch.setattr(story, "wikipedia_summaries", lambda titles, chars=9000, focus="", **k: "[Nvidia] Nvidia ...")

    class Checker:
        prompt = ""

        def ask_json(self, task, prompt, system="", temperature=0.0):
            Checker.prompt = prompt
            return {"contradicted": [], "unsupported": []}, type("R", (), {"provider": "x"})()
    story.fact_check(Checker(), {"sources": ["Nvidia"], "claims": ["c"]}, news="Nvidia stock plunges 14%")
    assert f"today is {date.today():%d %B %Y}" in Checker.prompt
