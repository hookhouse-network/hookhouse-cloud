"""Phase 6: A4 + US Letter in every printable download."""
import json

from PIL import Image, ImageDraw
from pypdf import PdfReader

from engine import page_sizes


def _letter_pdf(path, pages=3):
    imgs = []
    for k in range(pages):
        im = Image.new("RGB", (2550, 3300), "white")          # 8.5 x 11 in at 300 dpi = 612 x 792 pt
        ImageDraw.Draw(im).rectangle([200, 200, 2350, 3100], outline="black", width=12)
        imgs.append(im)
    imgs[0].save(path, save_all=True, append_images=imgs[1:], resolution=300)
    return path


def _product(tmp_path, files):
    d = tmp_path / "planner"
    d.mkdir()
    for f in files:
        if f.endswith(".pdf"):
            _letter_pdf(d / f)
        else:
            (d / f).write_text("x")
    (d / "product.json").write_text(json.dumps({"files": files, "pages": 3, "title": "2027 Weekly Planner Printable",
                                                "description": "x" * 250, "price_usd": "$4", "tags": ["planner"]}),
                                    encoding="utf-8")
    return d


def test_letter_pdf_gets_an_a4_twin_with_the_same_pages(tmp_path):
    d = _product(tmp_path, ["Planner.pdf", "Budget.xlsx"])
    assert page_sizes.missing_a4(d) == ["Planner.pdf"]
    made = page_sizes.ensure_a4(d, log=lambda *a: None)
    assert made == ["Planner_A4.pdf"]
    r = PdfReader(str(d / "Planner_A4.pdf"))
    box = r.pages[0].mediabox
    assert len(r.pages) == 3 and abs(float(box.width) - 595.28) < 0.5 and abs(float(box.height) - 841.89) < 0.5
    meta = json.loads((d / "product.json").read_text(encoding="utf-8"))
    assert meta["files"] == ["Planner.pdf", "Planner_A4.pdf", "Budget.xlsx"] and meta["page_sizes"] == ["US Letter", "A4"]
    assert page_sizes.missing_a4(d) == []
    assert page_sizes.ensure_a4(d, log=lambda *a: None) == []          # up to date: nothing re-made


def test_a4_twin_is_refreshed_when_the_letter_file_changes(tmp_path):
    import os
    d = _product(tmp_path, ["Planner.pdf"])
    page_sizes.ensure_a4(d, log=lambda *a: None)
    t = (d / "Planner_A4.pdf").stat().st_mtime
    os.utime(d / "Planner.pdf", (t + 100, t + 100))
    assert page_sizes.ensure_a4(d, log=lambda *a: None) == ["Planner_A4.pdf"]


def test_product_gate_holds_a_letter_only_printable(tmp_path, monkeypatch):
    d = _product(tmp_path, ["Planner.pdf"])
    from engine import product_gate
    probs = product_gate.verify("planner", folder=d, listed={})
    assert any("no A4 version" in p for p in probs)
    page_sizes.ensure_a4(d, log=lambda *a: None)
    assert not any("A4" in p for p in product_gate.verify("planner", folder=d, listed={}))
