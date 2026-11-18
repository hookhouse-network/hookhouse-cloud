"""Press "Create Page" on every filled 'Create a Page' tab (owner, 18 Nov: "you can do all the things"), then walk the
setup steps that follow (Next / Skip / Done) and report the new Page URL. python -m scripts.fb_page_create"""
import asyncio
import json
import time
import urllib.request

import websockets

CDP = "http://127.0.0.1:9333"


async def run(tab):
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

        async def press(labels):
            xy = await js('(() => { const want = %s; const b = [...document.querySelectorAll("div[role=button],'
                          'button,a[role=button]")].find(e => want.includes((e.innerText || "").trim()) && '
                          'e.getAttribute("aria-disabled") !== "true" && e.getBoundingClientRect().width > 0);'
                          ' if (!b) return null; b.scrollIntoView({block: "center"}); const r = b.getBoundingClientRect();'
                          ' return [r.x + r.width / 2, r.y + r.height / 2, (b.innerText || "").trim()]; })()'
                          % json.dumps(labels))
            if not xy:
                return None
            for t in ("mouseMoved", "mousePressed", "mouseReleased"):
                await cmd("Input.dispatchMouseEvent", {"type": t, "x": xy[0], "y": xy[1], "button": "left",
                                                       "clickCount": 1})
            return xy[2]
        await cmd("Page.bringToFront")
        name = await js('(() => { const e = [...document.querySelectorAll("input")].find(x => (x.closest("label") ? '
                        'x.closest("label").innerText : "").startsWith("Page name")); return e ? e.value : ""; })()')
        if not name:
            return None
        if not await press(["Create Page"]):
            return name, "Create Page button not ready"
        time.sleep(10)
        steps = []
        for _ in range(8):                                 # the 'finish setting up' wizard
            got = await press(["Next", "Skip", "Done", "Not now", "Continue"])
            if not got:
                break
            steps.append(got)
            time.sleep(5)
        url = await js("location.href")
        return name, f"created -> {url[:80]} (steps: {', '.join(steps) or 'none'})"


async def main():
    tabs = [t for t in json.loads(urllib.request.urlopen(f"{CDP}/json/list").read())
            if t["type"] == "page" and "pages/creation" in t["url"]]
    for t in tabs:
        r = await run(t)
        if r:
            print(f"{r[0]}: {r[1]}")


asyncio.run(main())
