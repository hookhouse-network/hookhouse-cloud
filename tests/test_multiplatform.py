"""Round 8 (12 Nov): every platform for every channel, winners share packs, Dailymotion, playlists, cross-links,
creator outreach on the phone, the kids Short (two big characters, clean close-ups) and the activity book."""
import json
import time

import pytest

from engine import platforms, publish


def _ch(cid, typ, **k):
    return {"id": cid, "type": typ, **k}


def test_platform_rules_kids_campaign_and_channel_lists(monkeypatch):
    kids = _ch("bloop_and_friends", "kids", made_for_kids=True)
    assert platforms.allowed(kids, "youtube") and platforms.allowed(kids, "dailymotion")
    for p in ("instagram", "facebook", "snapchat", "threads", "pinterest"):
        assert not platforms.allowed(kids, p), p
    story = _ch("unsolved_after_dark", "story")
    assert platforms.allowed(story, "snapchat") and platforms.allowed(story, "pinterest")
    assert platforms.allowed(story, "youtube_podcasts") and not platforms.allowed(_ch("b", "brainrot"), "youtube_podcasts")
    monkeypatch.setattr(platforms, "_campaign_platforms", lambda cid: ["youtube_shorts"])
    clip = _ch("hot_take_hq", "clips")
    assert platforms.allowed(clip, "youtube", {"campaign": "c1"})
    assert not platforms.allowed(clip, "instagram", {"campaign": "c1"})           # brief only licenses YouTube
    assert not platforms.allowed(clip, "dailymotion", {"campaign": "c1"})         # never our-content-only platforms
    monkeypatch.setattr(platforms, "connected", lambda ch, p: p not in ("threads", "pinterest"))   # not connected yet
    assert platforms.by_mode(story, "winners") == ["snapchat", "threads", "pinterest", "x"]
    assert platforms.allowed(clip, "dailymotion", {"permission": {"basis": "public_domain_us_gov"}})       # NASA clips
    assert not platforms.allowed(clip, "dailymotion", {"permission": {"basis": "written_permission"}})


def test_upload_skips_platforms_a_campaign_does_not_license(tmp_path, monkeypatch):
    monkeypatch.setattr(publish, "LOG", tmp_path / "log.jsonl")
    monkeypatch.setattr(platforms, "_campaign_platforms", lambda cid: ["youtube_shorts"])
    out = tmp_path / "c"
    out.mkdir()
    (out / "clip_01.mp4").write_bytes(b"x")
    (out / "clips.json").write_text(json.dumps([{"file": "clip_01.mp4", "title": "T", "caption": "c",
                                                 "permission": {"basis": "campaign"}, "campaign": "c1"}]))
    acts = publish.upload_item({"id": "i", "channel": "hot_take_hq", "channel_name": "H", "out_dir": str(out),
                                "file": "clip_01.mp4", "publish_at": ""}, dry_run=True,
                               platforms=("youtube", "instagram", "facebook", "dailymotion"))
    skipped = {a.platform for a in acts if a.what.startswith("SKIPPED: not for")}
    assert skipped == {"instagram", "facebook", "dailymotion"}


class R:
    def __init__(self, d, code=200):
        self.d, self.status_code, self.ok, self.content = d, code, code < 400, b"1"

    def json(self):
        return self.d

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


def test_dailymotion_hashtags_keep_the_hash_and_only_word_characters():
    """20-21 Nov: '#ThePlay' sent as 'ThePlay' was refused (INVALID_HASHTAGS) on every story channel."""
    assert publish.dm_hashtags(["#ThePlay", "#LakePeigneur", "#1971", "#D.B. Cooper", "ThePlay", "#", "#Avengers-Doom"]) \
        == ["#ThePlay", "#LakePeigneur", "#1971", "#DBCooper", "#AvengersDoom"]
    assert len(publish.dm_hashtags([f"#t{i}" for i in range(20)])) == 10


