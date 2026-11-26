"""20 Nov: GTA campaign clipping through Kick's own Download button (engine/kick.py + cr_footage.kick_job)."""
import json
import time

import pytest
from pathlib import Path

from engine import cr_footage, kick, weekly


def test_channel_slugs_skip_site_pages():
    assert kick.channel_slugs(["https://kick.com/dasgasd3m", "https://kick.com/terms-of-service",
                               "https://www.twitch.tv/clix", "https://kick.com/Dasgasd3m/clips"]) == ["dasgasd3m"]


def test_parse_cards_keeps_recent_game_clips_most_viewed_first():
    cards = [
        ["https://kick.com/d/clips/clip_A", "00:46\n1.3K\n1.3K views\nDasgasd3m\nGas price\nGrand Theft Auto VI (GTA)\n· 1 day ago"],
        ["https://kick.com/d/clips/clip_B", "02:35\n1.8K\n1.8K views\nDasgasd3m\nStripclub\nGrand Theft Auto VI (GTA)\n· 1 day ago"],
        ["https://kick.com/d/clips/clip_C", "01:00\n44.1K\n44.1K views\nDasgasd3m\nPOUND CAKE\nRocket League\n· 4 years ago"],
        ["https://kick.com/d/clips/clip_D", "00:30\n900\n900 views\nDasgasd3m\nold gta\nGrand Theft Auto VI (GTA)\n· 5 days ago"],
        ["https://kick.com/d/clips/clip_A", "dup"],
    ]
    got = kick.parse_cards(cards, "Grand Theft Auto VI", 3 * 86400, "dasgasd3m")
    assert [c["id"] for c in got] == ["clip_B", "clip_A"]
    assert got[1] == {"id": "clip_A", "url": cards[0][0], "title": "Gas price", "views": 1300.0, "age_s": 86400,
                      "seconds": 46}


def test_age_and_views():
    assert kick.age_s("· an hour ago") == 3600 and kick.age_s("· 3 days ago") == 3 * 86400 and kick.age_s("x") is None
    assert kick._views("1.3K views") == 1300 and kick._views("2M views") == 2e6


def test_pick_skips_gambling_old_seen_and_odd_lengths():
    clips = [{"id": "1", "title": "STAKE slots win", "age_s": 10, "seconds": 40},
             {"id": "2", "title": "Gas price", "age_s": 10, "seconds": 46},
             {"id": "3", "title": "old", "age_s": 10 ** 7, "seconds": 40},
             {"id": "4", "title": "seen", "age_s": 10, "seconds": 40},
             {"id": "5", "title": "too short", "age_s": 10, "seconds": 5},
             {"id": "6", "title": "Glitch", "age_s": 10, "seconds": 155},
             {"id": "8", "title": "Stripclub", "age_s": 10, "seconds": 155},
             {"id": "7", "title": "third", "age_s": 10, "seconds": 30}]
    assert [c["id"] for c in cr_footage.pick_kick_clips(clips, {"4"}, 86400, 2)] == ["2", "6"]


class Store:
    def __init__(self):
        self.put_names = []

    def put(self, tag, name, data, ctype=None):
        self.put_names.append(name)


def _setup(tmp_path, monkeypatch, camp):
    f = tmp_path / "picked.yaml"
    f.write_text(json.dumps({"campaigns": [camp]}), encoding="utf-8")       # JSON is valid YAML
    monkeypatch.setattr(cr_footage, "PICKED_FILE", f)
    monkeypatch.setattr(cr_footage, "KICK_STATE", tmp_path / "kick_state.json")
    monkeypatch.setattr(cr_footage, "ROOT", tmp_path)


