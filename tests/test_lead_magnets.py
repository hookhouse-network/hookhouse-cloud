"""Round 23 (16 Nov, owner's two income articles): free samples (lead magnets), buying questions in comments,
weekly product research before building."""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from engine import comments, links, product_research, store_copy, store_covers, store_publish


def test_every_freebie_has_a_spec_title_and_honest_copy():
    for pid in store_covers.FREEBIES:
        fid = "free_" + pid
        assert fid in store_covers.SPECS and store_covers.TITLES[fid].startswith("FREE")
        assert len(store_covers.TITLES[fid]) <= 100
        d = store_copy.description(fid, "payhip")
        assert "Try it free" in d and "purchase" not in d             # a free download is not a purchase
        assert "full version" in d


def test_planner_sample_is_not_called_a_bundle():
    assert "BUNDLE" not in " ".join(store_covers.SPECS["free_planner_2027"]["head"])


def test_buying_questions():
    assert comments.buying("where can I get this planner?")
    assert comments.buying("pdf link do bhai")
    assert comments.buying("ye kaha milega?")
    assert not comments.buying("great video, loved it")
    assert not comments.buying("buyer beware of this")                  # whole words only
    assert not comments.buying("free pdf here https://spam.example")    # spam is never intent


def test_free_link_in_description_footer(monkeypatch, tmp_path):
    shop = {"money_cheat_codes": ["2027 Planner", "https://payhip.com/b/PAID"],
            "money_cheat_codes#free": ["Free printable: year at a glance", "https://payhip.com/b/FREE"]}
    f = tmp_path / "shop_links.json"
    f.write_text(json.dumps(shop), encoding="utf-8")
    monkeypatch.setattr(store_publish, "products", lambda: [])          # cloud path: config/shop_links.json
    monkeypatch.setattr(store_publish, "SHOP_LINKS", f)
    monkeypatch.setattr(links, "data", lambda: {"money_cheat_codes": {"live": True}})
    out = links.footer("money_cheat_codes")
    assert out.index("FREE") < out.index("PAID") and "🎁" in out
    assert links.footer("money_cheat_codes", kids=True) == ""            # Made for Kids: never links


def test_research_scores_season_intent_and_skips_what_we_have():
    idea = {"id": "x", "name": "Habit tracker printable", "search": "habit tracker printable", "fits": "m",
            "months": [11], "build": "easy"}
    base = product_research.score(idea, {"median": 10000}, 0, 5)
    assert product_research.score(idea, {"median": 10000}, 0, 11) > base          # in season
    assert product_research.score(idea, {"median": 10000}, 2, 5) > base           # viewers asked for it
    assert product_research.score({**idea, "build": "have"}, {"median": 10 ** 6}, 0, 11) == 0
    assert product_research.intent(idea, [("m", "where can I get the habit tracker?"), ("m", "nice")]) == 1


def test_research_message_lists_new_ideas_only():
    rows = [{"name": "A (have)", "build": "have", "score": 0, "median_views": 5, "fits": "m", "months": [],
             "buy_questions": 0},
            {"name": "Christmas coloring", "build": "easy", "score": 9, "median_views": 8_000_000, "fits": "bloop",
             "months": [datetime.now().month], "buy_questions": 2}]
    msg = product_research.text(rows)
    assert "Christmas coloring" in msg and "2 of our viewers asked" in msg and "season" in msg
    assert "build <name>" in msg


def test_ideas_file_is_valid():
    ideas = product_research.ideas()
    assert len(ideas) >= 10
    for i in ideas:
        assert i["build"] in ("easy", "new", "have") and all(1 <= m <= 12 for m in i["months"]) and i["search"]
    assert json.dumps(ideas)


def test_late_approved_short_posts_within_48h_not_next_week(monkeypatch):
    """16 Nov: Brain Snack approved at 09:23 got 23 Nov because every day's slot held a planned (unmade) Short."""
    from zoneinfo import ZoneInfo
    from engine import autopilot
    z = ZoneInfo("Asia/Kolkata")
    now = datetime(2026, 11, 16, 9, 23, tzinfo=z)
    planned = [("2026-11-16", {"id": f"p{d}", "channel": "brain_snack", "kind": "short",
                               "publish_at": datetime(2026, 11, 16 + d, 5, 0, tzinfo=z).isoformat()}) for d in range(7)]
    monkeypatch.setattr(autopilot, "_now", lambda: now)
    monkeypatch.setattr(autopilot, "items", lambda a=0, b=0: planned)
    monkeypatch.setattr(autopilot, "_channel", lambda c: {"id": c, "market": "US", "schedule": {"shorts_per_day": 1}})
    new = datetime.fromisoformat(autopilot.next_free_slot("2026-11-16", {"id": "x", "channel": "brain_snack",
                                                                          "kind": "short"}))
    assert new - now < timedelta(hours=24)                               # tonight, not next week
    assert all(abs((new - datetime.fromisoformat(x["publish_at"])).total_seconds()) >= 7200 for _, x in planned)


def test_reschedule_keeps_status_and_changes_only_publish_time(monkeypatch):
    from engine import publish
    sent = {}

    class R:
        def __init__(self, code, data=None):
            self.status_code, self._d = code, data or {}

        def json(self):
            return self._d

        def raise_for_status(self):
            pass

    class S:
        def get(self, url, **kw):
            return R(200, {"items": [{"status": {"privacyStatus": "private", "selfDeclaredMadeForKids": False,
                                                  "containsSyntheticMedia": True, "publishAt": "2026-11-22T23:30:00Z",
                                                  "uploadStatus": "processed"}}]})

        def put(self, url, **kw):
            sent.update(kw["json"])
            return R(200)

    monkeypatch.setattr(publish, "yt_access_token", lambda c, s=None: "tok")
    monkeypatch.setattr(publish, "add_quota", lambda *a, **k: None)
    monkeypatch.setattr(publish, "_log", lambda a: None)
    assert publish.youtube_reschedule("clutch_tales", "vid", "2026-11-16T23:45:00+05:30", session=S())
    assert sent["status"]["publishAt"] == "2026-11-16T18:15:00Z"
    assert sent["status"]["containsSyntheticMedia"] is True and "uploadStatus" not in sent["status"]
