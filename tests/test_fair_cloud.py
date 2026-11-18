"""18 Nov (owner: "why the same videos again and again, where are the other channel's videos, telegram is not
working"): fair render order, missed videos still made, Brain Snack never repeats a format, light inbox runs."""
from datetime import timedelta

from engine import autopilot
from engine.cloud import runner


def _it(i, ch, hours, status="planned", kind="short"):
    return ("2026-11-16", {"id": i, "channel": ch, "kind": kind, "status": status,
                           "publish_at": (autopilot._now() + timedelta(hours=hours)).isoformat()})


def _setup(monkeypatch, its):
    monkeypatch.setattr(autopilot, "items", lambda *a, **k: its)
    monkeypatch.setattr(autopilot, "_connected", lambda cid: {"youtube": True, "meta": False})
    from engine import storyboard
    monkeypatch.setattr(storyboard, "images_blocked", lambda: False)


def test_channels_without_recent_videos_go_first(monkeypatch):
    its = [_it("b1", "brain_snack", 5), _it("b2", "brain_snack", 8), _it("posted", "brain_snack", -5, "posted"),
           _it("d1", "deep_blue_files", 20), _it("w1", "wild_instinct", 30)]
    _setup(monkeypatch, its)
    order = [it["id"] for _, it in runner._due_to_make(None, set())]
    assert order[:2] == ["d1", "w1"]                 # never-served channels before the one that already posted
    assert order.index("b1") < order.index("b2")      # brain snack's second video only after one of each


def test_missed_video_is_still_made_unless_a_newer_one_is_coming(monkeypatch):
    its = [_it("old", "ending_decoded", -20), _it("gone", "ending_decoded", -24 * 5),
           _it("old2", "cosmos_unboxed", -10), _it("new2", "cosmos_unboxed", 12)]
    _setup(monkeypatch, its)
    ids = {it["id"] for _, it in runner._due_to_make(None, set())}
    assert "old" in ids                               # 20 h late: still made (the missed step gives a new slot)
    assert "gone" not in ids                          # beyond OVERDUE_D (the window ends there)
    assert "new2" in ids and "old2" not in ids        # cosmos: make the upcoming one, not the stale one


def test_brain_snack_never_repeats_the_last_two_formats(tmp_path, monkeypatch):
    from engine.snack import maker
    monkeypatch.setattr(maker, "ROOT", tmp_path)
    out = tmp_path / "output" / "brain_snack"
    for n in ("20261115_213338_spiral", "20261116_204530_versus", "20261117_130229_ladder", "20261117_131859_spiral",
              "notes"):
        (out / n).mkdir(parents=True)
    made = maker.made_formats("brain_snack")
    assert made == ["spiral", "versus", "ladder", "spiral"]
    picks = {maker.choose_format([], made=made) for _ in range(100)}
    assert picks and not picks & {"spiral", "ladder"}


def test_light_tick_only_handles_the_inbox(monkeypatch):
    calls = []
    monkeypatch.setattr(runner, "Store", lambda: object())
    monkeypatch.setattr(runner.state, "pull", lambda s: 0)
    monkeypatch.setattr(runner.state, "push", lambda s: 0)
    monkeypatch.setattr(runner, "_kv", lambda: None)
    for name in ("merge_helper", "ensure_media", "process_inbox", "_campaign_footage", "snapshot"):
        monkeypatch.setattr(runner, name, lambda *a, _n=name, **k: calls.append(_n))
    monkeypatch.setattr(autopilot, "_post_due", lambda log: calls.append("post"))
    monkeypatch.setattr(autopilot, "_daily", lambda log: calls.append("daily"))
    runner.tick(log=lambda *_: None, light=True)
    assert "process_inbox" in calls and "post" in calls and "daily" not in calls and calls[-1] == "snapshot"


def test_live_stats_at_most_every_few_hours(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "LIVE_AT", tmp_path / "live_at.txt")
    assert runner._live_due() is True
    assert runner._live_due() is False                # just ran


def test_clip_sources_are_kept_and_campaign_footage_comes_back(tmp_path, monkeypatch):
    from engine import cr_footage, db, weekly
    from engine.cloud import state
    assert "data/clip_sources.txt" in state.PATHS          # kept between cloud runs
    monkeypatch.setattr(weekly, "CLIP_SOURCES", tmp_path / "clip_sources.txt")
    cid = "sega-steam-black-friday-sale-clipping"
    monkeypatch.setattr(db, "connect", lambda: None)
    monkeypatch.setattr(db, "list_campaigns", lambda conn, s: [{"id": cid}] if s == "joined" else [{"id": "ab"}])

    class Store:
        def assets(self, tag):
            return {f"src-{cid[:30]}-Set1_9x16.mp4": {}, "src-ab-x.mp4": {}, "done-1.json": {}}
    assert cr_footage.recover_sources(Store(), log=lambda *_: None) == 2
    lines = (tmp_path / "clip_sources.txt").read_text().splitlines()
    assert f"asset:src-{cid[:30]}-Set1_9x16.mp4 {cid}" in lines and "asset:src-ab-x.mp4 ab" in lines
    assert cr_footage.recover_sources(Store(), log=lambda *_: None) == 0        # nothing twice