def test_dailymotion_upload_flow(tmp_path, monkeypatch):
    monkeypatch.setattr(publish, "LOG", tmp_path / "log.jsonl")
    monkeypatch.setattr(publish, "dm_creds", lambda c: {"client_id": "a", "client_secret": "b", "profile_id": "p1"})
    v = tmp_path / "v.mp4"
    v.write_bytes(b"x")
    seen = {}

    class S:
        def post(self, url, data=None, files=None, headers=None, timeout=None):
            if "oauth2" in url:
                return R({"access_token": "T", "expires_in": 3600})
            if url.endswith("/files/upload_sessions"):
                return R({"upload_url": "https://upload.example/u"})
            if url.startswith("https://upload.example"):
                return R({"url": "https://storage.example/f.mp4"})
            seen["body"] = json.loads(data)
            return R({"id": "x9abc"}, 201)
    a = publish.dailymotion_upload("bloop_and_friends", v, {"title": "Count <to> 5", "made_for_kids": True},
                                   session=S(), dry_run=False)
    assert a.done and a.result["video_id"] == "x9abc"
    assert seen["body"]["is_for_kids"] is True and "<" not in seen["body"]["title"]
    assert seen["body"]["source"]["file_url"] == "https://storage.example/f.mp4"


def test_dailymotion_video_id_answer_counts_as_done(tmp_path, monkeypatch):
    """18 Nov (cloud log): Dailymotion created video xbxlvcy and answered {'video_id': ...}; it was logged as a failure."""
    monkeypatch.setattr(publish, "LOG", tmp_path / "log.jsonl")
    monkeypatch.setattr(publish, "dm_creds", lambda c: {"client_id": "a2", "client_secret": "b", "profile_id": "p1"})
    v = tmp_path / "v.mp4"
    v.write_bytes(b"x")

    class S:
        def post(self, url, data=None, files=None, headers=None, timeout=None):
            if "oauth2" in url:
                return R({"access_token": "T", "expires_in": 3600})
            if url.endswith("/files/upload_sessions"):
                return R({"upload_url": "https://upload.example/u"})
            if url.startswith("https://upload.example"):
                return R({"url": "https://storage.example/f.mp4"})
            return R({"video_id": "xbxlvcy", "title": "Limo vs Pretzo", "created_at": "2026-11-18T00:34:05Z"})
    a = publish.dailymotion_upload("brain_snack", v, {"title": "Limo vs Pretzo"}, session=S(), dry_run=False)
    assert a.done and a.result == {"video_id": "xbxlvcy"}


def test_playlist_is_created_once(tmp_path, monkeypatch):
    monkeypatch.setattr(publish, "PLAYLISTS", tmp_path / "pl.json")
    monkeypatch.setattr(publish, "QUOTA_FILE", tmp_path / "q.json")
    monkeypatch.setattr(publish, "yt_access_token", lambda c, s=None: "tok")
    calls = []

    class S:
        def post(self, url, headers=None, json=None, timeout=None):
            calls.append(url)
            return R({"id": "PL1"})
    assert publish.ensure_playlist("clutch_tales", "Clutch Tales: Shorts", session=S()) == "PL1"
    assert publish.ensure_playlist("clutch_tales", "Clutch Tales: Shorts", session=S()) == "PL1"
    assert len(calls) == 1
    assert publish.playlist_title("clutch_tales", "long").endswith("full episodes")


def test_cross_link_footer_only_for_live_non_kids(monkeypatch):
    from engine import links
    links.data.cache_clear()
    d = {"unsolved_after_dark": {"youtube": "@U", "instagram": "u", "live": True},
         "deep_blue_files": {"youtube": "@D", "live": True}, "cosmos_unboxed": {"youtube": "@C", "live": False},
         "siblings": {"unsolved_after_dark": ["deep_blue_files", "cosmos_unboxed"]}}
    monkeypatch.setattr(links, "data", lambda: d)
    monkeypatch.setattr(links, "_ig_connected", lambda c: True)
    f = links.footer("unsolved_after_dark")
    assert "@D" in f and "@C" not in f and "@u" in f
    monkeypatch.setattr(links, "_ig_connected", lambda c: False)     # 17 Nov: never a handle we don't own
    assert "@u" not in links.footer("unsolved_after_dark")
    assert links.footer("unsolved_after_dark", kids=True) == ""
    assert links.footer("cosmos_unboxed") == ""


