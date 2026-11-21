"""Digital products -> our stores, as one automated flow (owner, 14 Nov: "do all the things in automated flow, and
update our system"; "catchy, high quality, high selling").

  python cli.py products publish              covers + catchy titles + upload every product not listed yet
  python cli.py products publish --replace    also re-list products already up (new cover/title)
  python cli.py products covers               only (re)make the store covers

How: Payhip has no product-creation API, so the flow drives the logged-in co-pilot Chrome (data/browser_profile;
the owner signed in once). It reuses the open co-pilot window when it is running (CDP port 9333), otherwise opens
that profile itself. What is listed where is recorded in data/products/listed.json (no double listings; the
store links feed descriptions and bios). Prices are the catalogue's USD prices; checkout/payout settings are the
owner's (bank details are never typed by the system)."""
from __future__ import annotations

import json
import re
import time
import zipfile
from pathlib import Path

from .config import ROOT
from . import store_covers

PROD = ROOT / "data" / "products"
LISTED = PROD / "listed.json"
SHOP_LINKS = ROOT / "config" / "shop_links.json"   # committed copy: the cloud has no data/products (GitHub test fails
                                                   # of 14 Nov: cloud videos would have gone out without the shop line)
STORE_URL = {"payhip": "https://payhip.com/HookHouseMedia"}


def products() -> list[str]:
    return [pid for pid in store_covers.SPECS if (PROD / pid / "product.json").exists()]