def test_kick_job_uploads_new_clips_once_per_hour(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, {"id": "dasgasd3m-x-ruckus-gta-6", "name": "Dasgasd3m", "kick": "dasgasd3m",
                                   "game": "Grand Theft Auto VI", "footage_since": "2026-11-18",
                                   "deadline": "2026-12-19", "status": "joined"})
    now = time.mktime((2026, 11, 20, 2, 0, 0, 0, 0, -1))
    seen_args = {}

    def lister(slug, game, max_age_s):
        seen_args.update(slug=slug, game=game, max_age_s=max_age_s)
        return [{"id": "clip_01ABCDEFGHIJKL", "url": "u", "title": "Gas price", "views": 1300, "age_s": 86400,
                 "seconds": 46}]

    def downloader(clip, dest: Path):
        dest.mkdir(parents=True, exist_ok=True)
        f = dest / f"{clip['id']}.mp4"
        f.write_bytes(b"mp4")
        return f
    st = Store()
    assert cr_footage.kick_job(st, log=lambda m: None, lister=lister, downloader=downloader, now=now) == 1
    assert st.put_names == ["src-dasgasd3m-x-ruckus-gta-6-kick-ABCDEFGHIJKL.mp4"]   # recover_sources() picks it up
    assert seen_args["slug"] == "dasgasd3m" and seen_args["game"] == "Grand Theft Auto VI"
    assert 1.5 * 86400 < seen_args["max_age_s"] < 2.5 * 86400                        # only footage since 18 Nov
    assert cr_footage.kick_job(st, log=lambda m: None, lister=lister, downloader=downloader, now=now + 60) == 0
    assert cr_footage.kick_job(st, log=lambda m: None, lister=lister, downloader=downloader, now=now + 3700) == 0
    assert len(st.put_names) == 1                                                   # never the same clip twice


def test_a_clip_that_never_downloads_is_skipped_after_three_tries(tmp_path, monkeypatch):
    """21 Nov: one Kick clip gave 'no file' every hour all night and was retried forever."""
    _setup(tmp_path, monkeypatch, {"id": "dasgasd3m-x-ruckus-gta-6", "name": "Dasgasd3m", "kick": "dasgasd3m",
                                   "game": "Grand Theft Auto VI", "footage_since": "2026-11-18",
                                   "deadline": "2026-12-19", "status": "joined"})
    now = time.mktime((2026, 11, 20, 2, 0, 0, 0, 0, -1))
    tried = []

    def lister(slug, game, max_age_s):
        return [{"id": "clip_BROKEN", "url": "u", "title": "Gas price", "views": 900, "age_s": 3600, "seconds": 40}]

    def downloader(clip, dest):
        tried.append(clip["id"])
        return None
    st = Store()
    for k in range(5):
        cr_footage.kick_job(st, log=lambda m: None, lister=lister, downloader=downloader, now=now + k * 3700)
    assert tried == ["clip_BROKEN"] * cr_footage.KICK_MAX_TRIES and not st.put_names


def test_kick_job_waits_for_sign_in_and_stops_after_deadline(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, {"id": "c", "kick": "x", "deadline": "2026-11-01", "status": "joined"})
    monkeypatch.setattr(cr_footage, "KICK_ACCOUNT", tmp_path / "none.json")
    logs = []
    assert cr_footage.kick_job(Store(), log=logs.append) == 0
    assert any("not signed in to Kick" in m for m in logs)
    calls = []
    assert cr_footage.kick_job(Store(), log=logs.append, lister=lambda *a, **k: calls.append(1) or [],
                               now=time.time() + 7200) == 0
    assert not calls                                                                # deadline passed: not even listed


def test_config_campaigns_reach_the_database(tmp_path, monkeypatch):
    from engine import db
    _setup(tmp_path, monkeypatch, {"id": "dasgasd3m-x-ruckus-gta-6", "status": "joined", "account": "stream_clips",
                                   "required_tags": ["#dasgasdom3"], "rules": "keep his face"})
    conn = db.connect(tmp_path / "c.db")
    db.save_campaign(conn, {"id": "dasgasd3m-x-ruckus-gta-6", "name": "board copy", "status": "review"})
    assert cr_footage.ensure_config_campaigns(conn, log=lambda m: None) == 1
    c = db.get_campaign(conn, "dasgasd3m-x-ruckus-gta-6")
    assert c["status"] == "joined" and c["account"] == "stream_clips" and c["name"] == "board copy"
    assert c["other_rules"] == ["keep his face"]
    assert cr_footage.ensure_config_campaigns(conn, log=lambda m: None) == 0          # nothing new: no rewrite
    db.save_campaign(conn, dict(c, status="ended"))
    cr_footage.ensure_config_campaigns(conn, log=lambda m: None)
    assert db.get_campaign(conn, c["id"])["status"] == "ended"                       # ended stays ended


