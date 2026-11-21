"""A4 + US Letter in every printable download (master plan Phase 6, section 4.4b rule 4: "Formats buyers expect").

Our printables are drawn at US Letter (8.5 x 11 in, 612 x 792 pt). Buyers outside the US print on A4 (210 x 297 mm,
595.28 x 841.89 pt). Each Letter PDF gets an A4 twin made with pypdf (BSD licence): every page is scaled to the A4
width (x0.9727) and centred on an A4 page box. It is a vector transform, so nothing is re-rendered, nothing is cropped,
quality is unchanged and the file stays small. The A4 file is added to the product's `files`, so the store download
(engine/store_publish.download_file) zips both sizes together."""
from __future__ import annotations

import json
from pathlib import Path

LETTER = (612.0, 792.0)
A4 = (595.2756, 841.8898)
TOL = 2.0                                       # points


def is_letter(w: float, h: float) -> bool:
    return abs(w - LETTER[0]) <= TOL and abs(h - LETTER[1]) <= TOL


def a4_name(letter_pdf: str) -> str:
    return f"{Path(letter_pdf).stem}_A4.pdf"


def letter_to_a4(src: Path, dst: Path) -> Path:
    """Every Letter page -> an A4 page with the content scaled to the A4 width and centred vertically."""
    from pypdf import PdfWriter, Transformation
    from pypdf.generic import RectangleObject
    writer = PdfWriter(clone_from=str(src))          # pypdf 7: pages must belong to the writer before transforming
    for page in writer.pages:
        w, h = float(page.mediabox.width), float(page.mediabox.height)
        s = min(A4[0] / w, A4[1] / h)
        tx, ty = (A4[0] - w * s) / 2, (A4[1] - h * s) / 2
        page.add_transformation(Transformation().scale(s, s).translate(tx, ty))
        box = RectangleObject([0, 0, A4[0], A4[1]])
        page.mediabox = box
        page.cropbox = box
        page.trimbox = box
        page.bleedbox = box
        page.artbox = box
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(".part")
    with open(tmp, "wb") as fh:
        writer.write(fh)
    tmp.replace(dst)                                # never a half-written download
    return dst


def ensure_a4(folder: Path, log=print) -> list[str]:
    """For one product folder: an A4 twin for every Letter PDF in product.json `files` (made or refreshed when the
    Letter file is newer), listed right after its Letter file. Returns the A4 files that were (re)made."""
    pj = folder / "product.json"
    if not pj.exists():
        return []
    from pypdf import PdfReader
    meta = json.loads(pj.read_text(encoding="utf-8"))
    files = list(meta.get("files") or [])
    made, out = [], []
    for f in files:
        if f.endswith("_A4.pdf"):
            continue                                # re-added after its Letter file below
        out.append(f)
        src = folder / f
        if not (f.lower().endswith(".pdf") and src.exists()):
            continue
        box = PdfReader(str(src)).pages[0].mediabox
        if not is_letter(float(box.width), float(box.height)):
            continue
        twin = folder / a4_name(f)
        if not twin.exists() or twin.stat().st_mtime < src.stat().st_mtime:
            letter_to_a4(src, twin)
            made.append(twin.name)
        out.append(twin.name)
    if out != files:
        meta["files"] = out
        meta["page_sizes"] = ["US Letter", "A4"]
        pj.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    if made:
        log(f"{folder.name}: A4 version added ({', '.join(made)})")
    return made


def missing_a4(folder: Path) -> list[str]:
    """Letter PDFs in the download without their A4 twin (the product gate holds the listing)."""
    pj = folder / "product.json"
    if not pj.exists():
        return []
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError
    files = json.loads(pj.read_text(encoding="utf-8")).get("files") or []
    gaps = []
    for f in files:
        src = folder / f
        if f.endswith("_A4.pdf") or not (f.lower().endswith(".pdf") and src.exists()):
            continue
        try:
            box = PdfReader(str(src)).pages[0].mediabox
        except (PdfReadError, IndexError, KeyError, ValueError) as e:   # pdf_problems reports a broken PDF itself
            print(f"page size: {f} not readable ({type(e).__name__}); left to the PDF check")
            continue
        if is_letter(float(box.width), float(box.height)) and a4_name(f) not in files:
            gaps.append(f)
    return gaps


def ensure_all(root: Path | None = None, log=print) -> int:
    from .config import ROOT
    root = root or ROOT / "data" / "products"
    n = 0
    for pj in sorted(root.glob("*/product.json")):
        try:
            n += len(ensure_a4(pj.parent, log))
        except Exception as e:  # noqa: BLE001 - one broken product never stops the others; the gate still holds it
            log(f"{pj.parent.name}: A4 version failed ({type(e).__name__}: {e})")
    return n
