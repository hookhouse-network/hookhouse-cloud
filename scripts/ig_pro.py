"""Take the Instagram account in the sign-up window (data/pc/ig_signup_tab.txt) through "Switch to professional":
Creator -> Next -> Next -> category "Personal blog" (hidden on the profile) -> Done. It STOPS at Instagram's
"Switch to a professional profile?" Continue: the owner taps that (consent). Real mouse clicks, each step verified.
python -m scripts.ig_pro"""
import asyncio
import base64
import json
import urllib.request

import websockets

from engine.config import ROOT

CDP = "http://127.0.0.1:9333"
TID = (ROOT / "data" / "pc" / "ig_signup_tab.txt").read_text().strip()
SHOT = ROOT / "data" / "review" / "cdp_shot.png"
LEAF = '[...document.querySelectorAll("*")].filter(e => e.children.length === 0 && (e.textContent || "").trim() === %s)[0]'
BTN = '[...document.querySelectorAll("button,div[role=button]")].find(e => (e.innerText || "").trim() === %s)'


async def main():
    t = next(t for t in json.loads(urllib.request.urlopen(f"{CDP}/json/list").read()) if t["id"] == TID)
    async with websockets.connect(t["webSocketDebuggerUrl"], max_size=2 ** 26) as ws:
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

        async def click(sel):
            pos = '(() => { const e = %s; if (!e) return null; e.scrollIntoView({block: "center"}); ' \
                  'const r = e.getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; })()' % sel
            for _ in range(10):
                if await js(pos):
                    break
                await asyncio.sleep(1.5)
            else:
                return False
            await asyncio.sleep(0.8)
            x, y = await js(pos)
            for tt in ("mouseMoved", "mousePressed", "mouseReleased"):
                await cmd("Input.dispatchMouseEvent", {"type": tt, "x": x, "y": y, "button": "left", "clickCount": 1})
            return True

        async def radios():
            return await js('[...document.querySelectorAll("input[type=radio]")].map(r => r.checked)') or []

        async def heading():
            return (await js('(document.querySelector("h1,h2,span[dir=auto]") || {}).innerText || ""')
                    or "") + " / " + (await js('document.body.innerText.slice(0, 60).replace(/\\n/g, " ")') or "")

        await cmd("Page.navigate", {"url": "https://www.instagram.com/accounts/convert_to_professional_account/"})
        await asyncio.sleep(8)
        steps = [("Creator", LEAF, lambda r: bool(r) and r[0]), ("Next", BTN, None), ("Next", BTN, None),
                 ("Personal blog", LEAF, lambda r: any(r)), ("Done", BTN, None)]
        for label, kind, check in steps:
            ok = False
            for _ in range(3):
                if not await click(kind % json.dumps(label)):
                    break
                await asyncio.sleep(3)
                ok = check(await radios()) if check else True
                if ok:
                    break
            print(f"{label}: {'ok' if ok else 'FAILED'}")
            if not ok:
                break
            await asyncio.sleep(3)
        await asyncio.sleep(4)
        await cmd("Page.bringToFront")
        SHOT.write_bytes(base64.b64decode((await cmd("Page.captureScreenshot", {"format": "png"}))["data"]))
        seen = await js('[...document.querySelectorAll("button,div[role=button],div[role=dialog] *")]'
                        '.some(e => (e.innerText || "").trim() === "Continue")')
        print("waiting for the owner:", "press Continue" if seen else "(no Continue dialog seen: look at the screenshot)")


asyncio.run(asyncio.wait_for(main(), 150))
