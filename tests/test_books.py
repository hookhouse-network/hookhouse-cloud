"""Books on the dashboard / Telegram (owner, 15 Nov: see the book any time; automated, verified in Telegram)."""
import json

from engine import books


def _setup(tmp_path, monkeypatch, data):
    f = tmp_path / "books.json"
    f.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(books, "BOOKS", f)
    return f


def test_parse_bookshelf_reads_status_and_asin():
    data = {"a": {"title": "Toddler Coloring Book: Color with Bloop!"}, "b": {"title": "Big Fun Activity Book for Kids"}}
    text = ("Your titles\nToddler Coloring Book: Color with Bloop!: 24 Big\nby HookHouse Media\nKindle eBook\n"
            "+ Create Kindle eBook\nPaperback\nLive\nASIN: B0ABCDEF12\n$7.99\n"
            "Big Fun Activity Book for Kids\nPaperback\nDraft\n$9.99")
    f = books.parse_bookshelf(text, ["/en_US/title-setup/paperback/Y1QKXC53TWQ/details"], data)
    assert f["a"] == {"status": "live", "asin": "B0ABCDEF12"}
    assert f["b"]["status"] == "draft" and f["b"]["asin"] is None
    assert f["_ids"] == ["Y1QKXC53TWQ"]


def test_telegram_text_and_links(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, {
        "a": {"title": "Live Book", "status": "live", "asin": "B0ABCDEF12", "price": 7.99},
        "b": {"title": "Ready Book", "status": "ready", "isbn": "979"}})
    t = books.text()
    assert t.index("Live Book") < t.index("Ready Book")
    assert "https://www.amazon.com/dp/B0ABCDEF12" in t and "tap Publish" in t


def test_not_yet_tap_publishes_nothing(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, {"a": {"title": "X", "status": "ready"}})
    assert "not yet" in books.on_tap("bk:no:a").lower()
    assert books.load()["a"]["status"] == "ready"


def test_reject_and_change_are_stored_for_the_pc(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, {"a": {"title": "X", "status": "ready"}})
    put = []

    class FakeStore:
        def put(self, tag, name, data):
            put.append(json.loads(data))
    import engine.cloud.store as st
    monkeypatch.setattr(st, "Store", FakeStore)
    assert "Rejected" in books.on_tap("bk:rj:a")
    assert "Saved" in books.change_text("a", "bigger pictures")
    assert [p["decision"] for p in put] == ["reject", "change"] and put[1]["note"] == "bigger pictures"
    assert [b["callback_data"] for b in books.buttons("a")["inline_keyboard"][0]] == ["bk:ok:a", "bk:ch:a", "bk:rj:a"]


def test_approval_is_stored_for_the_pc(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, {"a": {"title": "X", "status": "ready"}})
    put = []

    class FakeStore:
        def put(self, tag, name, data):
            put.append((tag, name, json.loads(data)))
    import engine.cloud.store as st
    monkeypatch.setattr(st, "Store", FakeStore)
    assert "Approved" in books.on_tap("bk:ok:a")
    assert put[0][1] == "book-a.json" and put[0][2]["decision"] == "ok"


def test_dashboard_books_card(tmp_path, monkeypatch):
    from engine import dashboard
    html = dashboard._books_card({"a": {"title": "Live Book", "status": "live", "asin": "B0ABCDEF12"}})
    assert "Amazon books (1 live of 1)" in html and "amazon.com/dp/B0ABCDEF12" in html


def test_clip_punch_is_held_until_the_cut():
    """Owner 15 Nov: zoom in then zoom out mid-shot looked bad; a punch-in now holds until the next cut."""
    from types import SimpleNamespace as W
    from engine import clipv3
    shots = [{"t0": 0.0, "t1": 12.0, "layout": "A"}, {"t0": 12.0, "t1": 20.0, "layout": "A"}]
    p = clipv3.plan_punches([W(text="Million", start=2.0)], {"million"}, shots, 20.0)
    assert p == [(2.0, 12.0)]


def test_too_big_request_skips_to_next_model_without_resting(tmp_path):
    """Owner 15 Nov: one request over Groq's per-minute limit benched Groq and the whole render failed."""
    from engine.brain.router import Brain
    from engine.brain.providers import Provider, ProviderError

    class Big(Provider):
        name = "big"
        def available(self): return True
        def complete(self, *a, **k): raise ProviderError("too_big", "big: request too large")

    class Ok(Provider):
        name = "ok"
        def available(self): return True
        def complete(self, *a, **k): return "fine"
    b = Brain(providers={"big": Big(), "ok": Ok()}, routes={"writer": ["big", "ok"]},
              cooldown_minutes={"error": 5}, cooldown_file=tmp_path / "cd.json")
    assert b.ask("writer", "x").provider == "ok"
    assert not b.cooldowns.resting("big")


def test_pace_is_checked_against_the_channels_audience(tmp_path):
    """Owner 15 Nov: pace must suit the audience; spec.short_wpm is the research target per channel."""
    from engine import quality
    (tmp_path / "script.json").write_text(json.dumps({"beats": [{"narration": "word " * 100}]}), encoding="utf-8")
    (tmp_path / "captions.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nx\n\n2\n00:00:49,000 --> 00:00:50,000\ny\n",
                                           encoding="utf-8")
    slow = quality.pace_issues({"spec": {"short_wpm": 180}}, tmp_path, 55.0, "short")   # 100 words / 50 s = 120 wpm
    assert slow and "too slow" in slow[0][1]
    assert quality.pace_issues({"spec": {"short_wpm": 125}}, tmp_path, 55.0, "short") == []
