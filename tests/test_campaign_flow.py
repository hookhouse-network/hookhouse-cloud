"""Owner 17 Nov 2026: "campaign selection does not get selected and does not work, and you are not creating any clips
for that". Ticks must stick, Confirm must use them, joined campaigns must turn into footage + clips. No network."""
import json

from engine import clips, cr_footage, telegram_bot, weekly


def _kb(ticked):
    row = [{"text": ("☑️ " if i in ticked else "⬜ ") + str(i + 1), "callback_data": f"t:{i}"} for i in range(4)]
    return {"inline_keyboard": [row, [{"text": "✅ Confirm", "callback_data": "c"}]]}


def test_ticks_are_read_from_the_message_itself():
    assert telegram_bot.ticked_in(_kb({0, 2})) == [0, 2]
    assert telegram_bot.ticked_in(_kb(set())) == []
    assert telegram_bot.ticked_in({"inline_keyboard": [[{"text": "x", "callback_data": "ok:1"}]]}) is None


def test_confirm_uses_the_lists_own_campaigns(monkeypatch, tmp_path):
    monkeypatch.setattr(telegram_bot, "STATE", tmp_path / "s.json")
    telegram_bot._save({"digest": {"ids": ["new1", "new2"], "picked": []}, "digests": {"71": ["a", "b", "c", "d"]}})
    got = {}
    monkeypatch.setattr(telegram_bot, "confirm", lambda ids, conn=None: got.setdefault("ids", ids) and "ok")
    monkeypatch.setattr(telegram_bot, "send", lambda *a, **k: None)
    monkeypatch.setattr(telegram_bot, "api", lambda *a, **k: None)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "1")
    cb = {"id": "x", "data": "c", "message": {"message_id": 71, "chat": {"id": 1}, "reply_markup": _kb({1, 3})}}
    try:
        telegram_bot.handle({"callback_query": cb})
    except Exception:  # noqa: BLE001 - only the picked ids matter here
        pass
    assert got.get("ids") == ["b", "d"]


def test_ugc_film_yourself_campaigns_never_listed():
    assert telegram_bot._needs_face({"campaign_type": "ugc", "name": "SpyBox"})
    assert telegram_bot._needs_face({"campaign_type": "clipping", "name": "ApexHabits UGC"})
    assert not telegram_bot._needs_face({"campaign_type": "clipping", "content_type": "clipping podcast"})


def test_page_before_and_after_join():
    nodocs = lambda links: ([], "")                                 # noqa: E731
    half = {"text": "HookHouse Media\nAspire", "links": []}        # 17 Nov: a half-loaded page was taken for joined
    assert cr_footage.check({"url": "u"}, reader=lambda u: half, docs=nodocs)["joined"] is False
    locked = {"text": "HookHouse Media\nJoin Campaign\nReference materials\n2 files\nVisible once you join",
              "links": [], "loaded": True}
    r = cr_footage.check({"url": "u"}, reader=lambda u: locked, docs=nodocs)
    assert not r["joined"] and not r["ended"]
    joined = {"text": "HookHouse Media\nReference materials\nPodcast ep 4\nBudget", "materials": "Reference materials",
              "loaded": True,
              "links": ["https://contentrewards.com/c/campaigns/1", "https://discord.gg/x",
                        "https://drive.google.com/drive/folders/AbC123", "https://cdn.example.com/ep4.mp4",
                        "https://docs.google.com/document/d/DOC1/edit"]}
    docs = lambda links: (["https://www.youtube.com/watch?v=EP1", "https://dropbox.com/s/x/raw.mp4"], "brief")  # noqa: E731
    r = cr_footage.check({"url": "u"}, reader=lambda u: joined, docs=docs)
    assert r["joined"] and r["files"] == ["https://drive.google.com/drive/folders/AbC123",
                                          "https://cdn.example.com/ep4.mp4", "https://dropbox.com/s/x/raw.mp4"]
    assert r["episodes"] == ["https://www.youtube.com/watch?v=EP1"]


