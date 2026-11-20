"""Kick clips for clipping campaigns (owner 20 Nov 2026: "we need clipping to work because that is our main agenda").

Why Kick: the GTA 6 campaigns only point at streams (no files). Twitch lets only the streamer download clips and YouTube
offers no download; Kick's own Help Center says "All Clips can be downloaded when viewed ... Click the button labelled
Download ... .mp4", and Kick's Terms (2.1) give every user a licence to "use, reproduce, distribute, display and
perform such User Content as permitted through the functionality of the Service". The campaign brief is the
streamer's permission to post edits commercially.

PC only, the headless HookHouse Chrome (port 9333), the way a viewer uses the site: open the channel's Clips tab, set
the page's own filter (time) and sort (views), read the cards, open a clip, press its Download button. No internal
APIs, no stream rippers, no sign-in.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

CDP = "http://127.0.0.1:9333"
SLUG = re.compile(r"kick\.com/([A-Za-z0-9_-]{2,40})(?:[/?#]|$)", re.I)
NOT_CHANNELS = {"terms-of-service", "privacy-policy", "community-guidelines", "category", "categories", "browse",
                "help", "search", "following", "dashboard", "video", "clips"}
AGE = re.compile(r"(\d+|an?|one)\s+(second|minute|hour|day|week|month|year)s?\s+ago", re.I)
UNIT_S = {"second": 1, "minute": 60, "hour": 3600, "day": 86400, "week": 7 * 86400, "month": 30 * 86400,
          "year": 365 * 86400}

CARDS_JS = r"""(() => [...document.querySelectorAll('a[href*="/clips/clip_"]')].map(a => {
  let box = a; for (let i = 0; i < 6 && box.parentElement; i++) { box = box.parentElement;
    const t = box.innerText || ''; if (t.includes(' ago') && t.includes('views')) break; }
  return [a.href, (box.innerText || '').slice(0, 400)]; }))()"""


def channel_slugs(links: list[str]) -> list[str]:
    """Kick channel names among a campaign's links (kick.com/<name>)."""
    out = []
    for u in links:
        m = SLUG.search(u or "")
        if m and m.group(1).lower() not in NOT_CHANNELS:
            out.append(m.group(1).lower())
    return list(dict.fromkeys(out))


def age_s(text: str) -> float | None:
    m = AGE.search(text or "")
    if not m:
        return None
    n = 1 if m.group(1).lower() in ("a", "an", "one") else int(m.group(1))
    return n * UNIT_S[m.group(2).lower()]


def _views(text: str) -> float:
    m = re.search(r"([\d.,]+)\s*([KkMm]?)\s+views", text or "")
    if not m:
        return 0
    v = float(m.group(1).replace(",", ""))
    return v * {"k": 1e3, "m": 1e6}.get(m.group(2).lower(), 1)


def parse_cards(cards: list[list[str]], game: str = "", max_age_s: float = 3 * 86400, slug: str = "") -> list[dict]:
    """Card texts -> clips of the wanted game, newer than max_age_s, most viewed first."""
    out, seen = [], set()
    for href, text in cards:
        cid = href.rstrip("/").rsplit("/", 1)[-1]
        if cid in seen:
            continue
        seen.add(cid)
        age = age_s(text)
        if age is None or age > max_age_s or (game and game.lower() not in text.lower()):
            continue
        dur = re.search(r"\b(\d\d):(\d\d)\b", text)
        lines = [x.strip() for x in text.splitlines() if x.strip()]
        title = next((x for x in lines if not re.match(r"^[\d:.,KkMm ]+(views)?$", x) and "ago" not in x
                      and x.lower() not in (slug.lower(), game.lower()) and not x.lower().startswith(game.lower())), "")
        out.append({"id": cid, "url": href, "title": title[:100], "views": _views(text), "age_s": age,
                    "seconds": int(dur.group(1)) * 60 + int(dur.group(2)) if dur else 0})
    return sorted(out, key=lambda c: -c["views"])


