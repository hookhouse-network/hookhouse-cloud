"""20 Nov (owner: "avoid the strikes and any violations"): no copyrighted characters in AI pictures; campaign clips
only on the platforms their brief licenses (YouTube included)."""
from engine import ip_guard, platforms, storyboard


def test_franchise_characters_are_removed_from_picture_prompts():
    p, found = ip_guard.scrub("Doctor Doom in his green cloak and metal mask looming over the Avengers, noir lighting")
    assert "doctor doom" in found and "avengers" in found
    assert "doom" not in p.lower() and "avengers" not in p.lower()
    assert "original design" in p
    for txt in ("Darth Vader with a lightsaber", "Pikachu on a bench", "GTA 6 Vice City skyline", "Batman on a roof",
                "Harry Potter at Hogwarts", "a CoComelon style baby", "Spider-Man swinging"):
        assert ip_guard.hits(txt), txt


def test_everyday_words_are_never_touched():
    for txt in ("a predator stalks its prey in tall grass", "the terminator line on the Moon at dawn",
                "snake venom dripping from fangs", "a sonic boom over the desert", "a marvel of engineering",
                "a spy among us in a crowded station", "electrical transformers on a pole",
                "a penny-wise shopper with coupons", "a woody forest path", "Thor Heyerdahl's raft Kon-Tiki",
                "a deck of playing cards"):
        out, found = ip_guard.scrub(txt)
        assert found == [] and out == txt, (txt, found)


def test_every_storyboard_gets_the_copyright_rule():
    for cid in ("ending_decoded", "brain_snack", "clutch_tales", "itihaas_ke_raaz"):
        assert "copyrighted" in storyboard._rules({"id": cid})


def test_campaign_brief_limits_youtube_too(monkeypatch):
    monkeypatch.setattr(platforms, "_campaign_platforms", lambda cid: ["instagram_reels", "tiktok"])
    assert not platforms.campaign_allows("youtube", {"campaign": "c1"})
    assert platforms.campaign_allows("youtube", {})                      # our own videos: always
    monkeypatch.setattr(platforms, "_campaign_platforms", lambda cid: ["youtube_shorts"])
    assert platforms.campaign_allows("youtube", {"campaign": "c1"})
    monkeypatch.setattr(platforms, "_campaign_platforms", lambda cid: None)  # brief lists nothing: unchanged
    assert platforms.campaign_allows("youtube", {"campaign": "c1"})


def test_upload_skips_youtube_for_a_brief_without_it(tmp_path, monkeypatch):
    from engine import publish
    monkeypatch.setattr(publish, "LOG", tmp_path / "log.jsonl")
    monkeypatch.setattr(platforms, "_campaign_platforms", lambda cid: ["instagram_reels"])
    (tmp_path / "clip_01.mp4").write_bytes(b"x")
    (tmp_path / "clips.json").write_text('[{"file": "clip_01.mp4", "title": "t", "campaign": "c1"}]')
    called = []
    monkeypatch.setattr(publish, "youtube_upload", lambda *a, **k: called.append(1))
    it = {"id": "x1", "channel": "hot_take_hq", "out_dir": str(tmp_path), "file": "clip_01.mp4", "kind": "clip",
          "publish_at": "2026-11-21T05:00:00+05:30"}
    acts = publish.upload_item(it, dry_run=True, platforms=("youtube",))
    assert not called
    assert any(a.platform == "youtube" and a.what.startswith("SKIPPED") for a in acts)
