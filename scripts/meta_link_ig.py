"""Link a channel's Instagram account to its Facebook Page (the link Meta needs for Instagram insights and Page-based
publishing), all in the visible HookHouse Chrome, no password typed (owner 19 Nov: "do these all by yourself"):
1. Instagram (default browser profile): switch to the channel's account if it is among the saved logins;
2. Facebook: act as the channel's Page, Settings > Linked accounts > Instagram > Connect account > Connect >
   Continue > "Log in as <handle>" > Add to the business portfolio; then read back "Connected Instagram".
python -m scripts.meta_link_ig <channel_id> [...]"""
import asyncio
import json
import sys
import time
import urllib.request

import websockets

from engine.config import ROOT
from engine.links import data as links

CDP = "http://127.0.0.1:9333"


def tabs():
    return [t for t in json.loads(urllib.request.urlopen(f"{CDP}/json/list").read()) if t["type"] == "page"]


class Tab:
    def __init__(self, t):
        self.t, self.n = t, 0

    async def __aenter__(self):
        self.ws = await websockets.connect(self.t["webSocketDebuggerUrl"], max_size=2 ** 24)
        return self

    async def __aexit__(self, *a):
        await self.ws.close()

    async def cmd(self, m, p=None):
        self.n += 1
        await self.ws.send(json.dumps({"id": self.n, "method": m, "params": p or {}}))
        while True:
            r = json.loads(await self.ws.recv())
            if r.get("id") == self.n:
                return r.get("result", {})

    async def js(self, e):
        return (await self.cmd("Runtime.evaluate", {"expression": e, "returnByValue": True})).get("result", {}).get("value")

    async def go(self, url, wait=10):
        await self.cmd("Page.navigate", {"url": url})
        time.sleep(wait)

    async def click_text(self, text, scope="document", exact=True):
        q = (r'''((want) => { const root = %s; if (!root) return null; const b = [...root.querySelectorAll(
          "[role=button],button,a,div,span")].filter(e => { const t = (e.innerText || "").trim();
          return (%s) && e.getBoundingClientRect().width > 0; }).pop(); if (!b) return null;
          b.scrollIntoView({block: "center"}); const r = b.getBoundingClientRect();
          return [r.x + r.width / 2, r.y + r.height / 2]; })(%s)'''
             % (scope, "t === want" if exact else "t.startsWith(want)", json.dumps(text)))
        await self.js(q)
        time.sleep(0.5)
        xy = await self.js(q)
        if not xy:
            return False
        await self.cmd("Page.bringToFront")
        for t in ("mouseMoved", "mousePressed", "mouseReleased"):
            await self.cmd("Input.dispatchMouseEvent", {"type": t, "x": xy[0], "y": xy[1], "button": "left",
                                                        "clickCount": 1})
        return True


DIALOG = ('[...document.querySelectorAll("[role=dialog]")].filter(e => e.getBoundingClientRect().width > 0)'
          '.pop()')


async def ig_switch(handle: str) -> str:
    t = next((t for t in tabs() if t["url"].startswith("https://www.instagram.com/") and "oauth" not in t["url"]
              and t["id"] not in _private_ig()), None)
    if t is None:
        req = urllib.request.Request(f"{CDP}/json/new?https://www.instagram.com/", method="PUT")
        t = json.loads(urllib.request.urlopen(req).read())
        time.sleep(8)
    async with Tab(t) as tab:
        await tab.go("https://www.instagram.com/", 9)
        me = await tab.js('[...document.querySelectorAll("a[href]")].map(a => a.getAttribute("href"))'
                          '.filter(h => /^\\/[a-z0-9._]+\\/$/.test(h)).filter(h => !/reels|explore/.test(h))[0] || ""')
        if me.strip("/") == handle:
            return "already"
        if not await tab.click_text("Switch"):
            return "no Switch button"
        time.sleep(3)
        if not await tab.click_text(handle, DIALOG):
            return "not among the saved logins (needs its password once)"
        time.sleep(10)
        return "switched"


def _private_ig() -> set:
    """Tabs of the private Instagram windows made by ig_signup (other browser contexts)."""
    p = ROOT / "data" / "pc" / "ig_signup_tab.txt"
    try:
        return {p.read_text(encoding="utf-8").strip()}
    except OSError:
        return set()


async def fb_link(page_id: str, handle: str) -> str:
    t = next((t for t in tabs() if "facebook.com" in t["url"] and "developers" not in t["url"]
              and "pages/creation" not in t["url"] and "oauth" not in t["url"]), None)
    if t is None:
        req = urllib.request.Request(f"{CDP}/json/new?https://www.facebook.com/", method="PUT")
        t = json.loads(urllib.request.urlopen(req).read())
        time.sleep(6)
    async with Tab(t) as tab:
        await tab.go(f"https://www.facebook.com/profile.php?id={page_id}", 10)
        # personal profile: "Switch Now"; while acting as another Page the same control is just "Switch"
        if await tab.click_text("Switch Now") or await tab.click_text("Switch"):
            time.sleep(14)
        await tab.go("https://www.facebook.com/settings/?tab=linked_instagram", 12)
        body = await tab.js('(document.querySelector("[role=main]") || document.body).innerText')
        if "Connected Instagram" in (body or ""):
            if f"@{handle}" in body:
                return "already linked"
            return "acting as another Page (it shows a different Instagram): switch failed, nothing changed"
        if not await tab.click_text("Connect account"):
            return "no 'Connect account' button (not acting as the Page?)"
        time.sleep(4)
        before = {x["id"] for x in tabs()}
        for step in ("Connect", "Continue"):
            if not await tab.click_text(step, DIALOG):
                return f"dialog step '{step}' not found"
            time.sleep(5)
        pop = None
        for _ in range(10):
            pop = next((x for x in tabs() if x["id"] not in before and "instagram.com/oauth" in x["url"]), None)
            if pop:
                break
            time.sleep(1)
        if not pop:
            return "Instagram login window did not open"
        time.sleep(3)
        async with Tab(pop) as p:
            txt = await p.js("document.body.innerText") or ""
            if f"Log in as {handle}" not in txt:
                return f"Instagram window offers another account: {txt[:80]!r}"
            await p.click_text(f"Log in as {handle}")
        time.sleep(8)
        if await tab.click_text("Add", DIALOG):
            time.sleep(8)
        await tab.cmd("Page.reload")
        time.sleep(10)
        body = await tab.js('(document.querySelector("[role=main]") || document.body).innerText') or ""
        return "LINKED" if ("Connected Instagram" in body and handle in body) else f"not confirmed: {body[:120]!r}"


async def main():
    for cid in sys.argv[1:]:
        handle = str((links().get(cid) or {}).get("instagram") or "").lstrip("@")
        sec = ROOT / "data" / "secrets" / f"meta_{cid}.json"
        page = json.loads(sec.read_text(encoding="utf-8")).get("page_id") if sec.exists() else None
        if not (handle and page):
            print(f"{cid}: needs an Instagram handle and a connected Facebook Page first")
            continue
        sw = await ig_switch(handle)
        if sw not in ("already", "switched"):
            print(f"{cid}: Instagram {sw}")
            continue
        print(f"{cid}: Instagram @{handle} {sw}; Page: {await fb_link(page, handle)}", flush=True)

if __name__ == "__main__":
    asyncio.run(main())
