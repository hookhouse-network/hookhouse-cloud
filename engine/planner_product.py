"""2027 Printable Planner Bundle (owner, 14 Nov: "high selling demand, trending, latest, useful"): planners are
the top-selling printable category and peak from mid-November to January, the New Year rush.

21 pages, US Letter 8.5 x 11 in at 300 dpi (prints on A4 with "fit to page"), weeks start on Sunday (US buyers):
cover, 2027 year at a glance, goals, 12 monthly calendars with the real 2027 dates and US holidays, weekly
planner, daily planner, monthly habit tracker, monthly budget, reading list, dotted notes. Printer-friendly: white
pages, soft color bars only. Output: data/products/planner_2027/ (PDF + product.json + listing).
Usage: python -m engine.planner_product"""
from __future__ import annotations

import calendar
import json
from pathlib import Path

from PIL import Image, ImageDraw

from .config import ROOT

OUT = ROOT / "data" / "products" / "planner_2027"
FONTS = ROOT / "assets" / "fonts"
PW, PH, M = 2550, 3300, 210
INK, SOFT, LINE, ACC = (35, 38, 48), (232, 244, 241), (175, 182, 190), (18, 140, 126)
YEAR = 2027
# US federal holidays 2027 (fixed and rule-based dates checked against the 2027 calendar)
HOLIDAYS = {(1, 1): "New Year's Day", (1, 18): "MLK Day", (2, 15): "Presidents' Day", (5, 31): "Memorial Day",
            (6, 19): "Juneteenth", (7, 4): "Independence Day", (9, 6): "Labor Day", (10, 11): "Columbus Day",
            (11, 11): "Veterans Day", (11, 25): "Thanksgiving", (12, 25): "Christmas Day"}
DAYS = ["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"]


def _f(size: int, name: str = "Poppins-ExtraBold.ttf"):
    from PIL import ImageFont
    return ImageFont.truetype(str(FONTS / name), size)


def _page(title: str, sub: str = "") -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGB", (PW, PH), "white")
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, PW, 26], fill=ACC)
    d.text((M, M - 70), title, font=_f(130, "Anton-Regular.ttf"), fill=INK)
    if sub:
        d.text((M + 6, M + 105), sub, font=_f(48), fill=ACC)
    d.text((PW - M - 330, PH - 120), f"{YEAR} Planner · HookHouse Media", font=_f(30), fill=(150, 150, 160))
    return img, d


def _lines(d, x0, y0, x1, y1, step, dotted=False):
    y = y0
    while y <= y1:
        if dotted:
            for x in range(int(x0), int(x1), 60):
                d.ellipse([x - 4, y - 4, x + 4, y + 4], fill=LINE)
        else:
            d.line([(x0, y), (x1, y)], fill=LINE, width=3)
        y += step