def test_storage_and_runs_live_in_different_repos(monkeypatch):
    from engine.cloud import setup, store
    monkeypatch.setenv("GITHUB_REPOSITORY", "hookhouse-network/hookhouse-cloud")
    monkeypatch.setenv("STORE_REPO", "hookhouse-network/hookhouse")
    monkeypatch.setenv("STORE_TOKEN", "store-token")
    monkeypatch.setenv("GITHUB_TOKEN", "actions-token")
    monkeypatch.delenv("CODE_REPO", raising=False)
    assert store.repo() == "hookhouse-network/hookhouse" and store.token() == "store-token"
    assert store.code_repo() == "hookhouse-network/hookhouse-cloud"
    files = setup.public_files()
    assert files and not any(f.startswith(("docs/", "research_notes/")) or f in ("config/owner_todo.yaml", "CLAUDE.md")
                             for f in files)
    assert setup._USER_PATH.sub("C:/Users/<user>", r"see C:/Users/<user>\x.txt") == r"see C:/Users/<user>\x.txt"


def test_planned_topic_gets_a_topic_format_after_a_physics_video():
    from engine.snack import maker
    after_physics = {maker.choose_format([], made=["readfast", "spiral"], topic="The Day of Two Noons")
                     for _ in range(50)}
    assert after_physics <= maker.TOPIC_FORMATS - {"readfast"}          # ladder (readfast was 2 ago)
    after_topic = {maker.choose_format([], made=["spiral", "ladder"], topic="x") for _ in range(80)}
    assert after_topic & {"multiply", "versus", "readfast"}             # physics games still come (best views)


def test_never_made_topics_go_back_to_the_pool(tmp_path, monkeypatch):
    import json
    from datetime import datetime, timedelta, timezone
    from engine import weekly
    monkeypatch.setattr(weekly, "OUTPUT_DIR", tmp_path / "out")
    monkeypatch.setattr(weekly, "WEEKS_DIR", tmp_path / "weeks")
    now = datetime.now(timezone.utc)
    items = [{"channel": "deep_blue_files", "topic": "Old unmade", "status": "planned",
              "publish_at": (now - timedelta(days=5)).isoformat()},
             {"channel": "deep_blue_files", "topic": "Coming soon", "status": "planned",
              "publish_at": (now + timedelta(days=1)).isoformat()},
             {"channel": "deep_blue_files", "topic": "Posted one", "status": "posted",
              "publish_at": (now - timedelta(days=6)).isoformat()}]
    (tmp_path / "weeks" / "w").mkdir(parents=True)
    (tmp_path / "weeks" / "w" / "plan.json").write_text(json.dumps({"start": "w", "items": items}))
    past = weekly.past_topics("deep_blue_files")
    assert "Coming soon" in past and "Posted one" in past and "Old unmade" not in past


def test_browser_session_keeps_only_our_sites_and_setcookie_fields():
    from engine.cloud import browser_session as bs
    raw = [{"name": "s", "value": "1", "domain": ".contentrewards.com", "path": "/", "secure": True, "httpOnly": True,
            "sameSite": "Lax", "expires": 1900000000, "size": 9, "priority": "Medium", "session": False},
           {"name": "t", "value": "2", "domain": "next.frame.io", "path": "/", "expires": -1, "session": True},
           {"name": "x", "value": "3", "domain": ".gmail.com", "path": "/"},
           {"name": "y", "value": "4", "domain": "notcontentrewards.com", "path": "/"}]
    out = bs.clean(raw)
    assert [c["name"] for c in out] == ["s", "t"]                      # no mail, no look-alike domains
    assert "size" not in out[0] and "priority" not in out[0] and out[0]["expires"] == 1900000000
    assert "expires" not in out[1]                                       # session cookie


def test_cloud_browser_jobs_only_in_the_cloud(monkeypatch):
    from engine.cloud import browser_session as bs
    monkeypatch.delenv("HOOKHOUSE_CLOUD", raising=False)
    assert bs.cloud_jobs(object(), log=lambda *_: None) == 0
