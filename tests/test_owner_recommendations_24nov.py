"""Owner 24 Nov, after the honest status (output 3-5 videos a day as before, two zero days when the strict gates went
live, views lower than mid-November): "do as you recommendations".
1) Brain Snack 3 Shorts a day (its Shorts got 1,050-1,350 views each after 48 h, ~10x a story Short, no AI pictures).
2) The S10 human_feel judge coaches instead of blocking until its scores match real views (n=7: -0.62 with views; it
   held the read-fast format, the most watched); facts, copyright, ad-safety, the AI label, the AI-phrase count and
   campaign clips still block.
3) At most one remake per video (remakes spent the picture budget; new slots stayed unmade)."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from engine import content_gate, weekly
from engine.config import channel

HUMAN = "potential: looks/sounds obviously AI-made (human_feel 5, needs 6). Fix: open with a challenge"
RUBRIC = "potential: below 8/10 on hook 5. Fix: x"
PHRASES = "potential: reads like AI-written text (delve, tapestry): say it plainly like a person would"


def test_the_human_feel_judge_coaches_but_not_for_campaign_clips():
    assert content_gate.human_judge_coaches()
    assert content_gate.coached(HUMAN, "coach") and content_gate.coached(HUMAN, "block")   # not tied to the 28 Nov bar
    assert not content_gate.coached(HUMAN, "block", clip=True)
    assert not content_gate.coached(PHRASES, "coach")                                     # the AI-phrase count blocks
    assert content_gate.coached(RUBRIC, "coach") and not content_gate.coached(RUBRIC, "block")
    for hard in ("potential: speech starts at 2.0s (the hook must land within 0.6s)",
                 "potential: not advertiser-friendly (gun): limited or no ads = no earning",
                 "potential: not judged yet (no AI judge available here); it tries again"):
        assert not content_gate.coached(hard, "coach"), hard


def test_switching_the_judge_back_to_block(monkeypatch):
    real = content_gate.config()
    pot = dict(real.get("potential") or {}, ai_tell=dict((real.get("potential") or {}).get("ai_tell") or {}, judge="block"))
    monkeypatch.setattr(content_gate, "config", lambda: dict(real, potential=pot))
    assert not content_gate.coached(HUMAN, "coach")


def test_at_most_one_remake_and_brain_snack_three_a_day():
    assert content_gate.config()["defaults"]["auto_redo_max"] == 1
    assert channel("brain_snack")["schedule"]["shorts_per_day"] == 3


IST = timezone(timedelta(hours=5, minutes=30))


@pytest.fixture
def week(tmp_path, monkeypatch):
    monkeypatch.setattr(weekly, "WEEKS_DIR", tmp_path)
    now = datetime(2026, 11, 24, 13, 0, tzinfo=IST)                 # a Tuesday
    start = now.date() - timedelta(days=now.weekday())
    snack = channel("brain_snack")
    times = [w for w, k in weekly.slots_for(snack, start) if k == "short"]
    first = {}                                                       # the plan as made with 1 a day: one per day
    for w in times:
        first.setdefault(w.date(), w)
    items = [{"id": f"{w:%m%d_%H%M}_brain_snack_short", "channel": "brain_snack", "kind": "short",
              "publish_at": w.isoformat(), "status": "posted" if w < now else "planned", "topic": "a theme"}
             for w in first.values()]
    items.append({"id": "1125_0500_money_cheat_codes_short", "channel": "money_cheat_codes", "kind": "short",
                  "publish_at": "2026-11-25T05:00:00+05:30", "status": "planned", "topic": "t"})
    folder = weekly.week_dir(start.isoformat())                      # seed an existing week as a file (a fixture
    folder.mkdir(parents=True, exist_ok=True)                        # is not a status change, so no audit)
    (folder / "plan.json").write_text(json.dumps({"start": start.isoformat(), "created": 0, "items": items}),
                                      encoding="utf-8")
    return now, start


def test_the_week_gets_the_missing_brain_snack_slots_only_in_the_future(week):
    now, start = week
    before = weekly.load_plan(start)["items"]
    n = weekly.top_up_week(now=now, log=lambda *a: None)
    after = weekly.load_plan(start)["items"]
    new = [it for it in after if it.get("topped_up")]
    assert n == len(new) > 0
    assert all(datetime.fromisoformat(it["publish_at"]) >= now + timedelta(hours=2) for it in new)
    assert all(it["channel"] == "brain_snack" and it["status"] == "planned" and it["topic"] is None for it in new)
    per_day = {}
    for it in after:
        if it["channel"] == "brain_snack":
            per_day[it["id"][:4]] = per_day.get(it["id"][:4], 0) + 1
    assert max(per_day.values()) <= 3 and all(v == 3 for d, v in per_day.items() if d > f"{now:%m%d}")
    assert all(it in after for it in before)                                  # nothing existing changed
    assert weekly.top_up_week(now=now, log=lambda *a: None) == 0              # idempotent


def test_story_channels_are_never_topped_up(week):
    now, start = week
    weekly.top_up_week(now=now, log=lambda *a: None)
    assert not [it for it in weekly.load_plan(start)["items"] if it["channel"] == "money_cheat_codes" and it.get("topped_up")]
