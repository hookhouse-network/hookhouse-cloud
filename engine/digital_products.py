"""Digital products, made once and sold again and again on several stores (owner, 13 Nov 2026: "more and more
digital products on different platforms, anything that pays us first").

Every product is built from things we own: our own code-drawn characters, our own music engine, code-generated
puzzles and spreadsheets. No AI images, no third-party content, so no licence or "AI content" problems.

Stores, in the order they pay us (research 13 Nov, docs/digital_products_2026-11-13.md):
1. Payhip with Razorpay connected: the buyer's money reaches the owner's Razorpay in ~2 days (UPI + cards).
2. Gumroad: weekly (Tuesdays) to an Indian bank in INR; handles foreign sales tax.
3. Amazon KDP / Google Play Books: monthly, ~60 days after the sale, but huge reach for books.
4. Later: Etsy (needs a GSTIN + Payoneer; Indian shops sell abroad only), Teachers Pay Teachers (kids printables).
None of these stores has an upload API we can use, so the owner uploads each kit (files + cover + listing.md); the
system makes everything ready."""
from __future__ import annotations

import json
import random
import shutil
import subprocess
import zipfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from .config import ROOT
from .products import _font, _mascot, _objects, line_art

OUT = ROOT / "data" / "products"
PW, PH = 2550, 3300                       # 8.5 x 11 in at 300 dpi (KDP + US Letter printables)
M = 225                                   # 0.75 in margin
INK = (40, 40, 40)
DISCLAIMER = "For education and planning only. This is not financial advice."


def _new(title: str = "", size: tuple[int, int] = (PW, PH)) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGB", size, "white")
    d = ImageDraw.Draw(img)
    if title:
        f = _font(110)
        w = d.textlength(title, font=f)
        d.text(((size[0] - w) / 2, M - 40), title, font=f, fill=INK)
    return img, d


def _save_pdf(pages: list[Image.Image], path: Path, gray: bool = False) -> Path:
    """gray=True for black-and-white line art (puzzles): same print quality at 300 dpi, a fraction of the size (20 Nov:
    the 76-page sudoku book was 26 MB in RGB and the store upload timed out)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if gray:                                   # crisp 1-bit pages (fax-compressed in the PDF), threshold not dither
        pages = [p.convert("L").point(lambda v: 255 if v > 170 else 0, mode="1") for p in pages]
    else:
        pages = [p.convert("RGB") for p in pages]
    pages[0].save(path, save_all=True, append_images=pages[1:], resolution=300)
    return path


def _cover(title: str, subtitle: str, colour: tuple[int, int, int], art: Image.Image | None = None,
           size: tuple[int, int] = (1600, 2400)) -> Image.Image:
    """A bright, simple store cover (also used as the Gumroad/Payhip thumbnail when cropped square)."""
    W, H = size
    img = Image.new("RGB", size, colour)
    d = ImageDraw.Draw(img)
    for k in range(0, H, 6):                                    # soft top-to-bottom light
        a = int(40 * (1 - k / H))
        d.line([(0, k), (W, k)], fill=tuple(min(255, c + a) for c in colour), width=6)
    if art is not None:
        art = art.copy()
        art.thumbnail((int(W * 0.8), int(H * 0.5)))
        img.paste(art, ((W - art.width) // 2, int(H * 0.36)), art if art.mode == "RGBA" else None)
    for txt, size_, y in ((title, 150, 0.1), (subtitle, 70, 0.27)):
        f = _font(size_)
        lines, cur = [], ""
        for w in txt.split():
            if d.textlength((cur + " " + w).strip(), font=f) > W * 0.86:
                lines.append(cur)
                cur = w
            else:
                cur = (cur + " " + w).strip()
        lines.append(cur)
        yy = H * y
        for ln in lines:
            tw = d.textlength(ln, font=f)
            d.text(((W - tw) / 2 + 4, yy + 4), ln, font=f, fill=(0, 0, 0))
            d.text(((W - tw) / 2, yy), ln, font=f, fill="white")
            yy += size_ * 1.15
    return img


def art_maze(seed: int = 3, size: int = 1100) -> Image.Image:
    """Cover art: a real maze with its path, in white on transparent."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cells = maze(12, 12, seed)
    _maze_draw(d, cells, 20, 20, size - 40, size - 40, path=maze_path(cells), width=14)
    px = np.array(img)
    ink = px[..., 3] > 0
    red = (px[..., 0] > 150) & (px[..., 1] < 150)
    px[ink & ~red, :3] = 255                                   # walls white, the path stays red
    px[ink & red, :3] = (255, 230, 90)                         # the path in yellow
    return Image.fromarray(px)


def art_budget(size: int = 1100) -> Image.Image:
    """Cover art: rising bars, a trend line and coins."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    bw = size // 7
    for k, h in enumerate((0.3, 0.45, 0.4, 0.62, 0.8)):
        x = 60 + k * (bw + 40)
        d.rounded_rectangle([x, size * (1 - h) - 60, x + bw, size - 60], 24, fill=(255, 255, 255, 235))
    d.line([(60 + bw / 2 + k * (bw + 40), size * (1 - h) - 120) for k, h in enumerate((0.3, 0.45, 0.4, 0.62, 0.8))],
           fill=(255, 214, 80, 255), width=22, joint="curve")
    for cx, cy, r in ((size - 210, 230, 120), (size - 330, 380, 95)):
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255, 205, 60, 255), outline=(200, 140, 20, 255), width=14)
        d.ellipse([cx - r * .55, cy - r * .55, cx + r * .55, cy + r * .55], outline=(200, 140, 20, 255), width=10)
    return img


def art_wave(mp3: Path | None = None, size: tuple[int, int] = (1300, 700), seed: int = 0) -> Image.Image:
    """Cover art: the real sound wave of the pack's first track (rounded bars), or a smooth stand-in."""
    W, H = size
    n = 64
    amps = None
    if mp3 and mp3.exists():
        try:
            from .media import ffmpeg
            raw = subprocess.run([ffmpeg.ffmpeg_bin(), "-v", "error", "-i", str(mp3), "-ac", "1", "-ar", "8000",
                                  "-f", "s16le", "-"], capture_output=True, check=True).stdout
            x = np.abs(np.frombuffer(raw, np.int16).astype(np.float32))
            amps = np.array([c.mean() for c in np.array_split(x, n)])
            amps = 0.15 + 0.85 * amps / (amps.max() + 1e-9)
        except Exception:  # noqa: BLE001
            amps = None
    if amps is None:
        amps = 0.3 + 0.7 * np.abs(np.sin(np.linspace(0, 6, n) + seed))
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    bw = W / n
    for k, a in enumerate(amps):
        h = a * H * 0.9
        d.rounded_rectangle([k * bw + bw * 0.2, (H - h) / 2, k * bw + bw * 0.8, (H + h) / 2], int(bw * 0.3),
                            fill=(255, 255, 255, 230))
    return img


