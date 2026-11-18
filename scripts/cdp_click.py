"""Click on the visible HookHouse Chrome tab: by visible text (first match) or by x,y.
python -m scripts.cdp_click "3 options selected"     |     python -m scripts.cdp_click 760 272"""
import asyncio
import json
import sys
import urllib.request

import websockets


async def main(args):
    tab = [t for t in json.loads(urllib.request.urlopen("http://127.0.0.1:9333/json/list").read())
           if t["type"] == "page"][0]
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
        if len(args) == 2 and all(a.replace(".", "").isdigit() for a in args):
            xy = [float(args[0]), float(args[1])]
        else:
            text = json.dumps(args[0])
            r = await cmd("Runtime.evaluate", {"returnByValue": True, "expression":
                f'(() => {{ const want = {text}; const els = [...document.querySelectorAll("body *")]'
                '.filter(e => e.children.length === 0 && (e.innerText || "").trim() === want);'
                ' const e = els.find(x => x.getBoundingClientRect().width > 0); if (!e) return null;'
                ' e.scrollIntoView({block: "center"}); const b = e.getBoundingClientRect();'
                ' return [b.x + b.width / 2, b.y + b.height / 2]; })()'})
            xy = (r.get("result") or {}).get("value")
        if not xy:
            print("not found:", args)
            return
        for t in ("mouseMoved", "mousePressed", "mouseReleased"):
            await cmd("Input.dispatchMouseEvent", {"type": t, "x": xy[0], "y": xy[1], "button": "left", "clickCount": 1})
        print("clicked", xy)


asyncio.run(main(sys.argv[1:]))
