"""Self-healing and self-learning (owner, 18 Nov 2026): heal queue, end-of-day review, posting-time learning,
stats fetch that never saves 'not ready yet' as zero views."""
import json
import sqlite3
import time

import pytest

from engine import daily_review, heal, timing


# ---------------- heal queue ----------------
def test_same_failure_on_many_videos_is_one_entry_and_becomes_high_priority():
    for vid in ("abcDEF12345", "zzzYYY98765", "qqqWWW11111"):
        heal.report("upload:instagram", f"Instagram upload failed (HTTP 400) for media {vid}", channel="c1")
    items = heal.open_items()
    assert len(items) == 1
    sig, it = items[0]
    assert it["n"] == 3 and it["kind"] == "code" and it["priority"] == "high"


def test_two_channels_with_the_same_unexplained_error_is_high_priority_at_once():
    heal.report("make", "KeyError: 'scenes'", channel="a")
    it = heal.report("make", "KeyError: 'scenes'", channel="b")
    assert it["priority"] == "high"


def test_quota_and_network_errors_never_ask_for_a_code_fix():
    for _ in range(5):
        heal.report("make", "BrainError: daily limit reached (429)", channel="a")
        heal.report("upload", "ReadTimeout: timed out", channel="b")
    assert heal.open_items("high") == []
    assert {it["kind"] for _, it in heal.open_items()} == {"self"}


def test_owner_problems_get_one_plain_to_do_message():
    sent = []
    heal.report("upload:dailymotion", "{'code': 'MISSING_PERMISSIONS'}", platform="dailymotion")
    heal.report("upload:dailymotion", "{'code': 'MISSING_PERMISSIONS'}", platform="dailymotion")
    heal.notify_due(send=sent.append)
    heal.notify_due(send=sent.append)
    assert len(sent) == 1 and "permission" in sent[0].lower()


def test_high_priority_tells_the_owner_the_exact_claude_prompt_once_a_day():
    sent = []
    for _ in range(3):
        heal.report("step:post", "AttributeError: 'NoneType' object has no attribute 'get'")
    heal.notify_due(send=sent.append, now=time.time())
    heal.notify_due(send=sent.append, now=time.time() + 3600)
    assert len(sent) == 1 and "Heal and Improve the system" in sent[0]
    heal.notify_due(send=sent.append, now=time.time() + 25 * 3600)
    assert len(sent) == 2


def test_resolved_step_closes_its_entry_and_a_comeback_reopens_it():
    for _ in range(3):
        heal.report("step:post", "ValueError: bad thing")
    assert heal.resolve("step:post:") == 1
    assert heal.open_items() == []
    heal.report("step:post", "ValueError: bad thing")
    assert len(heal.open_items()) == 1


def test_brief_for_claude_lists_high_first_and_never_shows_tokens():
    heal.improve("weak:yt:c1", "content", "4 weak points", "rework hooks")
    for _ in range(3):
        heal.report("upload:x", "boom access_token=EAAsecretvalue123 failed")
    text = heal.brief()
    assert text.index("[high]") < text.index("[improve]")
    assert "EAAsecretvalue123" not in text


def test_watchdog_feeds_failed_steps_into_the_heal_queue(monkeypatch, tmp_path):
    from engine import watchdog
    monkeypatch.setattr(watchdog, "STATE", tmp_path / "wd.json")
    for _ in range(3):
        watchdog.record_steps({"post": "TypeError: x"}, ["post", "ask"])
    assert heal.open_items("high")
    watchdog.record_steps({}, ["post", "ask"])
    assert heal.open_items("high") == []


# ---------------- daily review ----------------
def _v(title, views, hours=30, **kw):
    base = {"id": title, "item": title, "title": title, "topic": title, "kind": "short", "hours": hours,
            "slot": "22:30", "music": "", "seconds": 40, "views": views, "engaged_views": None,
            "avg_pct_viewed": None, "avg_view_s": None, "likes": None, "comments": None, "shares": None,
            "saves": None, "subs_gained": None}
    base.update(kw)
    return base


