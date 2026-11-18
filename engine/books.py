"""Our Amazon KDP books at a glance (owner, 15 Nov: "update our system and dashboard so i can see the book at anytime").

config/books.json is committed, so the cloud dashboard and the Telegram /books command see the same list as the PC:
title, author (pen name), ISBN, price, KDP status, Amazon link and a small cover picture per book.
The PC refreshes it from the KDP bookshelf (co-pilot Chrome, already signed in): python -m engine.books sync
Usage: python -m engine.books [sync|show]"""
from __future__ import annotations

import base64
import io
import json
import re
import sys
import time
from pathlib import Path

from .config import ROOT

BOOKS = ROOT / "config" / "books.json"
PROD = ROOT / "data" / "products"
BOOKSHELF = "https://kdp.amazon.com/en_US/bookshelf"
STATUSES = ("Live", "In review", "Publishing", "Blocked", "Draft")      # words KDP prints on a bookshelf card
ICON = {"live": "🟢", "in review": "🟡", "publishing": "🟡", "ready": "🟠", "draft": "⚪", "blocked": "🔴",
        "not started": "⚪", "changes asked": "✏️", "rejected": "❌"}
LABEL = {"ready": "ready: tap Publish on KDP", "in review": "in review at Amazon (up to 72 h)", "not started": "not uploaded yet",
         "changes asked": "you asked for changes (being fixed)", "rejected": "rejected by you"}


def label(status: str) -> str:
    return LABEL.get(status, status)