def _kit(slug: str) -> Path:
    d = OUT / slug
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    return d


def _listing(folder: Path, info: dict) -> Path:
    """listing.md: one block per store, ready to paste."""
    lines = [f"# {info['title']}", "", info["description"], "", f"**Files:** {', '.join(info['files'])}", ""]
    for store in info["stores"]:
        lines += [f"## {store}", ""]
        if store in ("Gumroad", "Payhip"):
            lines += [f"- Name: {info['title']}", f"- Price: {info['price_usd']} (Payhip also {info['price_inr']})",
                      f"- Tags: {', '.join(info['tags'])}", "- Cover: cover.jpg, thumbnail: thumb.jpg", ""]
        elif store == "Amazon KDP":
            lines += [f"- Title: {info['title']}", f"- Subtitle: {info.get('subtitle', '')}",
                      "- Author: the brand name (pen name allowed on KDP)",
                      f"- Keywords (7): {', '.join(info['tags'][:7])}", f"- Categories: {info.get('kdp_categories', '')}",
                      f"- Print: 8.5 x 11 in, black & white interior, no bleed, {info.get('pages', '?')} pages",
                      f"- Price: {info.get('kdp_price', info['price_usd'])}",
                      "- AI content question: NO (made by our own code, no generative AI)",
                      "- Cover: make it with KDP Cover Creator using cover.jpg as the front image", ""]
        elif store == "Teachers Pay Teachers":
            lines += [f"- Grades: {info.get('grades', 'PreK-1')}", f"- Price: {info['price_usd']}", ""]
    if info.get("note"):
        lines += ["## Note", "", info["note"], ""]
    p = folder / "listing.md"
    p.write_text("\n".join(lines), encoding="utf-8")
    (folder / "product.json").write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")
    return p


