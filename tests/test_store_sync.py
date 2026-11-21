"""P6: live listings are updated IN PLACE (missing files uploaded next to the existing ones, never delete + re-list,
which changes the URL in posted shop links). The upload wait reads only Payhip's upload rows (22 Nov: the static
'You've completed 50% of your store setup' banner made every wait run to its limit)."""
import json

from engine import store_publish as sp


def test_missing_files_and_product_code(tmp_path, monkeypatch):
    d = tmp_path / "planner_2027"
    d.mkdir()
    for f in ("2027_Planner_Printable.pdf", "2027_Planner_Printable_A4.pdf",
              "2027_Planner_Digital_GoodNotes_Hyperlinked.pdf", "preview.mp3"):
        (d / f).write_bytes(b"x")
    (d / "product.json").write_text(json.dumps({"files": [
        "2027_Planner_Printable.pdf", "2027_Planner_Printable_A4.pdf",
        "2027_Planner_Digital_GoodNotes_Hyperlinked.pdf", "gone.pdf", "preview.mp3"]}), encoding="utf-8")
    monkeypatch.setattr(sp, "PROD", tmp_path)
    got = sp.missing_files("planner_2027", ["2027_planner_printable.pdf"])
    assert [f.name for f in got] == ["2027_Planner_Printable_A4.pdf", "2027_Planner_Digital_GoodNotes_Hyperlinked.pdf"]
    assert sp.missing_files("planner_2027", [f.name for f in got] + ["2027_Planner_Printable.pdf"]) == []
    monkeypatch.setattr(sp, "listed", lambda: {"planner_2027": {"payhip": {"public": "https://payhip.com/b/aWIJC"}}})
    assert sp.payhip_code("planner_2027") == "aWIJC" and sp.payhip_code("nothing") is None


def test_zip_listing_gets_only_the_files_its_zip_lacks(tmp_path, monkeypatch):
    import zipfile
    d = tmp_path / "bundle"
    d.mkdir()
    names = ["Planner.pdf", "Planner_A4.pdf", "Budget.xlsx"]
    for f in names:
        (d / f).write_bytes(b"x")
    (d / "product.json").write_text(json.dumps({"files": names}), encoding="utf-8")
    with zipfile.ZipFile(d / "bundle.zip", "w") as zf:          # what went up before the A4 twin existed
        zf.write(d / "Planner.pdf", "Planner.pdf")
        zf.write(d / "Budget.xlsx", "Budget.xlsx")
    monkeypatch.setattr(sp, "PROD", tmp_path)
    inside = sp.zip_members("bundle", ["bundle.zip"])
    assert sorted(inside) == ["Budget.xlsx", "Planner.pdf"]
    assert [f.name for f in sp.missing_files("bundle", ["bundle.zip"] + inside)] == ["Planner_A4.pdf"]
    assert sp.zip_members("bundle", ["Planner.pdf"]) == []        # no zip on the listing
    assert sp.zip_members("bundle", ["other.zip"]) is None        # a zip we do not have: contents unknown


def test_upload_wait_ignores_the_store_setup_banner():
    import shutil
    import subprocess
    assert "js-upload-digital-file-row" in sp.J_UPLOADING and "document.body.innerText" not in sp.J_UPLOADING
    if shutil.which("node"):                                  # 22 Nov: a line break inside a JS string broke it
        r = subprocess.run(["node", "-e", "const f = eval(process.argv[1]); if (typeof f !== 'function') process.exit(1)",
                            sp.J_UPLOADING], capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stderr
    src = open(sp.__file__, encoding="utf-8").read()
    assert r'/uploading|\d+%/i.test(document.body.innerText)' not in src
