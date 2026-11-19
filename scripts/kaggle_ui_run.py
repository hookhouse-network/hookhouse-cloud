"""Start the hookhouse-gpu notebook from Kaggle's own website (Save Version > Save & Run All), because Kaggle gives
notebook secrets (HF_TOKEN) only to website-started runs, not to `kaggle kernels push` runs (19 Nov).
python -m scripts.kaggle_ui_run"""
import asyncio
import json
import time
import urllib.request

import websockets

CDP = "http://127.0.0.1:9333"


async def main():
    tabs = [t for t in json.loads(urllib.request.urlopen(f"{CDP}/json/list").read())
            if t["type"] == "page" and "hookhouse-gpu/edit" in t["url"]]
    if not tabs:
        print("open https://www.kaggle.com/code/hookhousemedia/hookhouse-gpu/edit first")
        return
    for extra in tabs[1:]:
        urllib.request.urlopen(f"{CDP}/json/close/{extra['id']}")
    async with websockets.connect(tabs[0]["webSocketDebuggerUrl"], max_size=2 ** 24) as ws:
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

        async def click(where_js):
            xy = await js(where_js)
            if not xy:
                return False
            for k in ("mouseMoved", "mousePressed", "mouseReleased"):
                await cmd("Input.dispatchMouseEvent", {"type": k, "x": xy[0], "y": xy[1], "button": "left", "clickCount": 1})
            return True
        await cmd("Page.bringToFront")
        btn = ('((rx, inDialog) => { const root = inDialog ? [...document.querySelectorAll("[role=dialog]")].pop() : document; if (!root)'
               ' return null; const b = [...root.querySelectorAll("button,[role=button],label")].filter(e => new RegExp(rx, "i").test('
               '(e.innerText || "").trim()) && e.getBoundingClientRect().width > 0).pop(); if (!b) return null; const r ='
               ' b.getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; })(%s, %s)')
        if not await click(btn % (json.dumps("Save Version"), "false")):
            print("Save Version button not found")
            return
        time.sleep(3)
        dialog = (await js('([...document.querySelectorAll("[role=dialog]")].pop() || {}).innerText || ""') or "")
        print("dialog:", dialog[:200].replace("\n", " / "))
        await click(btn % (json.dumps("Save & Run All"), "true"))         # the commit option (runs every cell)
        time.sleep(1)
        ok = await click(btn % (json.dumps("^Save$"), "true"))
        time.sleep(5)
        print("started from the website:", ok)

if __name__ == "__main__":
    asyncio.run(main())