def test_paused_campaign_is_closed_not_clipped(monkeypatch, tmp_path):
    page = {"text": "Join Campaign\nPaused\nOut of budget since Nov 16.\nBudget\n$0 remaining", "links": [], "loaded": True}
    assert cr_footage.check({"url": "u"}, reader=lambda u: page, docs=lambda l: ([], ""))["ended"]
    from engine import db
    conn = db.connect(tmp_path / "s.db")
    db.save_campaign(conn, {"id": "asp", "name": "Aspire", "status": "picked"})
    monkeypatch.setattr(db, "connect", lambda *a, **k: conn)
    sent = []
    assert cr_footage.merge(FakeStore({"camp-asp.json": json.dumps({"id": "asp", "ended": True}).encode()}),
                            send=sent.append) == 1
    assert db.get_campaign(conn, "asp")["status"] == "ended" and "paused" in sent[0]


def test_drive_folder_expands_to_video_files(monkeypatch):
    html = ('<a href="https://drive.google.com/file/d/F1/view?usp=drive_web"><div class="flip-entry-title">ep1.mp4</div></a>'
            '<a href="https://drive.google.com/file/d/F2/view?usp=drive_web"><div class="flip-entry-title">logo.png</div></a>'
            '<a href="https://drive.google.com/file/d/F3/view?usp=drive_web"><div class="flip-entry-title">ep2.MOV</div></a>')

    class R:
        text = html

        def raise_for_status(self):
            pass
    monkeypatch.setattr(clips.requests, "get", lambda url, **k: R())
    assert clips.expand_source("https://drive.google.com/drive/folders/XYZ?usp=sharing") == [
        "https://drive.google.com/file/d/F1/view", "https://drive.google.com/file/d/F3/view"]
    assert clips.expand_source("https://x.com/a.mp4") == ["https://x.com/a.mp4"]


class FakeStore:
    def __init__(self, assets):
        self.a = dict(assets)

    def assets(self, tag):
        return {k: {} for k in self.a}

    def get(self, tag, name):
        return self.a.get(name)

    def delete(self, tag, name):
        self.a.pop(name, None)


def test_cloud_merge_queues_footage_and_tells_owner(monkeypatch, tmp_path):
    from engine import db
    conn = db.connect(tmp_path / "s.db")
    db.save_campaign(conn, {"id": "vi", "name": "Vi City Podcast Clips", "status": "picked"})
    monkeypatch.setattr(db, "connect", lambda *a, **k: conn)
    monkeypatch.setattr(weekly, "CLIP_SOURCES", tmp_path / "src.txt")
    monkeypatch.setattr(clips, "expand_source", lambda u: [u + "/f1", u + "/f2"])
    sent = []
    store = FakeStore({"camp-vi.json": json.dumps({"id": "vi", "joined": True, "files": ["https://d/x"]}).encode()})
    assert cr_footage.merge(store, send=sent.append) == 1
    assert db.get_campaign(conn, "vi")["status"] == "joined"
    assert (tmp_path / "src.txt").read_text().splitlines() == ["https://d/x/f1 vi", "https://d/x/f2 vi"]
    assert "2 footage file" in sent[0] and not store.a


def test_spare_clips_survive_between_cloud_runs(monkeypatch, tmp_path):
    """A spare clip whose folder isn't on this machine is fetched from the cloud copy, not thrown away."""
    monkeypatch.setattr(weekly, "CLIP_STATE", tmp_path / "pool.json")
    gone = str(tmp_path / "gone")
    weekly.save_clip_state({"pool": {"hot_take_hq": [{"out_dir": gone, "file": "c2.mp4", "at": 9e12,
                                                      "asset": "w1_clip.zip"}]}, "used": []})
    have = tmp_path / "here"
    have.mkdir()
    (have / "c2.mp4").write_bytes(b"v")
    from engine.cloud import media
    monkeypatch.setattr(media, "ensure_local", lambda store, it: have if it["cloud_asset"] == "w1_clip.zip" else None)
    import engine.cloud.store as st
    monkeypatch.setattr(st, "Store", lambda: None)
    out, f = weekly._make_clip({}, {"id": "w1_clip2"}, None, {"id": "hot_take_hq"}, None, print)
    assert (out, f) == (str(have), "c2.mp4") and weekly.clip_state()["pool"]["hot_take_hq"] == []


def test_free_limits_never_use_up_a_videos_tries(monkeypatch):
    """17 Nov: 'free pictures used up' counted as a failed try; after 3 the slot was skipped for good."""
    import time as _t
    from engine import autopilot, storyboard
    monkeypatch.setattr(storyboard, "reset_at", lambda: _t.time() + 5 * 3600)
    assert autopilot.free_limit_wait(storyboard.NoPictures("15/15 scenes")) > _t.time() + 4 * 3600

    class BrainError(Exception):
        pass
    assert autopilot.free_limit_wait(BrainError("No AI model available for 'writer'")) > _t.time()
    assert autopilot.free_limit_wait(RuntimeError("ffmpeg crashed")) is None