# ---------------- browser (headless HookHouse Chrome) ----------------
class _Tab:
    def __init__(self, url: str):
        # /json/new?<url> cuts a URL at '&' and an encoded one becomes an unknown scheme (Windows "Pick an app"
        # pop-ups, 20 Nov): open a blank tab, then navigate to the full URL over the protocol
        self.url = url
        req = urllib.request.Request(f"{CDP}/json/new?about:blank", method="PUT")
        self.t = json.loads(urllib.request.urlopen(req, timeout=15).read())
        self.n = 0

    async def __aenter__(self):
        import websockets
        self.ws = await websockets.connect(self.t["webSocketDebuggerUrl"], max_size=2 ** 24)
        if self.url and self.url != "about:blank":
            await self.cmd("Page.navigate", {"url": self.url})
        return self

    async def __aexit__(self, *a):
        await self.ws.close()
        urllib.request.urlopen(f"{CDP}/json/close/{self.t['id']}", timeout=10)

    async def cmd(self, method: str, params: dict | None = None) -> dict:
        self.n += 1
        await self.ws.send(json.dumps({"id": self.n, "method": method, "params": params or {}}))
        while True:
            r = json.loads(await self.ws.recv())
            if r.get("id") == self.n:
                return r.get("result", {})

    async def js(self, expr: str):
        r = await self.cmd("Runtime.evaluate", {"expression": expr, "returnByValue": True})
        return r.get("result", {}).get("value")

    async def click_text(self, *labels: str) -> bool:
        """Real mouse click on the first visible button/menu item whose text is one of labels."""
        want = json.dumps([x.lower() for x in labels])
        xy = await self.js(f"""(() => {{ const want = {want};
          const el = [...document.querySelectorAll('button,[role=button],[role=menuitem],[role=option],li,a')].find(e => {{
            const t = ((e.innerText || '').trim() || e.getAttribute('aria-label') || e.title || '').trim().toLowerCase(); const r = e.getBoundingClientRect();
            return want.includes(t) && r.width > 0 && r.height > 0; }}) || [...document.querySelectorAll('*')].find(e => {{
            const t = (e.innerText || '').trim().toLowerCase(); const r = e.getBoundingClientRect();
            return want.includes(t) && e.children.length <= 1 && r.width > 0 && r.height > 0; }});
          if (!el) return null; el.scrollIntoView({{block: 'center'}}); const r = el.getBoundingClientRect();
          return [r.x + r.width / 2, r.y + r.height / 2]; }})()""")
        if not xy:
            return False
        for k in ("mouseMoved", "mousePressed", "mouseReleased"):
            await self.cmd("Input.dispatchMouseEvent", {"type": k, "x": xy[0], "y": xy[1], "button": "left",
                                                        "clickCount": 1})
        return True


async def _dismiss(tab) -> None:
    """New-account pop-ups (welcome-reward survey, cookie choices) cover the page; close them without answering."""
    xy = await tab.js("""(() => { const d = [...document.querySelectorAll('[role=dialog]')].find(x => /welcome reward|thrilled/i.test(x.innerText));
      if (!d) return null; const b = [...d.querySelectorAll('button')].find(x => (x.innerText || x.getAttribute('aria-label') || '').trim() === 'Close');
      if (!b) return null; const r = b.getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; })()""")
    if xy:
        for k in ("mouseMoved", "mousePressed", "mouseReleased"):
            await tab.cmd("Input.dispatchMouseEvent", {"type": k, "x": xy[0], "y": xy[1], "button": "left", "clickCount": 1})
        await asyncio.sleep(1.5)
        await tab.click_text("Exit anyways")
        await asyncio.sleep(1.5)
    await tab.click_text("Confirm My Choices")


async def _list(slug: str, game: str, max_age_s: float, period: tuple[str, ...]) -> list[dict]:
    async with _Tab(f"https://kick.com/{slug}/clips") as tab:
        await asyncio.sleep(12)
        await _dismiss(tab)                      # no "I am 18+" here: that is the live player's gate (swaps the list out)
        if await tab.click_text("All Time"):                       # the page's own time filter
            await asyncio.sleep(2)
            await tab.click_text(*period)
            await asyncio.sleep(6)
        cards = []
        for _ in range(4):                                         # a few screens of cards
            cards += await tab.js(CARDS_JS) or []
            await tab.js("window.scrollBy(0, 2500)")
            await asyncio.sleep(2.5)
    return parse_cards(cards, game, max_age_s, slug)


def top_clips(slug: str, game: str = "Grand Theft Auto VI", max_age_s: float = 3 * 86400,
              period: tuple[str, ...] = ("Last Week",)) -> list[dict]:
    return asyncio.run(_list(slug, game, max_age_s, period))


async def _download(url: str, dest: Path, wait_s: float) -> Path | None:
    dest.mkdir(parents=True, exist_ok=True)
    before = {p.name for p in dest.glob("*")}
    async with _Tab(url) as tab:
        await tab.cmd("Browser.setDownloadBehavior", {"behavior": "allow", "downloadPath": str(dest.resolve())})
        await asyncio.sleep(10)
        await _dismiss(tab)
        await tab.click_text("I am 18+")
        await asyncio.sleep(2)
        if not await tab.click_text("Download"):                   # Kick's own button (Help Center: Download KICK Clips)
            return None
        await asyncio.sleep(3)
        await tab.click_text("Download clip")                      # the dialog's confirm (viewers: with Kick watermark)
        t0 = time.time()
        while time.time() - t0 < wait_s:
            await asyncio.sleep(2)
            new = [p for p in dest.glob("*") if p.name not in before and not p.name.endswith(".crdownload")]
            if new and all(not (dest / (p.name + ".crdownload")).exists() for p in new):
                return max(new, key=lambda p: p.stat().st_mtime)
    return None


def download(clip: dict, dest: Path, wait_s: float = 90) -> Path | None:
    """Press Download on the clip's page; returns the saved .mp4 (renamed to the clip id) or None."""
    f = asyncio.run(_download(clip["url"], dest, wait_s))
    if f is None:
        return None
    out = dest / f"{clip['id']}.mp4"
    if f != out:
        f.replace(out)
    return out
