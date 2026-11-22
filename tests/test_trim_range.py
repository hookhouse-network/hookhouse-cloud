"""23 Nov: the length trim missed the research range in 6 of the last 22 cuts (Deep Blue 152 -> 106 words for
125-150, Itihaas 188 -> 160 for 110-135; each miss costs 7 quality points, and from 29 Nov the bar is 100 again).
A cut under the range gets original lines back; a cut still over it, or a rejected cut, gets one more pass."""
from engine import story


def _beats(n: int, words: int = 10) -> list:
    return [{"narration": " ".join([f"w{i}"] * words), "visual": "photo", "query": f"q{i}"} for i in range(n)]


def _count(script: dict) -> int:
    return sum(len(b["narration"].split()) for b in script["beats"])


class Writer:
    """Answers each trim request with the next planned keep-list (index -> words to keep)."""
    def __init__(self, *plans):
        self.plans, self.asked = list(plans), 0

    def ask_json(self, role, prompt, temperature=0.3):
        assert "Tighten it" in prompt
        self.asked += 1
        plan = self.plans.pop(0)
        return {"keep": [{"i": i, "narration": " ".join(["k"] * w)} for i, w in plan]}, None


def test_a_cut_under_the_range_gets_original_lines_back():
    ch = {"spec": {"short_words": "125-150 words (about 43-52 seconds)"}}
    w = Writer([(i, 8) for i in range(0, 16, 2)])                    # 160 words -> 8 beats of 8 = 64 (far under)
    out = story.fit_length(w, ch, {"beats": _beats(16)}, log=lambda *a: None)
    n = _count(out)
    assert 125 <= n <= 150 and w.asked == 1
    qs = [b["query"] for b in out["beats"]]
    assert qs == sorted(qs, key=lambda q: int(q[1:])) and qs[0] == "q0"   # original order, the hook first
    assert out["_fact_check"] == {}                                        # wording changed: checked again


def test_a_cut_still_over_the_range_gets_one_more_pass():
    ch = {"spec": {"short_words": "110-135 words (about 45-55 seconds)"}}
    w = Writer([(i, 10) for i in range(16)], [(i, 10) for i in range(12)])   # 180 -> 160 (over) -> 120
    out = story.fit_length(w, ch, {"beats": _beats(18)}, log=lambda *a: None)
    assert _count(out) == 120 and w.asked == 2


def test_never_more_than_two_cuts():
    ch = {"spec": {"short_words": "110-135 words"}}
    w = Writer([(i, 10) for i in range(17)], [(i, 10) for i in range(16)])   # 180 -> 170 -> 160, both over
    out = story.fit_length(w, ch, {"beats": _beats(18)}, log=lambda *a: None)
    assert w.asked == 2 and _count(out) == 160                              # best effort, honestly over


def test_a_rejected_cut_is_tried_once_more():
    ch = {"spec": {"short_words": "110-135 words"}}
    w = Writer([(i, 10) for i in range(5)], [(i, 10) for i in range(12)])    # too few beats, then a good cut
    out = story.fit_length(w, ch, {"beats": _beats(18)}, log=lambda *a: None)
    assert w.asked == 2 and _count(out) == 120


def test_two_rejected_cuts_keep_the_original():
    ch = {"spec": {"short_words": "110-135 words"}}
    w = Writer([(i, 10) for i in range(1, 12)], [(i, 10) for i in range(1, 12)])   # both lose the hook
    out = story.fit_length(w, ch, {"beats": _beats(18)}, log=lambda *a: None)
    assert w.asked == 2 and _count(out) == 180


def test_putting_back_never_passes_the_top_of_the_range():
    beats = _beats(10)
    beats[1]["narration"] = " ".join(["long"] * 40)
    kept = [(i, dict(beats[i])) for i in range(10) if i != 1]                 # 90 words; beat 1 (40) was dropped
    assert sum(len(b["narration"].split()) for _, b in story._put_back(beats, kept, 125, 130)) == 130
    assert sum(len(b["narration"].split()) for _, b in story._put_back(beats, kept, 125, 125)) == 90


def test_a_script_in_range_is_not_touched():
    ch = {"spec": {"short_words": "110-135 words"}}
    w = Writer()
    out = story.fit_length(w, ch, {"beats": _beats(12)}, log=lambda *a: None)
    assert w.asked == 0 and _count(out) == 120
