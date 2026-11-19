"""Instagram 'Check your email - enter the code' page (auth_platform/codeentry) in any HookHouse Chrome window: reads the
newest Instagram code from the HookHouse Gmail and types it (real keystrokes), then Continue.
python -m scripts.ig_code_entry"""
import asyncio
import json
import time
import urllib.request

import websockets

from scripts.ig_signup_finish import gmail_code

CDP = "http://127.0.0.1:9333"


async def main():
    t = next((t for t in json.loads(urllib.request.urlopen(f"{CDP}/json/list").read())
              if t["type"] == "page" and "auth_platform/codeentry" in t["url"]), None)
    if not t:
        print("no code-entry page open")
        return
    code = await gmail_code("", time.time() - 0)
    if not code:
        print("no Instagram code in Gmail (last 15 minutes)")
        return
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
        xy = await js('(() => { const e = [...document.querySelectorAll("input")].find(i => i.offsetParent !== null && '
                      'i.type !== "hidden"); if (!e) return null; e.scrollIntoView({block: "center"}); const r = '
                      'e.getBoundingClientRect(); return [r.x + 12, r.y + r.height / 2]; })()')
        if not xy:
            print("code box not found")
            return
        await click(xy)
        for ch in code:
            await cmd("Input.dispatchKeyEvent", {"type": "keyDown", "key": ch, "text": ch})
            await cmd("Input.dispatchKeyEvent", {"type": "keyUp", "key": ch})
            time.sleep(0.08)
        time.sleep(1)
        bxy = await js('(() => { const b = [...document.querySelectorAll("button,div[role=button]")].filter(e => /^(continue|'
                       'confirm|submit|next)$/i.test((e.innerText || "").trim()) && e.getBoundingClientRect().width > 0).pop();'
                       ' if (!b) return null; const r = b.getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; })()')
        if bxy:
            await click(bxy)
        time.sleep(10)
        print("code entered; page now:", (await js("location.pathname")) or "")

if __name__ == "__main__":
    asyncio.run(main())
