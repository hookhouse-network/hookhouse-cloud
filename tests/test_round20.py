"""Round 20 (14 Nov 2026): Hindi numbers as words for the Parler voice (it read digits unreliably)."""
from engine.media.say import hi_words, normalise


def test_irregular_and_large_numbers():
    assert hi_words(0) == "शून्य" and hi_words(83) == "तिरासी" and hi_words(99) == "निन्यानवे"
    assert hi_words(183) == "एक सौ तिरासी"
    assert hi_words(150000) == "एक लाख पचास हज़ार"
    assert hi_words(12345678) == "एक करोड़ तेईस लाख पैंतालीस हज़ार छह सौ अठहत्तर"


def test_parler_gets_words_kokoro_keeps_digits():
    assert normalise("साल 1983 में 183 रन", "hi", engine="parler") == "साल उन्नीस सौ तिरासी में एक सौ तिरासी रन"
    assert "183" in normalise("183 रन", "hi", engine="kokoro")
    assert normalise("कोड 0091", "hi", engine="parler") == "कोड शून्य शून्य नौ एक"


def test_money_and_not_out_still_spoken_right():
    assert normalise("₹2.5 करोड़", "hi", engine="parler") == "ढाई करोड़ रुपये"
    assert normalise("100* बनाए", "hi", engine="parler") == "एक सौ नॉट आउट बनाए"


def test_claude_setting_stays_on_the_pc():
    from engine.cloud import setup
    assert setup.cloud_env_text({"USE_CLAUDE_CLI": "1", "GROQ_API_KEY": "g"}) == "GROQ_API_KEY=g\n"


def test_cloud_makes_connected_channels_first(monkeypatch):
    """Owner, 14 Nov: only connected channels can post, so the cloud's few minutes go to them first."""
    from datetime import timedelta
    from engine import autopilot
    from engine.cloud import runner
    now = autopilot._now()
    soon = (now + timedelta(hours=10)).isoformat()
    later = (now + timedelta(hours=20)).isoformat()
    its = [("2026-11-16", {"id": "a", "channel": "wild_instinct", "kind": "short", "status": "planned", "publish_at": soon}),
           ("2026-11-16", {"id": "b", "channel": "money_cheat_codes", "kind": "short", "status": "planned", "publish_at": later})]
    monkeypatch.setattr(autopilot, "items", lambda *a, **k: its)
    monkeypatch.setattr(autopilot, "_connected", lambda cid: {"youtube": cid == "money_cheat_codes", "meta": False})
    assert [it["id"] for _, it in runner._due_to_make(None, set())] == ["b", "a"]
    assert [it["id"] for _, it in runner._due_to_make(None, set(), connected_only=True)] == ["b"]
