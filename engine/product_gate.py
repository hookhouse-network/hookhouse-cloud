"""Product gate: nothing is listed in a store without passing it (owner 20 Nov 2026: "strictest policies, quality
control, verifications and validations"; "nothing should bypass these gates"). Runs in store_publish.publish /
publish_gumroad right before each listing (the only code paths that list products). Fail closed.

Checks:
  - record: product.json readable with title, description, files, price;
  - file: the download exists, 10 KB .. 1.5 GB; a PDF starts with %PDF, ends with %%EOF and has at least 90 % of
    the pages its record claims (a half-written PDF never ships);
  - listing: title 15-100 characters, description at least 200 characters, tags present;
  - policy: no protected franchise/character names (ip_guard), no never-topics (policy.topic_flags);
  - price: free_* products are free, paid ones $1-$50;
  - cover: the store cover exists and is at least 600 px wide;
  - no duplicate: no other listed product uses the same title;
  - AI art: a product made with AI art must say so where the store requires it (KDP)."""
from __future__ import annotations

import json
import re
from pathlib import Path

from .config import ROOT

PROD = ROOT / "data" / "products"
HELD = ROOT / "data" / "state" / "product_gate.json"
RULES = ROOT / "config" / "products.yaml"


def rules() -> dict:
    """config/products.yaml (owner 20 Nov: "too big and expensive books"): size, page and price limits per type."""
    import yaml
    try:
        return yaml.safe_load(RULES.read_text(encoding="utf-8")) or {}
    except (OSError, ValueError) as e:
        print(f"product rules unreadable ({type(e).__name__}): using the strict defaults")
        return {}


def ptype(pid: str, r: dict | None = None) -> tuple[str, dict]:
    types = (r if r is not None else rules()).get("types") or {}
    low = pid.lower()
    for name, spec in types.items():
        if name != "default" and any(k in low for k in spec.get("keywords") or []):
            return name, spec
    return "default", types.get("default") or {"max_pages": 120, "price": [1, 29]}
PAGE = re.compile(rb"/Type\s*/Page(?!s)")


def pdf_problems(path: Path, pages_claimed: int | None = None) -> list[str]:
    try:
        data = path.read_bytes()
    except OSError as e:
        return [f"file unreadable ({type(e).__name__})"]
    p = []
    if not data.startswith(b"%PDF"):
        p.append("not a PDF (no %PDF header)")
    if b"%%EOF" not in data[-2048:]:
        p.append("PDF is incomplete (no %%EOF at the end)")
    n = len(PAGE.findall(data))
    if pages_claimed and n < 0.9 * int(pages_claimed):
        p.append(f"PDF has {n} pages but the listing says {pages_claimed}")
    if n == 0:
        p.append("PDF has no pages")
    return p


def verify(pid: str, store: str = "payhip", folder: Path | None = None, listed: dict | None = None) -> list[str]:
    """[] = may be listed on `store`."""
    d = folder or PROD / pid
    try:
        meta = json.loads((d / "product.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return [f"product record unreadable ({type(e).__name__})"]
    p: list[str] = []
    r = rules()
    tname, tspec = ptype(pid.replace("free_", "", 1), r)
    max_mb = float(r.get("max_file_mb", 20))
    if meta.get("ai_art") and not r.get("ai_art_allowed", False):
        p.append("made with AI pictures: products are drawn by code (AI pictures are the videos' scarce quota)")
    for k in ("title", "description", "files", "price_usd"):
        if not meta.get(k):
            p.append(f"product record has no {k}")
    if p:
        return p
    files = [d / f for f in meta["files"] if not str(f).endswith("preview.mp3")]
    missing = [f.name for f in files if not f.exists()]
    if missing:
        p.append("download file missing: " + ", ".join(missing))
    for f in files:
        if not f.exists():
            continue
        size = f.stat().st_size
        if size < 10 * 1024 or size > max_mb * 1024 ** 2:
            p.append(f"{f.name} is {size / 1024 / 1024:.1f} MB (allowed 10 KB - {max_mb:g} MB)")
        if f.suffix.lower() == ".pdf":                 # an A4 twin has the same pages as its Letter file
            p += pdf_problems(f, meta.get("pages") if len([x for x in files if not x.name.endswith("_A4.pdf")]) == 1
                              else None)
    try:                                               # Phase 6: buyers outside the US print on A4
        from .page_sizes import missing_a4
        gaps = missing_a4(d)
        if gaps:
            p.append("US Letter only (no A4 version): " + ", ".join(gaps))
    except Exception as e:  # noqa: BLE001 - fail closed
        p.append(f"page size check could not run ({type(e).__name__})")
    cap = int(tspec.get("max_pages") or 0)
    if cap and int(meta.get("pages") or 0) > cap:
        p.append(f"{meta.get('pages')} pages: a {tname} product is focused, at most {cap} pages")
    title, desc = str(meta["title"]), str(meta["description"])
    if not 15 <= len(title) <= 100:
        p.append(f"title is {len(title)} characters (15-100)")
    if len(desc) < 200:
        p.append(f"description is {len(desc)} characters (at least 200)")
    if not meta.get("tags"):
        p.append("no tags")
    text = " ".join([title, desc, " ".join(map(str, meta.get("tags") or []))])
    try:
        from .ip_guard import hits
        names = hits(text)
        if names:
            p.append("names a protected franchise/character: " + ", ".join(names))
    except Exception as e:  # noqa: BLE001
        p.append(f"franchise check could not run ({type(e).__name__})")
    try:
        from .policy import topic_flags
        flags = topic_flags(text, mode="topic")
        if flags:
            p.append("touches a never-topic: " + ", ".join(flags))
    except Exception as e:  # noqa: BLE001
        p.append(f"never-topic check could not run ({type(e).__name__})")
    try:
        price = float(re.sub(r"[^\d.]", "", str(meta["price_usd"]).split("(")[0]) or 0)
    except ValueError:
        price = -1.0
    if pid.startswith("free_"):
        if price not in (0.0,) and "free" not in str(meta["price_usd"]).lower():
            p.append("a free_ product must be free")
    else:
        lo, hi = (tspec.get("price") or [1, 29])[:2]
        if not float(lo) <= price <= float(hi):
            p.append(f"price ${price:g} outside the {tname} band ${lo}-${hi}")
    cover = d / "store_cover.jpg"
    if not cover.exists():
        p.append("no store cover (store_cover.jpg)")
    else:
        try:
            from PIL import Image
            with Image.open(cover) as im:
                if im.width < 600:
                    p.append(f"store cover only {im.width}px wide")
        except Exception as e:  # noqa: BLE001
            p.append(f"store cover unreadable ({type(e).__name__})")
    if listed is None:
        try:
            listed = json.loads((PROD / "listed.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            listed = {}
    for other, stores in (listed or {}).items():
        if other == pid:
            continue
        for info in (stores or {}).values():
            if isinstance(info, dict) and str(info.get("title", "")).strip().lower() == title.strip().lower()[:100]:
                p.append(f"same title as listed product {other}")
                break
    if store == "kdp" and meta.get("ai_art") and not meta.get("ai_disclosed"):
        p.append("AI art must be disclosed to KDP")
    return list(dict.fromkeys(p))


def hold(pid: str, store: str, problems: list[str]) -> None:
    """Remember why a product waits (Studio / Telegram 'Anything broken?')."""
    try:
        d = json.loads(HELD.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        d = {}
    key = f"{pid}:{store}"
    if problems:
        d[key] = {"problems": problems}
    else:
        d.pop(key, None)
    from .core.atomic import write_json
    write_json(HELD, d)