def cover() -> Image.Image:
    img = Image.new("RGB", (PW, PH), (14, 92, 84))
    d = ImageDraw.Draw(img)
    for k in range(0, PH, 8):
        a = int(50 * k / PH)
        d.line([(0, k), (PW, k)], fill=(14 + a // 3, 92 + a, 84 + a // 2), width=8)
    d.text((M, 700), str(YEAR), font=_f(620, "Anton-Regular.ttf"), fill="white")
    d.text((M + 10, 1450), "PLANNER", font=_f(260, "Anton-Regular.ttf"), fill=(255, 210, 63))
    d.text((M + 14, 1800), "Plan the year. Own every month.", font=_f(80), fill="white")
    d.text((M + 14, PH - 400), "Name: ______________________________", font=_f(70), fill="white")
    return img


def year_at_a_glance() -> Image.Image:
    img, d = _page(f"{YEAR} AT A GLANCE")
    cal = calendar.Calendar(firstweekday=6)
    cw, ch = (PW - 2 * M - 120) / 3, (PH - M - 420 - 140) / 4
    for mo in range(1, 13):
        cx = M + ((mo - 1) % 3) * (cw + 60)
        cy = M + 300 + ((mo - 1) // 3) * (ch + 40)
        d.text((cx, cy), calendar.month_name[mo].upper(), font=_f(56), fill=ACC)
        cell = cw / 7
        for i, dn in enumerate("SMTWTFS"):
            d.text((cx + i * cell + cell / 2 - 14, cy + 90), dn, font=_f(36), fill=(120, 120, 130))
        for r, week in enumerate(cal.monthdayscalendar(YEAR, mo)):
            for i, day in enumerate(week):
                if day:
                    hol = (mo, day) in HOLIDAYS
                    t = str(day)
                    tw = d.textlength(t, font=_f(38))
                    if hol:
                        d.ellipse([cx + i * cell + cell / 2 - 32, cy + 150 + r * 70 - 6, cx + i * cell + cell / 2 + 32,
                                   cy + 150 + r * 70 + 58], fill=SOFT)
                    d.text((cx + i * cell + cell / 2 - tw / 2, cy + 150 + r * 70), t, font=_f(38), fill=INK)
    return img


def goals() -> Image.Image:
    img, d = _page(f"MY {YEAR} GOALS", "Write it down. Check it off.")
    areas = ["Health & Fitness", "Money & Savings", "Career & Study", "Relationships", "Learn Something New",
             "Fun & Travel"]
    bw, bh = (PW - 2 * M - 80) / 2, (PH - M - 560) / 3
    for k, a in enumerate(areas):
        x, y = M + (k % 2) * (bw + 80), M + 330 + (k // 2) * (bh + 40)
        d.rounded_rectangle([x, y, x + bw, y + bh], 40, outline=LINE, width=4)
        d.rounded_rectangle([x, y, x + bw, y + 110], 40, fill=SOFT)
        d.text((x + 40, y + 22), a, font=_f(58), fill=ACC)
        for j in range(4):
            yy = y + 200 + j * (bh - 240) / 4
            d.rectangle([x + 40, yy, x + 90, yy + 50], outline=INK, width=4)
            d.line([(x + 120, yy + 50), (x + bw - 40, yy + 50)], fill=LINE, width=3)
    return img


def month(mo: int) -> Image.Image:
    img, d = _page(f"{calendar.month_name[mo].upper()} {YEAR}", "Monthly focus: ______________________")
    weeks = calendar.Calendar(firstweekday=6).monthdayscalendar(YEAR, mo)
    x0, y0, x1, y1 = M, M + 330, PW - M, PH - 560
    cw, ch = (x1 - x0) / 7, (y1 - y0 - 90) / len(weeks)
    d.rectangle([x0, y0, x1, y0 + 90], fill=ACC)
    for i, dn in enumerate(DAYS):
        tw = d.textlength(dn, font=_f(46))
        d.text((x0 + i * cw + cw / 2 - tw / 2, y0 + 18), dn, font=_f(46), fill="white")
    for r, week in enumerate(weeks):
        for i, day in enumerate(week):
            cx, cy = x0 + i * cw, y0 + 90 + r * ch
            d.rectangle([cx, cy, cx + cw, cy + ch], outline=LINE, width=3, fill=None if day else (247, 248, 250))
            if day:
                d.text((cx + 20, cy + 12), str(day), font=_f(52), fill=INK)
                if (mo, day) in HOLIDAYS:
                    d.text((cx + 20, cy + ch - 60), HOLIDAYS[(mo, day)], font=_f(26), fill=ACC)
    d.text((M, PH - 520), "NOTES", font=_f(50), fill=ACC)
    _lines(d, M, PH - 420, PW - M, PH - 200, 90)
    return img


def weekly() -> Image.Image:
    img, d = _page("WEEKLY PLANNER", "Week of: ____________________")
    x0, y0 = M, M + 330
    colw = (PW - 2 * M - 60) / 2
    names = ["SUNDAY", "MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "TOP PRIORITIES"]
    bh = (PH - y0 - 220 - 3 * 40) / 4
    for k, nm in enumerate(names):
        x, y = x0 + (k % 2) * (colw + 60), y0 + (k // 2) * (bh + 40)
        d.rounded_rectangle([x, y, x + colw, y + bh], 30, outline=LINE, width=4,
                            fill=SOFT if nm == "TOP PRIORITIES" else None)
        d.text((x + 30, y + 20), nm, font=_f(50), fill=ACC)
        _lines(d, x + 30, y + 140, x + colw - 30, y + bh - 30, 85)
    return img


def daily() -> Image.Image:
    img, d = _page("DAILY PLANNER", "Date: ____________   S  M  T  W  T  F  S")
    x0, y0, mid = M, M + 330, PW / 2 + 40
    d.text((x0, y0), "SCHEDULE", font=_f(50), fill=ACC)
    for k, h in enumerate(range(6, 22)):
        y = y0 + 110 + k * 145
        lab = f"{(h - 1) % 12 + 1} {'AM' if h < 12 else 'PM'}"
        d.text((x0, y), lab, font=_f(40), fill=(120, 120, 130))
        d.line([(x0 + 170, y + 50), (mid - 80, y + 50)], fill=LINE, width=3)
    d.text((mid, y0), "TOP 3 TODAY", font=_f(50), fill=ACC)
    for j in range(3):
        yy = y0 + 130 + j * 120
        d.ellipse([mid, yy, mid + 60, yy + 60], outline=INK, width=4)
        d.line([(mid + 90, yy + 60), (PW - M, yy + 60)], fill=LINE, width=3)
    d.text((mid, y0 + 560), "TO DO", font=_f(50), fill=ACC)
    for j in range(8):
        yy = y0 + 680 + j * 110
        d.rectangle([mid, yy, mid + 50, yy + 50], outline=INK, width=4)
        d.line([(mid + 80, yy + 50), (PW - M, yy + 50)], fill=LINE, width=3)
    d.text((mid, y0 + 1620), "WATER", font=_f(50), fill=ACC)
    for j in range(8):
        d.rounded_rectangle([mid + j * 115, y0 + 1730, mid + j * 115 + 80, y0 + 1850], 18, outline=INK, width=4)
    d.text((mid, y0 + 1960), "NOTES & GRATITUDE", font=_f(50), fill=ACC)
    _lines(d, mid, y0 + 2080, PW - M, PH - 240, 90)
    return img


def habits(month_name: str = "") -> Image.Image:
    sub = (f"{month_name} {YEAR}" if month_name else "Month: ______________") + "   Tick a box every day you do it"
    img, d = _page("HABIT TRACKER", sub)
    x0, y0 = M, M + 330
    namew, days, rows = 520, 31, 14
    cw = (PW - 2 * M - namew) / days
    rh = (PH - y0 - 300) / (rows + 1)
    d.rectangle([x0, y0, PW - M, y0 + rh], fill=SOFT)
    d.text((x0 + 20, y0 + rh / 2 - 30), "HABIT", font=_f(46), fill=ACC)
    for k in range(days):
        t = str(k + 1)
        tw = d.textlength(t, font=_f(30))
        d.text((x0 + namew + k * cw + cw / 2 - tw / 2, y0 + rh / 2 - 20), t, font=_f(30), fill=INK)
    for r in range(rows + 2):
        d.line([(x0, y0 + r * rh), (PW - M, y0 + r * rh)], fill=LINE, width=3)
    for k in range(days + 1):
        x = x0 + namew + k * cw
        d.line([(x, y0), (x, y0 + (rows + 1) * rh)], fill=LINE, width=2)
    d.line([(x0, y0), (x0, y0 + (rows + 1) * rh)], fill=LINE, width=3)
    return img


def budget() -> Image.Image:
    img, d = _page("MONTHLY BUDGET", "Month: ______________")
    x0, y0, x1 = M, M + 330, PW - M
    blocks = [("INCOME", 4), ("BILLS & NEEDS", 8), ("WANTS", 6), ("SAVINGS & DEBT", 4)]
    y = y0
    for name, n in blocks:
        d.rectangle([x0, y, x1, y + 90], fill=SOFT)
        d.text((x0 + 20, y + 14), name, font=_f(46), fill=ACC)
        d.text((x1 - 620, y + 14), "PLANNED", font=_f(40), fill=INK)
        d.text((x1 - 300, y + 14), "ACTUAL", font=_f(40), fill=INK)
        for j in range(n):
            yy = y + 90 + (j + 1) * 82
            d.line([(x0, yy), (x1, yy)], fill=LINE, width=3)
        d.line([(x1 - 650, y + 90), (x1 - 650, y + 90 + n * 82)], fill=LINE, width=3)
        d.line([(x1 - 330, y + 90), (x1 - 330, y + 90 + n * 82)], fill=LINE, width=3)
        y += 90 + n * 82 + 50
    d.rounded_rectangle([x0, y + 10, x1, y + 170], 30, outline=ACC, width=5)
    d.text((x0 + 40, y + 55), "LEFT OVER (income - everything else):  ______________", font=_f(50), fill=INK)
    return img


def reading() -> Image.Image:
    img, d = _page("READING LIST", "Books I want to read this year")
    x0, y0, x1 = M, M + 330, PW - M
    cols = [("TITLE", 0.45), ("AUTHOR", 0.3), ("RATING", 0.25)]
    xs = [x0]
    for _, s in cols:
        xs.append(xs[-1] + (x1 - x0) * s)
    d.rectangle([x0, y0, x1, y0 + 90], fill=SOFT)
    for (n, _), x in zip(cols, xs):
        d.text((x + 20, y0 + 14), n, font=_f(44), fill=ACC)
    for r in range(25):
        yy = y0 + 90 + (r + 1) * 105
        d.line([(x0, yy), (x1, yy)], fill=LINE, width=3)
        for s in range(5):
            cx = xs[2] + 50 + s * 85
            d.text((cx, yy - 85), "☆", font=_f(56, "Mukta-ExtraBold.ttf"), fill=LINE)
    return img


def notes() -> Image.Image:
    img, d = _page("NOTES")
    _lines(d, M + 30, M + 300, PW - M, PH - 220, 75, dotted=True)
    return img


def make(log=print) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    pages = [cover(), year_at_a_glance(), goals()] + [month(m) for m in range(1, 13)] + \
            [weekly(), daily(), habits(), budget(), reading(), notes()]
    pdf = OUT / f"{YEAR}_Planner_Printable.pdf"
    pages[0].save(pdf, save_all=True, append_images=pages[1:], resolution=300)
    pages[0].save(OUT / "cover.jpg", quality=92)
    from .digital_planner import make as make_digital      # P6: GoodNotes / Notability version with working tabs
    digital = make_digital(OUT, log)
    info = {"title": f"{YEAR} Printable Planner Bundle", "files": [pdf.name, digital.name], "pages": len(pages),
            "description": f"A clean {YEAR} planner you print at home: year at a glance, goals, 12 monthly calendars "
                           "with US holidays, weekly and daily planners, habit tracker, monthly budget, reading list "
                           "and notes. US Letter, prints on A4 with 'fit to page'. Reprint any page as often as you like. "
                           "Bonus: a hyperlinked digital version for GoodNotes, Notability or any PDF app (tap a "
                           "month tab to jump there).",
            "price_usd": "$6", "price_inr": "₹149", "stores": ["Payhip", "Gumroad"], "channel": "money_cheat_codes",
            "tags": [f"{YEAR} planner", "printable planner", "monthly planner", "weekly planner", "habit tracker",
                     "budget planner", "goal planner", "daily planner"]}
    (OUT / "product.json").write_text(json.dumps(info, indent=1, ensure_ascii=False), encoding="utf-8")
    log(f"  {YEAR} planner ({len(pages)} pages) -> {OUT}")
    return OUT


HABIT_OUT = ROOT / "data" / "products" / "habit_tracker_2027"


def reflection(month_name: str) -> Image.Image:
    img, d = _page(f"{month_name.upper()} REVIEW", "What worked, what did not, what next")
    prompts = ["Habits I kept most days", "What got in the way", "One small win to celebrate",
               "What I will change next month"]
    bh = (PH - M - 560) / len(prompts)
    for k, q in enumerate(prompts):
        y = M + 330 + k * bh
        d.text((M + 30, y), q, font=_f(56), fill=ACC)
        _lines(d, M + 30, y + 110, PW - M, y + bh - 40, 80, dotted=True)
    return img


def habit_pages() -> list[Image.Image]:
    """Title, goals, then habit tracker + review for each month, two notes pages (the printable and the
    hyperlinked digital version use the same pages: engine/digital_planner.py)."""
    months = list(calendar.month_name)[1:]
    title, d = _page(f"{YEAR} HABIT TRACKER", "& New Year resolution planner")
    for txt, sz, y in (("Small steps. Every day.", 110, 0.40), ("12 monthly habit trackers", 70, 0.52),
                       ("Goals, monthly reviews, notes", 70, 0.58)):
        tw = d.textlength(txt, font=_f(sz))
        d.text(((PW - tw) / 2, PH * y), txt, font=_f(sz), fill=INK)
    pages = [title, goals()]
    for m in months:
        pages += [habits(m), reflection(m)]
    return pages + [notes(), notes()]


def habit_tracker(log=print) -> Path:
    """2027 Habit Tracker & Resolution Planner (research 17 Nov: habit trackers peak Dec-Feb with New Year
    resolutions; built from the planner's own page designs, no AI art)."""
    HABIT_OUT.mkdir(parents=True, exist_ok=True)
    pages = habit_pages()
    pdf = HABIT_OUT / f"{YEAR}_Habit_Tracker_Printable.pdf"
    pages[0].save(pdf, save_all=True, append_images=pages[1:], resolution=300)
    pages[0].save(HABIT_OUT / "cover.jpg", quality=92)
    info = {"title": f"{YEAR} Habit Tracker & New Year Resolution Planner (Printable PDF)", "files": [pdf.name],
            "pages": len(pages),
            "description": (f"Turn your {YEAR} resolutions into daily habits. {len(pages)} printable pages: a goals page "
                            "for six areas of life, a habit tracker for every month (14 habits x 31 days, month "
                            "already printed), a monthly review page with four questions that keep you honest, and "
                            "notes. US Letter, prints on A4 with 'fit to page'. Print any page as often as you like."),
            "price_usd": "$4", "price_inr": "\u20b999", "stores": ["Payhip", "Gumroad"], "channel": "money_cheat_codes",
            "tags": [f"{YEAR} habit tracker", "habit tracker printable", "new year resolution planner",
                     "goal planner", "monthly habit tracker", "self improvement planner", "printable planner"],
            # value-first promo Shorts (engine/product_promo.py): help first, the link sits in the description
            "promo_angles": ["Why so many New Year resolutions fade by February, and the tiny-habit fix",
                             "The 2-minute rule: start a habit so small you can't say no",
                             "Never miss twice: the one rule that rescues a broken habit streak"]}
    (HABIT_OUT / "product.json").write_text(json.dumps(info, indent=1, ensure_ascii=False), encoding="utf-8")
    log(f"  {YEAR} habit tracker ({len(pages)} pages) -> {HABIT_OUT}")
    return HABIT_OUT


if __name__ == "__main__":
    make()
