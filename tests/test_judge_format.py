"""23 Nov 01:15: the owner-approved Bloop long video (kids, 24 Nov 06:30) passed the title check under B but was held
by S10 'obviously AI-made' (human_feel 5, needs 6). Its verdict showed two judge errors, not a lower bar: the long
video was judged "can it WIN on YouTube Shorts, Instagram Reels and Facebook Reels" ("needs ... to compete on Shorts
platforms"), and human_feel penalises "same-shaped sentences" while the kids rubric scores joyful repetition (8/10).
Long videos are now judged as long videos and the kids human_feel text knows repetition is intended; only videos
whose judge texts changed are judged once more (grown-up Shorts keep their stored verdicts)."""
import pytest

from engine import potential_gate as pg, topic_proof as tp

STORY = {"id": "unsolved_after_dark", "name": "Unsolved After Dark", "type": "story", "niche": "true crime",
         "market": "US", "language": "en"}
KIDS = {"id": "bloop_and_friends", "name": "Bloop & Friends", "type": "kids", "niche": "preschool songs",
        "market": "US", "language": "en"}
SHORT_START = ("You are the strictest head of content at a top short-video studio. Decide if this video can WIN on "
               "YouTube Shorts, Instagram Reels and Facebook Reels and earn money. Score each criterion 0-10 where 9 "
               "means top 5% of what this niche posts this month and 10 means it could be one of the niche's best "
               "videos this week. Be harsh: generic, templated, slow or confusing content scores 6 or less. Platforms "
               "reward viewers who stay, rewatch and SEND videos to friends; YouTube does not monetise mass-produced "
               "content without its own insight.\n")


def _item(tmp_path, kind="short", said="One candy cane! Two candy canes! Can you count with me?"):
    (tmp_path / "captions.srt").write_text(f"1\n00:00:00,100 --> 00:00:03,000\n{said}\n", encoding="utf-8")
    return {"id": "x", "kind": kind, "topic": "count to 5", "out_dir": str(tmp_path), "file": "video.mp4",
            "made_at": 10.0}


def _prompt(ch, it, ctype):
    return pg._prompt(ch, it, {"title": "Counting to 5"}, ctype, pg._criteria(pg._cfg(), ctype), "")


def test_a_grown_up_short_is_asked_exactly_as_before(tmp_path):
    p = _prompt(STORY, _item(tmp_path), "story")
    assert p.startswith(SHORT_START)
    assert pg.CRITERIA_HELP["human_feel"] in p and pg.CRITERIA_HELP["hook"] in p
    assert pg.judge_tag("story", _item(tmp_path)) == ""                     # its stored verdict stays valid


def test_a_long_video_is_judged_as_a_long_video(tmp_path):
    it = _item(tmp_path, kind="long", said="word " * 1000)
    p = _prompt(STORY, it, "story")
    assert "LONG video can WIN on YouTube" in p and "first 30 seconds earn the stay" in p
    assert "Instagram Reels" not in p and "SEND videos to friends" not in p
    assert pg.HELP_LONG["hook"] in p and pg.CRITERIA_HELP["hook"] not in p
    assert "(the first minutes of a longer video)" in p                        # it only sees the start
    assert "first minutes" not in _prompt(STORY, _item(tmp_path, kind="long"), "story")


def test_kids_human_feel_does_not_count_the_planned_repetition(tmp_path):
    p = _prompt(KIDS, _item(tmp_path), "kids")
    assert pg.HELP_KIDS["human_feel"] in p and "sing-along repetition is GOOD here" in p
    assert "same-shaped sentences" not in p                                   # the generic text is replaced
    assert "joyful repetition" in p                                           # its own rubric criterion stays
    assert "children aged 2-5 and their parents" in p


def test_only_changed_judge_texts_get_a_new_verdict(tmp_path):
    short, long_ = _item(tmp_path), _item(tmp_path, kind="long")
    tags = {pg.judge_tag("story", short), pg.judge_tag("story", long_), pg.judge_tag("kids", short),
            pg.judge_tag("kids", long_)}
    assert pg.judge_tag("story", short) == "" and len(tags) == 4                # each changed case its own key
    assert pg.judge_tag("kids", long_) == pg.judge_tag("kids", dict(long_, id="y", made_at=99.0))   # stable


def test_a_long_story_script_is_judged_as_long(monkeypatch):
    from engine import story
    kinds = []

    def judge(script, ch, topic, brain, kind=""):
        kinds.append(kind)
        return {"scores": {}, "low": {}, "fixes": [], "need": 8}
    monkeypatch.setattr(pg, "judge_script", judge)
    monkeypatch.setattr(story, "_script_judge_cfg", lambda: {"enabled": True, "rounds": 2})
    for fmt in ("long", "short"):
        story._judge_loop(object(), STORY, {"title": "t", "beats": []}, "topic", fmt, None, lambda *a: None, {})
    assert kinds == ["long", ""]


class Judge:
    def __init__(self, scores):
        self.scores, self.calls = scores, 0

    def ask_json(self, task, prompt, temperature=0.4):
        self.calls += 1
        return {"scores": self.scores, "fixes": ["start with the surprise"], "summary": "ok"}, None


@pytest.mark.parametrize("ch,ctype,kind,again", [(STORY, "story", "short", False), (KIDS, "kids", "long", True),
                                                 (STORY, "story", "long", True), (KIDS, "kids", "short", True)])
def test_a_verdict_stored_before_the_fix(tmp_path, monkeypatch, ch, ctype, kind, again):
    from engine.core import ledger
    monkeypatch.setattr(pg, "deterministic", lambda *a, **k: [])
    monkeypatch.setattr(tp, "proof", lambda topic, c, **k: {"tier": "steady", "best_per_day": 900, "top": []})
    led = ledger.Ledger(tmp_path / "l.db")
    it = _item(tmp_path, kind=kind)
    old = {c: 9 for c in pg._criteria(pg._cfg(), ctype)}
    led.run_stage(it["id"], f"{pg.PREFIX}:10", lambda: {"scores": dict(old, human_feel=3), "fixes": []},
                  validate=lambda a: True)                                   # the 22 Nov verdict, old cache key
    j = Judge(dict(old, human_feel=7))
    probs = pg.problems(it, ch, {"title": "Counting to 5"}, brain_fn=lambda: j, led=led)
    assert j.calls == (1 if again else 0)
    assert any("obviously AI-made" in p for p in probs) != again               # new verdict decides, if judged
