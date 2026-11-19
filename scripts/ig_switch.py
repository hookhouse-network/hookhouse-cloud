"""Open Instagram's 'Switch' login box (visible HookHouse Chrome) with the username filled in; the owner types the
password. python -m scripts.ig_switch <instagram username>"""
import asyncio
import json
import sys
import time
import urllib.request

import websockets


async def main(user):
    tab = next(t for t in json.loads(urllib.request.urlopen("http://127.0.0.1:9333/json/list").read())
               if t["type"] == "page" and "instagram.com" in t["url"])
    async with websockets.connect(tab["webSocketDebuggerUrl"], max_size=2 ** 24) as ws:
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
            for t in ("mouseMoved", "mousePressed", "mouseReleased"):
                await cmd("Input.dispatchMouseEvent", {"type": t, "x": xy[0], "y": xy[1], "button": "left",
                                                       "clickCount": 1})
        await cmd("Page.bringToFront")
        await cmd("Page.navigate", {"url": "https://www.instagram.com/"})
        time.sleep(9)
        xy = await js('(() => { const e = [...document.querySelectorAll("a,div[role=button],span,button")].filter(x => '
                      '/^Switch$/i.test((x.innerText || "").trim()) && x.getBoundingClientRect().width > 0).pop();'
                      ' if (!e) return null; const b = e.getBoundingClientRect(); return [b.x + b.width / 2, b.y + b.height / 2]; })()')
        if not xy:
            print("no Switch link on the home page")
            return
        await click(xy)
        time.sleep(5)
        xy = await js('(() => { const d = document.querySelector("[role=dialog]"); const i = d && d.querySelector('
                      '"input[name=username], input[type=text]"); if (!i) return null; const b = i.getBoundingClientRect();'
                      ' return [b.x + 20, b.y + b.height / 2]; })()')
        if not xy:
            print("the switch box did not open")
            return
        await click(xy)
        await cmd("Input.insertText", {"text": user})
        got = await js('(() => { const d = document.querySelector("[role=dialog]"); d.querySelector("input[type=password]")'
                       '.focus(); return d.querySelector("input[name=username], input[type=text]").value; })()')
        print("username box:", got)


asyncio.run(main(sys.argv[1]))
