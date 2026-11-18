"""Round 13 (13 Nov): ideas from the open-source automation landscape, built our own way.
Threads by its official API (the Reel's own Instagram video link), Pinterest via Instagram claiming, retention curves
-> lessons, viewer comments -> approved replies + ideas, Bloop's lip-sync mouth shapes."""
import json
import sqlite3
import time

import numpy as np
import pytest

from engine import comments, platforms, retention, threads
from engine.media import mascot


class R:
    def __init__(self, data=None, code=200):
        self.data, self.status_code = data if data is not None else {}, code

    def json(self):
        return self.data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


# ---------------- Threads ----------------

@pytest.fixture
def th_env(tmp_path, monkeypatch):
    monkeypatch.setattr(threads, "SECRETS", tmp_path)
    monkeypatch.setenv("THREADS_APP_ID", "990602627938098")
    monkeypatch.setenv("THREADS_APP_SECRET", "a" * 32)
    monkeypatch.delenv("THREADS_REDIRECT_URI", raising=False)
    return tmp_path


def test_threads_code_comes_from_the_return_address(th_env):
    url = threads.DEFAULT_REDIRECT + "?code=AQBx-hBsH3abc&state=deep_blue_files#_"
    assert threads.is_return_page(url) and threads.code_from_url(url) == "AQBx-hBsH3abc"
    assert not threads.is_return_page("https://www.threads.com/?code=x")
    assert "client_id=990602627938098" in threads.auth_url("x") and "threads_content_publish" in threads.auth_url("x")


def test_threads_connect_saves_a_60_day_login_for_the_matching_channel(th_env):
    calls = []

    class S:
        def post(self, url, data=None, **k):
            calls.append(url)
            assert data["grant_type"] == "authorization_code" and data["redirect_uri"] == threads.DEFAULT_REDIRECT
            return R({"access_token": "THshort", "user_id": 1789})

        def get(self, url, params=None, **k):
            calls.append(url)
            if url.endswith("/access_token"):
                assert params["grant_type"] == "th_exchange_token"
                return R({"access_token": "THlong", "expires_in": 5184000})
            return R({"id": "1789", "username": "deepbluefiles"})
    msg = threads.connect("CODE", "wild_instinct", session=S())           # the username wins over the hint
    rec = json.loads((th_env / "threads_deep_blue_files.json").read_text())
    assert msg.startswith("✅") and rec["access_token"] == "THlong" and rec["expires_at"] > time.time() + 59 * 86400


def test_threads_text_fits_and_keeps_one_tag():
    meta = {"title": "The ship found with nobody on board", "description": "A full meal on the table.\nmore",
            "hashtags": ["#mystery", "#history"]}
    t = threads.text_for(meta, "abc123")
    assert len(t) <= 500 and "https://youtu.be/abc123" in t and t.count("#") == 1
    assert threads.text_for({**meta, "campaign": "c1"}).endswith("#ad")
    long = threads.text_for({"title": "x " * 400})
    assert len(long) <= 500


def test_threads_post_waits_for_processing_then_publishes(th_env):
    (th_env / "threads_deep_blue_files.json").write_text(json.dumps({"user_id": "17", "access_token": "T",
                                                                    "expires_at": time.time() + 9e5}))
    states = iter(["IN_PROGRESS", "FINISHED"])

    class S:
        def get(self, url, params=None, **k):
            if url.endswith("threads_publishing_limit"):
                return R({"data": [{"quota_usage": 3}]})
            return R({"status": next(states)})

        def post(self, url, data=None, **k):
            if url.endswith("/threads"):
                assert data["media_type"] == "VIDEO" and data["video_url"].startswith("https://cdn")
                return R({"id": "c1"})
            assert data["creation_id"] == "c1"
            return R({"id": "t9"})
    import engine.publish as pub
    act = threads.post_video("deep_blue_files", "https://cdn.example/v.mp4", "hi", session=S(), dry_run=False,
                             poll_s=0)
    assert act.done and act.result == {"thread_id": "t9"}
    assert pub.Action is type(act)


def test_threads_logins_renew_before_they_run_out(th_env):
    now = time.time()
    for cid, left, age in (("a", 10, 2), ("b", 40, 2), ("c", 10, 0.5)):
        (th_env / f"threads_{cid}.json").write_text(json.dumps({"user_id": "1", "access_token": f"old_{cid}",
                                                               "expires_at": now + left * 86400,
                                                               "saved_at": now - age * 86400}))

    class S:
        def get(self, url, params=None, **k):
            assert params["grant_type"] == "th_refresh_token"
            return R({"access_token": "new", "expires_in": 5184000})
    assert threads.refresh_all(session=S(), now=now) == 1
    assert json.loads((th_env / "threads_a.json").read_text())["access_token"] == "new"
    assert json.loads((th_env / "threads_b.json").read_text())["access_token"] == "old_b"


