"""23 Nov: the owner approved the Bloop long video (24 Nov 06:30) on the dashboard; it stayed held for 'title nearly
repeats an earlier one'. Its title 'Counting to 5 with Bouncy Candy Canes | Bloop & Friends Nursery Rhymes & Kids
Songs' scored 0.86 against 'Counting to 10 with Shiny Apples | (the same tag)': the shared series tag was most of the
text. A shared ending of 3+ words is now taken out before the comparison; real repeats are still caught."""
import json

from engine import content_gate as cg, potential_gate as pg, uniq

TAG = " | Bloop & Friends Nursery Rhymes & Kids Songs"
OLD = uniq._norm("Counting to 10 with Shiny Apples" + TAG)


def test_a_shared_series_tag_is_not_a_repeat():
    assert uniq.repeat_ratio("Counting to 5 with Bouncy Candy Canes" + TAG, OLD) < 0.85
    assert uniq.repeat_ratio("Counting to 5 with Shiny Apples" + TAG, OLD) >= 0.85            # same objects
    assert uniq.repeat_ratio("Counting to 10 with Shiny Apples" + TAG, OLD) == 1.0
    assert uniq.repeat_ratio("Shiny Apples" + TAG, OLD) == uniq.repeat_ratio(              # all of it is shared
        uniq._norm("Shiny Apples" + TAG), OLD)


def test_short_shared_endings_and_brain_snack_near_copies_are_unchanged():
    import difflib
    for a, b in (("Wait for the last try", "wait for the very last try"),             # 2-word ending: as before
                 ("Coco vs Mochi: who wins?", "limo vs pretzo who wins"),
                 ("The Town That Vanished Overnight", "the town that vanished over night")):
        assert uniq.repeat_ratio(a, b) == difflib.SequenceMatcher(None, uniq._norm(a), uniq._norm(b)).ratio()
    # Brain Snack (21-22 Nov): the same game in another shape is still a near-repeat
    assert uniq.repeat_ratio("1 bounce = 2 balls inside a heart (wait for the reveal)",
                             "1 bounce 2 balls inside a blob wait for the reveal") >= 0.85


def test_the_gate_lets_the_approved_bloop_title_through(tmp_path):
    it = {"id": "1124_0630_bloop_and_friends_long", "channel": "bloop_and_friends", "out_dir": str(tmp_path),
          "file": "video.mp4"}
    ch = {"id": "bloop_and_friends", "type": "kids"}
    held = pg.deterministic(it, ch, {"title": "Counting to 5 with Bouncy Candy Canes" + TAG}, past_titles=[OLD])
    assert not any("nearly repeats" in p for p in held)
    again = pg.deterministic(it, ch, {"title": "Counting to 10 with Shiny Apples!" + TAG},
                             past_titles=[uniq._norm("Counting to 10 with Shiny Apples, Part 1" + TAG)])
    assert any("nearly repeats" in p for p in again)


def test_title_repair_uses_the_same_measure(tmp_path):
    (tmp_path / "upload.json").write_text(json.dumps({
        "title": "Counting to 5 with Shiny Apples" + TAG,
        "title_options": ["Counting to 5 with Shiny Apples" + TAG, "Five Shiny Apples Song" + TAG,
                          "Let's Count 5 Bouncy Candy Canes!" + TAG]}), encoding="utf-8")
    it = {"id": "x", "channel": "bloop_and_friends", "out_dir": str(tmp_path)}
    probs = ['potential: title nearly repeats an earlier one ("counting to 10 with shiny apples")']
    assert cg.repair_title(it, {"id": "bloop_and_friends"}, probs, past=[OLD])
    m = json.loads((tmp_path / "upload.json").read_text(encoding="utf-8"))
    assert m["title"] == "Five Shiny Apples Song" + TAG           # the first option that is not a repeat
