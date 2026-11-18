"""Fill Facebook's "Create a Page" form in a new tab of the visible HookHouse Chrome for each given channel id
(name, category Digital creator, bio). The OWNER presses "Create Page" (it accepts Facebook's Pages terms).
python -m scripts.fb_page_fill <channel_id> [<channel_id> ...]"""
import asyncio
import json
import sys
import time
import urllib.request

import websockets

from engine.config import channels

CDP = "http://127.0.0.1:9333"


def new_tab(url):
    req = urllib.request.Request(f"{CDP}/json/new?{url}", method="PUT")
    return json.loads(urllib.request.urlopen(req, timeout=15).read())


async def fill(tab, name, bio):
    async with websockets.connect(tab["webSocketDebuggerUrl"], max_size=2 ** 24) as ws:
        n = 0

        async def cmd(method, params=None):
            nonlocal n
            n += 1
            await ws.send(json.dumps({"id": n, "method": method, "params": params or {}}))
            while True:
                m = json.loads(await ws.recv())
                if m.get("id") == n:
                    return m.get("result", {})

        async def js(expr):
            r = await cmd("Runtime.evaluate", {"expression": expr, "returnByValue": True})
            return (r.get("result") or {}).get("value")

        async def click_field(label_regex):
            xy = await js('(() => { const rx = new RegExp(%s, "i"); const els = [...document.querySelectorAll('
                          '"input,textarea")].filter(e => rx.test((e.getAttribute("aria-label") || "") + " " + '
                          '(e.closest("label") ? e.closest("label").innerText : ""))); const e = els[0]; if (!e) '
                          'return null; e.scrollIntoView({block: "center"}); const b = e.getBoundingClientRect(); '
                          'return [b.x + b.width / 2, b.y + b.height / 2]; })()' % json.dumps(label_regex))
            if not xy:
                return False
            for t in ("mouseMoved", "mousePressed", "mouseReleased"):
                await cmd("Input.dispatchMouseEvent", {"type": t, "x": xy[0], "y": xy[1], "button": "left",
                                                       "clickCount": 1})
            time.sleep(0.5)
            return True

        for _ in range(20):                                  # wait for the form
            if await js('!!document.querySelector("input")'):
                break
            time.sleep(1)
        await cmd("Page.bringToFront")
        ok = await click_field("Page name")
        if ok:
            await cmd("Input.insertText", {"text": name})
        ok2 = await click_field("Category")
        if ok2:
            await cmd("Input.insertText", {"text": "Digital creator"})
            time.sleep(2.5)
            picked = await js('(() => { const o = [...document.querySelectorAll("[role=option],li,[role=listbox] *")]'
                              '.find(e => /^Digital creator$/i.test((e.innerText || "").trim())); if (!o) return false;'
                              ' o.click(); return true; })()')
        else:
            picked = False
        ok3 = await click_field("Bio")
        if ok3:
            await cmd("Input.insertText", {"text": bio})
        return {"name": ok, "category": bool(picked), "bio": ok3}


async def main(ids):
    chans = {c["id"]: c for c in channels()}
    for cid in ids:
        c = chans[cid]
        bio = (c.get("about") or "").split(". ")[0].strip().rstrip(".") + "."
        tab = new_tab("https://www.facebook.com/pages/creation/")
        time.sleep(4)
        print(c["name"], await fill(tab, c["name"], bio[:250]))


asyncio.run(main(sys.argv[1:]))