def test_auto_platforms_wait_for_their_connection(monkeypatch):
    from engine.config import channel
    ch = channel("unsolved_after_dark")
    monkeypatch.setattr(threads, "creds", lambda cid: None)
    assert "threads" in platforms.by_mode(ch, "winners") and "threads" not in platforms.by_mode(ch, "auto")
    monkeypatch.setattr(threads, "creds", lambda cid: {"user_id": "1", "access_token": "t"})
    assert "threads" in platforms.by_mode(ch, "auto") and "threads" not in platforms.by_mode(ch, "winners")
    import engine.todo as todo
    monkeypatch.setattr(todo, "items", lambda: [{"id": "pinterest_claim", "done": True}])
    assert "pinterest" in platforms.by_mode(ch, "auto")
    kids = channel("bloop_and_friends")
    assert "threads" not in platforms.by_mode(kids, "auto") + platforms.by_mode(kids, "winners")


def test_setup_has_threads_steps_for_every_13_plus_channel():
    from engine import setup_steps as ss
    from engine.config import channels
    ids = {s["id"] for s in ss.steps()}
    for ch in channels():
        assert (f"th_{ch['id']}" in ids) == (ch.get("type") != "kids")
    assert {"threads_app", "pinterest_claim", "snapchat"} <= ids
    assert not ss.check_threads_redirect("https://localhost/threads")[0]
    assert ss.check_threads_redirect(threads.DEFAULT_REDIRECT)[0]


# ---------------- retention ----------------

def _curve(drop_at=40, bump_at=70):
    return [(i / 100, 1.0 - 0.004 * i - (0.08 if i >= drop_at else 0) + (0.05 if i == bump_at else 0), 0.6)
            for i in range(1, 101)]


def test_retention_finds_the_real_drop_and_the_rewatch():
    a = retention.analyse(_curve(), 50.0, "short")
    assert a["drops"] == [(20.0, 0.084)] and a["spikes"] == [(35.0, 0.046)]   # the dip after the bump isn't a loss
    assert 0.95 < a["hook_hold"] < 1.0 and a["rel_perf"] == 0.6


def test_retention_lesson_names_the_caption_line(tmp_path):
    (tmp_path / "captions.srt").write_text("1\n00:00:19,000 --> 00:00:21,500\nThe captain's log just stops.\n\n"
                                           "2\n00:00:34,000 --> 00:00:36,000\nThe table was still set.\n", encoding="utf-8")
    a = retention.analyse(_curve(), 50.0, "short")
    text = retention.lesson("Mary Celeste", "short", a, lambda t: retention.caption_at(tmp_path, t))
    assert "lost 8% at 0:20 during \"The captain's log just stops.\"" in text
    assert "rewatched at 0:35 (\"The table was still set.\")" in text


def test_retention_run_reads_each_video_once_and_feeds_memory(tmp_path, monkeypatch):
    import engine.publish as pub
    monkeypatch.setattr(pub, "yt_access_token", lambda cid, s=None: "tok")
    conn = retention.connect(tmp_path / "a.db")
    now = time.time()
    out = tmp_path / "vid"
    out.mkdir()
    (out / "upload.json").write_text(json.dumps({"title": "Mary Celeste", "format": "short", "duration_s": 50}))
    videos = [{"platform": "youtube", "channel": "unsolved_after_dark", "id": "v1", "item": "i1",
               "posted_at": now - 6 * 86400},
              {"platform": "youtube", "channel": "unsolved_after_dark", "id": "v2", "item": "i2",
               "posted_at": now - 1 * 86400}]                                   # too young: not read yet
    rows = [[r, w, p] for r, w, p in _curve()]

    class S:
        def get(self, url, params=None, **k):
            assert params["dimensions"] == "elapsedVideoTimeRatio" and params["filters"].startswith("video==v1")
            return R({"rows": rows})
    added = []

    class Mem:
        def add(self, kind, text, channel=None, meta=None):
            added.append((kind, channel, text))
    n = retention.run(session=S(), conn=conn, memory=Mem(), now=now, videos=videos, items={"i1": {"out_dir": str(out)}})
    assert n == 1 and added[0][0] == "playbook" and "Mary Celeste" in added[0][2]
    assert retention.run(session=S(), conn=conn, memory=Mem(), now=now, videos=videos, items={}) == 0
    s = retention.summary(conn, "unsolved_after_dark")
    assert s["short"]["videos"] == 1 and abs(s["short"]["drop_at"] - 0.4) < 0.01


