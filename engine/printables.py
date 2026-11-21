"""Printable kits drawn by code from config/printables.yaml (Phase 6 acceptance: 2 new products a week through the
product gate). Same look as the 2027 planner (engine/planner_product.py: US Letter at 300 dpi, white pages, soft
colour bars, printer friendly); an A4 twin is made by engine/page_sizes.py. Page kinds:
  cover       big title, subtitle, three promise lines, a colour-in progress motif
  steps       numbered how-to blocks (our own words) and a small-print note
  table       fill-in fields, a header row and ruled rows (row_labels: months | numbers)
  tracker     fields, 100 colour-in squares (1 % each) and a short log table
  grid        numbered boxes (52-week / 100-envelope challenges) and a total line
  bars        rows of fill-in fields with a segmented progress bar (sinking funds)
  milestones  check boxes with date and reward lines
  nospend     31 day circles to cross out, a tally and reflection lines
  notes       dotted lines
A kit becomes a product folder (PDF + A4 twin + product.json + cover.jpg); its `cover:` spec is registered in
engine/store_covers.SPECS, so covers, pins, the dashboard and the store publisher see it like any other product.
Listing a NEW product needs the owner's OK (first-time public); the product gate runs before every listing.
Usage: python -m engine.printables [ids]     build (no listing)"""
from __future__ import annotations

import calendar
import json
import math
from pathlib import Path

import yaml

from .config import ROOT

FILE = ROOT / "config" / "printables.yaml"
PROD = ROOT / "data" / "products"
BODY = "Hind-Bold.ttf"                      # readable body text (Latin + ₹); headings stay Poppins / Anton
GREY = (150, 150, 160)
OWN = ("title", "files", "pages", "description", "price_usd", "price_inr", "stores", "channel", "tags",
       "promo_angles", "idea", "made_by")


def specs() -> dict:
    try:
        return yaml.safe_load(FILE.read_text(encoding="utf-8")) or {}
    except (OSError, ValueError) as e:
        print(f"printables: {FILE.name} unreadable ({type(e).__name__})")
        return {}


def cover_specs() -> dict:
    """Store-cover specs for engine/store_covers.SPECS (only YAML is read here: store_covers imports this)."""
    out = {}
    for pid, s in specs().items():
        c = dict(s.get("cover") or {})
        if c and s.get("file"):
            c.setdefault("pdf", s["file"])
            c["bg"] = tuple(c.get("bg") or ("#0B3D2E", "#14A38F"))
            out[pid] = c
    return out


def copy_for(pid: str) -> dict:
    """Store copy (hook, inside, who, how, note, kdp, social) for engine/store_copy.copy_for; {} if none."""
    c = (specs().get(pid) or {}).get("copy") or {}
    return dict(c) if c.get("hook") and c.get("inside") else {}


# ------------------------------------------------------------------ drawing helpers
def _pp():
    from . import planner_product as pp
    return pp


def _font(size: int, name: str = "Poppins-ExtraBold.ttf"):
    return _pp()._f(int(size), name)


def _fit(d, text: str, name: str, start: int, max_w: float, min_size: int = 22):
    size = int(start)
    while size > min_size and d.textlength(text, font=_font(size, name)) > max_w:
        size -= 2
    return _font(size, name), size


def _wrap(d, text: str, font, width: float) -> list[str]:
    lines, cur = [], ""
    for w in text.split():
        t = f"{cur} {w}".strip()
        if cur and d.textlength(t, font=font) > width:
            lines.append(cur)
            cur = w
        else:
            cur = t
    return lines + ([cur] if cur else [])


def _center(d, cx: float, cy: float, text: str, font, size: int, fill) -> None:
    d.text((cx - d.textlength(text, font=font) / 2, cy - size * 0.62), text, font=font, fill=fill)


def _fields(d, fields: list[str] | None, y: float) -> float:
    """Fill-in fields side by side (wrapping to a new line when full); returns the y below them."""
    pp = _pp()
    if not fields:
        return y
    f = _font(40)
    x = pp.M
    for fld in fields:
        w = d.textlength(fld, font=f)
        if x > pp.M and x + w > pp.PW - pp.M:
            x, y = pp.M, y + 80
        d.text((x, y), fld, font=f, fill=pp.INK)
        x += w + 70
    return y + 120


