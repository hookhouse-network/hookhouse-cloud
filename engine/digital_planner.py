"""Hyperlinked digital planner for GoodNotes / Notability / any PDF app (plan P6 'Products 2.0': GoodNotes variant).

The printable 2027 planner's pages get a tab strip on the right margin (HOME + the 12 months) and real PDF links:
every tab jumps to its page from every page, each month on the year-at-a-glance page opens that month, HOME returns
to the year view. Same pages, same dates; shipped as a bonus file in the planner download (no new listing needed).
Links are PDF Link annotations (pypdf), which GoodNotes, Notability, Xodo and browsers follow."""
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


def tab_target(i: int) -> int:
    return HOME_PAGE if i == 0 else MONTH0 + i - 1


def draw_tabs(img, current: int | None) -> None:
    d = ImageDraw.Draw(img)
    for i, (x0, y0, x1, y1) in enumerate(tab_boxes()):
        on = current is not None and tab_target(i) == current
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


def make(out_dir: Path | None = None, log=print) -> Path:
    from pypdf import PdfReader, PdfWriter
    out_dir = out_dir or pp.OUT
    out_dir.mkdir(parents=True, exist_ok=True)
    pages = [pp.cover(), pp.year_at_a_glance(), pp.goals()] + [pp.month(m) for m in range(1, 13)] + \
            [pp.weekly(), pp.daily(), pp.habits(), pp.budget(), pp.reading(), pp.notes()]
    for k, img in enumerate(pages):
        if k:                                         # the cover stays clean
            draw_tabs(img, k)
    raw = out_dir / "_digital_raw.pdf"
    pages[0].save(raw, save_all=True, append_images=pages[1:], resolution=300)
    reader = PdfReader(str(raw))
    writer = PdfWriter(clone_from=reader)
    page_h = float(reader.pages[0].mediabox.height)
    for k in range(1, len(pages)):
        for i, box in enumerate(tab_boxes()):
            _attach(writer, k, _link(writer, _pdf_rect(box, page_h), tab_target(i)))
    for mo, box in enumerate(month_boxes()):
        _attach(writer, HOME_PAGE, _link(writer, _pdf_rect(box, page_h), MONTH0 + mo))
    out = out_dir / f"{pp.YEAR}_Planner_Digital_GoodNotes_Hyperlinked.pdf"
    with open(out, "wb") as f:
        writer.write(f)
    raw.unlink(missing_ok=True)
    log(f"  digital planner: {len(pages)} pages, {13 * (len(pages) - 1) + 12} links -> {out.name}")
    return out


BONUS = (" Bonus: a hyperlinked digital version for GoodNotes, Notability or any PDF app (tap a month tab to jump "
         "there).")


def add_to_product(folder: Path | None = None, log=print) -> Path:
    """Build the digital file into an EXISTING planner product and list it, keeping every other field (A4 twin,
    page sizes, store data) exactly as it is."""
    import json
    folder = folder or pp.OUT
    pj = folder / "product.json"
    info = json.loads(pj.read_text(encoding="utf-8"))
    out = make(folder, log)
    if out.name not in info.get("files", []):
        info["files"] = list(info.get("files", [])) + [out.name]
    if "hyperlinked digital version" not in str(info.get("description", "")):
        info["description"] = str(info.get("description", "")).rstrip() + BONUS
    pj.write_text(json.dumps(info, indent=1, ensure_ascii=False), encoding="utf-8")
    return out


if __name__ == "__main__":                            # python -m engine.digital_planner
    add_to_product()
