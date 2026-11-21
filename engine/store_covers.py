"""Store covers that sell (owner, 14 Nov: "catchy, high quality, high selling"): the look best-selling digital
products use on Payhip / Gumroad / Etsy-style stores.

Square 2000x2000 (every store crops to square thumbnails): bold headline + one-line promise, a fan of REAL preview
pages from the product (PDF pages rendered with PyMuPDF) or waveform track cards for music packs, an
"INSTANT DOWNLOAD" badge and 3-4 ticked features. Every claim comes from the product itself (page counts, files,
track lengths). Output: data/products/<id>/store_cover.jpg (+ store_thumb.jpg 600x600).
Usage: python -m engine.store_covers [product ids]"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .config import ROOT

PROD = ROOT / "data" / "products"
FONTS = ROOT / "assets" / "fonts"
S = 2000

# Store titles: what it is | who/what for | the words buyers search (under 100 characters)
TITLES = {   # 20 Nov: the first 40 characters must match the live listing (record_public matches on them)
    "planner_bundle_2027": "2027 Planner Bundle: Printable Planner + Habit Tracker | Budget Planner | Save 35%",
    "senior_puzzle_bundle": "Large Print Puzzle Bundle for Seniors: Word Search + Sudoku | 126 Puzzles | Save 22%",
    "habit_tracker_2027": "2027 Habit Tracker & New Year Resolution Planner | 12 Monthly Trackers, Goals & Reviews",
    "senior_sudoku": "Large Print Sudoku for Seniors: 60 Easy to Medium Puzzles | One Big Puzzle per Page",
    "activity_book": "Big Fun Activity Book for Kids Ages 4-8 | Mazes, Dot to Dot, Spot the Difference, Word Search",
    "seniors_word_search": "Large Print Word Search for Seniors | Nostalgia Edition | 50 Easy Puzzles from the Good Old Days",
    "tracing_workbook": "Preschool Tracing Workbook Ages 3-5 | Letters, Numbers, Shapes & Pen Control | 90 Pages",
    "color_by_number": "Color by Number for Kids Ages 4-8 | Fun Coloring Activity Book with Answer Key",
    "planner_2027": "2027 Printable Planner Bundle | Monthly, Weekly & Daily Planner, Habit Tracker, Goals",
    "money_budget_planner": "Budget Planner 2027 Spreadsheet | Excel & Google Sheets | 50/30/20, Savings & Debt Tracker",
    "bloop_colouring_book": "Toddler Coloring Book Printable | 24 Big Easy Pages for Ages 2-5 | Instant PDF",
    "christmas_colouring_book": "Christmas Coloring Pages for Kids | 20 Big Easy Pages + Letter to Santa | Printable PDF",
    "brain_snack_puzzle_book": "Printable Puzzle Book for Kids & Teens | Word Search, Mazes & Sudoku with Answers",
    "music_pack_cosmic": "No Copyright Space Ambient Music Pack | 5 Royalty-Free Tracks for YouTube & Reels",
    "music_pack_devotional": "Indian Devotional Background Music | 5 Royalty-Free Tracks for YouTube & Reels",
    "music_pack_dhol": "Dhol & Stadium Energy Music Pack | 5 Royalty-Free Indian Beats for Videos",
    "music_pack_ocean": "Deep Ocean Documentary Music | 5 Royalty-Free Cinematic Tracks for YouTube",
    "music_pack_retro": "Retro Bollywood Nostalgia Music | 5 Royalty-Free Tracks for Reels & Vlogs",
    "music_pack_wild": "Wildlife Documentary Music Pack | 5 Royalty-Free Cinematic Tracks for Videos",
}

MUSIC_FEATURES = ["Content ID-free: no claims", "Commercial use OK", "5 tracks x 90 seconds", "No credit needed"]
SPECS = {
    "planner_bundle_2027": dict(top="BUNDLE · SAVE 35%", head=["2027", "PLANNER BUNDLE"], sub="Planner + habit tracker + budget",
                                bg=("#0B3D2E", "#14A38F"), accent="#FFD23F", pdf="2027_Planner_Printable.pdf",
                                pages=[1, 3, 15], feats=["2027 printable planner", "12 monthly habit trackers",
                                                         "Budget planner (Excel + Sheets)", "US Letter + A4"]),
    "senior_puzzle_bundle": dict(top="BUNDLE · SAVE 22%", head=["PUZZLE BUNDLE", "FOR SENIORS"],
                                 sub="126 large-print puzzles", bg=("#5B2C1F", "#2E7BC4"), accent="#FFD9A0",
                                 pdf="Large_Print_Sudoku_Seniors.pdf", pages=[1, 21, 61],
                                 feats=["50 nostalgia word searches", "60 sudoku, easy to medium",
                                        "One big puzzle per page", "Answers included"]),
    "habit_tracker_2027": dict(top="PRINTABLE PDF", head=["2027", "HABIT TRACKER"], sub="Turn resolutions into daily habits",
                               bg=("#2B1B5E", "#6C4AB6"), accent="#FFD23F", pdf="2027_Habit_Tracker_Printable.pdf",
                               pages=[1, 2, 3], feats=["12 monthly habit trackers", "Goals for 6 areas of life",
                                                       "Monthly review questions", "Print again any time"]),
    "senior_sudoku": dict(top="LARGE PRINT", head=["SUDOKU", "FOR SENIORS"], sub="60 puzzles, easy to medium",
                          bg=("#123C6B", "#2E7BC4"), accent="#FFD9A0", pdf="Large_Print_Sudoku_Seniors.pdf",
                          pages=[1, 21, 61], feats=["One big puzzle per page", "Extra-large numbers",
                                                    "Every puzzle has one answer", "Answers at the back"]),
    "activity_book": dict(top="PRINTABLE PDF", head=["BIG FUN", "ACTIVITY BOOK"], sub="Ages 4-8 · 88 pages of play",
                          bg=("#1B7F4B", "#5CC98B"), accent="#FFD23F", pdf="Activity_Book_Ages_4-8.pdf", pages=[3, 16, 36],
                          feats=["12 mazes, easy to hard", "Dot to dot & spot the difference", "Word search & coloring",
                                 "Answers + certificate"]),
    "seniors_word_search": dict(top="LARGE PRINT", head=["WORD SEARCH", "NOSTALGIA"], sub="50 puzzles from the good old days",
                                bg=("#5B2C1F", "#B5651D"), accent="#FFD9A0", pdf="Large_Print_Word_Search_Nostalgia.pdf",
                                pages=[2, 10, 53], feats=["Extra-large letters", "Easy directions, no backwards",
                                                          "One theme per puzzle", "Answers included"]),
    "tracing_workbook": dict(top="PRINTABLE PDF", head=["TRACING", "WORKBOOK"], sub="Ages 3-5 · 90 pages of practice",
                             bg=("#E8603C", "#F5A623"), accent="#FFFFFF", pdf="Tracing_Workbook_Ages_3-5.pdf", pages=[8, 33, 62],
                             feats=["A-Z capitals & lowercase", "Numbers 0-20 + counting", "Pen control & shapes",
                                    "Stars to rate each page"]),
    "color_by_number": dict(top="PRINTABLE PDF", head=["COLOR BY", "NUMBER"], sub="Ages 4-8 · learn colors & numbers",
                            bg=("#1D6FB8", "#4FC3F7"), accent="#FFD23F", pdf="Color_by_Number_Ages_4-8.pdf", pages=[2, 4, 30],
                            feats=["24 color-by-number pages", "Color key on every page", "Answer key + certificate"]),
    "planner_2027": dict(top="PRINTABLE PDF", head=["2027", "PLANNER BUNDLE"], sub="21 pages to plan the whole year",
                         bg=("#0B4F47", "#14A38F"), accent="#FFD23F", pdf="2027_Planner_Printable.pdf", pages=[1, 3, 15],
                         feats=["12 monthly calendars + holidays", "Weekly & daily planners", "Habit tracker + budget",
                                "Goals, reading list, notes"]),
    "money_budget_planner": dict(top="EXCEL + GOOGLE SHEETS", head=["BUDGET", "PLANNER 2027"], sub="Does the math for you",
                                 bg=("#0B3D2E", "#11845B"), accent="#FFD23F", pdf="Money_Cheat_Codes_Printable_Planner.pdf",
                                 pages=[0, 1, 2], feats=["50/30/20 budget", "Savings goal tracker", "Debt payoff tracker",
                                                         "₹ + $ versions, 5 printables"]),
    "bloop_colouring_book": dict(top="PRINTABLE PDF", head=["TODDLER", "COLORING BOOK"], sub="24 big, bold pages for ages 2-5",
                                 bg=("#0E7BC7", "#43C6F0"), accent="#FFB703", pdf="Color_with_Bloop.pdf", pages=[1, 2, 3],
                                 feats=["Thick lines for little hands", "One picture per page", "Print at home, any time"]),
    "christmas_colouring_book": dict(top="PRINTABLE PDF", head=["CHRISTMAS", "COLORING PAGES"],
                                     sub="20 big, easy pages for ages 2-6", bg=("#8B0F1A", "#D62839"), accent="#FFD23F",
                                     pdf="Christmas_Coloring_Book_Bloop.pdf", pages=[1, 5, 21],
                                     feats=["Santa hats, trees, snowmen, presents", "Letter to Santa page",
                                            "Thick lines for little hands"]),
    "brain_snack_puzzle_book": dict(top="PRINTABLE PDF", head=["PUZZLE BOOK", "KIDS & TEENS"], sub="34 puzzles, easy to hard",
                                    bg=("#3A0CA3", "#7209B7"), accent="#4CC9F0", pdf="Brain_Snack_Puzzle_Book.pdf", pages=[1, 12, 24],
                                    feats=["Word search, mazes, sudoku", "Every answer included", "Large print, 1 per page"]),
    "music_pack_cosmic": dict(top="NO COPYRIGHT MUSIC", head=["SPACE", "AMBIENT"], sub="Royalty-free tracks for YouTube & Reels",
                              bg=("#0B0C2A", "#3A2C8F"), accent="#9D8CFF", music="cosmic", feats=MUSIC_FEATURES),
    "music_pack_devotional": dict(top="NO COPYRIGHT MUSIC", head=["DEVOTIONAL", "INDIAN"], sub="Calm, sacred background music",
                                  bg=("#5A1A00", "#C1440E"), accent="#FFC857", music="devotional", feats=MUSIC_FEATURES),
    "music_pack_dhol": dict(top="NO COPYRIGHT MUSIC", head=["DHOL &", "STADIUM"], sub="High-energy Indian beats",
                            bg=("#7A0010", "#E63946"), accent="#FFD166", music="dhol", feats=MUSIC_FEATURES),
    "music_pack_ocean": dict(top="NO COPYRIGHT MUSIC", head=["DEEP", "OCEAN"], sub="Cinematic documentary music",
                             bg=("#001B2E", "#00708A"), accent="#5EEAD4", music="ocean", feats=MUSIC_FEATURES),
    "music_pack_retro": dict(top="NO COPYRIGHT MUSIC", head=["RETRO", "BOLLYWOOD"], sub="Nostalgic tracks for Reels & vlogs",
                             bg=("#3D0B37", "#B5179E"), accent="#FFD60A", music="retro", feats=MUSIC_FEATURES),
    "music_pack_wild": dict(top="NO COPYRIGHT MUSIC", head=["WILDLIFE", "DOCUMENTARY"], sub="Cinematic nature music",
                            bg=("#0F2A12", "#2D6A4F"), accent="#B7E4C7", music="wild", feats=MUSIC_FEATURES),
}


def _f(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS / name), size)


def _rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _background(c1: str, c2: str) -> Image.Image:
    a, b = np.array(_rgb(c1), float), np.array(_rgb(c2), float)
    y, x = np.mgrid[0:S, 0:S]
    t = np.clip((x * 0.35 + y * 0.65) / S, 0, 1)[..., None]           # diagonal gradient
    img = a * (1 - t) + b * t
    glow = np.exp(-(((x - S * 0.72) ** 2 + (y - S * 0.62) ** 2) / (2 * (S * 0.33) ** 2)))[..., None]
    img = img + glow * 45                                              # soft light behind the previews
    noise = np.random.default_rng(3).normal(0, 3.0, (S, S, 1))         # fine grain: looks printed, not flat
    return Image.fromarray(np.clip(img + noise, 0, 255).astype(np.uint8))


def _shadowed(card: Image.Image, angle: float, blur: int = 28, off: int = 26) -> Image.Image:
    card = card.convert("RGBA")
    pad = blur * 3
    sh = Image.new("RGBA", (card.width + pad * 2, card.height + pad * 2), (0, 0, 0, 0))
    sh.paste((0, 0, 0, 150), (pad + off, pad + off, pad + off + card.width, pad + off + card.height))
    sh = sh.filter(ImageFilter.GaussianBlur(blur))
    sh.alpha_composite(card, (pad, pad))
    return sh.rotate(angle, resample=Image.BICUBIC, expand=True)


# Free samples = lead magnets (owner, 16 Nov, from the two income articles: "useful free content -> free resource ->
# email list -> paid product"; cold viewers download free far more often than they buy). Payhip asks for an email
# before a free download, so every sample also grows the list we tell about new products. Built by
# engine/lead_magnets.py: the parent's cover + these pages + a last page linking to the full version.
FREEBIES = {
    "planner_2027": dict(pages=[1, 2, 3], head=["2027", "PLANNER"], what="2027 year at a glance, goals page and January calendar",
                         title="FREE 2027 Printable Planner Sample | Year at a Glance, Goals & January Calendar"),
    "money_budget_planner": dict(pages=[1, 2], n=3, what="monthly budget, expense log and savings goal pages",
                                 title="FREE Printable Budget Planner Pages | Monthly Budget & Savings Tracker PDF"),
    "brain_snack_puzzle_book": dict(pages=[1, 12, 24], what="3 puzzles: a word search, a maze and a sudoku",
                                    title="FREE Printable Puzzles for Kids & Teens | Word Search, Maze & Sudoku Sample"),
    "seniors_word_search": dict(pages=[2, 3, 10], what="3 large print nostalgia word searches",
                                title="FREE Large Print Word Search for Seniors | 3 Printable Nostalgia Puzzles"),
    "activity_book": dict(pages=[3, 16, 36], what="3 activity pages: a maze, dot to dot and spot the difference",
                          title="FREE Kids Activity Pages Ages 4-8 | Printable Maze, Dot to Dot, Spot the Difference"),
    "color_by_number": dict(pages=[2, 4], what="2 color by number pages with their color key",
                            title="FREE Color by Number Printables for Kids Ages 4-8 | 2 Sample Pages"),
    "tracing_workbook": dict(pages=[8, 33, 62], what="3 tracing pages: letters, numbers and pen control",
                             title="FREE Preschool Tracing Worksheets Ages 3-5 | Letters, Numbers & Lines Sample"),
    "christmas_colouring_book": dict(pages=[1, 5, 21], what="3 Christmas pages: Bloop in a Santa hat, a big tree and the Letter to Santa",
                                     title="FREE Christmas Coloring Pages for Kids | 3 Printable Pages + Letter to Santa"),
    "bloop_colouring_book": dict(pages=[1, 2, 3], what="3 big, easy coloring pages",
                                 title="FREE Toddler Coloring Pages Printable | 3 Big Easy Pages for Ages 2-5"),
}
for _pid, _fb in FREEBIES.items():
    _n = _fb.get("n", len(_fb["pages"]))             # n: the parent has no cover page, so page 0 is content too
    SPECS["free_" + _pid] = {**SPECS[_pid], "top": "FREE PRINTABLE", "pdf": "FREE_" + SPECS[_pid]["pdf"],
                             "pages": [min(k, _n) for k in (1, 2, 3)], "sub": f"Free sample · {_n} printable pages",
                             "head": _fb.get("head", SPECS[_pid]["head"]),
                             "feats": [f"{_n} real pages, free", "Print at home, any time", "Full version inside"]}
    TITLES["free_" + _pid] = _fb["title"][:100]


def _printable_kits() -> tuple[dict, dict]:
    """P6: printable kits (config/printables.yaml `cover:` + `title:`) join SPECS and TITLES, so covers, pins, the
    dashboard and the store publisher see them like every other product; a hand-written entry above always wins."""
    try:
        from .printables import cover_specs, specs
        return cover_specs(), {k: str(s["title"])[:100] for k, s in specs().items() if s.get("title")}
    except Exception as e:  # noqa: BLE001 - the other products' covers must still work
        print(f"store covers: printable kits skipped ({type(e).__name__}: {e})")
        return {}, {}


_kit_specs, _kit_titles = _printable_kits()
for _pid, _spec in _kit_specs.items():
    SPECS.setdefault(_pid, _spec)
    if _pid in _kit_titles:
        TITLES.setdefault(_pid, _kit_titles[_pid])


def _pdf_pages(pdf: Path, pages: list[int], width: int) -> list[Image.Image]:
    import fitz
    doc = fitz.open(pdf)
    out = []
    for n in pages:
        pg = doc[min(n, len(doc) - 1)]
        z = width / pg.rect.width
        pix = pg.get_pixmap(matrix=fitz.Matrix(z, z), alpha=False)
        im = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        d = ImageDraw.Draw(im)
        d.rectangle([0, 0, im.width - 1, im.height - 1], outline=(220, 220, 220), width=3)
        out.append(im)
    return out


def _track_cards(folder: Path, key: str, accent: str, w: int = 1050, h: int = 230) -> list[Image.Image]:
    """Waveform cards from the real MP3s (Track 01-03)."""
    from .media import ffmpeg as ff
    import subprocess
    cards = []
    for n in range(1, 4):
        mp3 = folder / f"{key}_{n:02d}.mp3"
        r = subprocess.run([ff.ffmpeg_bin(), "-v", "error", "-i", str(mp3), "-ac", "1", "-ar", "4000", "-f", "s16le", "-"],
                           capture_output=True)
        a = np.abs(np.frombuffer(r.stdout, np.int16).astype(float)) if r.stdout else np.zeros(4000)
        bars = 70
        env = np.array([seg.mean() for seg in np.array_split(a, bars)]) if len(a) > bars else np.ones(bars)
        env = env / (env.max() or 1)
        card = Image.new("RGBA", (w, h), (255, 255, 255, 245))
        d = ImageDraw.Draw(card)
        d.rounded_rectangle([0, 0, w - 1, h - 1], 36, fill=(255, 255, 255, 245))
        d.ellipse([34, h // 2 - 52, 138, h // 2 + 52], fill=_rgb(accent))
        d.polygon([(74, h // 2 - 26), (74, h // 2 + 26), (110, h // 2)], fill=(20, 20, 30))
        d.text((170, 30), f"TRACK {n:02d}", font=_f("Poppins-ExtraBold.ttf", 40), fill=(25, 25, 35))
        d.text((w - 150, 30), "1:30", font=_f("Poppins-ExtraBold.ttf", 36), fill=(120, 120, 130))
        x0, x1, mid = 170, w - 50, h // 2 + 38
        bw = (x1 - x0) / bars
        for i, v in enumerate(env):
            bh = 8 + v * 62
            d.rounded_rectangle([x0 + i * bw, mid - bh / 2, x0 + i * bw + bw * 0.6, mid + bh / 2], 4,
                                fill=_rgb(accent) if i < bars * 0.4 else (200, 200, 210))
        cards.append(card)
    return cards


def _badge(img: Image.Image, text: str, x: int, y: int, fill: str, fg=(20, 20, 30)) -> int:
    d = ImageDraw.Draw(img)
    f = _f("Poppins-ExtraBold.ttf", 46)
    tw = d.textlength(text, font=f)
    d.rounded_rectangle([x, y, x + tw + 70, y + 92], 46, fill=_rgb(fill))
    d.text((x + 35, y + 18), text, font=f, fill=fg)
    return int(x + tw + 70)


def make(pid: str) -> Path:
    spec, folder = SPECS[pid], PROD / pid
    img = _background(*spec["bg"]).convert("RGBA")
    d = ImageDraw.Draw(img)
    # previews first (right/bottom), text on top of the clear left/top area
    if spec.get("pdf"):
        pages = _pdf_pages(folder / spec["pdf"], spec["pages"], 760)
        for im, (ang, x, y) in zip(pages, [(9, 1000, 820), (-6, 760, 900), (2, 1130, 1010)]):
            card = _shadowed(im, ang)
            img.alpha_composite(card, (x, y))
    else:
        for k, card in enumerate(_track_cards(folder, spec["music"], spec["accent"])):
            img.alpha_composite(_shadowed(card, -2 + k * 2, blur=22, off=18), (850 - k * 30, 900 + k * 290))
    d = ImageDraw.Draw(img)
    _badge(img, spec["top"], 110, 110, spec["accent"])
    y = 260
    for k, line in enumerate(spec["head"]):
        size = 230 if len(line) <= 9 else (190 if len(line) <= 12 else 160)
        f = _f("Anton-Regular.ttf", size)
        d.text((118, y + 8), line, font=f, fill=(0, 0, 0, 120))
        d.text((110, y), line, font=f, fill=(255, 255, 255) if k == 0 else _rgb(spec["accent"]))
        y += int(size * 1.12)
    d.text((114, y + 40), spec["sub"], font=_f("Poppins-ExtraBold.ttf", 60), fill=(255, 255, 255))
    fy = y + 170
    ff = _f("Poppins-ExtraBold.ttf", 50)
    for feat in spec["feats"]:
        d.ellipse([112, fy + 4, 172, fy + 64], fill=_rgb(spec["accent"]))
        d.line([(127, fy + 34), (139, fy + 48), (160, fy + 20)], fill=(20, 20, 30), width=9)
        d.text((196, fy), feat, font=ff, fill=(255, 255, 255))
        fy += 92
    _badge(img, "INSTANT DOWNLOAD", 110, S - 220, "#FFFFFF")
    bf = _f("Poppins-ExtraBold.ttf", 44)                                # brand top-right, clear of the previews
    d.text((S - 110 - d.textlength("HookHouse Media", font=bf), 128), "HookHouse Media", font=bf, fill=(255, 255, 255))
    out = folder / "store_cover.jpg"
    rgb = img.convert("RGB")
    rgb.save(out, quality=93, optimize=True)
    rgb.resize((600, 600), Image.LANCZOS).save(folder / "store_thumb.jpg", quality=92)
    return out


if __name__ == "__main__":
    for pid in sys.argv[1:] or list(SPECS):
        print(make(pid))