def test_clip_slot_only_with_this_channels_footage(tmp_path, monkeypatch):
    monkeypatch.setattr(weekly, "CLIP_STATE", tmp_path / "pool.json")
    monkeypatch.setattr(weekly, "PC_CLIP_USED", tmp_path / "pc_used.json")
    src = tmp_path / "sources.txt"
    monkeypatch.setattr(weekly, "CLIP_SOURCES", src)
    ch = {"id": "stream_clips", "type": "story", "clips_first": True}
    src.write_text("asset:other.mp4 camp-x channel=podcast_clips\nasset:loose.mp4\n", encoding="utf-8")
    assert not weekly.clip_slot(ch, {"kind": "short"})                    # other channels' or loose footage: no
    src.write_text("asset:src-k.mp4 c channel=stream_clips\n", encoding="utf-8")
    assert weekly.clip_slot(ch, {"kind": "short"}) and not weekly.clip_slot(ch, {"kind": "long"})
    assert not weekly.clip_slot(dict(ch, clips_first=False), {"kind": "short"})
    weekly.remember_used_on_pc("asset:src-k.mp4")                         # the PC cut it: not again before the merge
    assert not weekly.clip_slot(ch, {"kind": "short"})


def test_pc_picture_block_survives_the_cloud_pull(monkeypatch):
    from engine import storyboard as sb
    monkeypatch.delenv("HOOKHOUSE_CLOUD", raising=False)
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "a")
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "t")
    monkeypatch.delenv("POLLINATIONS_KEY", raising=False)
    for src in ("cloudflare", "hf"):
        sb._block(src)                                  # the PC hit both daily limits
    assert sb.images_blocked()
    sb.QUOTA.parent.mkdir(parents=True, exist_ok=True)
    sb.QUOTA.write_text('{"cloudflare": 0}', encoding="utf-8")      # the pull replaced data/state with the cloud's copy
    assert sb.images_blocked()                          # still remembered: no 20-minute failed videos all night


def test_pc_with_cloud_mode_is_not_the_runner(monkeypatch):
    from engine.core.where import in_runner
    monkeypatch.setenv("HOOKHOUSE_CLOUD", "1")            # the PC's .env says cloud mode is on ...
    assert not in_runner()                                # ... but it is not the GitHub runner
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    assert in_runner()


def test_tab_opens_blank_then_navigates_full_url(monkeypatch):
    """20 Nov: /json/new?<url> cut an OAuth link at '&'; encoding it made Windows 'Pick an app' pop-ups."""
    asked = []

    class R:
        def read(self):
            return b'{"id": "t1", "webSocketDebuggerUrl": "ws://x"}'
    monkeypatch.setattr(kick.urllib.request, "urlopen", lambda req, timeout=0: asked.append(req.full_url) or R())
    t = kick._Tab("https://accounts.google.com/o/oauth2/auth?client_id=a&response_type=code")
    assert asked == [f"{kick.CDP}/json/new?about:blank"]
    assert t.url.endswith("client_id=a&response_type=code")


def test_short_kick_highlight_is_kept_whole():
    """20 Nov: the first GTA clip failed ('no usable clips'): a 40 s gameplay highlight has no 20 s talking moment."""
    from engine import clips

    class B:
        def ask_json(self, task, prompt, **k):
            assert "ONE short highlight" in prompt
            return ({"title": "He Found The Gas Price In GTA 6", "hook_options": ["Wait for the price"],
                     "caption": "c", "scores": {"hook": 8, "brand_safe": 10}}, type("R", (), {"provider": "x"})())
    (m,) = clips.whole_clip_moment(B(), [], 74.0, max_len=58)
    assert (m["start"], m["end"]) == (16.0, 74.0) and m["whole_clip"] and m["hook_options"] == ["Wait for the price"]
    assert m["title"]