def _row_labels(kind, rows: int) -> list[str]:
    if kind == "months":
        return [calendar.month_name[m] for m in range(1, min(rows, 12) + 1)]
    if kind == "numbers":
        return [str(k + 1) for k in range(rows)]
    return list(kind or [])[:rows]


def _table(d, x0: float, y0: float, x1: float, y1: float, columns, rows: int, row_labels=None) -> None:
    pp = _pp()
    total = sum(float(w) for _, w in columns)
    widths = [float(w) / total * (x1 - x0) for _, w in columns]
    rh = (y1 - y0) / (rows + 1)
    d.rectangle([x0, y0, x1, y0 + rh], fill=pp.SOFT)
    x = x0
    for (label, _), w in zip(columns, widths):
        f, size = _fit(d, str(label), "Poppins-ExtraBold.ttf", min(44, int(rh * 0.42)), w - 36)
        d.text((x + 18, y0 + rh / 2 - size * 0.62), str(label), font=f, fill=pp.ACC)
        x += w
    for r in range(rows + 2):
        d.line([(x0, y0 + r * rh), (x1, y0 + r * rh)], fill=pp.LINE, width=3)
    x = x0
    for w in [0.0] + widths:
        x += w
        d.line([(x, y0), (x, y0 + (rows + 1) * rh)], fill=pp.LINE, width=2)
    labels = _row_labels(row_labels, rows)
    if labels:
        size = min(38, int(rh * 0.4))
        f = _font(size)
        for r, lab in enumerate(labels):
            d.text((x0 + 18, y0 + (r + 1) * rh + rh / 2 - size * 0.62), lab, font=f, fill=pp.INK)


# ------------------------------------------------------------------ page kinds
def _cover(d, page: dict, y: float) -> None:
    pp = _pp()
    for txt, sz, frac in zip((page.get("lines") or [])[:3], (110, 70, 70), (0.40, 0.52, 0.58)):
        f, size = _fit(d, txt, "Poppins-ExtraBold.ttf", sz, pp.PW - 2 * pp.M)
        d.text(((pp.PW - d.textlength(txt, font=f)) / 2, pp.PH * frac), txt, font=f, fill=pp.INK)
    n, gap = 10, 26                                     # colour-in progress motif: 6 of 10 squares done
    side = (pp.PW - 2 * pp.M - gap * (n - 1)) / n
    top = pp.PH * 0.70
    for k in range(n):
        x = pp.M + k * (side + gap)
        d.rounded_rectangle([x, top, x + side, top + side], radius=22, outline=pp.ACC, width=6,
                            fill=pp.ACC if k < 6 else None)


def _steps(d, page: dict, y: float) -> None:
    pp = _pp()
    x0, x1 = pp.M, pp.PW - pp.M
    blocks = page.get("blocks") or []
    size = 62
    for size in (62, 58, 54, 50, 46, 42, 38, 34):      # the largest size whose blocks fit above the note
        bf = _font(size, BODY)
        h = sum((size + 8) * 1.5 + len(_wrap(d, b["text"], bf, x1 - x0 - 40)) * size * 1.45 + 60 for b in blocks)
        if y + h <= pp.PH - 430:
            break
    hf, bf = _font(size + 8), _font(size, BODY)
    for b in blocks:
        d.text((x0, y), b["head"], font=hf, fill=pp.ACC)
        y += (size + 8) * 1.5
        for line in _wrap(d, b["text"], bf, x1 - x0 - 40):
            d.text((x0 + 40, y), line, font=bf, fill=pp.INK)
            y += size * 1.45
        y += 60
    if page.get("note"):
        nf = _font(34, BODY)
        ny = pp.PH - 380
        d.line([(x0, ny - 30), (x1, ny - 30)], fill=pp.LINE, width=2)
        for line in _wrap(d, page["note"], nf, x1 - x0):
            d.text((x0, ny), line, font=nf, fill=GREY)
            ny += 50


def _table_page(d, page: dict, y: float) -> None:
    pp = _pp()
    y = _fields(d, page.get("fields"), y)
    _table(d, pp.M, y, pp.PW - pp.M, pp.PH - 260, page["columns"], int(page["rows"]), page.get("row_labels"))


