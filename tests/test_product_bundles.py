"""P6: rebuilding a bundle keeps fields added after it was made (page_sizes) and brings a part's hyperlinked digital
bonus along with a description line, so bundle buyers never get less than buyers of the single product."""
import json

from engine import product_bundles as pb


def _part(root, pid, files, pages):
    d = root / pid
    d.mkdir()
    for f in files:
        (d / f).write_bytes(b"%PDF-1.4 x")
    (d / "product.json").write_text(json.dumps({"files": files, "pages": pages}), encoding="utf-8")


def test_rebuild_keeps_later_fields_and_adds_the_digital_bonus(tmp_path, monkeypatch):
    _part(tmp_path, "planner", ["P.pdf", "P_A4.pdf", "P_Digital_GoodNotes_Hyperlinked.pdf"], 21)
    _part(tmp_path, "habits", ["H.pdf", "H_A4.pdf"], 14)
    spec = {"parts": ["planner", "habits"], "title": "T", "price_usd": "$9", "price_inr": "₹199",
            "channel": "c", "description": "Two planners.", "tags": ["a"]}
    monkeypatch.setattr(pb, "PROD", tmp_path)
    monkeypatch.setattr(pb, "BUNDLES", {"b": spec})
    (tmp_path / "b").mkdir()
    (tmp_path / "b" / "product.json").write_text(json.dumps({"page_sizes": ["US Letter", "A4"], "files": ["x"]}),
                                                 encoding="utf-8")
    out = pb.make("b", log=lambda *_: None)
    info = json.loads((out / "product.json").read_text(encoding="utf-8"))
    assert info["page_sizes"] == ["US Letter", "A4"] and info["pages"] == 35
    assert info["files"] == ["P.pdf", "P_A4.pdf", "P_Digital_GoodNotes_Hyperlinked.pdf", "H.pdf", "H_A4.pdf"]
    assert info["description"] == "Two planners." + pb.digital_bonus(info["files"])
    assert " digital version of the p for GoodNotes" in info["description"]
    two = pb.digital_bonus(["2027_Planner_Digital_GoodNotes_Hyperlinked.pdf", "x.pdf",
                            "2027_Habit_Tracker_Digital_GoodNotes_Hyperlinked.pdf"])
    assert "digital versions of the planner and habit tracker for GoodNotes" in two
    assert pb.digital_bonus(["a.pdf"]) == ""
    assert (out / "P_Digital_GoodNotes_Hyperlinked.pdf").exists()
    again = json.loads((pb.make("b", log=lambda *_: None) / "product.json").read_text(encoding="utf-8"))
    assert again["description"].count("Bonus:") == 1                 # rebuilt from the spec: never doubled
