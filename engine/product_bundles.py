"""Bundles from products we already have (owner 20 Nov 2026: "find best selling strategy and create in-demand
digital products"; research in docs/MASTER_PLAN_2026-11-20.md 4.4b: focused bundles sell, products under $10 earn
little on their own, one-click upsells/bundles raise order value). Zero new production and zero AI pictures.

Each bundle copies its parts' downloads into its own folder (line-art PDFs over the size rule are re-saved as crisp
1-bit pages first), writes product.json with the summed page count and a bundle price below the parts' total, and
then goes through the same product gate as everything else (store_publish._gate_ok)."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from .config import ROOT

PROD = ROOT / "data" / "products"
BUNDLES = {
    "planner_bundle_2027": {
        "parts": ["planner_2027", "habit_tracker_2027", "money_budget_planner"],
        "title": "2027 Planner Bundle: Printable Planner + Habit Tracker + Budget Planner (Save 35%)",
        "price_usd": "$11", "price_inr": "₹279", "channel": "money_cheat_codes",
        "description": ("Everything to run 2027 in one download: the 2027 Printable Planner (year at a glance, 12 "
                        "monthly calendars, weekly and daily pages), the 2027 Habit Tracker & Resolution Planner (12 "
                        "monthly trackers, goals and monthly reviews) and the Budget Planner (Excel + Google Sheets "
                        "in rupees and dollars, plus printable pages). Bought separately they cost $17. Print at home "
                        "on US Letter or A4, as often as you like."),
        "tags": ["2027 planner bundle", "printable planner", "habit tracker", "budget planner", "new year planner",
                 "goal planner", "planner set"],
    },
    "senior_puzzle_bundle": {
        "parts": ["seniors_word_search", "senior_sudoku"],
        "title": "Large Print Puzzle Bundle for Seniors: Word Search + Sudoku (126 Puzzles, Save 22%)",
        "price_usd": "$7", "price_inr": "₹179", "channel": "brain_snack",
        "description": ("Two large-print puzzle books in one download: 50 nostalgic word searches from the good old "
                        "days and 60 sudoku puzzles from easy to medium, all with extra-large print, one puzzle per "
                        "page and answers at the back. Bought separately they cost $9. A thoughtful gift for parents "
                        "and grandparents; print at home on US Letter or A4."),
        "tags": ["large print puzzles", "puzzle book for seniors", "large print word search", "sudoku for seniors",
                 "gift for grandparents", "brain games", "printable puzzles"],
    },
}


def compress_pdf(src: Path, dst: Path, dpi: int = 300) -> Path:
    """Re-save a black-and-white PDF as 1-bit pages (fax-compressed): same print quality, a fraction of the size."""
    import fitz
    from PIL import Image
    doc = fitz.open(src)
    pages = []
    for pg in doc:
        pix = pg.get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72), alpha=False, colorspace=fitz.csGRAY)
        img = Image.frombytes("L", (pix.width, pix.height), pix.samples)
        pages.append(img.point(lambda v: 255 if v > 170 else 0, mode="1"))
    pages[0].save(dst, save_all=True, append_images=pages[1:], resolution=dpi)
    return dst


def make(bid: str, log=print) -> Path:
    from .product_gate import rules
    spec = BUNDLES[bid]
    out = PROD / bid
    out.mkdir(parents=True, exist_ok=True)
    max_mb = float(rules().get("max_file_mb", 20))
    files, pages = [], 0
    for part in spec["parts"]:
        meta = json.loads((PROD / part / "product.json").read_text(encoding="utf-8"))
        pages += int(meta.get("pages") or 0)
        for name in meta["files"]:
            src = PROD / part / name
            if not src.exists() or name.endswith("preview.mp3"):
                continue
            dst = out / name
            if src.suffix.lower() == ".pdf" and src.stat().st_size > max_mb * 1024 ** 2:
                compress_pdf(src, dst)
                log(f"  {name}: {src.stat().st_size / 1048576:.0f} MB -> {dst.stat().st_size / 1048576:.1f} MB (1-bit)")
            else:
                shutil.copy2(src, dst)
            files.append(name)
    info = {k: spec[k] for k in ("title", "price_usd", "price_inr", "channel", "description", "tags")}
    info.update(files=files, pages=pages, stores=["Payhip", "Gumroad"], bundle_of=spec["parts"])
    (out / "product.json").write_text(json.dumps(info, indent=1, ensure_ascii=False), encoding="utf-8")
    first = PROD / spec["parts"][0] / "cover.jpg"
    if first.exists():
        shutil.copy2(first, out / "cover.jpg")
    log(f"  bundle {bid}: {len(files)} files, {pages} pages -> {out}")
    return out


def make_all(log=print) -> list[Path]:
    return [make(b, log=log) for b in BUNDLES]


def planner_bundle(log=print) -> Path:
    return make("planner_bundle_2027", log=log)


def senior_bundle(log=print) -> Path:
    return make("senior_puzzle_bundle", log=log)