def test_config_campaign_speaks_the_gates_language(tmp_path, monkeypatch):
    """20 Nov: first GTA clip stopped: 'join date unknown; the campaign allows none of our platforms'."""
    from engine import db
    _setup(tmp_path, monkeypatch, {"id": "k", "status": "joined", "platforms": ["youtube"], "joined": "2026-11-19"})
    conn = db.connect(tmp_path / "c.db")
    cr_footage.ensure_config_campaigns(conn, log=lambda m: None)
    c = db.get_campaign(conn, "k")
    assert c["platforms"] == ["youtube_shorts"] and "joined" not in c
    assert time.strftime("%Y-%m-%d", time.gmtime(c["joined_at"] + 5.5 * 3600)) == "2026-11-19"
    assert cr_footage.ensure_config_campaigns(conn, log=lambda m: None) == 0          # stable: no rewrite each run


def test_campaign_clip_is_long_enough_and_credited():
    """20 Nov (owner: "clips are not as per the campaign design, too short"): brief = 20-60 s with setup, reaction and
    payoff, credit on screen, end on kick.com/dasgasd3m. Our first clip was a 26 s source tightened to 20.8 s."""
    assert cr_footage.pick_kick_clips([{"id": "s", "title": "x", "age_s": 1, "seconds": 26},
                                       {"id": "ok", "title": "y", "age_s": 1, "seconds": 45}], set(), 99, 5)[0]["id"] == "ok"
    c = next(x for x in cr_footage.config_campaigns() if x["id"].startswith("dasgasd3m"))
    assert c["length_seconds"]["min"] >= 30 and c["length_seconds"]["max"] == 60
    assert "dasgasd3m" in c["onscreen_tag"] and "kick.com/dasgasd3m" in c["end_text"]
    import inspect
    from engine import clipv3
    src = inspect.getsource(clipv3.render_clip_v3)
    assert 'moment.get("whole_clip")' in src and "end_img" in src                  # never tightened; end line drawn


def test_kick_outro_card_is_cut(tmp_path):
    """20 Nov: free Kick downloads end with Kick's 3 s 'Clipped by <user>' card; it must never reach our Short."""
    import cv2
    import numpy as np
    from engine import clips
    p = tmp_path / "k.mp4"
    vw = cv2.VideoWriter(str(p), cv2.VideoWriter_fourcc(*"mp4v"), 10, (64, 64))
    for i in range(100):                                   # 7 s of picture, then 3 s black card
        vw.write(np.full((64, 64, 3), 140 if i < 70 else 0, np.uint8))
    vw.release()
    assert clips.content_end(p, 10.0) == round(10.0 - clips.KICK_OUTRO_S, 2)
    f = tmp_path / "flash.mp4"                             # real Kick layout: picture, ONE flash frame, dark card
    vw = cv2.VideoWriter(str(f), cv2.VideoWriter_fourcc(*"mp4v"), 30, (64, 64))
    for i in range(990):                                   # 33.0 s: 30.000 s picture, flash at 30.000, card
        vw.write(np.full((64, 64, 3), 100 if i < 900 else (162 if i == 900 else 4), np.uint8))
    vw.release()
    end = clips.content_end(f, 33.0)
    assert end == 30.0 and not end < 30                    # 20 Nov: 3.05 s cut gave 29.95 s < the 30 s minimum
    q = tmp_path / "plain.mp4"
    vw = cv2.VideoWriter(str(q), cv2.VideoWriter_fourcc(*"mp4v"), 10, (64, 64))
    for i in range(100):
        vw.write(np.full((64, 64, 3), 140, np.uint8))
    vw.release()
    assert clips.content_end(q, 10.0) == 10.0                # no card: full length


def test_headline_band_is_white_with_dark_text():
    from engine import clipv3
    img = clipv3.headline_box("GTA 6 gas was too expensive for Dasgas Dom... so he robbed the store")
    assert img.shape[1] == clipv3.OUT_W and img.shape[2] == 4 and img[2, 2, :3].tolist() == [255, 255, 255]
    assert (img[..., :3] < 60).any()                       # black text drawn