def test_judge_names_winners_losers_and_unseen_videos():
    vids = [_v("a", 1000), _v("b", 200), _v("c", 210), _v("d", 50), _v("e", 0)]
    rep = daily_review.judge(vids)
    assert any("'a'" in g for g in rep["good"])
    assert any("'d'" in b for b in rep["bad"])
    assert any("'e'" in b and "0 views" in b for b in rep["bad"])


def test_judge_flags_early_exits_and_missing_likes():
    rep = daily_review.judge([_v("x", 500, avg_pct_viewed=41.0, likes=2, shares=0)])
    text = " ".join(rep["weak"])
    assert "41%" in text and "likes" in text and "shared" in text


def test_brand_new_video_with_zero_views_is_not_called_unseen():
    rep = daily_review.judge([_v("new", 0, hours=3)])
    assert rep["bad"] == []


def test_run_writes_platform_then_channel_folders_and_feeds_memory(monkeypatch):
    vids = [_v(f"t{i}", 100 * (i + 1)) for i in range(4)]
    monkeypatch.setattr(daily_review, "collect", lambda now=None, days=7: {("youtube", "brain_snack"): vids})

    class Brain:
        def ask_json(self, task, prompt, **kw):
            assert task == "manager" and "t3" in prompt
            return {"verdict": "ok", "keep": ["question hooks"], "change": ["shorter intro"],
                    "next_topics": ["octopus hearts"], "hooks": ["Wait..."], "music": "playful"}, None

    added = []

    class Mem:
        def search(self, *a, **k):
            return []

        def add(self, kind, text, channel=None, meta=None):
            added.append((kind, text, channel))

    sent = []
    out = daily_review.run(brain=Brain(), memory=Mem(), send=sent.append, log=lambda m: None)
    folder = daily_review.REVIEWS / "youtube" / "brain_snack"
    assert out["reports"] == 1 and (folder / f"{out['day']}.md").exists()
    assert json.loads((folder / "insights.json").read_text(encoding="utf-8"))["music"] == "playful"
    assert ("playbook", "CHANGE: shorter intro", "brain_snack") in added
    assert sent and "End-of-day review" in sent[0]
    assert "octopus hearts" in " ".join(daily_review.planner_hints("brain_snack"))
    assert "Brain Snack" in daily_review.telegram_text("brain snack") or "brain_snack" in daily_review.telegram_text()


# ---------------- posting times ----------------
def test_timing_scores_are_relative_to_the_channel_median_and_shrunk():
    t0 = 1_800_000_000
    rows = [("c", t0, 100)] * 4 + [("c", t0 + 3600, 400)] * 4
    sc = timing.scores(rows)["c"]
    lo, hi = sorted(sc.values(), key=lambda v: v["score"])
    assert hi["score"] > 1 > lo["score"] and hi["n"] == 4


def test_timing_keeps_research_slots_until_there_is_enough_evidence():
    ch = {"id": "c", "market": "US"}
    rec = timing.choose(ch, {"01:00": {"n": 5, "score": 3.0}}, n_videos=5)
    assert rec["slots"] == rec["default"] and rec["explore"]


def test_timing_switches_to_a_clearly_better_measured_slot():
    ch = {"id": "c", "market": "US"}
    ev = {"22:30": {"n": 6, "score": 0.6}, "01:00": {"n": 5, "score": 1.8}}
    rec = timing.choose(ch, ev, n_videos=20)
    assert "01:00" in rec["slots"] and len(rec["slots"]) == len(rec["default"])


def test_planner_uses_learned_slots_and_explores_twice_a_week(monkeypatch):
    from datetime import date
    from engine import weekly
    from engine.config import channel
    ch = channel("brain_snack")
    timing.STATE.write_text(json.dumps({"channels": {"brain_snack": {"slots": ["01:00"], "explore": "07:30"}}}),
                            encoding="utf-8")
    slots = weekly.slots_for(ch, date(2026, 11, 23))
    hm = {(w.weekday(), w.strftime("%H:%M")) for w, _ in slots}
    assert (0, "01:00") in hm                              # Monday: the learned slot
    assert any(d == 2 and t == "07:30" for d, t in hm)     # Wednesday: the experiment