def test_retention_retries_an_empty_curve_later(tmp_path, monkeypatch):
    import engine.publish as pub
    monkeypatch.setattr(pub, "yt_access_token", lambda cid, s=None: "tok")
    conn = retention.connect(tmp_path / "a.db")
    now = time.time()
    v = [{"platform": "youtube", "channel": "unsolved_after_dark", "id": "v1", "item": "i1", "posted_at": now - 6 * 86400}]
    hits = []

    class S:
        def get(self, url, params=None, **k):
            hits.append(1)
            return R({"rows": []})
    retention.run(session=S(), conn=conn, now=now, videos=v, items={})
    retention.run(session=S(), conn=conn, now=now + 3600, videos=v, items={})          # too soon: not asked again
    assert len(hits) == 2                                                                # 2 filters on the first try
    retention.run(session=S(), conn=conn, now=now + 4 * 86400, videos=v, items={})
    assert len(hits) == 4


# ---------------- comments ----------------

@pytest.fixture
def cdb(tmp_path):
    return comments.connect(tmp_path / "c.db")


def test_comments_are_fetched_once_and_spam_is_set_aside(cdb, monkeypatch):
    import engine.publish as pub
    monkeypatch.setattr(pub, "yt_access_token", lambda cid, s=None: "tok")
    monkeypatch.setattr(pub, "quota_ok", lambda u, bucket="general": True)
    monkeypatch.setattr(pub, "add_quota", lambda u, bucket="general": None)
    items = [{"snippet": {"topLevelComment": {"id": "c1", "snippet": {"textDisplay": "Was the crew ever found?",
                                                                     "authorDisplayName": "Ann", "likeCount": 5,
                                                                     "publishedAt": "2026-11-12T10:00:00Z"}}}},
             {"snippet": {"topLevelComment": {"id": "c2", "snippet": {"textDisplay": "sub4sub check my channel",
                                                                     "authorDisplayName": "X", "likeCount": 0,
                                                                     "publishedAt": "2026-11-12T10:00:00Z"}}}}]

    class S:
        def get(self, url, params=None, **k):
            assert params["videoId"] == "v1" and params["textFormat"] == "plainText"
            return R({"items": items})
    rows = comments.fetch_youtube("unsolved_after_dark", "v1", session=S())
    assert comments.store(cdb, rows, "unsolved_after_dark", "v1") == 2
    assert comments.store(cdb, rows, "unsolved_after_dark", "v1") == 0                  # no duplicates
    comments.classify(cdb, brain=None)
    st = dict(cdb.execute("SELECT comment_id, status FROM comments").fetchall())
    assert st == {"c1": "ready", "c2": "ignored"}                                         # question kept for a reply


def test_ai_drafts_are_made_safe_and_ideas_kept(cdb):
    comments.store(cdb, [{"platform": "youtube", "comment_id": "c1", "author": "Ann", "text": "Do the Dyatlov Pass next!",
                          "likes": 9, "published": time.time()}], "unsolved_after_dark", "v1")

    class Brain:
        def ask_json(self, task, prompt, **k):
            assert task == "manager" and "Dyatlov" in prompt
            return {"comments": [{"n": 1, "kind": "idea", "idea": "Dyatlov Pass incident",
                                  "reply": "Great pick! @Ann see https://spam.link we're on it"}]}, None
    comments.classify(cdb, brain=Brain())
    draft, idea, status = cdb.execute("SELECT draft, idea, status FROM comments").fetchone()
    assert "http" not in draft and "@" not in draft and status == "ready" and idea == "Dyatlov Pass incident"
    assert comments.ideas("unsolved_after_dark", conn=cdb) == ["Viewers asked: Dyatlov Pass incident"]


def test_digest_asks_and_reply_posts_only_after_the_tap(cdb, monkeypatch):
    import engine.publish as pub
    monkeypatch.setattr(pub, "yt_access_token", lambda cid, s=None: "tok")
    monkeypatch.setattr(pub, "quota_ok", lambda u, bucket="general": True)
    monkeypatch.setattr(pub, "add_quota", lambda u, bucket="general": None)
    comments.store(cdb, [{"platform": "youtube", "comment_id": "c1", "author": "Ann", "text": "Was it pirates?",
                          "likes": 2, "published": time.time()}], "unsolved_after_dark", "v1")
    cdb.execute("UPDATE comments SET kind='question', draft='No sign of pirates: nothing was stolen.', status='ready'")
    sent = []
    assert comments.digest(cdb, send=lambda text, **k: sent.append((text, k))) == 1
    assert "cr:1" in json.dumps(sent[0][1]) and "Was it pirates?" in sent[0][0]
    posts = []

    class S:
        def post(self, url, params=None, headers=None, json=None, **k):
            posts.append(json)
            return R({"id": "r1"})
    assert comments.reply(1, conn=cdb, session=S()) == "✅ Replied."
    assert posts[0]["snippet"] == {"parentId": "c1", "textOriginal": "No sign of pirates: nothing was stolen."}
    assert comments.reply(1, conn=cdb, session=S()) == "Already answered ✓" and len(posts) == 1