def test_held_clip_makes_the_slot_try_the_next_footage(tmp_path, monkeypatch):
    """20 Nov: Dom's clips are often explicit; a gate-held clip must not fill the slot, the next footage is tried."""
    monkeypatch.setattr(weekly, "CLIP_STATE", tmp_path / "pool.json")
    monkeypatch.setattr(weekly, "PC_CLIP_USED", tmp_path / "pc_used.json")
    src = tmp_path / "sources.txt"
    monkeypatch.setattr(weekly, "CLIP_SOURCES", src)
    src.write_text("asset:a.mp4 camp channel=stream_clips\nasset:b.mp4 camp channel=stream_clips\n", encoding="utf-8")
    from engine import clips, db
    monkeypatch.setattr(db, "get_campaign", lambda conn, cid: {"id": cid})
    monkeypatch.setattr(db, "connect", lambda *a: None)
    made = []

    def fake(brain, source, ch, campaign=None, **k):
        made.append(source)
        held = {"problems": ["breaks the rule (explicit)"]} if source.endswith("a.mp4") else {"problems": []}
        return tmp_path, [{"file": "clip_01.mp4", "gate": held}]
    monkeypatch.setattr(clips, "make_clips", fake)
    monkeypatch.setattr(weekly, "_pool_local", lambda clip: clip["out_dir"])
    item = {"id": "s1"}
    out, f = weekly._make_clip({}, item, None, {"id": "stream_clips"}, None, lambda *a: None)
    assert made == ["asset:a.mp4", "asset:b.mp4"] and item["clip_source"] == "asset:b.mp4" and f == "clip_01.mp4"
    assert "asset:a.mp4" in weekly.clip_state()["used"]           # the explicit footage is never cut again


def _two_sources(tmp_path, monkeypatch):
    monkeypatch.setattr(weekly, "CLIP_STATE", tmp_path / "pool.json")
    monkeypatch.setattr(weekly, "PC_CLIP_USED", tmp_path / "pc_used.json")
    monkeypatch.setattr(weekly, "PC_CLIP_FAILED", tmp_path / "pc_failed.json")
    src = tmp_path / "sources.txt"
    monkeypatch.setattr(weekly, "CLIP_SOURCES", src)
    src.write_text("asset:a.mp4 camp channel=stream_clips\nasset:b.mp4 camp channel=stream_clips\n", encoding="utf-8")
    from engine import db
    monkeypatch.setattr(db, "get_campaign", lambda conn, cid: {"id": cid})
    monkeypatch.setattr(db, "connect", lambda *a: None)
    monkeypatch.setattr(weekly, "_pool_local", lambda clip: clip["out_dir"])


def test_too_short_highlight_is_skipped_and_the_slot_uses_the_next_footage(tmp_path, monkeypatch):
    """20 Nov: the PC maker retried one 30 s Kick highlight (campaign minimum 30 s) every 6 minutes for hours."""
    _two_sources(tmp_path, monkeypatch)
    from engine import clips
    made = []

    def fake(brain, source, ch, campaign=None, **k):
        made.append(source)
        if source.endswith("a.mp4"):
            raise clips.UnusableFootage("Highlight is 29.9 s, under the campaign's 30 s minimum")
        return tmp_path, [{"file": "clip_01.mp4", "gate": {"problems": []}}]
    monkeypatch.setattr(clips, "make_clips", fake)
    item = {"id": "s1"}
    out, f = weekly._make_clip({}, item, None, {"id": "stream_clips"}, None, lambda *a: None)
    assert made == ["asset:a.mp4", "asset:b.mp4"] and item["clip_source"] == "asset:b.mp4"
    assert item["clip_skipped"] == ["asset:a.mp4"]                      # the done marker tells the cloud
    assert "asset:a.mp4" in weekly.clip_state()["used"]


def test_pc_failure_count_survives_the_pull_that_replaces_clip_pool(tmp_path, monkeypatch):
    """The PC's clip_pool.json is replaced on every pull: the 'failed twice -> skip' count must live on the PC too."""
    _two_sources(tmp_path, monkeypatch)
    from engine import clips
    monkeypatch.setattr("engine.core.where.in_runner", lambda: False)

    def boom(brain, source, ch, campaign=None, **k):
        raise OSError("network down")
    monkeypatch.setattr(clips, "make_clips", boom)
    for _ in range(2):
        (tmp_path / "pool.json").unlink(missing_ok=True)                # the pull replaced the cloud copy
        with pytest.raises(OSError):
            weekly._make_clip({}, {"id": "s1"}, None, {"id": "stream_clips"}, None, lambda *a: None)
    assert "asset:a.mp4" in weekly.clip_state()["used"]                 # skipped after the second failure
    assert weekly.next_source("stream_clips", weekly.clip_state()["used"])["source"] == "asset:b.mp4"