# ---------------- stats fetch ----------------
def test_young_youtube_video_uses_public_counters_not_empty_analytics(monkeypatch):
    from engine import stats_fetch
    monkeypatch.setenv("YOUTUBE_API_KEY", "k")

    class R:
        status_code = 200

        def __init__(self, j):
            self._j = j

        def json(self):
            return self._j

        def raise_for_status(self):
            pass

    class S:
        def get(self, url, **kw):
            assert "youtubeanalytics" not in url
            return R({"items": [{"statistics": {"viewCount": "57", "likeCount": "3"}}]})

    m = stats_fetch._youtube({"posted_at": time.time() - 5 * 3600, "channel": "c", "id": "v"}, S())
    assert m["views"] == 57 and m["likes"] == 3


def test_old_zero_snapshots_from_empty_analytics_are_repaired(monkeypatch, tmp_path):
    from engine import analytics, stats_fetch
    conn = analytics.connect(tmp_path / "a.db")
    now = time.time()
    analytics.record(conn, item_id="i", channel="c", platform="youtube", video_id="v", posted_at=now - 3600,
                     hours_after=2, views=0, avg_pct_viewed=0)
    monkeypatch.setattr(stats_fetch, "posted_videos", lambda: [])
    monkeypatch.setattr(stats_fetch, "channel_stats", lambda *a, **k: 0)
    stats_fetch.fetch(conn=conn, log=lambda m: None)
    assert conn.execute("SELECT COUNT(*) FROM video_metrics").fetchone()[0] == 0


def test_scheduled_video_is_not_queried_with_end_before_start(monkeypatch):
    from engine import connect
    monkeypatch.setattr(connect, "yt_access_token", lambda ch, s=None: "tok")

    class S:
        def get(self, *a, **k):
            raise AssertionError("no call for a video that isn't public yet")
    assert connect.fetch_youtube_metrics("c", "v", "2026-11-22", "2026-11-18", session=S()) == {}


# ---------------- connection test before posting ----------------
def test_preflight_warns_before_the_slot_and_only_once(monkeypatch, tmp_path):
    from engine import doctor, preflight
    monkeypatch.setattr(preflight, "STATE", tmp_path / "pf.json")
    monkeypatch.setattr(preflight, "due_targets", lambda now=None: {"instagram": {"brain_snack"}})
    calls = []

    def meta(session):
        calls.append(1)
        return [{"area": "Instagram brain_snack", "status": "bad", "seen": "Session has expired", "fix": "reconnect"},
                {"area": "Instagram other_channel", "status": "bad", "seen": "expired", "fix": ""}]
    monkeypatch.setattr(doctor, "meta", meta)
    sent = []
    probs = preflight.run(send=sent.append, log=lambda m: None)
    assert len(probs) == 1 and "brain_snack" in probs[0]          # nothing due on the other channel
    assert len(sent) == 1 and "Connection test" in sent[0]
    preflight.run(send=sent.append, log=lambda m: None)           # cached: no second check, no second message
    assert len(calls) == 1 and len(sent) == 1
    assert heal.open_items()[0][1]["kind"] == "owner"


def test_preflight_does_nothing_when_no_post_is_due(monkeypatch):
    from engine import preflight
    monkeypatch.setattr(preflight, "due_targets", lambda now=None: {})
    assert preflight.run(send=lambda m: 1 / 0, log=lambda m: None) == []


# ---------------- music that fits the video ----------------
def test_mood_comes_from_the_script_then_keywords_then_the_channel():
    from engine.media import music_library as ml
    assert ml.mood_for({"id": "brain_snack"}, {"music_mood": "Epic"}) == "epic"
    assert ml.mood_for({"id": "clutch_tales"}, {"title": "The ghost ship that vanished"}) == "mystery"
    assert ml.mood_for({"id": "money_cheat_codes"}, {"title": "Why prices end in 99"}) == "lofi"
    assert ml.mood_for({"id": "nobody"}, {}, fallback="upbeat") == "playful"