def _thumb(cover: Image.Image, folder: Path) -> None:
    cover.save(folder / "cover.jpg", quality=92)
    s = min(cover.size)
    sq = cover.crop(((cover.width - s) // 2, 0, (cover.width + s) // 2, s)).resize((1000, 1000))
    sq.save(folder / "thumb.jpg", quality=92)


# ======================================================================================================
# 1. Money Cheat Codes budget planner (Excel with working formulas + printable PDF pages)
# ======================================================================================================
NEEDS = ["Rent / home loan", "Groceries", "Electricity, water, gas", "Phone & internet", "Transport / fuel",
         "Insurance", "Minimum debt payments"]
WANTS = ["Eating out", "Shopping", "Entertainment", "Subscriptions", "Travel", "Gifts"]
SAVES = ["Emergency fund", "Investments", "Goal savings"]


def budget_workbook(path: Path, currency: str = "INR") -> Path:
    from openpyxl import Workbook
    from openpyxl.formatting.rule import CellIsRule, DataBarRule
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.worksheet.datavalidation import DataValidation

    money = '"₹"#,##0' if currency == "INR" else '"$"#,##0.00'
    head = PatternFill("solid", fgColor="1E8E5A")
    soft = PatternFill("solid", fgColor="E9F7EF")
    white_b = Font(bold=True, color="FFFFFF")
    bold = Font(bold=True)
    wb = Workbook()

    st = wb.active
    st.title = "Start Here"
    rows = ["Money Cheat Codes: Budget Planner", "",
            "1. Expense Tracker: write every spend (date, what, category, amount).",
            "2. Monthly Budget: type your income and your plan for each category. 'Actual' fills itself from the tracker.",
            "3. The 50/30/20 check shows your plan next to the classic split: 50% needs, 30% wants, 20% savings.",
            "4. Savings Goals and Debt Payoff show how many months each goal or debt needs.",
            "5. Net Worth: what you own minus what you owe. Update it once a month.", "",
            "Only edit the white cells; the green cells are formulas.", "", DISCLAIMER]
    for i, r in enumerate(rows, 1):
        st.cell(i, 1, r).font = Font(bold=i == 1, size=16 if i == 1 else 11)
    st.column_dimensions["A"].width = 110

    tr = wb.create_sheet("Expense Tracker")
    for c, h in enumerate(["Date", "What", "Category", "Amount"], 1):
        cell = tr.cell(1, c, h)
        cell.fill, cell.font = head, white_b
    cats = NEEDS + WANTS + SAVES
    lists = wb.create_sheet("Lists")
    for i, c in enumerate(cats, 1):
        lists.cell(i, 1, c)
    lists.sheet_state = "hidden"
    dv = DataValidation(type="list", formula1=f"=Lists!$A$1:$A${len(cats)}", allow_blank=True)
    tr.add_data_validation(dv)
    dv.add("C2:C1000")
    for r in range(2, 1001):
        tr.cell(r, 4).number_format = money
        tr.cell(r, 1).number_format = "dd-mmm-yyyy"
    for col, w in zip("ABCD", (14, 36, 26, 14)):
        tr.column_dimensions[col].width = w
    tr.freeze_panes = "A2"

    mb = wb.create_sheet("Monthly Budget", 1)
    mb["A1"] = "Monthly Budget"
    mb["A1"].font = Font(bold=True, size=16)
    mb["A3"], mb["A3"].font = "Income", bold
    inc = ["Salary", "Side income", "Other income"]
    for i, name in enumerate(inc):
        mb.cell(4 + i, 1, name)
        mb.cell(4 + i, 2).number_format = money
    mb["A7"], mb["B7"] = "Total income", "=SUM(B4:B6)"
    mb["A7"].font = mb["B7"].font = bold
    mb["B7"].number_format = money
    mb["B7"].fill = soft
    row = 9
    sections = {}
    for title, items in (("Needs", NEEDS), ("Wants", WANTS), ("Savings", SAVES)):
        for c, h in enumerate([title, "Planned", "Actual", "Difference"], 1):
            cell = mb.cell(row, c, h)
            cell.fill, cell.font = head, white_b
        first = row + 1
        for k, item in enumerate(items):
            r = first + k
            mb.cell(r, 1, item)
            mb.cell(r, 2).number_format = money
            mb.cell(r, 3, f"=SUMIF('Expense Tracker'!$C:$C,A{r},'Expense Tracker'!$D:$D)").number_format = money
            mb.cell(r, 4, f"=B{r}-C{r}").number_format = money
            mb.cell(r, 3).fill = mb.cell(r, 4).fill = soft
        last = first + len(items) - 1
        tot = last + 1
        mb.cell(tot, 1, f"Total {title.lower()}").font = bold
        for c, colL in ((2, "B"), (3, "C"), (4, "D")):
            cell = mb.cell(tot, c, f"=SUM({colL}{first}:{colL}{last})")
            cell.number_format, cell.font, cell.fill = money, bold, soft
        mb.conditional_formatting.add(f"D{first}:D{last}", CellIsRule(operator="lessThan", formula=["0"],
                                                                        fill=PatternFill("solid", fgColor="F8D7DA")))
        sections[title] = tot
        row = tot + 2
    mb.cell(row, 1, "50/30/20 check").font = Font(bold=True, size=13)
    for c, h in enumerate(["", "Your plan", "% of income", "Classic target"], 1):
        cell = mb.cell(row + 1, c, h)
        cell.fill, cell.font = head, white_b
    for k, (title, share) in enumerate((("Needs", 0.5), ("Wants", 0.3), ("Savings", 0.2))):
        r = row + 2 + k
        mb.cell(r, 1, title)
        mb.cell(r, 2, f"=B{sections[title]}").number_format = money
        mb.cell(r, 3, f'=IF($B$7>0,B{r}/$B$7,"")').number_format = "0%"
        mb.cell(r, 4, f"=$B$7*{share}").number_format = money
        for c in (2, 3, 4):
            mb.cell(r, c).fill = soft
    left = row + 6
    mb.cell(left, 1, "Left over after the plan").font = bold
    mb.cell(left, 2, f"=B7-B{sections['Needs']}-B{sections['Wants']}-B{sections['Savings']}").number_format = money
    mb.cell(left, 2).fill = soft
    for col, w in zip("ABCD", (34, 16, 16, 16)):
        mb.column_dimensions[col].width = w
    mb.cell(left + 2, 1, DISCLAIMER).font = Font(italic=True, color="777777")

    sg = wb.create_sheet("Savings Goals")
    for c, h in enumerate(["Goal", "Target", "Saved so far", "Saving per month", "Progress", "Months to go"], 1):
        cell = sg.cell(1, c, h)
        cell.fill, cell.font = head, white_b
    for r, (g, tgt) in enumerate((("Emergency fund (6 months of needs)", None), ("New phone", None),
                                  ("Trip", None), ("", None), ("", None)), 2):
        sg.cell(r, 1, g)
        for c in (2, 3, 4):
            sg.cell(r, c).number_format = money
        sg.cell(r, 5, f'=IF(B{r}>0,MIN(1,C{r}/B{r}),"")').number_format = "0%"
        sg.cell(r, 6, f'=IF(AND(B{r}>0,D{r}>0),MAX(0,ROUNDUP((B{r}-C{r})/D{r},0)),"")')
        sg.cell(r, 5).fill = sg.cell(r, 6).fill = soft
    sg.conditional_formatting.add("E2:E6", DataBarRule(start_type="num", start_value=0, end_type="num", end_value=1,
                                                       color="1E8E5A"))
    for col, w in zip("ABCDEF", (38, 14, 14, 18, 12, 14)):
        sg.column_dimensions[col].width = w

    dp = wb.create_sheet("Debt Payoff")
    for c, h in enumerate(["Debt (smallest first = snowball)", "Balance", "Interest % a year", "Monthly payment",
                           "Months to pay off", "Total interest"], 1):
        cell = dp.cell(1, c, h)
        cell.fill, cell.font = head, white_b
    for r in range(2, 8):
        dp.cell(r, 2).number_format = money
        dp.cell(r, 4).number_format = money
        dp.cell(r, 5, f'=IF(AND(B{r}>0,D{r}>0),IFERROR(ROUNDUP(IF(C{r}=0,B{r}/D{r},'
                      f'NPER(C{r}/1200,-D{r},B{r})),0),"payment too low"),"")')
        dp.cell(r, 6, f'=IF(ISNUMBER(E{r}),MAX(0,E{r}*D{r}-B{r}),"")').number_format = money
        dp.cell(r, 5).fill = dp.cell(r, 6).fill = soft
    for col, w in zip("ABCDEF", (36, 14, 18, 18, 18, 16)):
        dp.column_dimensions[col].width = w

    nw = wb.create_sheet("Net Worth")
    nw["A1"], nw["A1"].font = "What I own", bold
    nw["C1"], nw["C1"].font = "What I owe", bold
    for k, (a, b) in enumerate((("Bank & cash", "Home loan"), ("Investments", "Car loan"), ("Retirement (PF/NPS/401k)",
                                "Credit cards"), ("Property", "Other loans"), ("Other", ""))):
        nw.cell(2 + k, 1, a)
        nw.cell(2 + k, 3, b)
        nw.cell(2 + k, 2).number_format = money
        nw.cell(2 + k, 4).number_format = money
    nw["A8"], nw["B8"], nw["C8"], nw["D8"] = "Total owned", "=SUM(B2:B6)", "Total owed", "=SUM(D2:D6)"
    nw["A10"], nw["B10"] = "NET WORTH", "=B8-D8"
    for c in ("B8", "D8", "B10"):
        nw[c].number_format, nw[c].fill, nw[c].font = money, soft, bold
    nw["A10"].font = Font(bold=True, size=14)
    for col, w in zip("ABCD", (30, 16, 22, 16)):
        nw.column_dimensions[col].width = w
    for ws in wb.worksheets:
        for r in ws.iter_rows():
            for cell in r:
                cell.alignment = Alignment(vertical="center")
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path


def _table_page(title: str, cols: list[tuple[str, float]], rows: int, foot: str = "") -> Image.Image:
    img, d = _new(title)
    x0, x1, y0 = M, PW - M, M + 220
    rh = (PH - M - 200 - y0) / (rows + 1)
    f = _font(52)
    xs = [x0]
    for _, share in cols:
        xs.append(xs[-1] + (x1 - x0) * share)
    d.rectangle([x0, y0, x1, y0 + rh], fill=(220, 240, 228))
    for (name, _), xa in zip(cols, xs):
        d.text((xa + 18, y0 + rh / 2 - 30), name, font=f, fill=INK)
    for r in range(rows + 2):
        y = y0 + r * rh
        d.line([(x0, y), (x1, y)], fill=(150, 150, 150), width=3)
    for xa in xs:
        d.line([(xa, y0), (xa, y0 + (rows + 1) * rh)], fill=(150, 150, 150), width=3)
    if foot:
        ff = _font(40, bold=False)
        d.text((M, PH - M - 60), foot, font=ff, fill=(110, 110, 110))
    return img


def budget_planner(log=print) -> Path:
    folder = _kit("money_budget_planner")
    for cur in ("INR", "USD"):
        budget_workbook(folder / f"Money_Cheat_Codes_Budget_Planner_{cur}.xlsx", cur)
    pages = [_table_page("Monthly Budget", [("Category", 0.4), ("Planned", 0.2), ("Actual", 0.2), ("Difference", 0.2)],
                         22, DISCLAIMER),
             _table_page("Expense Log", [("Date", 0.18), ("What", 0.42), ("Category", 0.22), ("Amount", 0.18)], 28),
             _table_page("Savings Goals", [("Goal", 0.4), ("Target", 0.2), ("Saved", 0.2), ("Months left", 0.2)], 12),
             _table_page("Debt Payoff", [("Debt", 0.34), ("Balance", 0.22), ("Rate %", 0.2), ("Payment", 0.24)], 12),
             _table_page("Net Worth", [("Own", 0.3), ("Amount", 0.2), ("Owe", 0.3), ("Amount", 0.2)], 12)]
    _save_pdf(pages, folder / "Money_Cheat_Codes_Printable_Planner.pdf")
    cover = _cover("Budget Planner", "Spreadsheet + printable pages · 50/30/20 · goals · debt payoff",
                   (30, 142, 90), art_budget())
    _thumb(cover, folder)
    _listing(folder, {
        "title": "Money Cheat Codes Budget Planner (Excel + Google Sheets + Printable)",
        "description": ("A simple budget planner that does the math for you. Track every spend, see your plan next to "
                        "the 50/30/20 rule, watch your savings goals fill up, and see how many months each debt "
                        "needs. Works in Excel and Google Sheets (File > Import). Rupee (₹) and dollar ($) versions "
                        "plus 5 printable pages. " + DISCLAIMER),
        "files": [p.name for p in sorted(folder.glob("*.xlsx")) + sorted(folder.glob("*.pdf"))],
        "price_usd": "$7", "price_inr": "₹199", "tags": ["budget planner", "budget spreadsheet", "50 30 20",
                                                            "savings tracker", "debt payoff", "expense tracker",
                                                            "google sheets budget", "excel budget template"],
        "stores": ["Payhip", "Gumroad"], "channel": "money_cheat_codes",
        "note": "Link it in Money Cheat Codes descriptions (education only, never a promise of returns)."})
    log(f"  budget planner -> {folder}")
    return folder


# ======================================================================================================
# 2. Brain Snack puzzle book (word search, mazes, sudoku; all checked by code)
# ======================================================================================================
THEMES = {
    "Space": ["PLANET", "COMET", "GALAXY", "ORBIT", "ROCKET", "METEOR", "NEBULA", "ASTEROID", "SATURN", "JUPITER",
              "MOON", "STAR"],
    "Ocean": ["CORAL", "WHALE", "SHARK", "DOLPHIN", "OCTOPUS", "SQUID", "REEF", "TIDE", "WAVE", "CRAB", "KELP",
              "ANCHOR"],
    "Wild Animals": ["TIGER", "ZEBRA", "GIRAFFE", "LION", "MONKEY", "PANDA", "KOALA", "RHINO", "CAMEL", "OTTER",
                     "EAGLE", "HIPPO"],
    "Yummy Food": ["PIZZA", "MANGO", "BANANA", "NOODLE", "COOKIE", "BURGER", "APPLE", "CHEESE", "PASTA", "GRAPE",
                   "LEMON", "SAMOSA"],
    "Sports": ["CRICKET", "SOCCER", "TENNIS", "HOCKEY", "CHESS", "SKATING", "BOXING", "CYCLING", "ROWING", "KARATE",
               "GOLF", "RUGBY"],
    "Science": ["ATOM", "ENERGY", "MAGNET", "GRAVITY", "OXYGEN", "CELL", "LASER", "ROBOT", "FOSSIL", "VOLCANO",
                "PRISM", "CIRCUIT"],
    "Weather": ["THUNDER", "RAINBOW", "STORM", "CLOUD", "BREEZE", "SUNNY", "FROST", "HAIL", "MONSOON", "TORNADO",
                "FOG", "DRIZZLE"],
    "Music": ["GUITAR", "PIANO", "DRUM", "VIOLIN", "FLUTE", "TABLA", "SITAR", "RHYTHM", "MELODY", "CHORUS", "TEMPO",
              "HARP"],
    "Dinosaurs": ["TREX", "RAPTOR", "FOSSIL", "JURASSIC", "SPINO", "STEGO", "TRICERA", "EGGS", "CLAW", "TAIL",
                  "BONES", "EXTINCT"],
    "Inventions": ["WHEEL", "PHONE", "RADIO", "ENGINE", "CAMERA", "LIGHTBULB", "PRINTER", "COMPASS", "ROCKET",
                   "BATTERY", "COMPUTER", "PLANE"],
}
DIRS = [(0, 1), (1, 0), (1, 1), (-1, 1)]                      # right, down, diagonal down, diagonal up


def word_search(words: list[str], size: int = 15, seed: int = 0) -> tuple[list[list[str]], dict]:
    """A filled grid and where each word sits {word: [(r, c), ...]}; raises if a word can't be placed."""
    rng = random.Random(seed)
    grid = [[""] * size for _ in range(size)]
    where = {}
    for w in sorted(words, key=len, reverse=True):
        for _ in range(500):
            dr, dc = rng.choice(DIRS)
            r0, c0 = rng.randrange(size), rng.randrange(size)
            cells = [(r0 + dr * k, c0 + dc * k) for k in range(len(w))]
            if all(0 <= r < size and 0 <= c < size and grid[r][c] in ("", w[k]) for k, (r, c) in enumerate(cells)):
                for k, (r, c) in enumerate(cells):
                    grid[r][c] = w[k]
                where[w] = cells
                break
        else:
            raise ValueError(f"could not place {w}")
    letters = "ABCDEFGHIJKLMNOPRSTUVWY"
    for r in range(size):
        for c in range(size):
            if not grid[r][c]:
                grid[r][c] = rng.choice(letters)
    return grid, where


def maze(rows: int, cols: int, seed: int = 0) -> list[list[set]]:
    """A perfect maze (exactly one path between any two cells): cell -> set of open directions 'NSEW'."""
    rng = random.Random(seed)
    cells = [[set() for _ in range(cols)] for _ in range(rows)]
    seen = {(0, 0)}
    stack = [(0, 0)]
    step = {"N": (-1, 0, "S"), "S": (1, 0, "N"), "E": (0, 1, "W"), "W": (0, -1, "E")}
    while stack:
        r, c = stack[-1]
        nxt = [(d, r + dr, c + dc, back) for d, (dr, dc, back) in step.items()
               if 0 <= r + dr < rows and 0 <= c + dc < cols and (r + dr, c + dc) not in seen]
        if not nxt:
            stack.pop()
            continue
        d, nr, nc, back = rng.choice(nxt)
        cells[r][c].add(d)
        cells[nr][nc].add(back)
        seen.add((nr, nc))
        stack.append((nr, nc))
    return cells


def maze_path(cells: list[list[set]]) -> list[tuple[int, int]]:
    rows, cols = len(cells), len(cells[0])
    step = {"N": (-1, 0), "S": (1, 0), "E": (0, 1), "W": (0, -1)}
    prev = {(0, 0): None}
    queue = [(0, 0)]
    while queue:
        r, c = queue.pop(0)
        for d in cells[r][c]:
            nr, nc = r + step[d][0], c + step[d][1]
            if (nr, nc) not in prev:
                prev[(nr, nc)] = (r, c)
                queue.append((nr, nc))
    path, cur = [], (rows - 1, cols - 1)
    while cur is not None:
        path.append(cur)
        cur = prev[cur]
    return path[::-1]


def _sudoku_solutions(g: list[list[int]], limit: int = 2) -> int:
    for r in range(9):
        for c in range(9):
            if g[r][c] == 0:
                count = 0
                for v in range(1, 10):
                    if _ok(g, r, c, v):
                        g[r][c] = v
                        count += _sudoku_solutions(g, limit - count)
                        g[r][c] = 0
                        if count >= limit:
                            return count
                return count
    return 1


def _ok(g, r, c, v) -> bool:
    if v in g[r] or any(g[k][c] == v for k in range(9)):
        return False
    br, bc = 3 * (r // 3), 3 * (c // 3)
    return all(g[i][j] != v for i in range(br, br + 3) for j in range(bc, bc + 3))


def sudoku(clues: int = 34, seed: int = 0) -> tuple[list[list[int]], list[list[int]]]:
    """(puzzle, solution): a full grid, then cells removed while the answer stays unique."""
    rng = random.Random(seed)
    sol = [[0] * 9 for _ in range(9)]

    def fill(k=0) -> bool:
        if k == 81:
            return True
        r, c = divmod(k, 9)
        vals = list(range(1, 10))
        rng.shuffle(vals)
        for v in vals:
            if _ok(sol, r, c, v):
                sol[r][c] = v
                if fill(k + 1):
                    return True
                sol[r][c] = 0
        return False
    fill()
    puz = [row[:] for row in sol]
    cells = [(r, c) for r in range(9) for c in range(9)]
    rng.shuffle(cells)
    left = 81
    for r, c in cells:
        if left <= clues:
            break
        keep = puz[r][c]
        puz[r][c] = 0
        if _sudoku_solutions([row[:] for row in puz]) != 1:
            puz[r][c] = keep
        else:
            left -= 1
    return puz, sol


def _ws_page(theme: str, grid, where, solution: bool = False, box=None) -> Image.Image:
    img, d = _new("" if box else f"Word Search: {theme}")
    n = len(grid)
    x0, y0, side = box or (M + 75, M + 260, PW - 2 * M - 150)
    cell = side / n
    f = _font(int(cell * 0.62))
    if solution:
        for w, cells in where.items():
            (r0, c0), (r1, c1) = cells[0], cells[-1]
            d.line([(x0 + (c0 + .5) * cell, y0 + (r0 + .5) * cell), (x0 + (c1 + .5) * cell, y0 + (r1 + .5) * cell)],
                   fill=(255, 214, 102), width=int(cell * 0.7))
    for r in range(n):
        for c in range(n):
            ch = grid[r][c]
            tw = d.textlength(ch, font=f)
            d.text((x0 + c * cell + (cell - tw) / 2, y0 + r * cell + cell * 0.12), ch, font=f, fill=INK)
    d.rectangle([x0 - 20, y0 - 20, x0 + side + 20, y0 + side + 20], outline=INK, width=6)
    if not box:
        fw = _font(64)
        ws = sorted(where)
        for k, w in enumerate(ws):
            col, row = k % 3, k // 3
            d.text((M + 60 + col * (PW - 2 * M) / 3, y0 + side + 110 + row * 100), w, font=fw, fill=INK)
    return img


def _maze_draw(d, cells, x0, y0, side_w, side_h, path=None, width=6):
    rows, cols = len(cells), len(cells[0])
    cw, ch = side_w / cols, side_h / rows
    for r in range(rows):
        for c in range(cols):
            x, y = x0 + c * cw, y0 + r * ch
            if "N" not in cells[r][c] and not (r == 0 and c == 0):
                d.line([(x, y), (x + cw, y)], fill=INK, width=width)
            if "W" not in cells[r][c]:
                d.line([(x, y), (x, y + ch)], fill=INK, width=width)
    d.line([(x0, y0 + side_h), (x0 + side_w - cw, y0 + side_h)], fill=INK, width=width)   # exit at bottom right
    d.line([(x0 + side_w, y0), (x0 + side_w, y0 + side_h)], fill=INK, width=width)
    if path:
        pts = [(x0 + (c + .5) * cw, y0 + (r + .5) * ch) for r, c in path]
        d.line(pts, fill=(230, 80, 80), width=max(4, int(width * 1.2)))


def _sudoku_draw(d, puz, x0, y0, side, sol=None):
    cell = side / 9
    f = _font(int(cell * 0.6))
    for k in range(10):
        w = 8 if k % 3 == 0 else 2
        d.line([(x0, y0 + k * cell), (x0 + side, y0 + k * cell)], fill=INK, width=w)
        d.line([(x0 + k * cell, y0), (x0 + k * cell, y0 + side)], fill=INK, width=w)
    for r in range(9):
        for c in range(9):
            v = puz[r][c] or (sol[r][c] if sol else 0)
            if v:
                tw = d.textlength(str(v), font=f)
                d.text((x0 + c * cell + (cell - tw) / 2, y0 + r * cell + cell * 0.15), str(v), font=f,
                       fill=INK if puz[r][c] else (60, 110, 200))


def senior_sudoku(seed: int = 71, log=print) -> Path:
    """Large Print Sudoku for Seniors (research 17 Nov: seniors' puzzles sell Nov-Jan as gifts). 60 puzzles, one
    big grid per page, easy -> medium, every puzzle with exactly one answer (checked by the solver), answers at the
    back four to a page."""
    folder = _kit("senior_sudoku")
    pages, sols = [], []
    for k in range(60):
        clues = 44 if k < 20 else (38 if k < 40 else 34)
        puz, sol = sudoku(clues, seed + k)
        sols.append((puz, sol))
        level = ["Easy", "Easy-Medium", "Medium"][k // 20]
        img, d = _new(f"Puzzle {k + 1}  ({level})")
        _sudoku_draw(d, puz, M + 25, M + 420, PW - 2 * M - 50)
        pages.append(img)
    half = (PW - 2 * M - 100) / 2
    sol_pages = []
    for chunk in range(0, len(sols), 4):
        img, d = _new("Answers")
        for j, (puz, sol) in enumerate(sols[chunk:chunk + 4]):
            x, y = M + (j % 2) * (half + 100), M + 300 + (j // 2) * (half + 250)
            d.text((x, y - 90), f"Puzzle {chunk + j + 1}", font=_font(54), fill=INK)
            _sudoku_draw(d, puz, x, y, half, sol)
        sol_pages.append(img)
    title, d0 = _new()
    for txt, sz, y in (("LARGE PRINT", 170, 0.25), ("SUDOKU", 230, 0.34), ("60 puzzles, easy to medium", 80, 0.47),
                       ("One big puzzle per page, answers included", 64, 0.55)):
        tw = d0.textlength(txt, font=_font(sz))
        d0.text(((PW - tw) / 2, PH * y), txt, font=_font(sz), fill=INK)
    allp = [title] + pages + sol_pages
    if len(allp) % 2:
        allp.append(_new("Notes")[0])
    _save_pdf(allp, folder / "Large_Print_Sudoku_Seniors.pdf", gray=True)
    cover = _cover("Large Print Sudoku", "60 puzzles, big numbers, answers included", (24, 76, 140))
    _thumb(cover, folder)
    _listing(folder, {
        "title": "Large Print Sudoku for Seniors: 60 Easy to Medium Puzzles, One per Page (Printable PDF)",
        "subtitle": "60 big-number sudoku puzzles with answers",
        "description": ("60 sudoku puzzles in extra-large print, one big grid per page so the numbers are easy to "
                        "read and write in. They start easy and build up to medium, and every puzzle has exactly one "
                        "answer (checked by computer). All answers are at the back. Print at home on US Letter or A4 "
                        "and print your favourites again any time. A thoughtful gift for grandparents."),
        "files": ["Large_Print_Sudoku_Seniors.pdf"], "pages": len(allp),
        "price_usd": "$4 (printable PDF)", "price_inr": "\u20b999", "kdp_price": "$6.99 paperback",
        "tags": ["large print sudoku", "sudoku for seniors", "easy sudoku", "puzzle book for adults",
                 "brain games for seniors", "gift for grandparents", "printable sudoku"],
        "kdp_categories": "Humor & Entertainment > Puzzles & Games > Sudoku",
        "stores": ["Payhip", "Gumroad", "Amazon KDP"], "channel": "brain_snack",
        "promo_angles": ["A sudoku trick most people never learn: look for the hidden single",
                         "Can you solve this sudoku row in 10 seconds?"]})
    log(f"  large print sudoku ({len(allp)} pages) -> {folder}")
    return folder


def puzzle_book(seed: int = 11, log=print) -> Path:
    folder = _kit("brain_snack_puzzle_book")
    pages, sol_pages = [], []
    searches = []
    for k, (theme, words) in enumerate(THEMES.items()):
        grid, where = word_search(words, 15, seed + k)
        searches.append((theme, grid, where))
        pages.append(_ws_page(theme, grid, where))
    mazes = []
    for k in range(12):
        rows, cols = (14, 11) if k < 4 else ((18, 14) if k < 8 else (24, 18))
        cells = maze(rows, cols, seed + 100 + k)
        mazes.append(cells)
        img, d = _new(f"Maze {k + 1}  ({['Easy', 'Medium', 'Hard'][k // 4]})")
        _maze_draw(d, cells, M + 60, M + 300, PW - 2 * M - 120, PH - 2 * M - 500)
        d.text((M + 60, M + 220), "START", font=_font(56), fill=INK)
        d.text((PW - M - 330, PH - M - 170), "FINISH", font=_font(56), fill=INK)
        pages.append(img)
    sudokus = []
    for k in range(12):
        clues = 38 if k < 4 else (32 if k < 8 else 28)
        puz, sol = sudoku(clues, seed + 200 + k)
        sudokus.append((puz, sol))
        img, d = _new(f"Sudoku {k + 1}  ({['Easy', 'Medium', 'Hard'][k // 4]})")
        _sudoku_draw(d, puz, M + 75, M + 400, PW - 2 * M - 150)
        pages.append(img)
    # solutions: 4 word searches / mazes per page, 4 sudoku per page
    half = (PW - 2 * M - 100) / 2
    for chunk in range(0, len(searches), 4):
        img, d = _new("Solutions: Word Search")
        for j, (theme, grid, where) in enumerate(searches[chunk:chunk + 4]):
            x, y = M + (j % 2) * (half + 100), M + 300 + (j // 2) * (half + 250)
            d.text((x, y - 90), theme, font=_font(54), fill=INK)
            sub = _ws_page(theme, grid, where, solution=True, box=(x, y, half))
            img.paste(sub.crop((int(x - 30), int(y - 30), int(x + half + 30), int(y + half + 30))),
                      (int(x - 30), int(y - 30)))
        sol_pages.append(img)
    for chunk in range(0, len(mazes), 4):
        img, d = _new("Solutions: Mazes")
        for j, cells in enumerate(mazes[chunk:chunk + 4]):
            x, y = M + (j % 2) * (half + 100), M + 300 + (j // 2) * (half * 1.3 + 150)
            d.text((x, y - 90), f"Maze {chunk + j + 1}", font=_font(54), fill=INK)
            _maze_draw(d, cells, x, y, half, half * 1.25, path=maze_path(cells), width=3)
        sol_pages.append(img)
    for chunk in range(0, len(sudokus), 4):
        img, d = _new("Solutions: Sudoku")
        for j, (puz, sol) in enumerate(sudokus[chunk:chunk + 4]):
            x, y = M + (j % 2) * (half + 100), M + 300 + (j // 2) * (half + 250)
            d.text((x, y - 90), f"Sudoku {chunk + j + 1}", font=_font(54), fill=INK)
            _sudoku_draw(d, puz, x, y, half, sol)
        sol_pages.append(img)
    title, d0 = _new()
    for txt, sz, y in (("BRAIN SNACK", 220, 0.25), ("Puzzle Book", 150, 0.36),
                       ("Word Search · Mazes · Sudoku", 80, 0.47), ("With all the answers", 64, 0.55)):
        tw = d0.textlength(txt, font=_font(sz))
        d0.text(((PW - tw) / 2, PH * y), txt, font=_font(sz), fill=INK)
    allp = [title] + pages + sol_pages
    if len(allp) % 2:
        allp.append(_new("Notes")[0])
    _save_pdf(allp, folder / "Brain_Snack_Puzzle_Book.pdf")
    cover = _cover("Brain Snack Puzzle Book", "Word search · mazes · sudoku · answers included", (232, 87, 154),
                   art_maze(seed))
    _thumb(cover, folder)
    _listing(folder, {
        "title": "Brain Snack Puzzle Book: Word Search, Mazes and Sudoku for Kids and Teens",
        "subtitle": f"{len(THEMES)} word searches, 12 mazes and 12 sudoku from easy to hard, with answers",
        "description": (f"{len(pages)} puzzles that get harder as you go: {len(THEMES)} themed word searches (space, "
                        "ocean, animals, food, sports, science and more), 12 mazes and 12 sudoku, each from easy to "
                        "hard, with every answer at the back. Large print, one puzzle per page. Every maze has "
                        "exactly one way through and every sudoku has exactly one answer."),
        "files": ["Brain_Snack_Puzzle_Book.pdf"], "pages": len(allp),
        "price_usd": "$4 (printable PDF)", "price_inr": "₹99", "kdp_price": "$6.99 paperback",
        "tags": ["puzzle book for kids", "word search for kids", "mazes for kids", "sudoku for kids",
                 "activity book ages 8-12", "brain games", "large print puzzles", "travel activity book"],
        "kdp_categories": "Children's Books > Activities, Crafts & Games > Puzzles; Games & Activities > Puzzles",
        "stores": ["Amazon KDP", "Payhip", "Gumroad"], "channel": "brain_snack"})
    log(f"  puzzle book ({len(allp)} pages) -> {folder}")
    return folder


# ======================================================================================================
# 3. Royalty-free music packs from our own music engine
# ======================================================================================================
PACKS = {
    "devotional": ("Indian Devotional Background Music", "devotional", "Temple bells, tanpura, bansuri and shankh"),
    "dhol": ("Indian Dhol & Stadium Energy Music", "dhol", "Dhol grooves that build, crowd swells"),
    "retro": ("Retro Bollywood Nostalgia Music", "retro", "Harmonium, santoor, tabla and old-record warmth"),
    "cosmic": ("Space & Cosmos Ambient Music", "cosmic", "Slow wide pads and starry shimmer"),
    "ocean": ("Deep Ocean Documentary Music", "ocean", "Deep pads and slow wave swells"),
    "wild": ("Wildlife Documentary Music", "wild", "Warm pads, plucked arpeggios, hand drums"),
}
LICENSE = """ROYALTY-FREE MUSIC LICENSE ({brand})
You may use these tracks in your own videos, podcasts, streams, games, apps and presentations, including monetized
YouTube/Instagram/Facebook videos and client work, forever, with no extra payment and no credit required.
You may NOT: resell or share the tracks as music files, put them in another music library or pack, or register them
with YouTube Content ID or any other fingerprinting service.
All music was composed and produced by {brand} with our own software. No samples from third parties."""


def _mp3(wav: Path, mp3: Path, bitrate: str = "256k") -> None:
    from .media import ffmpeg
    subprocess.run([ffmpeg.ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-y", "-i", str(wav), "-codec:a",
                    "libmp3lame", "-b:a", bitrate, str(mp3)], check=True)


def music_pack(key: str, tracks: int = 5, seconds: float = 90.0, brand: str = "HookHouse Media", log=print) -> Path:
    import soundfile as sf

    from .media import emotion_music, sfx
    title, mood, blurb = PACKS[key]
    folder = _kit(f"music_pack_{key}")
    tmp = folder / "_wav"
    tmp.mkdir()
    names = []
    for k in range(tracks):
        rng = random.Random(1000 + k)
        if mood in emotion_music.PALETTES:
            climax = seconds * rng.uniform(0.62, 0.75)
            reveals = [seconds * rng.uniform(0.3, 0.45)]
            x = emotion_music.score(seconds, mood, climax=climax, reveals=reveals, seed=k + 3)
        else:
            x = sfx.music_bed(seconds, mood, seed=k + 3)
        x = np.asarray(x, np.float32)
        x = 0.89 * x / (np.abs(x).max() + 1e-9)
        name = f"{key}_{k + 1:02d}"
        wav = tmp / f"{name}.wav"
        sf.write(wav, np.column_stack([x, x]), 48000)
        _mp3(wav, folder / f"{name}.mp3")
        names.append(f"{name}.mp3")
    preview = folder / "preview.mp3"                             # 30 s preview for the store page
    from .media import ffmpeg
    subprocess.run([ffmpeg.ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-y", "-i", str(tmp / f"{key}_01.wav"),
                    "-t", "30", "-af", "afade=t=out:st=27:d=3", "-b:a", "128k", str(preview)], check=True)
    shutil.rmtree(tmp)
    (folder / "LICENSE.txt").write_text(LICENSE.format(brand=brand), encoding="utf-8")
    with zipfile.ZipFile(folder / f"{key}_music_pack.zip", "w", zipfile.ZIP_DEFLATED) as z:
        for n in names + ["LICENSE.txt"]:
            z.write(folder / n, n)
    colours = {"devotional": (150, 70, 20), "dhol": (180, 40, 60), "retro": (120, 60, 110), "cosmic": (30, 30, 80),
               "ocean": (10, 70, 110), "wild": (40, 100, 50)}
    cover = _cover(title, f"{tracks} royalty-free tracks · {blurb}", colours.get(key, (40, 52, 90)),
                   art_wave(folder / f"{key}_01.mp3"))
    _thumb(cover, folder)
    _listing(folder, {
        "title": f"{title} ({tracks} Royalty-Free Tracks for Videos)",
        "description": (f"{tracks} original tracks, {int(seconds)} seconds each, made for YouTube, Reels and podcasts: "
                        f"{blurb.lower()}. Each track builds, has a quiet moment and a peak, so it fits a story. "
                        "Use them in monetized videos and client work, no credit needed. Content ID-free: our "
                        "music is never registered, so your videos won't get claims."),
        "files": [f"{key}_music_pack.zip", "preview.mp3"], "price_usd": "$9", "price_inr": "₹249",
        "tags": ["royalty free music", "background music for youtube", "no copyright music", f"{key} music",
                 "music for videos", "content id free", "music pack"],
        "stores": ["Payhip", "Gumroad"], "channel": ""})
    log(f"  music pack {key} -> {folder}")
    return folder


# ======================================================================================================
# 4. Bloop coloring book (our own characters as line art)
# ======================================================================================================
def colouring_book(log=print) -> Path:
    folder = _kit("bloop_colouring_book")
    objs = _objects()
    pages = []
    cast = ["Bloop", "Pip", "Mo", "Dee"]
    things = list(objs)
    title, d = _new()
    for txt, sz, y in (("Color with Bloop!", 190, 0.3), ("A coloring book for little hands", 80, 0.42)):
        tw = d.textlength(txt, font=_font(sz))
        d.text(((PW - tw) / 2, PH * y), txt, font=_font(sz), fill=INK)
    pages.append(title)
    for k in range(24):
        name = cast[k % 4]
        thing = things[k % len(things)]
        img, d = _new(f"{name} and the {thing}s" if thing != "fish" else f"{name} and the fish")
        hero = line_art(_mascot(name, 900), 1300, thick=9)
        img.paste(hero.convert("RGB"), ((PW - hero.width) // 2 - 250, PH // 2 - hero.height // 2), hero.getchannel("A"))
        art = line_art(objs[thing], 520, thick=8)
        for j, (x, y) in enumerate(((PW - M - 600, PH // 2 - 700), (PW - M - 600, PH // 2), (PW - M - 600, PH // 2 + 700))):
            if j < 2 + k % 2:
                img.paste(art.convert("RGB"), (int(x), int(y - 260)), art.getchannel("A"))
        pages.append(img)
    if len(pages) % 2:
        pages.append(_new("My own drawing")[0])
    _save_pdf(pages, folder / "Color_with_Bloop.pdf")
    cover_art = Image.fromarray(np.ascontiguousarray(_mascot("Bloop", 900)[..., [2, 1, 0, 3]]), "RGBA")
    cover = _cover("Color with Bloop!", "24 big, simple pages for ages 2-5", (63, 184, 224), cover_art)
    _thumb(cover, folder)
    _listing(folder, {
        "title": "Color with Bloop! A Coloring Book for Toddlers and Preschoolers (Ages 2-5)",
        "subtitle": "24 big, simple pages with Bloop & Friends",
        "description": ("24 big, bold pages of Bloop, Pip, Mo and Dee with friendly things to color: apples, stars, "
                        "ducks, balloons and more. Thick lines for little hands, one picture per page, a blank page "
                        "for their own drawing. From the Bloop & Friends counting show."),
        "files": ["Color_with_Bloop.pdf"], "pages": len(pages), "price_usd": "$3 (printable PDF)", "price_inr": "₹79",
        "kdp_price": "$5.99 paperback", "grades": "PreK-K",
        "tags": ["coloring book for toddlers", "coloring book ages 2-4", "preschool coloring book", "big simple coloring",
                 "kids activity book", "toddler gifts", "bloop and friends"],
        "kdp_categories": "Children's Books > Activities, Crafts & Games > Coloring Books",
        "stores": ["Amazon KDP", "Payhip", "Gumroad", "Teachers Pay Teachers"], "channel": "bloop_and_friends",
        "note": "Kids channel: no shop links in Made-for-Kids video descriptions (YouTube's promotion rules). Sell "
                "through the stores' own search and the KDP listing."})
    log(f"  coloring book ({len(pages)} pages) -> {folder}")
    return folder


# ======================================================================================================
def catalogue() -> list[dict]:
    out = []
    for p in sorted(OUT.glob("*/product.json")):
        info = json.loads(p.read_text(encoding="utf-8"))
        info["folder"] = str(p.parent.relative_to(ROOT))
        out.append(info)
    return out


def make_all(log=print) -> list[Path]:
    made = [budget_planner(log), puzzle_book(log=log), colouring_book(log)]
    for key in PACKS:
        made.append(music_pack(key, log=log))
    write_catalogue()
    return made


def write_catalogue() -> Path:
    rows = ["# Our digital products (upload kits)", "",
            "Each folder has the files, cover.jpg / thumb.jpg and listing.md (paste per store).",
            "Stores in the order they pay: Payhip + Razorpay (~2 days), Gumroad (weekly, INR), KDP (monthly).", "",
            "| Product | Price | Stores | Folder |", "|---|---|---|---|"]
    for info in catalogue():
        rows.append(f"| {info['title']} | {info['price_usd']} / {info['price_inr']} | {', '.join(info['stores'])} | "
                    f"{info['folder']} |")
    p = OUT / "CATALOGUE.md"
    p.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return p