def test_done_marker_skipped_footage_is_merged_into_cloud_used(tmp_path, monkeypatch):
    monkeypatch.setattr(weekly, "CLIP_STATE", tmp_path / "pool.json")
    monkeypatch.setattr(weekly, "PC_CLIP_USED", tmp_path / "pc_used.json")
    from engine import autopilot
    from engine.cloud import runner

    class Store:
        files = {"done-s1.json": json.dumps({"id": "s1", "start": "2026-11-16", "out_rel": "output/x",
                                             "clip_source": "asset:b.mp4", "clip_skipped": ["asset:a.mp4"]}).encode()}

        def assets(self, tag):
            return list(self.files)

        def get(self, tag, name):
            return self.files.get(name)

        def delete(self, tag, name):
            self.files.pop(name, None)
    monkeypatch.setattr(autopilot, "items", lambda *a: [("2026-11-16", {"id": "s1", "status": "making", "channel": "c"})])
    monkeypatch.setattr(autopilot, "update_item", lambda *a, **k: None)
    assert runner.merge_helper(Store(), log=lambda *a: None) == 1
    assert {"asset:a.mp4", "asset:b.mp4"} <= set(weekly.clip_state()["used"])


def test_a_browser_tab_that_never_answers_cannot_freeze_the_pc_maker(monkeypatch):
    """20 Nov: kick.download waited on a DevTools reply forever; the PC maker made nothing for 30+ minutes."""
    import asyncio

    class SilentWs:
        async def send(self, msg):
            pass

        async def recv(self):
            await asyncio.sleep(3600)

    tab = kick._Tab.__new__(kick._Tab)
    tab.ws, tab.n = SilentWs(), 0
    monkeypatch.setattr(kick, "CDP_REPLY_S", 0.2)
    t0 = time.time()
    with pytest.raises(TimeoutError):
        asyncio.run(tab.cmd("Runtime.evaluate", {"expression": "1"}))
    assert time.time() - t0 < 5


def test_a_job_that_ignores_cancellation_is_abandoned(tmp_path, monkeypatch):
    """20 Nov: wait_for alone still hung 30+ min (the cancelled job's clean-up never ended). The hard limit returns."""
    import asyncio

    async def stubborn(url, dest, wait_s):
        while True:
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                continue                                    # like a clean-up that never finishes
    monkeypatch.setattr(kick, "_download", stubborn)
    monkeypatch.setattr(kick, "DOWNLOAD_EXTRA_S", 0.1)
    monkeypatch.setattr(kick, "HARD_GRACE_S", 0.5)
    t0 = time.time()
    with pytest.raises(TimeoutError, match="abandoned"):
        kick.download({"url": "https://kick.com/x/clips/1", "id": "1"}, tmp_path, wait_s=0.1)
    assert time.time() - t0 < 5


def test_whole_kick_download_has_a_wall_clock_limit(tmp_path, monkeypatch):
    import asyncio

    async def stuck(url, dest, wait_s):
        await asyncio.sleep(3600)
    monkeypatch.setattr(kick, "_download", stuck)
    monkeypatch.setattr(kick, "DOWNLOAD_EXTRA_S", 0.1)
    t0 = time.time()
    with pytest.raises(TimeoutError):
        kick.download({"url": "https://kick.com/x/clips/1", "id": "1"}, tmp_path, wait_s=0.1)
    assert time.time() - t0 < 5


def test_campaign_judge_is_told_starred_words_are_muted():
    """20 Nov: muted + starred swear words made the judge hold every Dasgas clip as 'explicit profanity'."""
    from engine import campaign_gate

    class Reply:
        def __init__(self, data):
            self.data = data

        def json(self):
            return self.data

    class Judge:
        prompt = ""

        def ask(self, task, prompt, temperature=0.0):
            Judge.prompt = prompt
            return Reply([{"rule": 1, "result": "pass", "why": ""}])
    rule = ["Keep Dom's face or voice; no explicit material"]
    assert campaign_gate._soft_check(Judge(), rule, "Dom robs the store", "what the f*** bro") == []
    assert "MUTED in the audio" in Judge.prompt
    campaign_gate._soft_check(Judge(), rule, "Dom robs the store", "what a run bro")
    assert "MUTED" not in Judge.prompt                     # no stars, no note


