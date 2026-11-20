"""The whole digital-product pipeline as one command (owner, 14 Nov: "all should be automated, our system should handle
all these"): python cli.py products all

1. build any book that has no PDF yet (engine/kdp_books.py, engine/planner_product.py)
2. store covers + square thumbnails, Pinterest pins, KDP print covers + listings (fast, offline)
3. list new products on Payhip (live) and Gumroad (draft until the owner connects a bank)
4. record everything in data/products/listed.json -> dashboard "Products & stores", shop links, pins
KDP uploads stay a separate step (they need the owner's tax interview first). Pins post 2 a day from the PC helper.
Research behind the choices: docs/kdp_research.md, docs/earning_platforms_research.md."""
from __future__ import annotations

from .config import ROOT

PROD = ROOT / "data" / "products"
BUILDERS = {   # product id -> (pdf name, builder)
    "tracing_workbook": ("Tracing_Workbook_Ages_3-5.pdf", "engine.kdp_books:tracing"),
    "color_by_number": ("Color_by_Number_Ages_4-8.pdf", "engine.kdp_books:color_by_number"),
    "planner_2027": ("2027_Planner_Printable.pdf", "engine.planner_product:make"),
    "seniors_word_search": ("Large_Print_Word_Search_Nostalgia.pdf", "engine.kdp_books:seniors_word_search"),
    "activity_book": ("Activity_Book_Ages_4-8.pdf", "engine.kdp_books:activity_book"),
    # 20 Nov: in-season winners of the product research (Nov-Jan)
    "habit_tracker_2027": ("2027_Habit_Tracker_Printable.pdf", "engine.planner_product:habit_tracker"),
    "senior_sudoku": ("Large_Print_Sudoku_Seniors.pdf", "engine.digital_products:senior_sudoku"),
}


def _call(path: str):
    import importlib
    mod, fn = path.split(":")
    return getattr(importlib.import_module(mod), fn)


def build_missing(log=print) -> list[str]:
    made = []
    for pid, (pdf, builder) in BUILDERS.items():
        if not (PROD / pid / pdf).exists():
            _call(builder)(log=log)
            made.append(pid)
    return made


def assets(log=print) -> None:
    from . import kdp, pins, store_covers
    for pid in store_covers.SPECS:
        if (PROD / pid / "product.json").exists():
            store_covers.make(pid)
            pins.make(pid)
    for pid in kdp.BOOKS:
        if (PROD / pid / kdp.BOOKS[pid]["pdf"]).exists():
            kdp.cover(pid)
    log("covers, thumbnails, pins and KDP covers up to date")


def run(log=print) -> list[str]:
    from . import store_publish
    out = [f"built {p}" for p in build_missing(log)]
    assets(log)
    out += store_publish.publish("payhip", log=log)            # only products not listed yet
    out += store_publish.publish_gumroad(log=log)
    return out
