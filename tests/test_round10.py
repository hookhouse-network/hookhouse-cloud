"""Round 10 (12 Nov): SEO ideas adapted from claude-seo (answer-first descriptions + key facts, hub-and-spoke topic
clusters, YouTube search terms + drift alert) and trend-led Bloop songs with an automatic quality gate."""
import datetime
import json
from datetime import datetime as dt

from engine import stats_fetch, weekly


def test_long_description_has_key_facts_and_chapters():
    from engine import story
    ch = {"id": "unsolved_after_dark", "name": "Unsolved After Dark", "language": "en"}
    script = {"summary": "The Mary Celeste was found empty near the Azores in 1872.\nWhy did ten people leave?",
              "claims": ["The Mary Celeste left New York in November 1872.", "It was found on 4 December 1872.",
                         "Ten people were aboard.", "A later claim"], "sources": ["Mary Celeste"]}
    d = story.build_description(ch, script, [], chapters=[(0, "A Ship's Past"), (300, "Why Was It Empty?"),
                                                          (600, "The Clues")])
    assert d.startswith("The Mary Celeste was found empty")              # answer-first, quotable opening
    assert "Key facts:" in d and "A later claim" not in d                # 3 early, fact-checked statements
    assert "Chapters:" in d and "Why Was It Empty?" in d


def test_cluster_slots_put_hub_on_long_and_spokes_after():
    slots = [(dt(2099, 1, 5, 5), "short"), (dt(2099, 1, 6, 6, 30), "long"), (dt(2099, 1, 7, 5), "short"),
             (dt(2099, 1, 8, 5), "short"), (dt(2099, 1, 9, 5), "short")]
    topics = [{"topic": f"T{i}"} for i in range(5)]
    out = weekly.cluster_slots(slots, topics, {"hub": 2, "spokes": [{"topic": "S1"}, {"topic": "S2"}]})
    assert out[1]["topic"] == "T2" and out[1]["role"] == "hub"
    assert [out[2]["topic"], out[3]["topic"]] == ["S1", "S2"] and out[2]["hub"] == "T2"
    assert weekly.cluster_slots(slots, topics, {"hub": 9}) == topics            # bad data: plan unchanged


def test_search_terms_snapshot_and_drift_alert(tmp_path, monkeypatch):
    sec = tmp_path / "secrets"
    sec.mkdir()
    (sec / "youtube_clutch_tales.json").write_text("{}")
    monkeypatch.setattr(stats_fetch, "SECRETS", sec)
    monkeypatch.setattr(stats_fetch, "TERMS", tmp_path / "terms.json")
    import engine.publish as pub
    monkeypatch.setattr(pub, "yt_access_token", lambda c, s=None: "tok")
    totals = iter([[["miracle on ice", 900], ["herb brooks", 300]], [["miracle on ice", 300]]])

    class R:
        def __init__(self, rows):
            self.rows = rows

        def json(self):
            return {"rows": self.rows}

        def raise_for_status(self):
            pass

    class S:
        def get(self, url, **k):
            assert k["params"]["filters"] == "insightTrafficSourceType==YT_SEARCH"
            return R(next(totals))
    first = stats_fetch.search_terms(session=S(), log=lambda m: None)
    assert first["channels"]["clutch_tales"][0] == ["miracle on ice", 900] and not first["alerts"]
    state = json.loads((tmp_path / "terms.json").read_text())
    state["clutch_tales"]["history"][0]["week"] = "2000-W01"                  # pretend it was last week
    (tmp_path / "terms.json").write_text(json.dumps(state))
    second = stats_fetch.search_terms(session=S(), log=lambda m: None)
    assert second["alerts"] and "1,200 -> 300" in second["alerts"][0]
    assert stats_fetch.top_terms("clutch_tales")[0] == ("miracle on ice", 300)


def test_song_planner_follows_season_and_trends():
    from engine import songs
    dec = [s["id"] for s in songs.plan_releases(datetime.date(2026, 12, 5), [])]
    assert dec[0] == "count_the_snowflakes"
    may = [s["id"] for s in songs.plan_releases(datetime.date(2027, 5, 5), ["Bedtime lullaby songs for babies"])]
    assert may[0] == "goodnight_bloop"
    assert all(s.get("season") for s in songs.SONGS)