def test_muted_words_are_filled_with_room_tone_not_dead_silence():
    """20 Nov: digital silence where swear words were muted scored 'dead silence: sounds broken' (86/100)."""
    from engine import profanity
    af = profanity.mute_filter([(1.0, 1.8), (3.0, 3.4)], offset=0.0)
    assert af.count("volume=0") == 2 and "aeval=" in af and "random(0)" in af
    assert "between(t,1.000,1.800)+between(t,3.000,3.400)" in af
    assert profanity.mute_filter([], 0.0) == "anull"


def test_reel_variant_never_goes_under_the_campaign_minimum(tmp_path, monkeypatch):
    """20 Nov: the Reel of a 30.0 s clip was trimmed to 29.7 s and held ('outside the campaign's 30-60s')."""
    from engine import reels
    cuts = []
    monkeypatch.setattr(reels, "trimmed_variant", lambda src, out, trim: cuts.append(round(trim, 3)) or out)
    meta = {"file": "clip_01.mp4", "duration_s": 30.0, "caption": "x #ad", "hook_options": []}
    reels.clip_reel(tmp_path, meta, {}, min_s=30)
    reels.clip_reel(tmp_path, dict(meta, duration_s=45.0), {}, min_s=30)
    reels.clip_reel(tmp_path, meta, {})
    assert cuts == [0.0, 0.3, 0.3]


def test_each_clip_writes_its_own_captions_file(tmp_path):
    from engine import clips
    from engine.media.captions import Word
    ws = [Word("Dom", 10.0, 10.4), Word("robs", 10.4, 10.8), Word("the", 10.8, 11.0), Word("f***", 11.0, 11.3),
          Word("store", 11.3, 11.8), Word("now", 11.8, 12.0), Word("later", 40.0, 40.5)]
    out = clips.write_clip_srt(ws, 10.0, 30.0, tmp_path / "clip_01.srt", per_line=3)
    text = out.read_text(encoding="utf-8")
    assert text.startswith("1\n00:00:00,000 --> ") and "Dom robs the" in text and "f*** store now" in text
    assert "later" not in text                                      # outside the clip
    from engine.potential_gate import srt_text
    (tmp_path / "clip_00.srt").write_text("1\n00:00:05,000 --> 00:00:06,000\nother clip\n", encoding="utf-8")
    said, first = srt_text(tmp_path, "clip_01")
    assert said.startswith("Dom robs") and first == 0.0             # its own file, not the first in the folder


def test_swear_words_and_slurs_are_muted_and_starred():
    """20 Nov: every Dom clip was held for profanity/slurs; the brief allows muting ("cut, mute or blur")."""
    from engine import profanity
    from engine.media.captions import Word
    ws = [Word("What", 0, .3), Word("the", .3, .5), Word("fuck,", .5, .9), Word("bro", .9, 1.2),
          Word("nigga", 1.2, 1.6), Word("damn", 2, 2.3), Word("Shit!", 3, 3.4), Word("assume", 4, 4.5)]
    out, spans = profanity.clean(ws)
    assert [w.text for w in out] == ["What", "the", "f***,", "bro", "n****", "damn", "S***!", "assume"]
    assert len(spans) == 3 and spans[0][0] < .5 and spans[0][1] > .9          # padded; 'damn' and 'assume' kept
    af = profanity.mute_filter(spans, offset=0.4)
    assert af.count("volume=0") == 3 and "between(t,0.060," in af               # relative to the cut's start


def test_kick_clips_must_survive_the_outro_cut():
    """26 Nov: 8 Kick clips of 30-33 s fell to 29.x s once the 3 s outro card was cut and were thrown away after the
    download; the fetch now asks for 34 s or more."""
    from engine import cr_footage
    assert cr_footage.KICK_MIN_S >= 30 + 3 + 1
