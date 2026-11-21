"""P6 printable kits (engine/printables.py, config/printables.yaml): every spec is listable (title, description, price
band, page cap, known page kinds), every page kind draws, a build makes the PDF + A4 twin + product.json, kits join
the store-cover registry and store copy, and a NEW kit waits for the owner's OK in the product gate."""
import json

import pytest

from engine import printables as pr
from engine import product_gate as pg


def test_every_kit_spec_is_listable():
    rules = pg.rules()
    kits = pr.specs()
    assert {"debt_payoff_planner", "savings_challenge_tracker"} <= set(kits)
    for pid, s in kits.items():
        assert 15 <= len(s["title"]) <= 100 and len(" ".join(str(s["description"]).split())) >= 200, pid
        assert s["tags"] and s["channel"] and s["file"].endswith(".pdf"), pid
        tname, spec = pg.ptype(pid, rules)
        lo, hi = spec["price"]
        assert lo <= float(s["price_usd"].strip("$")) <= hi, pid
        pages = sum(max(1, int(p.get("repeat", 1))) for p in s["pages"])
        assert pages <= spec["max_pages"], pid
        assert all(p["kind"] in pr.KINDS for p in s["pages"]), pid
        assert all(0 <= k < pages for k in s["cover"]["pages"]), pid          # cover previews exist
        assert pr.copy_for(pid)["hook"] and pr.cover_specs()[pid]["pdf"] == s["file"]


@pytest.mark.parametrize("page", [
    {"kind": "cover", "title": "T", "lines": ["One", "Two", "Three"]},
    {"kind": "steps", "title": "T", "blocks": [{"head": "1. A", "text": "word " * 40}], "note": "Small print."},
    {"kind": "table", "title": "T", "columns": [["Month", 20], ["Paid", 80]], "rows": 12, "row_labels": "months"},
    {"kind": "tracker", "title": "T", "fields": ["Debt: ____"], "log": [["Date", 1], ["Paid", 1]]},
    {"kind": "grid", "title": "T", "count": 52, "cols": 4, "small": "WEEK {n}", "big": "{n}", "total": "1,378"},
    {"kind": "bars", "title": "T", "rows": 8, "segments": 20, "label": "Fund: ____  Goal: ____"},
    {"kind": "milestones", "title": "T", "items": ["First", "Second"]},
    {"kind": "nospend", "title": "T", "fields": ["Month: ____"], "repeat": 2},
    {"kind": "notes", "title": "NOTES"},
])
def test_every_page_kind_draws(page):
    imgs = pr.render(page, "Kit · HookHouse Media")
    assert len(imgs) == max(1, int(page.get("repeat", 1))) and imgs[0].size == (2550, 3300)
    assert imgs[0].convert("L").resize((60, 78)).getextrema()[0] < 200       # something was drawn


def test_unknown_kind_is_refused():
    with pytest.raises(ValueError):
        pr.render({"kind": "poster"})


def test_build_makes_pdf_twin_and_record_and_waits_for_the_owner(tmp_path, monkeypatch):
    spec = {"file": "Kit.pdf", "title": "Test Kit Printable | Two Pages", "description": "d " * 120,
            "price_usd": "$4", "channel": "money_cheat_codes", "tags": ["kit"], "footer": "Kit · HookHouse",
            "pages": [{"kind": "cover", "title": "KIT", "lines": ["a"]}, {"kind": "notes", "title": "NOTES"}]}
    monkeypatch.setattr(pr, "specs", lambda: {"test_kit": spec})
    monkeypatch.setattr(pr, "PROD", tmp_path)
    out = pr.build("test_kit", log=lambda *_: None)
    info = json.loads((out / "product.json").read_text(encoding="utf-8"))
    assert info["files"] == ["Kit.pdf", "Kit_A4.pdf"] and info["pages"] == 2 and info["page_sizes"] == ["US Letter", "A4"]
    assert info["needs_owner_ok"] is True and "owner_ok" not in info and (out / "cover.jpg").exists()
    from pypdf import PdfReader
    assert len(PdfReader(str(out / "Kit.pdf")).pages) == 2
    pr.approve("test_kit")
    pr.build("test_kit", log=lambda *_: None)                                 # a rebuild keeps the OK
    again = json.loads((out / "product.json").read_text(encoding="utf-8"))
    assert again["owner_ok"]["by"] == "owner" and again["files"] == ["Kit.pdf", "Kit_A4.pdf"]


def test_kits_join_covers_and_store_copy():
    from engine import store_copy, store_covers
    assert "debt_payoff_planner" in store_covers.SPECS and store_covers.SPECS["planner_2027"]["head"]
    assert store_copy.copy_for("savings_challenge_tracker")["inside"]


def test_the_gate_holds_a_new_product_until_the_owner_says_yes(tmp_path):
    from PIL import Image
    d = tmp_path / "debt_payoff_planner"
    d.mkdir()
    body = b"%PDF-1.4\n" + b"1 0 obj << /Type /Page >> endobj\n" * 13 + b"x" * 12000 + b"\n%%EOF\n"
    (d / "Kit.pdf").write_bytes(body)
    (d / "Kit_A4.pdf").write_bytes(body)
    Image.new("RGB", (1200, 1200), "white").save(d / "store_cover.jpg")
    meta = {"title": "Debt Payoff Planner Printable | Snowball Tracker", "files": ["Kit.pdf", "Kit_A4.pdf"],
            "pages": 13, "description": "x" * 250, "price_usd": "$4", "tags": ["debt"], "channel": "money_cheat_codes",
            "page_sizes": ["US Letter", "A4"], "needs_owner_ok": True}
    (d / "product.json").write_text(json.dumps(meta))
    probs = pg.verify("debt_payoff_planner", folder=d, listed={})
    assert any("waits for the owner's OK" in p for p in probs)
    meta["owner_ok"] = {"by": "owner", "at": "2026-11-22 09:00"}
    (d / "product.json").write_text(json.dumps(meta))
    assert not any("owner" in p for p in pg.verify("debt_payoff_planner", folder=d, listed={}))
