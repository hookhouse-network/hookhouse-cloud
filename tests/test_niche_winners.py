"""Weekly 'what is winning in each niche' (official YouTube search): sorted by views, never-topics dropped, stored
once, deleted after 30 days (YouTube API policy), own quota bucket."""
import json
import sqlite3
import time

from engine import niche_winners, publish


class FakeMem:
    def __init__(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, kind TEXT, channel TEXT, text TEXT, meta TEXT, "
                          "performance REAL, embedder TEXT, vector BLOB, created REAL)")

    def add(self, kind, text, channel=None, meta=None, performance=None):
        self.conn.execute("INSERT INTO items(kind, channel, text, meta, performance, created) VALUES (?,?,?,?,?,?)",
                          (kind, channel, text, json.dumps(meta or {}), performance, time.time()))
        self.conn.commit()


class R:
    def __init__(self, d):
        self.d, self.ok, self.status_code = d, True, 200

    def json(self):
        return self.d

    def raise_for_status(self):
        pass


class S:
    def __init__(self):
        self.calls = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append((url, params))
        if url.endswith("/search"):
            return R({"items": [
                {"id": {"videoId": "a1"}, "snippet": {"title": "The Ship That Vanished #shorts", "channelTitle": "X"}},
                {"id": {"videoId": "b2"}, "snippet": {"title": "Casino heist gone wrong", "channelTitle": "Y"}},
                {"id": {"videoId": "c3"}, "snippet": {"title": "Why Nobody Found Flight 19", "channelTitle": "Z"}}]})
        return R({"items": [{"id": "a1", "statistics": {"viewCount": "1200"}},
                            {"id": "b2", "statistics": {"viewCount": "9000"}},
                            {"id": "c3", "statistics": {"viewCount": "50000"}}]})


def test_winners_are_sorted_filtered_and_stored_once(tmp_path, monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", "k")
    monkeypatch.setattr(publish, "QUOTA_FILE", tmp_path / "q.json")
    from engine import config
    monkeypatch.setattr(config, "channels", lambda: [{"id": "unsolved_after_dark", "language": "en",
                                                      "schedule": {"long_per_week": 0}}])
    mem, s = FakeMem(), S()
    report = niche_winners.refresh(mem, log=lambda m: None, session=s)
    titles = [r["title"] for r in report["unsolved_after_dark"]]
    assert titles[0] == "Why Nobody Found Flight 19" and "#shorts" not in " ".join(titles)
    assert not any("Casino" in t for t in titles)                    # never-topic (gambling) dropped
    niche_winners.refresh(mem, log=lambda m: None, session=s)          # second week: same videos not added twice
    assert mem.conn.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 2
    p = s.calls[0][1]
    assert p["order"] == "viewCount" and p["videoDuration"] == "short" and p["q"] == "unsolved mystery"
    q = json.loads((tmp_path / "q.json").read_text())
    assert q["search_used"] == 200 and q["used"] == 2                 # search bucket separate from the general one


def test_examples_are_deleted_after_30_days():
    mem = FakeMem()
    mem.add("viral_example", "old", meta={"source": "youtube_search", "video_id": "x"})
    mem.conn.execute("UPDATE items SET created = ?", (time.time() - 31 * 86400,))
    mem.add("viral_example", "new", meta={"source": "youtube_search", "video_id": "y"})
    mem.add("hook", "our own winner")
    assert niche_winners.purge(mem) == 1
    assert {r[0] for r in mem.conn.execute("SELECT text FROM items")} == {"new", "our own winner"}


def test_no_search_without_key_or_login(tmp_path, monkeypatch):
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
    monkeypatch.setattr(niche_winners, "ROOT", tmp_path)
    assert niche_winners.search({"id": "unsolved_after_dark"}, session=S()) == []