def test_share_pack_captions_fit_each_platform():
    from engine import share_packs
    caps = share_packs.captions({"title": "The Lake That Vanished " * 6, "description": "A drill hole. " * 50,
                                 "hashtags": ["#mystery", "unsolved", "#truecrime", "#extra"]},
                                {"topic": "Lake"}, {"youtube": "https://youtu.be/X"})
    assert len(caps["snapchat"]) <= 160 and len(caps["threads"]) <= 480 and len(caps["pinterest"]) <= 480
    assert caps["snapchat"].count("#") <= 3 or len(caps["snapchat"]) == 160


def test_outreach_buttons_and_trial(tmp_path, monkeypatch):
    from engine import outreach, pitch, telegram_bot as tb, weekly
    monkeypatch.setattr(pitch, "DB", tmp_path / "sys.db")
    monkeypatch.setattr(tb, "STATE", tmp_path / "tg.json")
    monkeypatch.setattr(outreach, "REGISTER", tmp_path / "clip_sources.yaml")
    monkeypatch.setattr(outreach, "PERMISSIONS", tmp_path / "perm")
    monkeypatch.setattr(outreach, "ROOT", tmp_path)
    monkeypatch.setattr(weekly, "CLIP_SOURCES", tmp_path / "clip_sources.txt")
    conn = pitch.connect()
    pid = pitch.add(conn, "Great Pod", "podcast")
    assert "pitched" in outreach.decide("s", pid)
    assert "replied" in outreach.decide("r", pid)
    assert "FILE link" in outreach.start_trial(pid, "https://www.youtube.com/watch?v=x")
    msg = outreach.start_trial(pid, "https://drive.google.com/file/d/ABC/view")
    assert "Free trial started" in msg
    assert "channel=hot_take_hq" in (tmp_path / "clip_sources.txt").read_text()
    assert "written_permission" in (tmp_path / "clip_sources.yaml").read_text()
    assert conn.execute("SELECT status FROM prospects WHERE id=?", (pid,)).fetchone()[0] == "trial"


def test_kids_short_two_big_characters_no_cut():
    from engine import kids
    try:
        lines = [{"who": w, "say": "Hi", "kind": "story", "section": "problem"} for w in ("Bloop", "Mo", "Dee", "Pip")]
        out, duo = kids.duo_lines(lines, seed=0)
        assert duo == ("Bloop", "Pip") and {ln["who"] for ln in out} == {"Bloop", "Pip"}
        kids.use_layout("short", duo=duo)
        assert len(kids.CAST) == 2 and kids.CAST["Bloop"][2] > 440        # bigger than the old 0.72 scale (317)
        for who in duo:
            cx, z = kids._solo_frame(who, kids.MED[1])
            w = kids.CW / z
            other = [n for n in duo if n != who][0]
            half = kids.CAST[other][2] * {"tall": 0.31, "sprout": 0.35, "drop": 0.37, "ears": 0.40}[kids.CAST[other][1]]
            a, b = kids.CAST[other][4] - half, kids.CAST[other][4] + half
            assert b <= cx - w / 2 + 1 or a >= cx + w / 2 - 1                # the other character is fully out
    finally:
        kids.use_layout("long")


def test_activity_book_pages_are_print_ready():
    from engine import products
    art = products._objects()
    p = products.trace_page(3, list(art)[0], art)
    assert p.size == (2550, 3300) and p.mode == "L"                          # 8.5 x 11 in at 300 dpi, B&W
