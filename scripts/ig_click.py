"""Click a button by exact text (scrolls it into view, real mouse click) in the Instagram sign-up window; or type into
the search box. python -m scripts.ig_click "Next"    |    python -m scripts.ig_click --type "Digital creator"
Prints the first lines of the page afterwards."""
import asyncio
import json
import sys
import time
import urllib.request

import websockets

from engine.config import ROOT

CDP = "http://127.0.0.1:9333"
tid = (ROOT / "data" / "pc" / "ig_signup_tab.txt").read_text().strip()


async def main(args):
    t = next(t for t in json.loads(urllib.request.urlopen(f"{CDP}/json/list").read()) if t["id"] == tid)
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
        if args[0] == "--type":
            ok = await js(r'''((v) => { const i = [...document.querySelectorAll("input")].find(x => x.offsetParent && x.type !== "hidden");
              if (!i) return "no input"; i.focus(); Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(i, v);
              i.dispatchEvent(new Event("input", {bubbles: true})); return "typed"; })(%s)''' % json.dumps(args[1]))
            print(ok)
        else:
            label = args[0]
            find = (r'''((l) => { const b = [...document.querySelectorAll("button,div[role=button],div[role=radio],label,span")]'''
                    r'''.filter(e => e.offsetParent && (e.innerText || "").trim() === l).pop(); if (!b) return null;'''
                    r''' b.scrollIntoView({block: "center"}); const r = b.getBoundingClientRect();'''
                    r''' return [r.x + r.width / 2, r.y + r.height / 2]; })(%s)''' % json.dumps(label))
            xy = await js(find)
            if not xy:
                print("not found:", label)
            else:
                time.sleep(0.8)
                xy = await js(find)
                for tt in ("mouseMoved", "mousePressed", "mouseReleased"):
                    await cmd("Input.dispatchMouseEvent", {"type": tt, "x": xy[0], "y": xy[1], "button": "left",
                                                           "clickCount": 1})
                print("clicked:", label)
        time.sleep(5)
        x = await js("document.body.innerText") or ""
        lines = [l for l in x.split("\n") if l.strip()]
        cut = next((k for k, l in enumerate(lines) if l == "Meta"), len(lines))
        sys.stdout.buffer.write((" | ".join(lines[:cut])[:500] + "\n").encode("utf-8"))


asyncio.run(main(sys.argv[1:]))
