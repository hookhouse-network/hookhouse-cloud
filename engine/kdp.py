"""Amazon KDP paperbacks from our printable books (owner, 14 Nov: "setup amazon kdp").

For each book: a print-ready wrap-around cover PDF (back + spine + front, 0.125 in bleed, 300 dpi) sized with KDP's
formula for white paper (spine = pages x 0.002252 in), a clear 2 x 1.2 in box bottom-right of the back for the
barcode KDP prints, no spine text under 79 pages (KDP rule), and kdp_listing.json with the fields the KDP form asks
for (title, subtitle, description written for Amazon, 7 keywords, categories, price).
Interior: the existing 8.5 x 11 in PDFs (0.75 in margins, more than KDP's minimum).
Usage: python -m engine.kdp [book ids]"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import ImageDraw

from .config import ROOT
from . import store_copy, store_covers

PROD = ROOT / "data" / "products"
DPI = 300
TRIM_W, TRIM_H, BLEED = 8.5, 11.0, 0.125
BOOKS = {
    "activity_book": dict(
        pdf="Activity_Book_Ages_4-8.pdf", title="Big Fun Activity Book for Kids",
        subtitle="Ages 4-8: Mazes, Dot to Dot, Spot the Difference, Word Search and Coloring, with Answers",
        price=9.99, keywords=["activity book for kids ages 4-8", "mazes for kids ages 4-8", "dot to dot books for kids",
                              "spot the difference book for kids", "word search for kids ages 6-8", "road trip activity book",
                              "kindergarten activity book"],
        categories=["Children's Books > Activities, Crafts & Games > Activity Books",
                    "Children's Books > Activities, Crafts & Games > Mazes"], age="4-8", badge="AGES 4-8",
        front_feats=["Mazes & dot to dot", "Spot the difference", "Answers included"]),
    "seniors_word_search": dict(
        pdf="Large_Print_Word_Search_Nostalgia.pdf", title="Large Print Word Search for Seniors",
        subtitle="Nostalgia Edition: 50 Easy-to-Read Puzzles from the Good Old Days, with Answers",
        price=9.99, keywords=["large print word search for seniors", "word search books for adults large print",
                              "nostalgia puzzle book", "puzzle books for seniors", "easy word search for adults",
                              "word find puzzles for elderly", "gifts for grandparents puzzle book"],
        categories=["Humor & Entertainment > Puzzles & Games > Word Search",
                    "Humor & Entertainment > Puzzles & Games > Puzzles"], age="18-18", badge="LARGE PRINT",
        front_feats=["50 nostalgic puzzles", "Extra-large letters", "Answers included"]),
    "tracing_workbook": dict(
        pdf="Tracing_Workbook_Ages_3-5.pdf", title="My First Tracing Workbook",
        subtitle="Preschool Handwriting Practice for Ages 3-5: Letters, Numbers, Shapes and Pen Control",
        price=9.99, keywords=["tracing workbook for preschoolers", "letter tracing for kids ages 3-5",
                              "handwriting practice book for kids", "pre k workbooks ages 4-5", "kindergarten prep workbook",
                              "number tracing book", "pen control activity book"],
        categories=["Children's Books > Education & Reference > Language Arts > Handwriting",
                    "Children's Books > Activities, Crafts & Games > Activity Books"], age="3-5", badge="AGES 3-5",
        front_feats=["Letters A-Z", "Numbers 0-20", "Shapes & pen control"]),
    "color_by_number": dict(
        pdf="Color_by_Number_Ages_4-8.pdf", title="Bloop & Friends Color by Number",
        subtitle="Fun Coloring Activity Book for Kids Ages 4-8 to Learn Colors and Numbers, with Answer Key",
        price=9.99, keywords=["color by number for kids ages 4-8", "color by number coloring book", "kids activity book",
                              "learn colors book for kids", "coloring books for kids ages 4-8", "kindergarten coloring book",
                              "color by number for toddlers"],
        categories=["Children's Books > Activities, Crafts & Games > Activity Books > Coloring Books",
                    "Children's Books > Early Learning > Basic Concepts > Colors"], age="4-8", badge="AGES 4-8",
        front_feats=["24 pictures", "Color key on every page", "Answer key included"]),
    "bloop_colouring_book": dict(
        pdf="Color_with_Bloop.pdf", title="Toddler Coloring Book: Color with Bloop!",
        subtitle="24 Big, Easy Coloring Pages for Kids Ages 2-5 with Thick Lines and Friendly Characters",
        price=5.99, keywords=["toddler coloring book", "coloring books for kids ages 2-4", "big simple coloring pages",
                              "preschool coloring book", "first coloring book", "thick lines coloring book",
                              "coloring book for boys and girls"],
        categories=["Children's Books > Activities, Crafts & Games > Coloring Books",
                    "Children's Books > Early Learning > Basic Concepts"], age="2-5", badge="AGES 2-5",
        front_feats=["24 big, easy pictures", "Thick lines for little hands", "One picture per page"]),
    "christmas_colouring_book": dict(
        pdf="Christmas_Coloring_Book_Bloop.pdf", title="Christmas Coloring Book for Kids Ages 2-6: Merry Christmas with Bloop!",
        subtitle="20 Big, Easy Christmas Coloring Pages with Santa Hats, Trees, Snowmen and Presents, plus a Letter to Santa",
        price=6.99, keywords=["christmas coloring book for kids", "christmas coloring book for toddlers",
                              "christmas gifts for kids", "stocking stuffers for kids", "christmas activity book",
                              "coloring books for kids ages 2-4", "preschool christmas"],
        categories=["Children's Books > Holidays & Celebrations > Christmas & Advent",
                    "Children's Books > Activities, Crafts & Games > Coloring Books"], age="2-6", badge="AGES 2-6",
        front_feats=["20 big Christmas pictures", "Letter to Santa page", "Thick lines for little hands"]),
    "brain_snack_puzzle_book": dict(
        pdf="Brain_Snack_Puzzle_Book.pdf", title="Brain Snack Puzzle Book for Kids & Teens",
        subtitle="34 Word Searches, Mazes and Sudoku from Easy to Hard, Large Print, with Answers",
        price=6.99, keywords=["puzzle book for kids", "word search for kids", "mazes for kids", "sudoku for kids",
                              "activity book for teens", "large print puzzle book", "brain games for kids"],
        categories=["Children's Books > Activities, Crafts & Games > Puzzles",
                    "Children's Books > Activities, Crafts & Games > Activity Books"], age="8-15", badge="LARGE PRINT",
        front_feats=["Word search, mazes, sudoku", "Easy to hard", "Every answer included"]),
}


def spine_in(pages: int) -> float:
    return round(pages * 0.002252, 4)                          # KDP white paper


def _px(inches: float) -> int:
    return round(inches * DPI)


def cover(pid: str) -> Path:
    import fitz
    spec, folder = BOOKS[pid], PROD / pid
    pages = len(fitz.open(folder / spec["pdf"]))
    sp = spine_in(pages)
    W, H = _px(BLEED * 2 + TRIM_W * 2 + sp), _px(BLEED * 2 + TRIM_H)
    front_x = _px(BLEED + TRIM_W + sp)
    look = store_covers.SPECS[pid]
    img = store_covers._background(*look["bg"]).resize((W, H)).convert("RGBA")
    d = ImageDraw.Draw(img)
    # front (print): tall layout, no "download" wording; previews of the real pages in the lower half
    fx, fy = front_x + _px(0.6), _px(BLEED + 0.6)
    acc = store_covers._rgb(look["accent"])
    f_b = store_covers._f("Poppins-ExtraBold.ttf", 70)
    tw = d.textlength(spec["badge"], font=f_b)
    d.rounded_rectangle([fx, fy, fx + tw + 100, fy + 130], 65, fill=acc)
    d.text((fx + 50, fy + 25), spec["badge"], font=f_b, fill=(20, 20, 30))
    y = fy + 220
    for k, line in enumerate(look["head"]):
        size = 330 if len(line) <= 9 else (270 if len(line) <= 12 else 230)
        f = store_covers._f("Anton-Regular.ttf", size)
        d.text((fx + 10, y + 10), line, font=f, fill=(0, 0, 0, 120))
        d.text((fx, y), line, font=f, fill=(255, 255, 255) if k == 0 else acc)
        y += int(size * 1.1)
    f_f = store_covers._f("Poppins-ExtraBold.ttf", 72)
    y += 40
    for feat in spec["front_feats"]:
        d.ellipse([fx, y + 8, fx + 80, y + 88], fill=acc)
        d.line([(fx + 20, y + 48), (fx + 36, y + 66), (fx + 62, y + 30)], fill=(20, 20, 30), width=12)
        d.text((fx + 115, y), feat, font=f_f, fill="white")
        y += 120
    prev = store_covers._pdf_pages(folder / spec["pdf"], look["pages"], 950)
    base_y = y + 90                                            # fill the middle, stay inside the trim
    for im, (ang, dx, dy) in zip(prev, [(8, 1050, 0), (-6, 450, 110), (2, 1150, 230)]):
        img.alpha_composite(store_covers._shadowed(im, ang, blur=34, off=30), (front_x + dx, base_y + dy))
    d = ImageDraw.Draw(img)
    d.text((fx, H - _px(BLEED + 0.7)), "HookHouse Media", font=store_covers._f("Poppins-ExtraBold.ttf", 60), fill="white")
    # back: blurb + feature ticks; barcode box kept clear (bottom-right of the back, 0.25 in from trim)
    bx, by = _px(BLEED + 0.75), _px(BLEED + 1.0)
    f_head = store_covers._f("Anton-Regular.ttf", 120)
    f_txt = store_covers._f("Poppins-ExtraBold.ttf", 50)
    d.text((bx, by), "WHAT'S INSIDE", font=f_head, fill=store_covers._rgb(look["accent"]))
    y = by + 200
    for item in store_copy.copy_for(pid)["inside"]:
        if "rintable PDF" in item or "print as many" in item:
            continue                                           # a printed book: no PDF talk
        d.ellipse([bx, y + 8, bx + 46, y + 54], fill=store_covers._rgb(look["accent"]))
        words, line = item.split(), ""
        for w in words:                                        # wrap to the back panel
            if d.textlength((line + " " + w).strip(), font=f_txt) > _px(TRIM_W - 1.6):
                d.text((bx + 70, y), line, font=f_txt, fill="white")
                y += 70
                line = w
            else:
                line = (line + " " + w).strip()
        d.text((bx + 70, y), line, font=f_txt, fill="white")
        y += 110
    f_par = store_covers._f("Poppins-ExtraBold.ttf", 46)
    y += 60
    words, line = store_copy.description(pid, "kdp").split(), ""
    for w in words:                                            # the Amazon description, wrapped on the back
        if d.textlength((line + " " + w).strip(), font=f_par) > _px(TRIM_W - 1.5):
            d.text((bx, y), line, font=f_par, fill=(235, 235, 245))
            y += 68
            line = w
        else:
            line = (line + " " + w).strip()
    d.text((bx, y), line, font=f_par, fill=(235, 235, 245))
    d.text((bx, H - _px(BLEED + 1.0)), "HookHouse Media", font=f_txt, fill="white")
    bc_w, bc_h = _px(2.0), _px(1.2)                            # KDP prints the barcode here: keep it plain white
    bc_x = _px(BLEED + TRIM_W) - _px(0.25) - bc_w
    bc_y = H - _px(BLEED) - _px(0.25) - bc_h
    d.rectangle([bc_x, bc_y, bc_x + bc_w, bc_y + bc_h], fill="white")
    img = img.convert("RGB")
    out = folder / "kdp_cover.pdf"
    img.save(out, "PDF", resolution=DPI)
    img.resize((W // 4, H // 4)).save(folder / "kdp_cover_preview.jpg", quality=85)
    listing = {**{k: v for k, v in spec.items() if k != "pdf"}, "interior": spec["pdf"], "pages": pages,
               "trim": "8.5 x 11 in", "paper": "black & white interior, white paper", "bleed": "no bleed (interior)",
               "cover_finish": "glossy", "spine_in": sp, "cover_size_in": [round(W / DPI, 3), round(H / DPI, 3)],
               "description": store_copy.description(pid, "kdp"), "author": "HookHouse Media",
               "ai_content": "No: pages, puzzles and art are drawn by our own code (no generative AI). Answer honestly; "
                             "if a future book uses AI images or text, this must become Yes"}
    (folder / "kdp_listing.json").write_text(json.dumps(listing, indent=1, ensure_ascii=False), encoding="utf-8")
    return out


if __name__ == "__main__":
    for pid in sys.argv[1:] or list(BOOKS):
        print(cover(pid))
