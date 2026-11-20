"""20 Nov (owner: "building, checking and listing new products, plus promo Shorts for them"; gates strictest,
nothing bypasses them)."""
import json

import pytest

from engine import product_gate as pg, product_promo as pp


def _pdf(path, pages):
    body = b"%PDF-1.4\n" + b"".join(b"1 0 obj << /Type /Page >> endobj\n" for _ in range(pages)) + \
        b"2 0 obj << /Type /Pages >> endobj\n" + b"x" * 12000 + b"\n%%EOF\n"
    path.write_bytes(body)


@pytest.fixture
def prod(tmp_path):
    d = tmp_path / "habit_tracker_2027"
    d.mkdir()
    _pdf(d / "Tracker.pdf", 30)
    from PIL import Image
    Image.new("RGB", (1200, 1200), "white").save(d / "store_cover.jpg")
    meta = {"title": "2027 Habit Tracker & New Year Resolution Planner", "files": ["Tracker.pdf"], "pages": 30,
            "description": "x" * 250, "price_usd": "$4", "tags": ["habit tracker"], "channel": "money_cheat_codes",
            "promo_angles": ["The 2-minute rule"]}
    (d / "product.json").write_text(json.dumps(meta))
    return d, meta


def _write(d, meta):
    (d / "product.json").write_text(json.dumps(meta))


def test_a_good_product_passes(prod):
    d, _ = prod
    assert pg.verify("habit_tracker_2027", folder=d, listed={}) == []


@pytest.mark.parametrize("change, expect", [
    ({"title": "Short"}, "title is 5 characters"),
    ({"description": "too short"}, "description is"),
    ({"tags": []}, "no tags"),
    ({"price_usd": "$0"}, "outside the tracker band"),
    ({"price_usd": "$19"}, "outside the tracker band"),
    ({"pages": 30, "ai_art": True}, "made with AI pictures"),
    ({"pages": 60}, "PDF has 30 pages but the listing says 60"),
    ({"title": "Mickey Mouse Habit Tracker for 2027 Fans"}, "protected franchise"),
    ({"files": ["Missing.pdf"]}, "download file missing"),
])
def test_each_problem_holds_the_product(prod, change, expect):
    d, meta = prod
    _write(d, dict(meta, **change))
    assert any(expect in p for p in pg.verify("habit_tracker_2027", folder=d, listed={})), \
        pg.verify("habit_tracker_2027", folder=d, listed={})


def test_broken_pdf_cover_and_duplicates(prod):
    d, meta = prod
    (d / "Tracker.pdf").write_bytes(b"%PDF-1.4\n" + b"y" * 20000)         # cut off: no pages, no %%EOF
    probs = pg.verify("habit_tracker_2027", folder=d, listed={})
    assert any("incomplete" in p for p in probs) and any("no pages" in p for p in probs)
    _pdf(d / "Tracker.pdf", 30)
    (d / "store_cover.jpg").unlink()
    assert any("no store cover" in p for p in pg.verify("habit_tracker_2027", folder=d, listed={}))
    from PIL import Image
    Image.new("RGB", (1200, 1200), "white").save(d / "store_cover.jpg")
    dup = {"other": {"payhip": {"title": meta["title"]}}}
    assert any("same title" in p for p in pg.verify("habit_tracker_2027", folder=d, listed=dup))


def test_listing_is_refused_without_the_gate(monkeypatch):
    from engine import store_publish as sp
    monkeypatch.setattr(pg, "verify", lambda pid, store="payhip", **k: ["description is 10 characters"])
    monkeypatch.setattr(pg, "hold", lambda *a, **k: None)
    out = []
    assert sp._gate_ok("x", "payhip", out, lambda m: None) is False and "held by the product gate" in out[0]
    monkeypatch.setattr(pg, "verify", lambda pid, store="payhip", **k: (_ for _ in ()).throw(RuntimeError("x")))
    assert sp._gate_ok("x", "payhip", [], lambda m: None) is False                  # a crashing gate holds


# ---------------------------------------------------------------- promo Shorts
@pytest.fixture
def promos(tmp_path, monkeypatch, prod):
    d, meta = prod
    monkeypatch.setattr(pp, "FILE", tmp_path / "promos.json")
    monkeypatch.setattr(pp, "PROD", d.parent)
    (d.parent / "listed.json").write_text(json.dumps({"habit_tracker_2027": {"payhip": {"public": "https://payhip.com/b/X"}}}))
    monkeypatch.setattr("engine.config.channel", lambda cid: {"id": cid, "type": "story"})
    return d


def test_promo_registers_once_and_never_for_kids(promos, monkeypatch):
    assert pp.register("habit_tracker_2027") and not pp.register("habit_tracker_2027")
    assert not pp.register("free_habit_tracker_2027")
    monkeypatch.setattr("engine.config.channel", lambda cid: {"id": cid, "type": "kids"})
    pp._save({})
    assert not pp.register("habit_tracker_2027")


def test_one_promo_per_week_capped_and_linked(promos):
    pp.register("habit_tracker_2027")
    p1 = pp.promo_for("money_cheat_codes", "2026-11-23")
    assert p1 == {"pid": "habit_tracker_2027", "title": "2027 Habit Tracker & New Year Resolution Planner",
                  "angle": "The 2-minute rule"}
    assert pp.promo_for("money_cheat_codes", "2026-11-23") is None                # never twice in a week
    assert pp.promo_for("other_channel", "2026-11-30") is None
    for w in ("2026-11-30", "2026-12-07"):
        assert pp.promo_for("money_cheat_codes", w)
    assert pp.promo_for("money_cheat_codes", "2026-12-14") is None                # PER_PRODUCT = 3
    line = pp.description_line({"product": "habit_tracker_2027"})
    assert line.strip() == "🛒 2027 Habit Tracker & New Year Resolution Planner: https://payhip.com/b/X"


def test_the_description_carries_the_link(promos, tmp_path):
    from engine import publish
    pp.register("habit_tracker_2027")
    out = tmp_path / "v"
    out.mkdir()
    (out / "upload.json").write_text(json.dumps({"title": "T", "description": "Useful video."}))
    meta = publish.item_meta({"id": "i", "out_dir": str(out), "product": "habit_tracker_2027"})
    assert meta["description"].endswith("https://payhip.com/b/X")
    (out / "upload.json").write_text(json.dumps({"title": "T", "description": "x", "made_for_kids": True}))
    assert "payhip" not in publish.item_meta({"id": "i", "out_dir": str(out), "product": "habit_tracker_2027"})["description"]


def test_focused_products_page_cap_and_file_size(prod, monkeypatch):
    d, meta = prod
    _pdf(d / "Tracker.pdf", 60)
    _write(d, dict(meta, pages=60))
    assert any("at most 40 pages" in p for p in pg.verify("habit_tracker_2027", folder=d, listed={}))
    monkeypatch.setattr(pg, "rules", lambda: {"max_file_mb": 0.005, "types": {}})
    assert any("MB (allowed" in p for p in pg.verify("habit_tracker_2027", folder=d, listed={}))


def test_types_follow_the_id():
    r = pg.rules()
    assert pg.ptype("senior_sudoku", r)[0] == "puzzle" and pg.ptype("habit_tracker_2027", r)[0] == "tracker"
    assert pg.ptype("planner_bundle_2027", r)[0] == "bundle" and pg.ptype("something_new", r)[0] == "default"
