"""24 Nov: the kids Short opens on the "problem" lines, and the child was first asked something in line 4; both judged
versions of Bloop 1125_0500 scored human_feel 5 with the same fix (open with a direct challenge to the child, Dora's
ask-the-viewer-for-help). The problem part now starts with the narrator asking for help, in the writer's own words."""
from engine import kids


def test_the_problem_part_starts_with_the_narrator_asking_the_child_for_help():
    p = kids.STORY_PROMPT
    i = p.index('"problem":')
    first = p[i:i + 200]
    assert "line 1 is the narrator asking the child for help right away" in first and "the Short starts here" in first
    assert '"Can you' not in first                       # no example line to copy word for word


def test_the_short_still_opens_on_the_problem():
    lines = ([{"section": "intro", "who": "Bloop", "say": "Oopsie-doodle!"}]
             + [{"section": "problem", "who": "narrator", "say": f"p{i}"} for i in range(4)]
             + [{"section": "count", "who": "narrator", "say": "One star!"}])
    assert kids.short_lines(lines)[0]["say"] == "p0"
