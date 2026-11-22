"""23 Nov: Brain Snack's read-fast format offered only 3 fixed titles, so after 3 videos all were taken: the next got
'(Round 2)', was held as a repeat, was swapped to 'What word did you lose it at?' and the judge called the title vague
('mention butter vs heavy cream'). The fact writer already returns titles about its fact; they now come first."""
from engine.snack import maker

FACT = {"fact": "Butter is just cream shaken until the fat clumps together; the leftover liquid is real buttermilk.",
        "title_options": ["Butter is just over-whipped cream 🧈", "  ", "Where buttermilk really comes from",
                          "Shake cream long enough and this happens", "a fourth one"]}


def test_the_facts_own_titles_come_first():
    titles = maker.titles_for({"format": "readfast", "fact": FACT})
    assert titles[:3] == ["Butter is just over-whipped cream 🧈", "Where buttermilk really comes from",
                          "Shake cream long enough and this happens"]
    assert "Read it before it speeds up 😳" in titles                      # the fixed ones stay as backup
    assert maker.titles_for({"format": "readfast"})[0] == "If you can read this, your brain is fast 🧠"


def test_a_used_up_channel_gets_a_title_about_the_fact(monkeypatch):
    from engine import uniq
    used = {uniq._norm(t) for t in maker.titles_for({"format": "readfast"})}    # all three fixed ones taken
    monkeypatch.setattr(uniq, "used_titles", lambda cid: used)
    picked = uniq.pick("brain_snack", maker.titles_for({"format": "readfast", "fact": FACT}))
    assert picked[0] == "Butter is just over-whipped cream 🧈" and "Round" not in picked[0]
