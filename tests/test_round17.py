"""Round 17 (13 Nov): digital products on several stores (owner: "more and more digital products on different
platforms, anything that pays us first"). Every puzzle is checked by code; the planner's formulas are real."""
import json

import pytest

from engine import digital_products as dp


def test_word_search_places_every_word_on_the_grid():
    for k, (theme, words) in enumerate(dp.THEMES.items()):
        grid, where = dp.word_search(words, 15, seed=k)
        assert sorted(where) == sorted(words), theme
        for w, cells in where.items():
            assert "".join(grid[r][c] for r, c in cells) == w
        assert all(len(row) == 15 and all(ch.isalpha() for ch in row) for row in grid)


def test_mazes_are_perfect_and_solvable():
    for seed in range(5):
        cells = dp.maze(14, 11, seed)
        openings = sum(len(c) for row in cells for c in row) // 2
        assert openings == 14 * 11 - 1                                 # a tree: exactly one way between any 2 cells
        path = dp.maze_path(cells)
        assert path[0] == (0, 0) and path[-1] == (13, 10)


@pytest.mark.parametrize("clues", [38, 28])
def test_sudoku_has_exactly_one_answer(clues):
    puz, sol = dp.sudoku(clues, seed=clues)
    assert sum(v != 0 for row in puz for v in row) >= clues
    assert dp._sudoku_solutions([r[:] for r in puz]) == 1
    for i in range(9):
        assert sorted(sol[i]) == list(range(1, 10)) and sorted(sol[r][i] for r in range(9)) == list(range(1, 10))
    assert all(puz[r][c] in (0, sol[r][c]) for r in range(9) for c in range(9))


def test_budget_workbook_has_working_formulas(tmp_path):
    from openpyxl import load_workbook
    for cur, sym in (("INR", "₹"), ("USD", "$")):
        p = dp.budget_workbook(tmp_path / f"b_{cur}.xlsx", cur)
        wb = load_workbook(p)
        assert {"Start Here", "Monthly Budget", "Expense Tracker", "Savings Goals", "Debt Payoff", "Net Worth"} <= set(
            wb.sheetnames)
        mb = wb["Monthly Budget"]
        formulas = [c.value for row in mb.iter_rows() for c in row if isinstance(c.value, str) and c.value.startswith("=")]
        assert any("SUMIF('Expense Tracker'" in f for f in formulas)      # actuals fill themselves from the tracker
        assert any("*0.5" in f for f in formulas) and any("*0.2" in f for f in formulas)   # 50/30/20 check
        assert sym in mb["B7"].number_format
        assert "NPER" in str(wb["Debt Payoff"]["E2"].value)
        assert any(dp.DISCLAIMER in str(c.value) for c in wb["Start Here"]["A"])


def test_music_pack_kit_is_complete(tmp_path, monkeypatch):
    monkeypatch.setattr(dp, "OUT", tmp_path)
    folder = dp.music_pack("devotional", tracks=1, seconds=12.0, log=lambda m: None)
    names = {p.name for p in folder.iterdir()}
    assert {"devotional_01.mp3", "preview.mp3", "LICENSE.txt", "devotional_music_pack.zip", "cover.jpg", "thumb.jpg",
            "listing.md", "product.json"} <= names
    info = json.loads((folder / "product.json").read_text(encoding="utf-8"))
    assert info["stores"][0] == "Payhip"                                # the store that pays first, first
    assert "Content ID" in (folder / "LICENSE.txt").read_text(encoding="utf-8")


def test_listing_has_a_block_per_store(tmp_path):
    p = dp._listing(tmp_path, {"title": "T", "description": "D", "files": ["a.pdf"], "price_usd": "$3",
                               "price_inr": "₹79", "tags": ["x"] * 8, "stores": ["Payhip", "Amazon KDP"], "pages": 30})
    txt = p.read_text(encoding="utf-8")
    assert "## Payhip" in txt and "## Amazon KDP" in txt and "AI content question: NO" in txt


def test_catalogue_lists_the_kits(tmp_path, monkeypatch):
    monkeypatch.setattr(dp, "OUT", tmp_path)
    monkeypatch.setattr(dp, "ROOT", tmp_path.parent)
    dp._listing(dp._kit("one"), {"title": "One", "description": "", "files": [], "price_usd": "$1", "price_inr": "₹1",
                                  "tags": [], "stores": ["Payhip"]})
    txt = dp.write_catalogue().read_text(encoding="utf-8")
    assert "| One |" in txt and "Payhip + Razorpay" in txt


def test_setup_lists_payhip_first():
    from engine import setup_steps
    steps = [s for s in setup_steps.steps() if s.get("group") == "Books & music"] if hasattr(setup_steps, "steps") else []
    if steps:
        assert steps[0]["id"] == "payhip"
    else:
        src = open(setup_steps.__file__, encoding="utf-8").read()
        assert src.index('"payhip"') < src.index('"kdp", "Amazon KDP')
