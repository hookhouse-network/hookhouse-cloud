"""20 Nov: GTA campaign clipping through Kick's own Download button (engine/kick.py + cr_footage.kick_job)."""
import json
import time
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
