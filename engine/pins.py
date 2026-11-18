"""Pinterest pins for our products (owner, 14 Nov: "set up pinterest", "eye catching", "marketing").

Research (docs/earning_platforms_research.md): Pinterest is a search engine with buyer intent for printables and
planners; tall 2:3 pins (1000 x 1500) with a bold benefit headline and real previews perform best; a few fresh pins
a week beat bursts; boards are organised by what buyers search.

For every product: 2 different pin designs (different headline + layout) in data/products/<id>/pins/, and
pins.json with title (<= 100 chars), description (<= 500 chars, keywords early, no hashtag stuffing), board and the
store link. Posting: by the Pinterest API once approved (engine/pinterest... later) or through the browser flow.
Usage: python -m engine.pins [product ids]"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw

from . import store_copy, store_covers
from .config import ROOT

PROD = ROOT / "data" / "products"
W, H = 1000, 1500
BOARDS = {
    "planner_2027": "Printable Planners & Organization",
    "money_budget_planner": "Budget Planner & Money Tips",
    "bloop_colouring_book": "Toddler Activities & Coloring Pages",
    "christmas_colouring_book": "Toddler Activities & Coloring Pages",
    "brain_snack_puzzle_book": "Puzzles & Brain Games for Kids",
    "music_pack": "No Copyright Music for Creators",
}
HEADLINES = {   # 2 angles per product: benefit + curiosity
    "planner_2027": [("PLAN YOUR", "BEST YEAR"), ("2027", "PLANNER")],
    "money_budget_planner": [("WHERE DID MY", "MONEY GO?"), ("BUDGET", "PLANNER")],
    "bloop_colouring_book": [("QUIET TIME", "SAVER"), ("TODDLER", "COLORING")],
    "christmas_colouring_book": [("CHRISTMAS", "COLORING"), ("STOCKING", "STUFFER")],
    "brain_snack_puzzle_book": [("SCREEN-FREE", "FUN"), ("34", "PUZZLES")],
}


def _board(pid: str) -> str:
    if pid.startswith("free_"):                                   # free samples sit with the full version's pins
        pid = pid[len("free_"):]
    return BOARDS.get(pid) or (BOARDS["music_pack"] if pid.startswith("music_pack_") else "HookHouse Media")


def _headlines(pid: str) -> list[tuple[str, str]]:
    if pid in HEADLINES:
        return HEADLINES[pid]
    if pid.startswith("free_"):                                   # "free printable" is a top Pinterest search
        head = store_covers.SPECS[pid]["head"]
        return [("FREE", "PRINTABLE"), ("FREE " + head[0], head[1])]
    head = store_covers.SPECS[pid]["head"]
    return [("NO COPYRIGHT", head[0] + " " + head[1] if len(head[0] + head[1]) < 14 else head[0]), tuple(head)]


def _fit(d, text: str, font_name: str, max_w: int, start: int) -> object:
    size = start
    while size > 40:
        f = store_covers._f(font_name, size)
        if d.textlength(text, font=f) <= max_w:
            return f
        size -= 6
    return store_covers._f(font_name, 40)


def make_pin(pid: str, variant: int) -> Path:
    spec, folder = store_covers.SPECS[pid], PROD / pid
    a, b = _headlines(pid)[variant % 2]
    bg = store_covers._background(*spec["bg"]).resize((W, H))
    img = bg.convert("RGBA")
    d = ImageDraw.Draw(img)
    acc = store_covers._rgb(spec["accent"])
    top = 80 if variant == 0 else 900                           # variant 1: text below the previews
    f1 = _fit(d, a, "Anton-Regular.ttf", W - 120, 150)
    f2 = _fit(d, b, "Anton-Regular.ttf", W - 120, 190)
    for txt, f, col, y in ((a, f1, (255, 255, 255), top), (b, f2, acc, top + f1.size + 10)):
        tw = d.textlength(txt, font=f)
        d.text(((W - tw) / 2 + 6, y + 6), txt, font=f, fill=(0, 0, 0, 120))
        d.text(((W - tw) / 2, y), txt, font=f, fill=col)
    sub = spec["sub"]
    fs = _fit(d, sub, "Poppins-ExtraBold.ttf", W - 140, 48)
    sy = top + f1.size + f2.size + 55
    d.text(((W - d.textlength(sub, font=fs)) / 2, sy), sub, font=fs, fill="white")
    # previews: real pages / track cards, centered
    if spec.get("pdf"):
        pages = store_covers._pdf_pages(folder / spec["pdf"], spec["pages"], 420)
        py = 560 if variant == 0 else 120
        for im, (ang, x, y) in zip(pages, [(7, 470, py), (-6, 110, py + 60), (2, 330, py + 120)]):
            img.alpha_composite(store_covers._shadowed(im, ang, blur=18, off=16), (x, y))
    else:
        cards = store_covers._track_cards(folder, spec["music"], spec["accent"], w=760, h=170)
        py = 640 if variant == 0 else 150
        for k, c in enumerate(cards):
            img.alpha_composite(store_covers._shadowed(c, -2 + 2 * k, blur=16, off=12), (90, py + k * 220))
    d = ImageDraw.Draw(img)
    pill = "INSTANT DOWNLOAD"
    fp = store_covers._f("Poppins-ExtraBold.ttf", 40)
    pw_ = d.textlength(pill, font=fp) + 70
    py2 = H - 150
    d.rounded_rectangle([(W - pw_) / 2, py2, (W + pw_) / 2, py2 + 84], 42, fill=acc)
    d.text(((W - pw_) / 2 + 35, py2 + 16), pill, font=fp, fill=(20, 20, 30))
    out = folder / "pins" / f"pin_{variant + 1}.jpg"
    out.parent.mkdir(exist_ok=True)
    img.convert("RGB").save(out, quality=92)
    return out


def plan(pid: str) -> dict:
    from .store_publish import listed, title_for
    c = store_copy.copy_for(pid)
    link = ((listed().get(pid) or {}).get("payhip") or {}).get("public") or "https://payhip.com/HookHouseMedia"
    base = title_for(pid).split("|")[0].strip()
    desc = f"{c['hook']} {c['inside'][0]}. {c['who']} Instant download from HookHouse Media."
    return {"board": _board(pid), "link": link,
            "pins": [{"image": f"pins/pin_{k + 1}.jpg", "title": (base if k == 0 else f"{base}: {c['social']}")[:100],
                      "description": desc[:500]} for k in range(2)]}


def make(pid: str) -> Path:
    for v in range(2):
        make_pin(pid, v)
    p = PROD / pid / "pins" / "pins.json"
    p.write_text(json.dumps(plan(pid), indent=1, ensure_ascii=False), encoding="utf-8")
    return p


if __name__ == "__main__":
    for pid in sys.argv[1:] or list(store_covers.SPECS):
        print(make(pid))
