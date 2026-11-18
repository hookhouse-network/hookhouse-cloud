"""Free samples (lead magnets) and bundles, from the two income articles the owner shared on 16 Nov:
- "Useful free content -> free resource -> email list -> paid product": a stranger downloads something free far more
  readily than they buy. Each printable gets a free sample: its cover, a few real pages and a last page that links to
  the full version and the store. Payhip asks for an email before a free download, so the samples also build the
  buyer list (Payhip > Marketing > Email: tell them about new products).
- "Add upsells or bundles later": bundles sell the whole set for less than the parts.
The samples go to Payhip like any product (price 0), to Pinterest ("free printable" is one of its biggest searches)
and to the matching channel's video descriptions (not Made-for-Kids channels: no links there by law).
Usage: python -m engine.lead_magnets            build every free sample (+ store cover + pins)"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw

from . import store_covers
from .config import ROOT

PROD = ROOT / "data" / "products"
STORE = "https://payhip.com/HookHouseMedia"
PW, PH = 2550, 3300                                  # US Letter at 300 dpi, like the parent PDFs


def free_id(pid: str) -> str:
    return "free_" + pid


def _paid_link(pid: str) -> str:
    try:
        rec = json.loads((PROD / "listed.json").read_text(encoding="utf-8")).get(pid) or {}
    except (OSError, ValueError):
        rec = {}
    return (rec.get("payhip") or {}).get("public") or STORE


def _font(size: int, name: str = "Poppins-ExtraBold.ttf"):
    return store_covers._f(name, size)


def _centered(d, y: int, text: str, font, fill) -> int:
    d.text(((PW - d.textlength(text, font=font)) / 2, y), text, font=font, fill=fill)
    return y + int(font.size * 1.25)


def upsell_page(pid: str, link: str) -> Image.Image:
    """The last page: what the full version adds, its price and the link (also clickable in the PDF)."""
    spec, meta = store_covers.SPECS[pid], json.loads((PROD / pid / "product.json").read_text(encoding="utf-8"))
    acc = store_covers._rgb(spec["accent"])
    img = store_covers._background(*spec["bg"]).resize((PW, PH)).convert("RGB")
    d = ImageDraw.Draw(img)
    y = _centered(d, 360, "LIKED THESE PAGES?", _font(150, "Anton-Regular.ttf"), (255, 255, 255))
    y = _centered(d, y + 10, "GET THE FULL VERSION", _font(170, "Anton-Regular.ttf"), acc)
    y = _centered(d, y + 40, " ".join(spec["head"]).title() + ": " + spec["sub"], _font(70), (255, 255, 255))
    y += 80
    for feat in spec["feats"]:
        d.ellipse([430, y + 8, 510, y + 88], fill=acc)
        d.line([(450, y + 48), (466, y + 66), (494, y + 30)], fill=(20, 20, 30), width=12)
        d.text((550, y), feat, font=_font(72), fill=(255, 255, 255))
        y += 130
    price = str(meta.get("price_usd", "")).split("(")[0].strip()
    y += 80
    if price:
        y = _centered(d, y, f"Only {price}, instant download", _font(90), acc)
    pill = link.replace("https://", "")
    f = _font(78)
    w = d.textlength(pill, font=f) + 160
    d.rounded_rectangle([(PW - w) / 2, y + 60, (PW + w) / 2, y + 230], 85, fill=acc)
    d.text(((PW - w) / 2 + 80, y + 95), pill, font=f, fill=(20, 20, 30))
    _centered(d, PH - 520, "More printables and planners:", _font(64), (255, 255, 255))
    _centered(d, PH - 420, STORE.replace("https://", ""), _font(64), acc)
    _centered(d, PH - 260, "Made by HookHouse Media · free for personal & classroom use", _font(46), (230, 230, 230))
    return img


def build_free(pid: str, log=print) -> Path:
    """data/products/free_<pid>/: the sample PDF, product.json, store cover and 2 Pinterest pins."""
    import fitz
    fb, spec = store_covers.FREEBIES[pid], store_covers.SPECS[pid]
    out = PROD / free_id(pid)
    out.mkdir(parents=True, exist_ok=True)
    src = fitz.open(PROD / pid / spec["pdf"])
    doc = fitz.open()
    for n in [0] + fb["pages"]:                                   # the real cover + the chosen real pages
        doc.insert_pdf(src, from_page=min(n, len(src) - 1), to_page=min(n, len(src) - 1))
    link = _paid_link(pid)
    img = upsell_page(pid, link)
    tmp = out / "_upsell.jpg"
    img.save(tmp, quality=90)
    w, h = src[0].rect.width, src[0].rect.height
    pg = doc.new_page(width=w, height=h)
    pg.insert_image(pg.rect, filename=str(tmp))
    pg.insert_link({"kind": fitz.LINK_URI, "from": fitz.Rect(0, h * 0.45, w, h * 0.85), "uri": link})
    pg.insert_link({"kind": fitz.LINK_URI, "from": fitz.Rect(0, h * 0.85, w, h * 0.92), "uri": STORE})
    pdf = out / store_covers.SPECS[free_id(pid)]["pdf"]
    doc.save(pdf, garbage=3, deflate=True)
    tmp.unlink(missing_ok=True)
    parent = json.loads((PROD / pid / "product.json").read_text(encoding="utf-8"))
    meta = {"title": store_covers.TITLES[free_id(pid)], "free_of": pid, "files": [pdf.name], "price_usd": "$0",
            "price_inr": "₹0", "channel": parent.get("channel", ""), "stores": ["Payhip"],
            "description": f"Free sample: {fb['what']}. The last page links to the full version.",
            "tags": ["free printable"] + list(parent.get("tags", []))[:7],
            "note": "Lead magnet: Payhip collects the email before the free download."}
    (out / "product.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False), encoding="utf-8")
    store_covers.make(free_id(pid))
    try:
        from . import pins
        pins.make(free_id(pid))
    except Exception as e:  # noqa: BLE001 - pins are a bonus, the sample itself is ready
        log(f"{free_id(pid)}: pins not made ({e})")
    log(f"{free_id(pid)}: {len(doc)} pages -> {pdf.relative_to(ROOT)}")
    return pdf


def build_all(log=print) -> list[Path]:
    return [build_free(pid, log) for pid in store_covers.FREEBIES if (PROD / pid / "product.json").exists()]


if __name__ == "__main__":
    ids = sys.argv[1:] or list(store_covers.FREEBIES)
    for p in ids:
        build_free(p)
