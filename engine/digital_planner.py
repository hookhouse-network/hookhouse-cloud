"""Hyperlinked digital planner for GoodNotes / Notability / any PDF app (plan P6 'Products 2.0': GoodNotes variant).

The printable 2027 planner's pages get a tab strip on the right margin (HOME + the 12 months) and real PDF links:
every tab jumps to its page from every page, each month on the year-at-a-glance page opens that month, HOME returns
to the year view. Same pages, same dates; shipped as a bonus file in the planner download (no new listing needed).
The habit tracker gets the same strip (HOME = goals page, a month tab opens that month's tracker; its review page
lights the month too). Links are PDF Link annotations (pypdf), which GoodNotes, Notability, Xodo and browsers follow."""
from __future__ import annotations

import calendar
from pathlib import Path

from PIL import ImageDraw

from . import planner_product as pp

TAB_W, TAB_GAP = 118, 8
TAB_X0 = pp.PW - TAB_W - 14                       # inside the 210 px right margin
TAB_Y0 = 230
TAB_LABELS = ["HOME"] + [calendar.month_abbr[m].upper() for m in range(1, 13)]
HOME_PAGE, MONTH0 = 1, 3                          # page 1 = year at a glance; months are pages 3..14 (0-based)
PT = 72 / 300                                      # pixels (300 dpi) -> PDF points


def tab_boxes() -> list[tuple[int, int, int, int]]:
    """(x0, y0, x1, y1) in pixels of HOME + 12 month tabs, top to bottom."""
    h = (pp.PH - TAB_Y0 - 230 - TAB_GAP * 12) / 13
    return [(TAB_X0, int(TAB_Y0 + i * (h + TAB_GAP)), pp.PW - 14, int(TAB_Y0 + i * (h + TAB_GAP) + h))
            for i in range(13)]


def tab_target(i: int, home: int = HOME_PAGE, month0: int = MONTH0, step: int = 1) -> int:
    """The page a tab opens: HOME, or the first page of month i (a month spans `step` pages)."""
    return home if i == 0 else month0 + (i - 1) * step


def tab_for_page(k: int, home: int = HOME_PAGE, month0: int = MONTH0, step: int = 1) -> int | None:
    """Which tab is lit on page k (a month's later pages light that month too)."""
    if k == home:
        return 0
    if month0 <= k < month0 + 12 * step:
        return 1 + (k - month0) // step
    return None


def draw_tabs(img, current: int | None, home: int = HOME_PAGE, month0: int = MONTH0, step: int = 1) -> None:
    d = ImageDraw.Draw(img)
    lit = tab_for_page(current, home, month0, step) if current is not None else None
    for i, (x0, y0, x1, y1) in enumerate(tab_boxes()):
        on = lit == i
        d.rounded_rectangle([x0, y0, x1, y1], radius=18, fill=pp.ACC if on else pp.SOFT)
        label = TAB_LABELS[i]
        f = pp._f(30)
        tw = d.textlength(label, font=f)
        d.text(((x0 + x1) / 2 - tw / 2, (y0 + y1) / 2 - 18), label, font=f, fill=(255, 255, 255) if on else pp.INK)


