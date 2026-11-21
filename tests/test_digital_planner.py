"""P6 Products 2.0: the hyperlinked digital planner (GoodNotes / Notability) has working tabs on every page and
month links on the year view, all pointing at the right pages."""
from pypdf import PdfReader

from engine import digital_planner as dp


def test_tabs_fit_the_margin_and_cover_home_plus_12_months():
    boxes = dp.tab_boxes()
    assert len(boxes) == 13 and boxes[0][1] >= dp.TAB_Y0 and boxes[-1][3] <= dp.pp.PH - 200
    assert all(x0 >= dp.pp.PW - dp.pp.M for x0, _y0, _x1, _y1 in boxes)    # inside the right margin
    assert dp.tab_target(0) == 1 and dp.tab_target(1) == 3 and dp.tab_target(12) == 14


def test_adding_to_a_live_product_keeps_every_other_field(tmp_path):
    import json
    info = {"title": "2027 Printable Planner Bundle", "files": ["2027_Planner_Printable.pdf",
                                                                "2027_Planner_Printable_A4.pdf"],
            "page_sizes": ["Letter", "A4"], "description": "A clean planner.", "price_usd": "$6"}
    (tmp_path / "product.json").write_text(json.dumps(info), encoding="utf-8")
    out = dp.add_to_product(tmp_path, log=lambda *_: None)
    got = json.loads((tmp_path / "product.json").read_text(encoding="utf-8"))
    assert got["files"] == info["files"] + [out.name] and got["page_sizes"] == ["Letter", "A4"]
    assert got["description"].startswith("A clean planner.") and "GoodNotes" in got["description"]
    dp.add_to_product(tmp_path, log=lambda *_: None)                          # idempotent
    again = json.loads((tmp_path / "product.json").read_text(encoding="utf-8"))
    assert again["files"].count(out.name) == 1 and again["description"].count("Bonus:") == 1


def test_the_digital_file_needs_no_a4_twin(tmp_path):
    import json

    from PIL import Image

    from engine import page_sizes
    letter = Image.new("RGB", (850, 1100), "white")
    for name in ("2027_Planner_Printable.pdf", "2027_Planner_Printable_A4.pdf",
                 "2027_Planner_Digital_GoodNotes_Hyperlinked.pdf"):
        letter.save(tmp_path / name, resolution=100)
    (tmp_path / "product.json").write_text(json.dumps({"files": [
        "2027_Planner_Printable.pdf", "2027_Planner_Printable_A4.pdf",
        "2027_Planner_Digital_GoodNotes_Hyperlinked.pdf"]}), encoding="utf-8")
    assert page_sizes.missing_a4(tmp_path) == []                              # tablets never print it


def test_the_pdf_links_jump_to_the_right_pages(tmp_path):
    out = dp.make(out_dir=tmp_path, log=lambda *_: None)
    r = PdfReader(str(out))
    assert len(r.pages) == 21
    index = {p.indirect_reference.idnum: i for i, p in enumerate(r.pages)}

    def targets(page_no):
        found = []
        for a in r.pages[page_no].get("/Annots") or []:
            a = a.get_object()
            if a.get("/Subtype") == "/Link":
                dest = a.get("/Dest") or (a.get("/A") or {}).get("/D")
                found.append(index.get(dest[0].idnum))
        return found
    assert targets(0) == []                                                   # the cover stays clean
    home = targets(1)
    assert sorted(home) == sorted([1] + list(range(3, 15)) + list(range(3, 15)))   # tabs + 12 month blocks
    assert sorted(targets(20)) == [1] + list(range(3, 15))                    # notes page: HOME + 12 months
    assert not (tmp_path / "_digital_raw.pdf").exists()