def test_reply_never_carries_links_or_never_topics():
    assert comments.safe_reply("Thanks! see https://x.y and @bob") == "Thanks! see and"
    assert len(comments.safe_reply("word " * 100)) <= comments.REPLY_CHARS


def test_comment_data_is_deleted_after_30_days(cdb):
    comments.store(cdb, [{"platform": "youtube", "comment_id": "old", "author": "A", "text": "hi", "likes": 0,
                          "published": 0}], "unsolved_after_dark", "v1")
    cdb.execute("UPDATE comments SET fetched_at=?", (time.time() - 31 * 86400,))
    assert comments.purge(cdb) == 1


# ---------------- lip-sync ----------------

def test_words_become_mouth_shapes():
    assert mascot.mouth_sounds("Bloop") == ["closed", "teeth", "round", "closed"]
    shapes = mascot.mouth_sounds("Five fish, see?")
    assert shapes[0] == "fv" and "wide" in shapes and "open" in shapes


def test_mouth_shapes_follow_the_loud_parts():
    sr, fps = 24000, 30
    t = np.arange(int(sr * 1.0)) / sr
    audio = np.zeros_like(t)
    for a, b in ((0.15, 0.45), (0.6, 0.9)):                       # two loud syllables: "ba ba"
        m = (t >= a) & (t < b)
        audio[m] = 0.3 * np.sin(2 * np.pi * 220 * t[m])
    track = mascot.viseme_track([(0.0, 1.0, "ba ba")], audio.astype(np.float32), sr, fps)
    loud = [track[f] for f in range(int(0.2 * fps), int(0.4 * fps))]
    assert loud.count("open") > len(loud) // 2                     # vowels sit on the loud frames
    assert "closed" in track[:int(0.2 * fps)] and track[-1] == "rest"


def test_each_mouth_shape_draws_differently():
    m = mascot.Mascot(size=200, body="#7FD3FF", outline="#2E3A59", seed=1, shape="drop")
    sprites = {v: m.draw(1.0, mouth=0.7, viseme=v) for v in mascot.VISEMES}
    vs = list(sprites)
    for i in range(len(vs)):
        for j in range(i + 1, len(vs)):
            assert np.abs(sprites[vs[i]].astype(int) - sprites[vs[j]].astype(int)).sum() > 0, (vs[i], vs[j])
    classic = mascot.Mascot(size=200, seed=1)
    assert np.array_equal(classic.draw(1.0, mouth=0.7, viseme="round"), classic.draw(1.0, mouth=0.7))

def test_threads_follows_the_instagram_reel_in_the_same_post(tmp_path, monkeypatch):
    import engine.publish as pub
    monkeypatch.setattr(pub, "LOG", tmp_path / "log.jsonl")
    out = tmp_path / "v"
    out.mkdir()
    (out / "video.mp4").write_bytes(b"x")
    (out / "upload.json").write_text(json.dumps({"title": "The ship with nobody on board", "format": "short",
                                                 "description": "A meal still on the table.", "hashtags": ["#mystery"]}))

    def fake_reel(channel_id, video, caption, **k):
        a = pub.Action("instagram", channel_id, k.get("item_id", ""), "publish Reel")
        a.done, a.result = True, {"media_id": "ig1"}
        return a
    monkeypatch.setattr(pub, "instagram_reel", fake_reel)
    monkeypatch.setattr(pub, "_duration", lambda v: 30.0)
    monkeypatch.setattr(threads, "ig_video_url", lambda cid, mid, session=None: f"https://cdn.example/{mid}.mp4")
    seen = {}

    def fake_post(cid, url, text, session=None, dry_run=True, item_id=""):
        seen.update(url=url, text=text, dry=dry_run)
        a = pub.Action("threads", cid, item_id, "publish Threads video")
        a.done, a.result = True, {"thread_id": "t1"}
        return a
    monkeypatch.setattr(threads, "post_video", fake_post)
    it = {"id": "i1", "channel": "unsolved_after_dark", "channel_name": "U", "out_dir": str(out), "publish_at": "",
          "youtube_id": "yt9"}
    acts = pub.upload_item(it, dry_run=False, platforms=("instagram", "threads"))
    th = [a for a in acts if a.platform == "threads"]
    assert th and th[0].done and seen["url"] == "https://cdn.example/ig1.mp4" and seen["dry"] is False
    assert "https://youtu.be/yt9" in seen["text"] and "#mystery" in seen["text"]
    monkeypatch.setattr(pub, "instagram_reel", lambda *a, **k: pub.Action("instagram", "x", "i1", "publish Reel"))
    acts = pub.upload_item(it, dry_run=False, platforms=("instagram", "threads"))       # no Reel -> no Threads post
    assert [a for a in acts if a.platform == "threads"][0].details.get("dry_run")