class _Resp:
    def __init__(self, j=None, content=b"", status=200):
        self._j, self.content, self.status_code, self.ok = j, content, status, status == 200

    def json(self):
        return self._j

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


def _hit(i, lic="cc0", dur=90_000, title="Calm theme"):
    return {"id": f"t{i}", "title": title, "creator": "Ann", "license": lic, "license_version": "4.0",
            "url": f"https://cdn.freesound.org/previews/{i}.mp3", "foreign_landing_url": f"https://freesound.org/s/{i}",
            "duration": dur, "source": "freesound", "tags": []}


@pytest.mark.real_music_library
def test_catalogue_keeps_only_commercial_music_and_never_jamendo():
    from engine.media import music_library as ml
    seen = []

    class S:
        def get(self, url, params=None, **kw):
            seen.append(params)
            return _Resp({"results": [_hit(1), _hit(2, dur=3_000), _hit(3, title="vocal chop"), _hit(4, lic="by")]})
    ml.refresh(["calm"], session=S(), log=lambda m: None)
    ids = [t["id"] for t in json.loads(ml.CATALOG.read_text(encoding="utf-8"))["moods"]["calm"]["tracks"]]
    assert ids == ["t1", "t4"]                                  # too short and vocals dropped
    assert all(p["license_type"] == "commercial" and "jamendo" not in p["source"] for p in seen)


@pytest.mark.real_music_library
def test_track_rotates_per_channel_and_credits_cc_by():
    from engine.media import music_library as ml
    ml.CATALOG.write_text(json.dumps({"moods": {"calm": {"at": time.time(), "tracks": [
        {"id": "a", "title": "A", "creator": "X", "license": "by", "license_version": "4.0",
         "url": "https://x/a.mp3", "page": "https://x/a", "seconds": 60}]}}, "used": {}}), encoding="utf-8")

    class S:
        def get(self, url, **kw):
            return _Resp(content=b"0" * 30_000)
    p, t = ml.track("calm", "c1", session=S())
    assert p.exists() and "CC BY 4.0" in ml.credit(t) and "https://x/a" in ml.credit(t)
    assert json.loads(ml.CATALOG.read_text(encoding="utf-8"))["used"]["c1"] == ["a"]


def test_music_bed_loops_to_length_with_fades(tmp_path):
    import subprocess
    from engine.media import music_library as ml
    src = tmp_path / "tone.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=8", str(src)],
                   check=True)
    b = ml.bed(src, 20.0, sr=16000)
    assert len(b) == 20 * 16000 and abs(b[0]) < 0.01 and abs(b[-1]) < 0.01 and b.max() <= 0.71


# ---------------- festivals, holidays, anniversaries ----------------
def test_holidays_go_to_the_right_market_and_kids_get_only_kid_days():
    from datetime import date
    from engine import events
    h = events.holiday_hints(date(2027, 3, 15), days=14)
    assert any("Holi" in x for x in h["itihaas_ke_raaz"])
    assert not any("Holi" in x for x in h.get("money_cheat_codes", []))
    assert any("Easter" in x for x in h["brain_snack"])
    assert all(events.KIDS_DAYS.search(x) for x in h["bloop_and_friends"])
    assert "hot_take_hq" not in h                                   # clip channels: the footage decides


@pytest.mark.real_events
def test_round_anniversaries_are_routed_by_whole_words():
    from datetime import date
    from engine import events

    class S:
        def get(self, url, **kw):
            return _Resp({"selected": [
                {"year": 2001, "text": "Astronomers detected sodium in the atmosphere of a planet."},
                {"year": 1996, "text": "A hijacked plane crashed into the Indian Ocean."},
                {"year": 1993, "text": "A random event that is 33 years old."}]})
    h = events.anniversary_hints(date(2026, 11, 23), days=1, session=S())
    assert any("25 years ago" in x for x in h["cosmos_unboxed"])
    assert "cricket_ke_kisse" not in h and "itihaas_ke_raaz" not in h      # 'sodium', 'Indian Ocean'
    assert any("30 years ago" in x for x in h["unsolved_after_dark"])
    assert not any("33 years" in x for v in h.values() for x in v)