def test_paused_or_ended_campaigns_are_never_offered(tmp_path):
    from engine import db, discover
    conn = db.connect(tmp_path / "s.db")
    rows = [{"id": "a", "name": "FM27", "ca_ref": "sega/fm27", "status": "eligible"},
            {"id": "b", "name": "Vi City", "ca_ref": "vi-city/podcast", "status": "eligible"},
            {"id": "c", "name": "Aspire", "ca_ref": "aspire/sofia", "status": "eligible"}]
    states = {"sega/fm27": "paused", "vi-city/podcast": "live", "aspire/sofia": "ended"}

    class M:
        def tool(self, name, campaign):
            return {"campaign": {"state": states[campaign]}}
    for c in rows:
        db.save_campaign(conn, c)
    assert [c["id"] for c in discover.refresh_states(rows, mcp=M(), conn=conn)] == ["b"]
    assert db.get_campaign(conn, "a")["status"] == "ended" and db.get_campaign(conn, "c")["status"] == "ended"


def test_creator_channel_footage_is_not_offered():
    assert telegram_bot._needs_face({"campaign_type": "clipping", "allowed_sources": ["The creator's channels"]})
    assert not telegram_bot._needs_face({"campaign_type": "clipping", "allowed_sources": ["Brand footage only"]})


def test_asset_sources_and_dropbox_links_are_accepted(monkeypatch, tmp_path):
    """17 Nov: Frame.io footage reaches the cloud as asset:<name>; dropbox.com was refused as 'x.com'."""
    assert not clips.PLATFORM_LINKS.search("https://www.dropbox.com/s/abc/ep.mp4")
    assert clips.PLATFORM_LINKS.search("https://x.com/user/status/1")
    from engine.cloud import store as st
    from engine.cloud import media

    class S:
        def get(self, tag, name):
            return b"video-bytes" if name == "src-a.mp4" else None
    monkeypatch.setattr(st, "Store", lambda: S())
    p = clips.fetch_source("asset:src-a.mp4", tmp_path)
    assert p.read_bytes() == b"video-bytes"
    assert cr_footage.FOOTAGE.search("https://f.io/LGgDvyP3")


def test_brand_rules_reach_the_campaign_and_the_logo_is_drawn(tmp_path):
    """17 Nov: SEGA wants #Ad, @SEGA_West and its logo on screen; clips that miss them get rejected."""
    from engine import campaign_rules, clipv3
    text = ("Caption must include #Ad | Caption must mention @sth_game on TikTok and Instagram | "
            "Caption must mention @SEGA_West on YouTube | Show the brand logo on screen | Caption must mention @x on TikTok")
    r = campaign_rules.parse(text, ["https://crusercontent.com/o/campaigns/references/assets/logo.png"])
    assert r["required_tags"] == ["#Ad", "@sth_game", "@SEGA_West"] and r["disclosure_text"] == "Ad"
    assert r["needs_logo"] and r["logo_urls"]
    from PIL import Image
    p = tmp_path / "logo.png"
    Image.new("RGBA", (800, 400), (255, 0, 0, 255)).save(p)
    spr = clipv3.brand_logo(str(p))
    assert spr.shape[1] <= 230 and spr.shape[0] <= 150 and spr.shape[2] == 4


def test_facebook_issued_instagram_keys_are_renewed(tmp_path, monkeypatch):
    """17 Nov: the new Instagram accounts use 60-day Facebook-issued keys; they must renew by themselves."""
    import time as _t
    from engine import connect
    monkeypatch.setattr(connect, "SECRETS", tmp_path)
    (tmp_path / "meta_brain_snack.json").write_text(json.dumps({"ig_user_id": "1", "access_token": "old", "login": "facebook",
        "expires_at": _t.time() + 5 * 86400, "saved_at": _t.time() - 50 * 86400}))
    monkeypatch.setattr(connect, "meta_long_lived", lambda tok, session=None: ("new", _t.time() + 60 * 86400))
    assert connect.refresh_instagram_tokens() == ["brain_snack"]
    assert json.loads((tmp_path / "meta_brain_snack.json").read_text())["access_token"] == "new"