def load() -> dict:
    try:
        return json.loads(BOOKS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save(books: dict) -> None:
    BOOKS.parent.mkdir(parents=True, exist_ok=True)
    BOOKS.write_text(json.dumps(books, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def record(pid: str, **fields) -> dict:
    books = load()
    b = books.setdefault(pid, {})
    b.update({k: v for k, v in fields.items() if v is not None})
    b["updated"] = time.strftime("%Y-%m-%d %H:%M")
    save(books)
    return b


def amazon_url(b: dict) -> str:
    """The book's Amazon page once it has an ASIN; before that an ISBN search (works as soon as it is live)."""
    if b.get("asin"):
        return f"https://www.amazon.com/dp/{b['asin']}"
    if b.get("isbn"):
        return f"https://www.amazon.com/s?k={b['isbn']}"
    return ""


def _thumb(folder: Path) -> str:
    """Small JPEG (base64) of the front cover: the right half of the wrap-around cover preview."""
    src = folder / "kdp_cover_preview.jpg"
    if not src.exists():
        return ""
    from PIL import Image
    im = Image.open(src).convert("RGB")
    w, h = im.size
    im = im.crop((w // 2 + int(w * 0.004), 0, w, h))
    im.thumbnail((120, 160))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=70)
    return base64.b64encode(buf.getvalue()).decode()


def refresh_local() -> dict:
    """Fill every book's fixed facts from its KDP listing kit (PC only: data/products is not in the cloud)."""
    books = load()
    try:
        old = json.loads((PROD / "kdp_state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        old = {}
    try:
        listed = json.loads((PROD / "listed.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        listed = {}
    for lj in sorted(PROD.glob("*/kdp_listing.json")):
        pid = lj.parent.name
        k = json.loads(lj.read_text(encoding="utf-8"))
        b = books.setdefault(pid, {})
        b.update({"title": k.get("title", pid), "subtitle": k.get("subtitle", ""), "author": k.get("author", ""),
                  "pages": k.get("pages"), "format": "Paperback " + str(k.get("trim", ""))})
        b.setdefault("status", (old.get(pid) or {}).get("status", "not started").split(" (")[0])
        for key in ("isbn", "price"):
            if (old.get(pid) or {}).get(key) and not b.get(key):
                b[key] = old[pid][key]
        b.setdefault("price", k.get("price"))
        pdf = ((listed.get(pid) or {}).get("payhip") or {}).get("public")
        if pdf:
            b["pdf_url"] = pdf                               # the printable PDF version on Payhip
        t = _thumb(lj.parent)
        if t:
            b["thumb"] = t
    save(books)
    return books


def parse_bookshelf(text: str, links: list[str], books: dict) -> dict:
    """Status / ASIN / KDP id for each of our books from the bookshelf page text (pure function, tested)."""
    found = {}
    titles = sorted(((b.get("title") or ""), pid) for pid, b in books.items() if b.get("title"))
    pos = sorted((text.find(t), pid) for t, pid in titles if text.find(t) >= 0)
    for n, (start, pid) in enumerate(pos):
        end = pos[n + 1][0] if n + 1 < len(pos) else len(text)
        card = text[start:end]
        para = card.split("Paperback", 1)[1] if "Paperback" in card else card
        status = next((s for s in STATUSES if re.search(rf"\b{s}\b", para[:400])), None)
        asin = re.search(r"\b(B0[A-Z0-9]{8})\b", card)
        found[pid] = {"status": status.lower() if status else None, "asin": asin.group(1) if asin else None}
    for url in links:
        m = re.search(r"/title-setup/paperback/([A-Z0-9]{8,})/", url) or re.search(r"/paperback/([A-Z0-9]{8,})/", url)
        if m:
            found.setdefault("_ids", []).append(m.group(1))
    return found


def sync(port: int = 9333) -> str:
    """Read the KDP bookshelf in the co-pilot Chrome (owner already signed in) and update config/books.json."""
    from playwright.sync_api import sync_playwright
    books = refresh_local()
    with sync_playwright() as pw:
        br = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
        page, mine = _kdp_page(br)
        try:
            page.goto(BOOKSHELF, wait_until="commit", timeout=90000)
            page.wait_for_timeout(9000)
            text = page.inner_text("body")
            links = [a.get_attribute("href") or "" for a in page.locator("a[href*='paperback']").all()]
        finally:
            if mine:
                page.close()
    if "Bookshelf" not in text:
        return "KDP bookshelf did not open (signed out?). Nothing changed."
    found = parse_bookshelf(text, links, books)
    changed = []
    _changes.clear()
    for pid, f in found.items():
        if pid.startswith("_"):
            continue
        b = books[pid]
        if f["status"] and f["status"] != b.get("status") and not (b.get("status") == "ready" and f["status"] == "draft"):
            changed.append(f"{b['title'][:40]}: {b.get('status')} -> {f['status']}")
            _changes.append((pid, f["status"]))
            b["status"] = f["status"]
        if f["asin"]:
            b["asin"] = f["asin"]
        b["checked"] = time.strftime("%Y-%m-%d %H:%M")
    save(books)
    return "Books synced. " + ("; ".join(changed) if changed else "No status change.")


def text() -> str:
    """Telegram /books: every book with its status and links."""
    books = load()
    if not books:
        return "No books yet."
    lines = ["📚 Our books (Amazon KDP, author name HookHouse Media)"]
    order = {"live": 0, "in review": 1, "publishing": 1, "ready": 2, "draft": 3, "not started": 4, "blocked": 5}
    for pid, b in sorted(books.items(), key=lambda kv: (order.get(kv[1].get("status", ""), 9), kv[1].get("title", ""))):
        st = b.get("status", "not started")
        line = f"{ICON.get(st, '⚪')} {b.get('title', pid)}  ·  {label(st)}"
        if b.get("price"):
            line += f"  ·  ${b['price']}"
        if st in ("live",) and amazon_url(b):
            line += f"\n   Amazon: {amazon_url(b)}"
        elif b.get("isbn") and st != "not started":
            line += f"\n   ISBN {b['isbn']} (Amazon page appears when it is live)"
        if b.get("pdf_url"):
            line += f"\n   PDF version: {b['pdf_url']}"
        lines.append(line)
    lines.append(f"KDP bookshelf: {BOOKSHELF}")
    return "\n".join(lines)


_changes: list[tuple[str, str]] = []                   # (book id, new status) from the last sync


def _kdp_page(br):
    """An open KDP tab in the co-pilot Chrome if there is one (signed in, not throttled), else a new tab."""
    ctx = br.contexts[0]
    for pg in ctx.pages:
        if "kdp.amazon.com" in pg.url:
            return pg, False
    return ctx.new_page(), True


# ---------- Telegram approval, then the PC publishes (owner, 15 Nov: "automated ... verify through telegram") ----------
ASK_EVERY_H = 24
APPROVAL = "book-{pid}.json"                            # cloud Store asset written by the owner's Telegram tap


def review_pdf(pid: str) -> Path | None:
    """One PDF the owner can flip through like the printed book: front cover, every interior page, back cover.
    (KDP takes the cover as a separate wrap-around file: back | spine | front, with 0.125 in bleed.)"""
    import fitz                                            # PyMuPDF
    folder = PROD / pid
    try:
        kit = json.loads((folder / "kdp_listing.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    cover, inside = folder / "kdp_cover.pdf", folder / kit.get("interior", "")
    if not (cover.is_file() and inside.is_file()):
        return None
    out = folder / f"{inside.stem}_full_book_preview.pdf"
    if out.exists() and out.stat().st_mtime > max(cover.stat().st_mtime, inside.stat().st_mtime):
        return out
    bleed, spine = 0.125 * 72, float(kit.get("spine_in") or 0) * 72
    src = fitz.open(cover)
    page = src[0]
    w, h = page.rect.width, page.rect.height
    half = (w - spine) / 2
    back = fitz.Rect(bleed, bleed, half, h - bleed)                      # trim box of each side, bleed cut off
    front = fitz.Rect(half + spine, bleed, w - bleed, h - bleed)
    doc = fitz.open()
    for clip in (front,):
        p = doc.new_page(width=clip.width, height=clip.height)
        p.show_pdf_page(p.rect, src, 0, clip=clip)
    doc.insert_pdf(fitz.open(inside))
    p = doc.new_page(width=back.width, height=back.height)
    p.show_pdf_page(p.rect, src, 0, clip=back)
    doc.save(out, garbage=3, deflate=True)
    return out


def ask_publish(pid: str) -> bool:
    """ONE Telegram message (owner, 15 Nov): the whole book PDF (front cover, every page, back cover) with the facts
    as its caption and ✅ Approve / ✏️ Change / ❌ Reject under it. Nothing goes on sale without that tap."""
    from . import telegram_bot as tb
    b = load().get(pid) or {}
    cap = (f"📚 Book ready for Amazon: {b.get('title', pid)}\n{(b.get('subtitle') or '')[:120]}\n"
           f"Author name {b.get('author') or 'HookHouse Media'} · {b.get('pages', '?')} pages · ${b.get('price', '?')}"
           f"{' · ISBN ' + b['isbn'] if b.get('isbn') else ''}\n"
           "Open the PDF: front cover, every page, back cover (Amazon prints the barcode in the white box).\n"
           "✅ Approve: on sale worldwide after Amazon's review (up to 72 h) · ✏️ Change: type what to fix · "
           "❌ Reject: not published")
    kb = buttons(pid)
    pdf = None
    try:
        pdf = review_pdf(pid)
    except Exception:  # noqa: BLE001 - fall back to the cover picture
        pdf = None
    if pdf and pdf.stat().st_size < 49 * 1024 * 1024:                # Telegram bot file limit is 50 MB
        name = re.sub(r"[^A-Za-z0-9]+", "_", b.get("title", pid))[:60].strip("_") + "_full_preview.pdf"
        with pdf.open("rb") as fh:
            tb.api("sendDocument", files={"document": (name, fh, "application/pdf")}, chat_id=tb._chat(),
                   caption=cap[:1024], reply_markup=kb, http_timeout=300)
    else:
        cover = PROD / pid / "kdp_cover_preview.jpg"
        if cover.exists():
            with cover.open("rb") as fh:
                tb.api("sendPhoto", files={"photo": (cover.name, fh, "image/jpeg")}, chat_id=tb._chat(),
                       caption=cap[:1024], reply_markup=kb, http_timeout=120)
        else:
            tb.send(cap, reply_markup=kb)
    record(pid, asked=time.time())
    return True


def buttons(pid: str) -> dict:
    """The same three choices as a video: Approve, Change (type what to fix), Reject."""
    return {"inline_keyboard": [[{"text": "✅ Approve & publish", "callback_data": f"bk:ok:{pid}"},
                                 {"text": "✏️ Change", "callback_data": f"bk:ch:{pid}"},
                                 {"text": "❌ Reject", "callback_data": f"bk:rj:{pid}"}]]}


def _decide(pid: str, decision: str, note: str = "") -> None:
    """The decision goes to the cloud store: the cloud's books.json is replaced by the PC's copy on every tick,
    so the PC helper is the one that applies it."""
    from .cloud.store import Store
    from .cloud import media
    Store().put(media.TAG, APPROVAL.format(pid=pid),
                json.dumps({"pid": pid, "decision": decision, "note": note, "at": time.time()}).encode())


def on_tap(data: str) -> str:
    """Telegram button (cloud or PC bot). "ch" is answered by the bot asking what to change (see change_text)."""
    _, decision, pid = data.split(":", 2)
    title = (load().get(pid) or {}).get("title", pid)
    if decision == "no":                                 # older messages had "Not yet"
        return "⏸ OK, not yet. I'll ask again tomorrow."
    if decision == "rj":
        _decide(pid, "reject")
        return f"❌ Rejected: {title} will not be published. Tap ✏️ Change instead next time if it only needs fixes."
    _decide(pid, "ok")
    return (f"✅ Approved: {title}. The PC publishes it on Amazon the next time it is on (within about 15 minutes), "
            "then I message you. Amazon's review takes up to 72 hours.")


def change_text(pid: str, text: str) -> str:
    """The owner typed what to fix after ✏️ Change: saved for the next book update; nothing is published."""
    _decide(pid, "change", text[:1000])
    return ("✏️ Saved: \"" + text[:200] + "\". The book stays unpublished; I'll fix it, then send you the new version "
            "to approve.")


def publish(pid: str, port: int = 9333) -> str:
    """Click "Publish Your Paperback Book" for an owner-approved book whose setup is complete (PC, co-pilot Chrome)."""
    from playwright.sync_api import sync_playwright
    b = load().get(pid) or {}
    if not b.get("kdp_id"):
        return f"{pid}: no KDP id yet"
    if b.get("status") != "ready":                       # owner 17 Nov: an old Approve button must not publish a
        return f"{b.get('title', pid)}: not published, it is being redesigned ({b.get('status')})"  # book being redone
    with sync_playwright() as pw:
        br = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
        page, mine = _kdp_page(br)
        try:
            page.goto(f"https://kdp.amazon.com/en_US/title-setup/paperback/{b['kdp_id']}/pricing",
                      wait_until="commit", timeout=90000)
            page.wait_for_timeout(9000)
            btn = page.get_by_role("button", name="Publish Your Paperback Book")
            if not btn.count():
                return f"{b.get('title', pid)}: the Publish button is not there (setup incomplete?)"
            btn.first.click()
            page.wait_for_timeout(15000)
            body = page.inner_text("body")
        finally:
            if mine:
                page.close()
    if any(w in body for w in ("submitted", "Congratulations", "In review", "Bookshelf")):
        record(pid, status="in review", submitted=time.strftime("%Y-%m-%d %H:%M"))
        return f"{b.get('title', pid)}: sent to Amazon (in review, up to 72 h)"
    return f"{b.get('title', pid)}: clicked Publish but could not confirm; I'll check the bookshelf next time"


def pc_job(log=print) -> list[str]:
    """PC helper (co-pilot Chrome open): publish approved books, refresh statuses, tell the owner what changed,
    ask about books that are ready, and share books.json with the cloud."""
    from . import telegram_bot as tb
    from .cloud.store import Store
    from .cloud import media
    out, store = [], Store()
    for pid in list(load()):
        name = APPROVAL.format(pid=pid)
        raw = store.get(media.TAG, name)
        if not raw:
            continue
        d = json.loads(raw)
        if d.get("decision") == "ok":
            msg = publish(pid)
            tb.notify("📚 " + msg)
        elif d.get("decision") == "reject":
            record(pid, status="rejected")
            msg = f"{pid}: rejected by the owner"
        else:                                            # change: Claude/the book builder applies it, then asks again
            record(pid, status="changes asked", change=d.get("note", ""))
            msg = f"{pid}: change asked: {d.get('note', '')[:80]}"
        store.delete(media.TAG, name)
        out.append(msg)
    out.append(sync())
    for pid, st in list(_changes):
        b = load()[pid]
        if st == "live":
            tb.notify(f"📚 {b['title']} is LIVE on Amazon: {amazon_url(b)}")
        elif st == "blocked":
            tb.notify(f"📚 Amazon blocked {b['title']}: open the KDP bookshelf to see why ({BOOKSHELF})")
    for pid, b in load().items():
        if b.get("status") == "ready" and time.time() - float(b.get("asked") or 0) > ASK_EVERY_H * 3600:
            ask_publish(pid)
            out.append(f"asked the owner about {pid}")
    store.put(media.TAG, "books.json", BOOKS.read_bytes())         # the cloud dashboard and /books read this copy
    for line in out:
        log("books: " + line)
    return out


def pull_cloud_copy() -> bool:
    """Cloud tick: take the PC's latest books.json (statuses change on the PC, which sees the KDP bookshelf)."""
    from .cloud.store import Store
    from .cloud import media
    raw = Store().get(media.TAG, "books.json")
    if not raw:
        return False
    BOOKS.write_bytes(raw)
    return True


if __name__ == "__main__":
    from .config import load_env
    load_env()
    arg = sys.argv[1] if len(sys.argv) > 1 else "show"
    if arg == "sync":
        print(sync())
    elif arg == "job":
        pc_job()
    elif arg == "ask" and len(sys.argv) > 2:
        print(ask_publish(sys.argv[2]))
    elif arg == "local":
        refresh_local()
        print(text())
    else:
        print(text())
