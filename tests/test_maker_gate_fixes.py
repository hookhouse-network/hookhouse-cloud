"""Plan P0 item 2 (20 Nov gate report): fix the MAKER so its videos pass the gate, never loosen the gate.
Held for: titles over 40 characters, the search phrase not spoken in the first lines, protected franchise topics."""
from engine import story, weekly


class FakeBrain:
    def __init__(self, reply):
        self.reply, self.calls = reply, []

    def ask_json(self, task, prompt, **k):
        self.calls.append(prompt)
        return self.reply, None


def test_long_title_is_shortened_by_one_writer_call():
    s = {"title": "Rekha's makeup room mirror and the secret she kept for forty years", "title_options": []}
    b = FakeBrain({"titles": ["x" * 60, "Rekha's mirror kept a 40-year secret"]})
    out = story.shorten_title(b, s, log=lambda *a: None)
    assert out["title"] == "Rekha's mirror kept a 40-year secret" and len(b.calls) == 1
    assert s["title"] in out["title_options"]


def test_title_that_fits_costs_no_ai_call_and_bad_replies_keep_the_title():
    b = FakeBrain({"titles": []})
    ok = {"title": "The day the clocks stopped"}
    assert story.shorten_title(b, ok)["title"] == ok["title"] and not b.calls
    long = {"title": "A" * 55}
    assert story.shorten_title(FakeBrain(["not a dict"]), long, log=lambda *a: None)["title"] == long["title"]


def _script(first):
    return {"search_phrase": "rekha makeup room mirror", "beats": [{"narration": first},
                                                                   {"narration": "Nobody saw it coming."}]}


def test_search_phrase_is_put_into_the_opening_line():
    b = FakeBrain({"line": "In Rekha's makeup room, one mirror hid a secret for forty years."})
    out = story.phrase_early(b, _script("One object hid a secret for forty years."), log=lambda *a: None)
    from engine.quality import seo_issues
    assert not [x for x in seo_issues({}, out, {}, "short") if "search phrase" in x[1]]
    assert out["_fact_check"] == {}                         # the new wording is fact-checked again


def test_search_phrase_rewrite_is_dropped_when_it_misses_or_runs_long():
    s = _script("One object hid a secret for forty years.")
    assert story.phrase_early(FakeBrain({"line": "Still no phrase here."}), s, log=lambda *a: None) == s
    wordy = {"line": "Rekha makeup room mirror " + "very " * 20 + "long."}
    assert story.phrase_early(FakeBrain(wordy), s, log=lambda *a: None) == s


def test_opening_that_already_says_the_phrase_costs_no_ai_call():
    b = FakeBrain({"line": "x"})
    s = _script("Rekha's makeup room mirror hid a secret.")
    assert story.phrase_early(b, s) == s and not b.calls


def test_franchise_topics_are_never_picked():
    assert weekly.franchise_names({"topic": "Avengers: Doomsday ending explained", "angle": "Doctor Doom's plan"})
    assert weekly.franchise_names({"topic": "GTA 6 price: why $70 is a bargain"})
    assert not weekly.franchise_names({"topic": "The Day of Two Noons: 18 November 1883"})


def test_planned_franchise_topic_is_replaced_before_making(monkeypatch):
    item = {"id": "i1", "channel": "ending_decoded", "kind": "short", "topic": "Avengers ending explained",
            "status": "redo", "gate_note": "names a protected franchise/character: avengers"}

    def refresh(plan, it, ch, brain, memory, log):
        it.update(topic="The lighthouse keeper's last log, explained")
    monkeypatch.setattr(weekly, "_refresh_topic", refresh)
    monkeypatch.setattr("engine.config.channel", lambda cid: {"id": cid, "name": "Ending Decoded", "type": "story"})
    made = {}

    def fake_make(brain, ch, topic, fmt, memory, log, **k):     # **k: script / on_script / bank (P3)
        made["topic"] = topic
        raise StopIteration                                     # stop before rendering
    monkeypatch.setattr(story, "make", fake_make)
    monkeypatch.setattr(weekly, "clip_slot", lambda ch, it: False)
    try:
        weekly.make_item({"items": [item]}, item, brain=object(), log=lambda *a: None)
    except StopIteration:
        pass
    assert made["topic"].startswith("The lighthouse keeper") and "gate_note" not in item


def test_franchise_topic_without_replacement_fails_early(monkeypatch):
    item = {"id": "i1", "channel": "money_cheat_codes", "kind": "short", "topic": "GTA 6 price", "status": "planned"}
    monkeypatch.setattr(weekly, "_refresh_topic", lambda *a: None)
    monkeypatch.setattr("engine.config.channel", lambda cid: {"id": cid, "name": "Money", "type": "story"})
    monkeypatch.setattr(weekly, "clip_slot", lambda ch, it: False)
    import pytest
    with pytest.raises(RuntimeError, match="protected franchise"):
        weekly.make_item({"items": [item]}, item, brain=object(), log=lambda *a: None)