def month_boxes() -> list[tuple[float, float, float, float]]:
    """Year-at-a-glance month blocks (pixels), same geometry as planner_product.year_at_a_glance."""
    cw, ch = (pp.PW - 2 * pp.M - 120) / 3, (pp.PH - pp.M - 420 - 140) / 4
    out = []
    for mo in range(1, 13):
        cx = pp.M + ((mo - 1) % 3) * (cw + 60)
        cy = pp.M + 300 + ((mo - 1) // 3) * (ch + 40)
        out.append((cx, cy, cx + cw, cy + ch))
    return out


def _pdf_rect(box, page_h_pt: float) -> tuple[float, float, float, float]:
    x0, y0, x1, y1 = box
    return (x0 * PT, page_h_pt - y1 * PT, x1 * PT, page_h_pt - y0 * PT)   # PDF origin is bottom-left


def _link(writer, rect, target: int):
    """A Link annotation whose /Dest is the target PAGE OBJECT (a page number there is only valid for links into
    other files; strict readers ignore it), no border, fit the page."""
    from pypdf.generic import ArrayObject, DictionaryObject, FloatObject, NameObject, NumberObject
    return DictionaryObject({
        NameObject("/Type"): NameObject("/Annot"), NameObject("/Subtype"): NameObject("/Link"),
        NameObject("/Rect"): ArrayObject([FloatObject(round(v, 2)) for v in rect]),
        NameObject("/Border"): ArrayObject([NumberObject(0), NumberObject(0), NumberObject(0)]),
        NameObject("/Dest"): ArrayObject([writer.pages[target].indirect_reference, NameObject("/Fit")])})


def _attach(writer, page_no: int, annotation) -> None:
    """Append an annotation to a page's /Annots (pypdf's add_annotation rewrites link targets into page numbers)."""
    from pypdf.generic import ArrayObject, NameObject
    page = writer.pages[page_no]
    ref = writer._add_object(annotation)
    annots = page.get("/Annots")
    if annots is None:
        page[NameObject("/Annots")] = ArrayObject([ref])
    else:
        annots.get_object().append(ref)


def build(pages: list, out: Path, home: int, month0: int, step: int = 1, year_boxes=None, log=print) -> Path:
    """Tabs + links on every page but the cover, month links on the HOME page when it shows the year."""
    from pypdf import PdfReader, PdfWriter
    out.parent.mkdir(parents=True, exist_ok=True)
    for k, img in enumerate(pages):
        if k:                                         # the cover stays clean
            draw_tabs(img, k, home, month0, step)
    raw = out.parent / "_digital_raw.pdf"
    pages[0].save(raw, save_all=True, append_images=pages[1:], resolution=300)
    reader = PdfReader(str(raw))
    writer = PdfWriter(clone_from=reader)
    page_h = float(reader.pages[0].mediabox.height)
    n = 0
    for k in range(1, len(pages)):
        for i, box in enumerate(tab_boxes()):
            _attach(writer, k, _link(writer, _pdf_rect(box, page_h), tab_target(i, home, month0, step)))
            n += 1
    for mo, box in enumerate(year_boxes or []):
        _attach(writer, home, _link(writer, _pdf_rect(box, page_h), month0 + mo * step))
        n += 1
    with open(out, "wb") as f:
        writer.write(f)
    raw.unlink(missing_ok=True)
    log(f"  digital: {len(pages)} pages, {n} links -> {out.name}")
    return out


def make(out_dir: Path | None = None, log=print) -> Path:
    """The 2027 planner: HOME = year at a glance (its month blocks link too), months are pages 3..14."""
    out_dir = out_dir or pp.OUT
    pages = [pp.cover(), pp.year_at_a_glance(), pp.goals()] + [pp.month(m) for m in range(1, 13)] + \
            [pp.weekly(), pp.daily(), pp.habits(), pp.budget(), pp.reading(), pp.notes()]
    return build(pages, out_dir / f"{pp.YEAR}_Planner_Digital_GoodNotes_Hyperlinked.pdf", HOME_PAGE, MONTH0, 1,
                 month_boxes(), log)


HABIT_HOME, HABIT_MONTH0, HABIT_STEP = 1, 2, 2    # goals page; each month = tracker + review


def make_habit(out_dir: Path | None = None, log=print) -> Path:
    """The 2027 habit tracker: HOME = goals, a month tab opens that month's tracker (its review page lights it)."""
    out_dir = out_dir or pp.HABIT_OUT
    return build(pp.habit_pages(), out_dir / f"{pp.YEAR}_Habit_Tracker_Digital_GoodNotes_Hyperlinked.pdf",
                 HABIT_HOME, HABIT_MONTH0, HABIT_STEP, None, log)


BONUS = (" Bonus: a hyperlinked digital version for GoodNotes, Notability or any PDF app (tap a month tab to jump "
         "there).")


def add_to_product(folder: Path | None = None, log=print, kind: str = "planner") -> Path:
    """Build the digital file into an EXISTING planner/habit product and list it, keeping every other field (A4
    twin, page sizes, store data) exactly as it is."""
    import json
    folder = folder or (pp.HABIT_OUT if kind == "habit" else pp.OUT)
    pj = folder / "product.json"
    info = json.loads(pj.read_text(encoding="utf-8"))
    out = (make_habit if kind == "habit" else make)(folder, log)
    if out.name not in info.get("files", []):
        info["files"] = list(info.get("files", [])) + [out.name]
    if "hyperlinked digital version" not in str(info.get("description", "")):
        info["description"] = str(info.get("description", "")).rstrip() + BONUS
    pj.write_text(json.dumps(info, indent=1, ensure_ascii=False), encoding="utf-8")
    return out


if __name__ == "__main__":                            # python -m engine.digital_planner [habit]
    import sys
    add_to_product(kind="habit" if "habit" in sys.argv[1:] else "planner")