def listed() -> dict:
    try:
        return json.loads(LISTED.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _record(pid: str, store: str, **info) -> None:
    data = listed()
    data.setdefault(pid, {})[store] = {**info, "at": time.strftime("%Y-%m-%d %H:%M")}
    LISTED.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")


def title_for(pid: str) -> str:
    meta = json.loads((PROD / pid / "product.json").read_text(encoding="utf-8"))
    return store_covers.TITLES.get(pid, meta["title"])[:100]


def description_for(pid: str, platform: str = "payhip") -> str:
    """Written for the product and the platform (engine/store_copy.py); the catalogue text if none is written."""
    from .store_copy import description
    text = description(pid, platform)
    if text:
        return text
    meta = json.loads((PROD / pid / "product.json").read_text(encoding="utf-8"))
    return meta["description"] + "\n\nInstant download right after purchase. Made by HookHouse Media."


def download_file(pid: str) -> Path:
    d = PROD / pid
    meta = json.loads((d / "product.json").read_text(encoding="utf-8"))
    files = [d / f for f in meta["files"] if (d / f).exists() and not f.endswith("preview.mp3")]
    if len(files) == 1:
        return files[0]
    z = d / f"{pid}.zip"                                      # several files -> one download
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            zf.write(f, f.name)
    return z


def price_usd(pid: str) -> float:
    meta = json.loads((PROD / pid / "product.json").read_text(encoding="utf-8"))
    return float(re.sub(r"[^\d.]", "", meta["price_usd"].split("(")[0]) or 5)


def _upload_timeout(f: Path) -> float:
    """Milliseconds for a browser file upload: 30 s + 10 s per MB, at most 10 minutes (20 Nov: a 26 MB PDF timed out
    at the fixed 30 s; files travel through the DevTools connection)."""
    try:
        mb = Path(f).stat().st_size / 1024 / 1024
    except OSError:
        mb = 0
    return min(600_000, 30_000 + 10_000 * mb)


def _gate_ok(pid: str, store: str, out: list, log) -> bool:
    """engine/product_gate.py, fail closed: a gate that cannot run holds the product."""
    from . import product_gate
    try:
        probs = product_gate.verify(pid, store)
    except Exception as e:  # noqa: BLE001
        probs = [f"product gate could not run ({type(e).__name__}: {str(e)[:80]})"]
    try:
        product_gate.hold(pid, store, probs)
        product_gate.report(pid, store, probs)               # Phase 6: every listing's gate report is kept
    except OSError as e:
        log(f"product gate record: {e}")
    if probs:
        out.append(f"{pid}: held by the product gate: {'; '.join(probs)[:300]}")
        log(out[-1])
        return False
    try:
        from . import product_promo                         # value-first promo Shorts on the matching channel
        product_promo.register(pid)
    except Exception as e:  # noqa: BLE001 - the listing matters more than the promo note
        log(f"promo register: {type(e).__name__}: {e}")
    return True


# ---------------- Payhip (browser) ----------------
J_ROWS = r"""() => Array.from(document.querySelectorAll('a')).filter(a => /^edit$/i.test(a.innerText.trim()))
  .map(a => { let r = a; for (let k = 0; k < 6 && r; k++) { if (r.innerText && r.innerText.length > 40) break; r = r.parentElement; }
              const v = r ? Array.from(r.querySelectorAll('a')).find(x => /^view$/i.test(x.innerText.trim())) : null;
              return [a.href, (r ? r.innerText : '').split('\n')[0].trim(), v ? v.href : '']; })"""


def connect(pw, tries: int = 3):
    """The co-pilot Chrome over CDP. A frozen tab can block the attach, so stuck blank tabs are closed and the
    connection retried (never a second Chrome on the same profile: Chrome refuses that)."""
    import json as _json
    import urllib.request
    last = None
    for _ in range(tries):
        try:
            return pw.chromium.connect_over_cdp("http://127.0.0.1:9333", timeout=45000)
        except Exception as e:  # noqa: BLE001
            last = e
            try:
                tabs = _json.loads(urllib.request.urlopen("http://127.0.0.1:9333/json", timeout=10).read())
                for t in tabs:
                    if t.get("type") == "page" and t.get("url") in ("about:blank", ""):
                        urllib.request.urlopen(f"http://127.0.0.1:9333/json/close/{t['id']}", timeout=10).read()
            except OSError:
                raise RuntimeError("the co-pilot Chrome is not open: start it with python -m engine.copilot serve")
    raise RuntimeError(f"could not attach to the co-pilot Chrome: {last}")


def _page(pw):
    b = connect(pw)
    from .browser_windows import window_for
    page = window_for(b, "payhip.com", "https://payhip.com/products", "left")   # own window: never throttled
    page.bring_to_front()
    return page


def payhip_rows(p) -> list[tuple[str, str, str]]:
    """(edit url, title as shown, public url) for every product in the store."""
    rows: list[tuple[str, str, str]] = []
    for page_no in range(1, 20):                              # Payhip shows ~10 products per page: read them all
        p.goto(f"https://payhip.com/products?page={page_no}", timeout=90000, wait_until="domcontentloaded")
        p.wait_for_timeout(2500)
        if "login" in p.url:
            raise RuntimeError("Payhip is signed out in the co-pilot Chrome: sign in once, then run again")
        new = [tuple(x) for x in p.evaluate(J_ROWS) if tuple(x) not in rows]
        if not new:
            break
        rows += new
    return rows


J_ROW_MENU = r"""(code) => {
  const a = Array.from(document.querySelectorAll('a')).find(x => (x.getAttribute('href') || '').endsWith('/product/edit/' + code));
  if (!a) return false;
  let r = a; for (let k = 0; k < 8 && r; k++) { r = r.parentElement; if (r && r.querySelector('.dropdown-toggle')) break; }
  const t = r && r.querySelector('.dropdown-toggle'); if (!t) return false; t.click(); return true; }"""


def payhip_delete_product(p, code: str) -> bool:
    """Delete a whole product (row menu > Delete product > confirm). NOT the edit page's 'Delete' link: that one
    only removes the download file (learned 14 Nov)."""
    for page_no in range(1, 20):
        p.goto(f"https://payhip.com/products?page={page_no}", timeout=90000, wait_until="domcontentloaded")
        p.wait_for_timeout(2000)
        if p.evaluate(J_ROW_MENU, code):
            p.wait_for_timeout(800)
            p.locator(".dropdown-menu a", has_text="Delete product").filter(visible=True).first.click()
            p.wait_for_timeout(1200)
            yes = p.locator("button", has_text=re.compile(r"Yes|Delete", re.I)).filter(visible=True)
            if yes.count():
                yes.last.click()
            p.wait_for_timeout(3000)
            return True
        if not p.evaluate(J_ROWS):
            break
    return False


FILE_NAME = re.compile(r"[\w\-]+\.(?:zip|pdf|xlsx|csv|png|jpg|epub)", re.I)
# 22 Nov: "/uploading|\d+%/" on the whole page matched Payhip's static "You've completed 50% of your store setup"
# banner, so every upload wait ran to its full limit; only the upload rows tell whether a file is still uploading
J_UPLOADING = (r"""() => Array.from(document.querySelectorAll('.js-upload-digital-file-row, .upload_ebook_file_row, """
               r"""[class*=plupload], [class*=progress]')).some(r => r.offsetParent && """
               r"""/uploading|\b\d{1,2}%/i.test(r.innerText))""")


def payhip_code(pid: str) -> str | None:
    """The product code from our record's public link (https://payhip.com/b/<code>)."""
    pub = str(((listed().get(pid) or {}).get("payhip") or {}).get("public") or "")
    m = re.search(r"/b/([A-Za-z0-9]+)", pub)
    return m.group(1) if m else None


def missing_files(pid: str, shown: list[str]) -> list[Path]:
    """Files of the product (product.json) that the live listing does not have yet."""
    d = PROD / pid
    meta = json.loads((d / "product.json").read_text(encoding="utf-8"))
    have = {s.lower() for s in shown}
    return [d / f for f in meta.get("files", []) if (d / f).exists() and not f.endswith("preview.mp3")
            and f.lower() not in have]


def zip_members(pid: str, shown: list[str]) -> list[str] | None:
    """Names inside the zips a listing delivers (several files went up as one {pid}.zip), read from the local zip,
    which is the one that was uploaded (download_file rebuilds it only when a product is listed; never call it
    here). New files then go up NEXT TO the zip, so nothing is deleted. None = a zip we do not have."""
    names: list[str] = []
    for s in shown:
        if not s.lower().endswith(".zip"):
            continue
        local = PROD / pid / s
        if not local.exists():
            return None
        with zipfile.ZipFile(local) as zf:
            names += [Path(n).name for n in zf.namelist() if not n.endswith("/")]
    return names


def payhip_files(p, code: str) -> list[str]:
    """The files a live listing delivers. 22 Nov: a read 3.5 s after load missed the file rows (still drawing) and
    the sync uploaded the existing file again: now it waits until the list is drawn and reads the same twice."""
    p.goto(f"https://payhip.com/product/edit/{code}", timeout=90000, wait_until="domcontentloaded")
    if "login" in p.url:
        raise RuntimeError("Payhip is signed out in the co-pilot Chrome")
    last = None
    for _ in range(20):
        p.wait_for_timeout(1500)
        now = sorted(FILE_NAME.findall(p.evaluate("() => document.body.innerText")))
        if now and now == last:
            return sorted(set(now))
        last = now
    raise RuntimeError("the listing's file rows never finished drawing")


def payhip_sync_files(p, pid: str, dry_run: bool = False, log=print) -> dict:
    """P6 (22 Nov): bring a LIVE listing's download up to date IN PLACE: upload the product's missing files next to
    the existing ones ('Upload another product file'), save, re-read. Never deletes anything and never re-lists
    (re-listing changes the URL used in posted shop links and may cut existing buyers off)."""
    code = payhip_code(pid)
    if not code:
        return {"pid": pid, "ok": False, "why": "no Payhip listing recorded"}
    shown = payhip_files(p, code)
    inside = zip_members(pid, shown)
    if inside is None:
        return {"pid": pid, "ok": False, "why": "the listing's zip is not on this PC: its contents are unknown",
                "shown": shown}
    todo = missing_files(pid, shown + inside)
    if not todo:
        return {"pid": pid, "ok": True, "added": [], "shown": shown}
    link = p.locator("a", has_text="Upload another product file").filter(visible=True)
    if link.count():
        link.first.click()
        p.wait_for_timeout(1200)
    files = p.locator("input[type=file]")
    vis = [i for i in range(files.count()) if files.nth(i).evaluate("e => e.offsetParent !== null")]
    if not vis:
        return {"pid": pid, "ok": False, "why": "no file input on the edit page"}
    files.nth(vis[0]).set_input_files([str(f) for f in todo],
                                      timeout=min(900_000, sum(_upload_timeout(f) for f in todo)))   # ms
    want = {f.name.lower() for f in todo}
    for _ in range(600):                                      # every upload finished and listed by name
        p.wait_for_timeout(1000)
        listed_now = {n.lower() for n in FILE_NAME.findall(p.evaluate("() => document.body.innerText"))}
        if want <= listed_now and not p.evaluate(J_UPLOADING):
            break
    names_now = sorted(set(FILE_NAME.findall(p.evaluate("() => document.body.innerText"))))
    if dry_run:
        return {"pid": pid, "ok": True, "dry_run": True, "would_add": [f.name for f in todo], "page_lists": names_now}
    p.click("#addsubmit")
    p.wait_for_timeout(6000)
    after = payhip_files(p, code)
    ok = all(f.name.lower() in {a.lower() for a in after} for f in todo)
    log(f"{pid}: {'added' if ok else 'NOT all added'} {[f.name for f in todo]} -> now {after}")
    return {"pid": pid, "ok": ok, "added": [f.name for f in todo], "now": after}


def payhip_add(p, pid: str) -> str:
    folder = PROD / pid
    p.goto("https://payhip.com/product/add/digital", timeout=90000, wait_until="domcontentloaded")
    p.wait_for_timeout(3500)
    files = p.locator("input[type=file]")
    vis = [i for i in range(files.count()) if files.nth(i).evaluate("e => e.offsetParent !== null")]
    files.nth(vis[0]).set_input_files(str(download_file(pid)), timeout=_upload_timeout(download_file(pid)))
    p.wait_for_timeout(1500)
    p.fill("#p_name", title_for(pid))
    p.fill("#p_price", f"{price_usd(pid):.2f}")
    cover = folder / "store_cover.jpg"
    if len(vis) > 1 and cover.exists():
        files.nth(vis[1]).set_input_files(str(cover))
    ed = p.locator("[contenteditable=true]").filter(visible=True).first
    ed.click()
    p.keyboard.type(description_for(pid), delay=1)
    try:            # owner, 16 Nov (income articles): every buyer and free download joins our free Payhip mailing list
        p.evaluate("() => { const c = document.getElementById('subscribe-customers-to-mailing-list-checkbox');"
                   " if (c && !c.checked) c.click(); }")
    except Exception:  # noqa: BLE001 - the listing itself matters more
        pass
    for _ in range(180):                                       # big zips: wait for the uploads
        if not p.evaluate(J_UPLOADING):
            break
        p.wait_for_timeout(1000)
    p.wait_for_timeout(2000)
    p.click("#addsubmit")
    p.wait_for_timeout(6000)
    err = p.evaluate("() => Array.from(document.querySelectorAll('.alert-danger,.has-error,.error,.invalid-feedback,"
                     ".help-block')).filter(e => e.offsetParent && e.innerText.trim()).map(e => e.innerText).join(' ')")
    if err.strip():
        raise RuntimeError(err.strip()[:200])
    if p.url.rstrip("/").endswith("/product/add/digital"):   # still on the blank form: refused without an error box
        raise RuntimeError("Payhip kept the form open: " + p.evaluate("() => document.body.innerText")[:300])
    return p.url


def publish(store: str = "payhip", ids: list[str] | None = None, replace: bool = False, log=print) -> list[str]:
    from playwright.sync_api import sync_playwright
    out = []
    todo = ids or products()
    for pid in todo:                                           # covers first (fast, offline)
        if replace or not (PROD / pid / "store_cover.jpg").exists():
            store_covers.make(pid)
    with sync_playwright() as pw:
        p = _page(pw)
        rows = payhip_rows(p)
        for pid in todo:
            meta = json.loads((PROD / pid / "product.json").read_text(encoding="utf-8"))
            names = {title_for(pid)[:40].lower(), meta["title"][:40].lower()}
            mine = [u for u, t, _ in rows if t[:40].lower() in names]
            recorded = bool((listed().get(pid) or {}).get(store))   # our own record wins (no double listing)
            if (mine or recorded) and not replace:
                out.append(f"{pid}: already listed")
                continue
            if not _gate_ok(pid, store, out, log):              # 20 Nov: nothing is listed past the product gate
                continue
            try:
                for u in mine:                                   # replace: remove the whole old product
                    payhip_delete_product(p, u.rstrip("/").split("/")[-1])
                url = payhip_add(p, pid)
                _record(pid, store, title=title_for(pid), url=url, price_usd=price_usd(pid))
                out.append(f"{pid}: {'re-listed' if mine else 'listed'} on Payhip (${price_usd(pid):.2f})")
            except Exception as e:  # noqa: BLE001 - keep going with the next product
                out.append(f"{pid}: FAILED {type(e).__name__}: {str(e)[:160]}")
            log(out[-1])
        try:                                                   # public links, for descriptions and bios
            record_public(p, store)
        except Exception as e:  # noqa: BLE001
            log(f"public links not read: {e}")
    return out


# ---------------- Gumroad (browser) ----------------
class GumroadLimit(RuntimeError):
    pass


def gumroad_page(pw):
    """The Gumroad page in its own window (left half) so it never slows a job in another tab."""
    from .browser_windows import window_for
    b = connect(pw)
    p = window_for(b, "gumroad.com", "https://gumroad.com/products", "left")
    p.bring_to_front()
    return p


def gumroad_add(p, pid: str) -> str:
    """New digital product -> description, cover, square thumbnail -> file -> saved (published only once a payout
    method is connected; until then it stays a draft, which Gumroad allows)."""
    folder = PROD / pid
    p.goto("https://gumroad.com/products/new", timeout=120000, wait_until="commit")
    name = p.locator("input[id^=name-]")
    name.wait_for(state="visible", timeout=90000)
    name.fill(title_for(pid))
    p.locator("button", has_text="Digital product").first.click()
    p.locator("input[id^=price-]").fill(f"{price_usd(pid):.0f}")
    p.get_by_role("button", name="Next: Customize").click()
    try:
        p.wait_for_url(re.compile(r"/products/\w+/edit"), timeout=30000, wait_until="commit")
    except Exception as e:  # noqa: BLE001
        raise GumroadLimit("Gumroad won't create more products yet: new accounts are capped at 10 unpublished "
                           "products until a payout method (bank) is connected") from e
    p.locator("[contenteditable=true]").first.wait_for(state="visible", timeout=90000)
    p.wait_for_timeout(2000)
    ed = p.locator("[contenteditable=true]").first
    ed.click()
    p.keyboard.type(description_for(pid, "gumroad"), delay=1)
    p.locator("button", has_text="Upload images or videos").first.click()
    p.wait_for_timeout(1000)
    cf = p.get_by_text("Computer files", exact=True).first
    cf.scroll_into_view_if_needed()
    with p.expect_file_chooser(timeout=20000) as fc:
        cf.click()
    fc.value.set_files(str((folder / "store_cover.jpg").resolve()))
    p.wait_for_timeout(6000)
    up = p.get_by_text("Upload", exact=True).last
    up.scroll_into_view_if_needed()
    with p.expect_file_chooser(timeout=20000) as fc:
        up.click()
    fc.value.set_files(str((folder / "store_thumb.jpg").resolve()))
    p.wait_for_timeout(8000)
    p.get_by_role("button", name="Save and continue").click()
    p.wait_for_url(re.compile(r"/edit/content"), timeout=90000, wait_until="commit")
    p.wait_for_timeout(3000)
    f = download_file(pid)
    p.locator("input[type=file]").first.set_input_files(str(f.resolve()), timeout=_upload_timeout(f))
    for _ in range(300):                                       # big zips: wait for the upload
        t = p.evaluate("() => document.body.innerText")
        if f.stem[:20] in t and "Uploading" not in t and "%" not in t:
            break
        p.wait_for_timeout(2000)
    p.wait_for_timeout(3000)
    p.get_by_role("button", name="Save changes").click()
    p.wait_for_timeout(5000)
    return p.url.replace("/content", "")


def publish_gumroad(ids: list[str] | None = None, log=print) -> list[str]:
    from playwright.sync_api import sync_playwright
    out = []
    with sync_playwright() as pw:
        p = gumroad_page(pw)
        for pid in ids or products():
            if ((listed().get(pid) or {}).get("gumroad") or {}).get("url"):
                out.append(f"{pid}: already on Gumroad")
                continue
            if not _gate_ok(pid, "gumroad", out, log):          # 20 Nov: nothing is listed past the product gate
                continue
            try:
                url = gumroad_add(p, pid)
                _record(pid, "gumroad", title=title_for(pid), url=url, price_usd=price_usd(pid), draft=True)
                out.append(f"{pid}: on Gumroad (draft until a payout method is connected)")
            except GumroadLimit as e:
                out.append(f"Gumroad paused: {e}. The rest go up automatically on the next run after that.")
                log(out[-1])
                break
            except Exception as e:  # noqa: BLE001
                out.append(f"{pid}: FAILED {type(e).__name__}: {str(e)[:160]}")
            log(out[-1])
    return out


def record_public(p, store: str = "payhip") -> int:
    n = 0
    for _, t, view in payhip_rows(p):
        for pid in products():
            if view and t[:40].lower() == title_for(pid)[:40].lower():
                info = (listed().get(pid) or {}).get(store) or {}
                info.pop("at", None)
                _record(pid, store, **{**info, "title": title_for(pid), "public": view})
                n += 1
    if n:
        write_shop_links()
    return n


def _shop_link_local(channel_id: str, free: bool = False) -> tuple[str, str] | None:
    """free=False: the channel's paid product; free=True: its free sample (lead magnet, engine/lead_magnets.py)."""
    from .store_copy import description
    for pid in products():
        meta = json.loads((PROD / pid / "product.json").read_text(encoding="utf-8"))
        if meta.get("channel") != channel_id or bool(meta.get("free_of")) != free:
            continue
        for store in ("payhip", "gumroad"):
            url = ((listed().get(pid) or {}).get(store) or {}).get("public")
            if url:
                return description(pid, "social") or meta["title"], url
    return None


def write_shop_links() -> dict:
    """config/shop_links.json = {channel: [caption, url]} for every channel with a product on sale (goes to the cloud
    with the code)."""
    from .config import channels
    out = {}
    for ch in channels():
        got = _shop_link_local(ch["id"])
        if got:
            out[ch["id"]] = list(got)
        free = _shop_link_local(ch["id"], free=True)
        if free:
            out[ch["id"] + "#free"] = list(free)
    SHOP_LINKS.write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    return out


def shop_link(channel_id: str, free: bool = False) -> tuple[str, str] | None:
    """(caption, public url) of the product that belongs to this channel, if it is on sale (free=True: its free
    sample). PC: from the product kits; cloud (no kits): from config/shop_links.json."""
    if products():
        return _shop_link_local(channel_id, free)
    try:
        got = json.loads(SHOP_LINKS.read_text(encoding="utf-8")).get(channel_id + ("#free" if free else ""))
    except (OSError, ValueError):
        return None
    return tuple(got) if got else None
