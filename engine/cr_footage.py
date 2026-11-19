"""Footage for the campaigns the owner picked (owner 17 Nov 2026: "campaign selection does not work and you are not
creating any clips for that").

Why no clips were made: on Content Rewards a campaign's source files ("Reference materials") are only shown AFTER
joining, and ClippingAlpha lists none for most campaigns. Joining is the owner's own tap on the board; everything after
it runs by itself:

  PC helper (signed-in Chrome, port 9333) -> open each picked campaign page READ-ONLY -> once it shows the files
  (= joined), collect the footage links -> hand them to the cloud as an asset `camp-<id>.json`
  cloud tick -> `merge()`: campaign becomes "joined", links go to data/clip_sources.txt with the campaign id
  (clip slots start by themselves), owner gets one Telegram line.

Never clicks anything on the board, never types, never downloads from video-platform pages.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
import urllib.request

from .config import ROOT

CDP = "http://127.0.0.1:9333"
import os as _os
# PC: data/pc (data/campaigns is overwritten by each pull). Cloud (18 Nov, logged-in jobs moved there): data/state,
# which the memory bundle keeps, so each campaign is still checked at most every CHECK_EVERY_S.
SEEN = ROOT / "data" / ("state" if _os.environ.get("HOOKHOUSE_CLOUD") else "pc") / "footage_checked.json"
WATCH = ROOT / "data" / "pc" / "join_watch.json"         # campaigns opened on the PC for the owner to Join
CHECK_EVERY_S = 30 * 60
LOCKED = re.compile(r"visible once you join|join to unlock", re.I)
FOOTAGE = re.compile(r"(drive\.google\.com/(file/d/|open\?id=|uc\?|drive/(u/\d+/)?folders/)|dropbox\.com/|"
                     r"frame\.io/|//f\.io/|wetransfer\.com/|box\.com/s/|\.(mp4|mov|mkv|webm|m4v)(\?|$))", re.I)
NAV = re.compile(r"contentrewards\.com/(c/|$|[\w-]+/?$)|discord|twitter\.com|//(www\.)?x\.com/|instagram\.com|tiktok\.com|"
                 r"youtube\.com|youtu\.be|twitch\.tv|kick\.com|apple\.com|google\.com/(?!.*folders)(?!file)", re.I)

READ = r"""(() => {
  const t = document.body.innerText;
  const links = [...document.querySelectorAll('a[href]')].map(a => a.href);
  const urls = (t.match(/https?:\/\/[^\s)"'<>]+/g) || []);
  const i = t.indexOf('Reference materials');
  return JSON.stringify({text: t.slice(0, 20000), links: links.concat(urls), materials: i >= 0 ? t.slice(i, i + 3000) : ''});
})()"""


# ---------------- reading a page (read-only CDP, own tab) ----------------
def _cdp_json(path: str, method: str = "GET"):
    req = urllib.request.Request(CDP + path, method=method)
    return json.loads(urllib.request.urlopen(req, timeout=15).read() or b"null")


async def _eval(ws_url: str, expr: str):
    import websockets
    async with websockets.connect(ws_url, max_size=2 ** 24) as ws:
        await ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate",
                                  "params": {"expression": expr, "returnByValue": True}}))
        while True:
            msg = json.loads(await ws.recv())
            if msg.get("id") == 1:
                return (msg.get("result") or {}).get("result", {}).get("value")


def chrome_up() -> bool:
    try:
        _cdp_json("/json/version")
        return True
    except Exception:  # noqa: BLE001
        return False


LOADED = re.compile(r"Reference materials|\bBudget\b", re.I)
ENDED = re.compile(r"out of budget|campaign (has )?ended|no longer accepting|\bPaused\b", re.I)
DOC = re.compile(r"https://docs\.google\.com/document/d/([\w-]+)")
EPISODE = re.compile(r"https?://(www\.)?(youtube\.com/(watch|live|shorts)|youtu\.be/)\S+", re.I)


def read_page(url: str, wait_s: float = 30) -> dict:
    """Open the URL in a new tab of the automation Chrome, wait until the campaign has really loaded (17 Nov: a
    half-loaded page was taken for 'joined'), read text + links, close the tab."""
    tab = _cdp_json("/json/new?" + url, method="PUT")
    try:
        page, t0 = {}, time.time()
        while time.time() - t0 < wait_s:
            time.sleep(3)
            page = json.loads(asyncio.run(_eval(tab["webSocketDebuggerUrl"], READ)) or "{}")
            if LOADED.search(page.get("text") or ""):
                time.sleep(2)                          # the rest of the page settles
                page = json.loads(asyncio.run(_eval(tab["webSocketDebuggerUrl"], READ)) or "{}")
                page["loaded"] = True
                break
        return page
    finally:
        try:
            _cdp_json(f"/json/close/{tab['id']}")
        except Exception:  # noqa: BLE001
            pass


def doc_links(links: list[str]) -> tuple[list[str], str]:
    """Briefs are often a shared Google Doc holding the footage link: read its plain-text export (public docs only)."""
    import requests
    found, text = [], ""
    for doc_id in list(dict.fromkeys(m.group(1) for u in links for m in [DOC.search(u)] if m))[:3]:
        try:
            r = requests.get(f"https://docs.google.com/document/d/{doc_id}/export?format=txt", timeout=30)
        except requests.RequestException:
            continue
        if r.ok and "text/plain" in r.headers.get("content-type", ""):
            text += r.text[:6000] + "\n"
            found += re.findall(r"https?://[^\s)\]>\"']+", r.text)
    return found, text


def footage_links(page: dict) -> list[str]:
    out = []
    for u in page.get("links") or []:
        u = u.rstrip(".,;")
        if FOOTAGE.search(u) and not NAV.search(u) and u not in out:
            out.append(u)
    return out


def check(c: dict, reader=read_page, docs=doc_links) -> dict:
    """{'joined', 'ended', 'files', 'episodes', 'materials'} for one campaign page."""
    page = reader(c.get("url") or "")
    text = page.get("text") or ""
    if not text or "Sign in" in text[:400] and "HookHouse" not in text:
        return {"joined": False, "error": "not signed in to Content Rewards in the PC browser"}
    if not page.get("loaded"):
        return {"joined": False, "error": "page did not finish loading"}
    ended = bool(ENDED.search(text))
    joined = not LOCKED.search(text) and "Join Campaign" not in text
    out = {"joined": joined, "ended": ended, "files": [], "episodes": [],
           "materials": (page.get("materials") or "")[:1500]}
    if joined:
        extra, brief = docs(page.get("links") or [])
        allp = dict(page, links=(page.get("links") or []) + extra)
        from .campaign_rules import parse
        out["rules"] = parse((page.get("materials") or "") + "\n" + brief, allp["links"])
        out["files"] = footage_links(allp)
        out["episodes"] = list(dict.fromkeys(m.group(0).rstrip(".,;") for u in allp["links"] for m in [EPISODE.search(u)] if m))[:5]
        out["brief"] = brief[:3000]
    return out


# ---------------- PC side ----------------
def watched() -> list[dict]:
    try:
        return json.loads(WATCH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def _seen() -> dict:
    try:
        return json.loads(SEEN.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def pc_job(store, log=print, reader=read_page) -> int:
    """For every picked (not yet joined) Content Rewards campaign: once the owner has joined, send its footage links."""
    from . import db
    from .cloud import media
    if not chrome_up():
        return 0
    seen, n = _seen(), 0
    picked = {c["id"]: c for c in db.list_campaigns(db.connect(), "picked")}
    joined = {c["id"] for c in db.list_campaigns(db.connect(), "joined")}
    for c in watched():
        if c["id"] not in joined:
            picked.setdefault(c["id"], c)
    for c in picked.values():
        if "contentrewards.com" not in str(c.get("url")) or time.time() - seen.get(c["id"], 0) < CHECK_EVERY_S:
            continue
        seen[c["id"]] = time.time()
        try:
            r = check(c, reader)
        except Exception as e:  # noqa: BLE001 - one page must not stop the rest
            log(f"campaign {c['id']}: {type(e).__name__}: {e}")
            continue
        if r.get("joined"):
            r["files"] = _frameio_to_assets(store, c["id"], r.get("files") or [], log)
        if r.get("joined") or r.get("ended"):
            store.put(media.TAG, f"camp-{c['id']}.json", json.dumps({"id": c["id"], **r}).encode())
            log(f"campaign {c.get('name', '')[:40]}: {'ended' if r.get('ended') else 'joined'}, "
                f"{len(r['files'])} footage link(s), {len(r['episodes'])} episode page(s)")
            n += 1
    SEEN.parent.mkdir(parents=True, exist_ok=True)
    SEEN.write_text(json.dumps(seen), encoding="utf-8")
    return n


FRAMEIO = re.compile(r"(//f\.io/|frame\.io/)", re.I)


def _frameio_to_assets(store, campaign_id: str, links: list[str], log=print, per_share: int = 3) -> list[str]:
    """Frame.io shares need a browser: the PC saves a few vertical videos and puts them in cloud storage
    ("asset:<name>" sources the cloud clip maker can read). Other links pass through unchanged."""
    from . import frameio
    from .cloud import media
    out = []
    for u in links:
        if not FRAMEIO.search(u):
            out.append(u)
            continue
        try:
            files = frameio.download(u, ROOT / "data" / "pc" / "footage" / campaign_id, limit=per_share, log=log)
        except Exception as e:  # noqa: BLE001
            log(f"  frame.io {u}: {e}")
            continue
        for f in files:
            name = f"src-{campaign_id[:30]}-{f.name}"
            store.put(media.TAG, name, f.read_bytes(), "video/mp4")
            out.append(f"asset:{name}")
    return out


# ---------------- cloud side ----------------
def add_sources(campaign_id: str, links: list[str]) -> int:
    from . import clips, weekly
    files = []
    for u in links:
        if u.startswith("asset:"):
            files.append(u)
            continue
        try:
            files += clips.expand_source(u)
        except Exception:  # noqa: BLE001 - a private folder: the owner gets the /source hint
            continue
    have = {s["source"] for s in weekly._read_sources()}
    new = [u for u in dict.fromkeys(files) if u not in have and not clips.DRIVE_FOLDER.search(u)]
    if new:
        weekly.CLIP_SOURCES.parent.mkdir(parents=True, exist_ok=True)
        with weekly.CLIP_SOURCES.open("a", encoding="utf-8") as fh:
            fh.writelines(f"{u} {campaign_id}\n" for u in new)
    return len(new)


def recover_sources(store, log=print) -> int:
    """Campaign footage the PC already put in cloud storage (src-<campaign id[:30]>-<file>) back into the clip source
    list. 18 Nov: data/clip_sources.txt was not kept between cloud runs, so the SEGA and Wa-Chaa footage fetched on
    17 Nov was forgotten right after it was added. Safe to run every tick: only missing lines are added."""
    from . import db
    from .cloud import media
    names = [x for x in store.assets(media.TAG) if x.startswith("src-") and x.endswith(".mp4")]
    if not names:
        return 0
    conn = db.connect()
    camps = [c for s in ("joined", "picked") for c in db.list_campaigns(conn, s)]
    n = 0
    for name in names:
        c = next((c for c in camps if name.startswith(f"src-{c['id'][:30]}-")), None)
        if c:
            n += add_sources(c["id"], [f"asset:{name}"])
    if n:
        log(f"campaign footage: {n} file(s) back in the clip list")
    return n


def merge(store, log=print, send=None) -> int:
    """Cloud tick: campaigns the PC found joined -> status joined + footage queued for clips + one owner message."""
    from . import db
    from .cloud import media
    if send is None:
        from .telegram_bot import send
    conn, n = db.connect(), 0
    for name in [x for x in store.assets(media.TAG) if x.startswith("camp-") and x.endswith(".json")]:
        try:
            info = json.loads(store.get(media.TAG, name) or b"{}")
            c = db.get_campaign(conn, info.get("id", ""))
            if not c:
                continue
            if info.get("rules_only"):                 # brand rules for an already-joined campaign: no message
                rules = info.get("rules") or {}
                c["required_tags"] = list(dict.fromkeys((c.get("required_tags") or []) + rules.get("required_tags", [])))
                for k in ("disclosure_text", "needs_logo", "logo_urls"):
                    if rules.get(k):
                        c[k] = rules[k]
                db.save_campaign(conn, c)
                n += 1
                continue
            if info.get("ended"):                      # paused / out of budget: views would not be paid
                c["status"] = "ended"
                db.save_campaign(conn, c)
                send(f"⏸️ {c.get('name', '')[:60]}: the campaign is paused or out of budget, so I won't clip it. "
                     "Pick another with /campaigns.")
                n += 1
                continue
            c["status"], c["joined_at"] = "joined", time.time()
            c["materials"] = info.get("materials", "")
            c["brief"] = info.get("brief", "")
            rules = info.get("rules") or {}
            if rules:                                  # brand rules the clips must follow (tags, Ad label, logo)
                c["required_tags"] = list(dict.fromkeys((c.get("required_tags") or []) + rules.get("required_tags", [])))
                for k in ("disclosure_text", "needs_logo", "logo_urls"):
                    if rules.get(k):
                        c[k] = rules[k]
            c["episode_pages"] = info.get("episodes") or []
            db.save_campaign(conn, c)
            added = add_sources(c["id"], info.get("files") or [])
            if not added and c["episode_pages"]:
                send(f"⚠️ {c.get('name', '')[:60]}: joined ✅. Its footage is a YouTube episode, which I never download "
                     "(YouTube's rules). Ask the campaign in its Discord/chat for the source file (Google Drive), then "
                     "send it here with /source <link>.")
            elif added:
                send(f"📥 {c.get('name', '')[:60]}: joined ✅, {added} footage file(s) found. Clips are being made; "
                     "you'll get each one to approve.")
            else:
                send(f"⚠️ {c.get('name', '')[:60]}: joined ✅ but I couldn't find a downloadable footage link on the "
                     "page. Open the campaign's Reference materials and send the link here with /source <link>.")
            n += 1
        finally:
            store.delete(media.TAG, name)
    return n
