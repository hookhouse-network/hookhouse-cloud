"""Facebook (visible HookHouse Chrome): stop acting as a Page and switch back to the personal profile through the account
menu (top right). python -m scripts.fb_switch_personal"""
import asyncio
import json
import time
import urllib.request

import websockets

CDP = "http://127.0.0.1:9333"


async def main():
    t = next(t for t in json.loads(urllib.request.urlopen(f"{CDP}/json/list").read()) if t["type"] == "page"
             and "facebook.com" in t["url"] and "developers" not in t["url"] and "pages/creation" not in t["url"])
    async with websockets.connect(t["webSocketDebuggerUrl"], max_size=2 ** 24) as ws:
        n = 0

        async def cmd(m, p=None):
            nonlocal n
            n += 1
            await ws.send(json.dumps({"id": n, "method": m, "params": p or {}}))
            while True:
                r = json.loads(await ws.recv())
                if r.get("id") == n:
                    return r.get("result", {})

        async def js(e):
            return (await cmd("Runtime.evaluate", {"expression": e, "returnByValue": True})).get("result", {}).get("value")

        async def click(xy):
            for k in ("mouseMoved", "mousePressed", "mouseReleased"):
                await cmd("Input.dispatchMouseEvent", {"type": k, "x": xy[0], "y": xy[1], "button": "left", "clickCount": 1})
        await cmd("Page.bringToFront")
        await cmd("Page.navigate", {"url": "https://www.facebook.com/"})
        time.sleep(10)
        xy = await js('(() => { const b = [...document.querySelectorAll("[aria-label]")].find(e => /^Your profile$/i'
                      '.test(e.getAttribute("aria-label")) && e.getBoundingClientRect().width > 0); if (!b) return null;'
                      ' const r = b.getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; })()')
        if not xy:
            print("account menu not found")
            return
        await click(xy)
        time.sleep(3)
        items = await js('[...document.querySelectorAll("[role=dialog] [role=button], [role=dialog] a, [role=menu] [role=button],'
                         ' [role=dialog] [role=listitem], [role=dialog] div[tabindex]")].map(e => (e.innerText || "").trim())'
                         '.filter(t => t && t.length < 60)')
        print("menu:", [i.replace("\n", " / ") for i in (items or [])][:15])
        # the first profile entry in the switcher that is NOT a known Page = the personal profile
        pages = ("Brain Snack", "Clutch Tales", "Hot Take HQ", "Deep Blue Files", "Stream Clips", "Creepy Case Club")
        xy = await js('((pages) => { const els = [...document.querySelectorAll("[role=dialog] [role=button], [role=dialog] '
                      'div[role=listitem], [role=dialog] a")].filter(e => e.getBoundingClientRect().width > 0);'
                      ' const e = els.find(x => { const t = (x.innerText || "").trim(); return t && !pages.some(p => '
                      't.startsWith(p)) && /^[A-Z][a-z]+ [A-Z][a-z]+$/.test(t.split("\\n")[0]); });'
                      ' if (!e) return null; const r = e.getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2,'
                      ' (e.innerText || "").split("\\n")[0]]; })(%s)' % json.dumps(pages))
        if not xy:
            print("personal profile entry not found in the menu")
            return
        await click(xy)
        time.sleep(14)
        print("switched to the personal profile")

if __name__ == "__main__":
    asyncio.run(main())