def _tracker(d, page: dict, y: float) -> None:
    pp = _pp()
    y = _fields(d, page.get("fields"), y)
    x0, x1 = pp.M, pp.PW - pp.M
    gh = 1250
    cw, ch = (x1 - x0) / 10, gh / 10
    f = _font(26)
    for k in range(100):
        cx, cy = x0 + (k % 10) * cw, y + (k // 10) * ch
        d.rounded_rectangle([cx + 8, cy + 8, cx + cw - 8, cy + ch - 8], radius=14, outline=pp.LINE, width=3)
        d.text((cx + 22, cy + 18), f"{k + 1}%", font=f, fill=(165, 170, 178))
    y += gh + 70
    _table(d, x0, y, x1, pp.PH - 260, page.get("log") or [["Date", 1], ["Amount", 1], ["Balance", 1]], 8)


def _grid(d, page: dict, y: float) -> None:
    pp = _pp()
    y = _fields(d, page.get("fields"), y)
    n, cols = int(page["count"]), int(page["cols"])
    rows = math.ceil(n / cols)
    x0, x1 = pp.M, pp.PW - pp.M
    bottom = pp.PH - 340 if page.get("total") else pp.PH - 260
    cw, ch = (x1 - x0) / cols, (bottom - y) / rows
    big = int(min(cw, ch) * 0.42)
    small = max(22, int(min(ch * 0.16, 30)))
    for k in range(n):
        cx, cy = x0 + (k % cols) * cw, y + (k // cols) * ch
        d.rounded_rectangle([cx + 10, cy + 10, cx + cw - 10, cy + ch - 10], radius=18, outline=pp.ACC, width=4)
        if page.get("small"):
            d.text((cx + 30, cy + 22), page["small"].format(n=k + 1), font=_font(small), fill=pp.ACC)
        text = str(page.get("big", "{n}")).format(n=k + 1)
        f, size = _fit(d, text, "Poppins-ExtraBold.ttf", big, cw * 0.6)
        _center(d, cx + cw * (0.62 if page.get("small") else 0.5), cy + ch / 2 + 6, text, f, size, pp.INK)
    if page.get("total"):
        f = _font(54)
        d.text(((pp.PW - d.textlength(page["total"], font=f)) / 2, pp.PH - 300), page["total"], font=f,
               fill=pp.INK)


def _bars(d, page: dict, y: float) -> None:
    pp = _pp()
    rows, seg = int(page["rows"]), int(page.get("segments", 20))
    x0, x1 = pp.M, pp.PW - pp.M
    bh = (pp.PH - 260 - y) / rows
    f, size = _fit(d, page["label"], "Poppins-ExtraBold.ttf", 38, x1 - x0)
    sw = (x1 - x0) / seg
    for r in range(rows):
        top = y + r * bh
        d.text((x0, top + 10), page["label"], font=f, fill=pp.INK)
        by0 = top + size + 50
        by1 = min(by0 + 110, top + bh - 30)
        for s in range(seg):
            d.rounded_rectangle([x0 + s * sw + 5, by0, x0 + (s + 1) * sw - 5, by1], radius=10, outline=pp.ACC,
                                width=3)


def _milestones(d, page: dict, y: float) -> None:
    pp = _pp()
    items = page.get("items") or []
    x0 = pp.M
    rh = (pp.PH - 260 - y) / max(1, len(items))
    for k, item in enumerate(items):
        top = y + k * rh + 20
        d.rounded_rectangle([x0, top, x0 + 110, top + 110], radius=16, outline=pp.ACC, width=6)
        f, _ = _fit(d, item, "Poppins-ExtraBold.ttf", 60, pp.PW - pp.M - x0 - 160)
        d.text((x0 + 160, top + 4), item, font=f, fill=pp.INK)
        d.text((x0 + 160, top + 130), "Date: ______________      My reward: ________________________________",
               font=_font(38), fill=pp.INK)


def _nospend(d, page: dict, y: float) -> None:
    pp = _pp()
    y = _fields(d, page.get("fields"), y)
    x0, x1 = pp.M, pp.PW - pp.M
    cols = 7
    cw = (x1 - x0) / cols
    r = min(cw, 260) * 0.38
    for k in range(31):
        cx = x0 + (k % cols) * cw + cw / 2
        cy = y + (k // cols) * (2 * r + 50) + r
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=pp.ACC, width=5)
        size = int(r * 0.8)
        _center(d, cx, cy + 6, str(k + 1), _font(size), size, pp.INK)
    y += 5 * (2 * r + 50) + 40
    f = _font(44)
    for line in ("No-spend days: ______ / 31", "Money I did not spend: ______________", "What I learned:"):
        d.text((x0, y), line, font=f, fill=pp.INK)
        y += 100
    _pp()._lines(d, x0 + 30, y + 20, x1, pp.PH - 260, 85, dotted=True)


def _notes(d, page: dict, y: float) -> None:
    pp = _pp()
    pp._lines(d, pp.M + 30, pp.M + 300, pp.PW - pp.M, pp.PH - 220, 75, dotted=True)


KINDS = {"cover": _cover, "steps": _steps, "table": _table_page, "tracker": _tracker, "grid": _grid,
         "bars": _bars, "milestones": _milestones, "nospend": _nospend, "notes": _notes}


def render(page: dict, footer: str | None = None) -> list:
    """The page (or `repeat` copies of it) as 300-dpi US Letter images."""
    pp = _pp()
    kind = page.get("kind")
    if kind not in KINDS:
        raise ValueError(f"unknown page kind {kind!r}")
    out = []
    for _ in range(max(1, int(page.get("repeat", 1)))):
        img, d = pp._page(page.get("title", ""), page.get("sub", ""), footer)
        KINDS[kind](d, page, pp.M + 330)
        out.append(img)
    return out


def build(pid: str, log=print) -> Path:
    """PDF + A4 twin + product.json (fields added later, such as page_sizes, stay) + cover.jpg."""
    from .page_sizes import ensure_a4
    s = specs()[pid]
    out = PROD / pid
    out.mkdir(parents=True, exist_ok=True)
    pages = [img for page in s["pages"] for img in render(page, s.get("footer"))]
    pdf = out / s["file"]
    pages[0].save(pdf, save_all=True, append_images=pages[1:], resolution=300)
    pages[0].save(out / "cover.jpg", quality=92)
    pj = out / "product.json"
    old = json.loads(pj.read_text(encoding="utf-8")) if pj.exists() else {}
    info = {k: v for k, v in old.items() if k not in OWN}
    info.update({"title": s["title"], "files": [s["file"]], "pages": len(pages),
                 "description": " ".join(str(s["description"]).split()), "price_usd": s["price_usd"],
                 "price_inr": s.get("price_inr", ""), "stores": ["Payhip", "Gumroad"], "channel": s["channel"],
                 "tags": list(s.get("tags") or []), "promo_angles": list(s.get("promo_angles") or []),
                 "idea": s.get("idea", ""), "made_by": "engine/printables.py"})
    info.setdefault("needs_owner_ok", True)              # first listing waits for the owner (product gate)
    pj.write_text(json.dumps(info, indent=1, ensure_ascii=False), encoding="utf-8")
    ensure_a4(out, log)                                  # A4 twin listed right after the Letter file
    log(f"  {pid}: {len(pages)} pages -> {pdf.name}")
    return out


def approve(pid: str, by: str = "owner") -> dict:
    """Record the owner's OK for a kit's first listing (the product gate then lets it through)."""
    import time
    pj = PROD / pid / "product.json"
    info = json.loads(pj.read_text(encoding="utf-8"))
    info["owner_ok"] = {"by": by, "at": time.strftime("%Y-%m-%d %H:%M")}
    pj.write_text(json.dumps(info, indent=1, ensure_ascii=False), encoding="utf-8")
    return info


def build_missing(log=print) -> list[str]:
    made = []
    for pid, s in specs().items():
        if s.get("file") and not (PROD / pid / s["file"]).exists():
            build(pid, log)
            made.append(pid)
    return made


if __name__ == "__main__":
    import sys
    for _pid in sys.argv[1:] or list(specs()):
        build(_pid)
