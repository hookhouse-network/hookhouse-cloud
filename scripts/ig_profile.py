"""Instagram web, 'Edit profile' of the account logged in on the visible HookHouse Chrome: new bio (brand_art.BIOS)
and new profile picture (output/brand/<channel>/avatar.png). python -m scripts.ig_profile <channel_id>"""
import asyncio
import json
import sys
import time
import urllib.request

import websockets

from engine import brand_art

CDP = "http://127.0.0.1:9333"


async def main(cid):
    tab = next(t for t in json.loads(urllib.request.urlopen(f"{CDP}/json/list").read())
               if t["type"] == "page" and "instagram.com" in t["url"])
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
        await cmd("Page.bringToFront")
        await js('location.href = "https://www.instagram.com/accounts/edit/"')
        time.sleep(8)
        user = await js('(() => { const a = document.body.innerText.split("\\n").map(s => s.trim()); '
                        'return a[a.indexOf("Edit profile") + 1] || ""; })()')
        print("logged in as:", user)
        bio = brand_art.BIOS[cid][0]
        xy = await js('(() => { const t = document.querySelector("textarea"); if (!t) return null; t.scrollIntoView('
                      '{block: "center"}); const b = t.getBoundingClientRect(); return [b.x + 20, b.y + 20]; })()')
        if xy:
            for t in ("mouseMoved", "mousePressed", "mouseReleased"):
                await cmd("Input.dispatchMouseEvent", {"type": t, "x": xy[0], "y": xy[1], "button": "left",
                                                       "clickCount": 1})
            await cmd("Input.dispatchKeyEvent", {"type": "keyDown", "key": "a", "code": "KeyA", "modifiers": 2})
            await cmd("Input.dispatchKeyEvent", {"type": "keyUp", "key": "a", "code": "KeyA", "modifiers": 2})
            await cmd("Input.insertText", {"text": bio})
            time.sleep(1)
            sub = await js('(() => { const b = [...document.querySelectorAll("div[role=button],button")].find(e => '
                           '(e.innerText || "").trim() === "Submit"); if (!b) return null; b.scrollIntoView({block: '
                           '"center"}); const r = b.getBoundingClientRect(); return [r.x + r.width / 2, r.y + '
                           'r.height / 2]; })()')
            if sub:
                for t in ("mouseMoved", "mousePressed", "mouseReleased"):
                    await cmd("Input.dispatchMouseEvent", {"type": t, "x": sub[0], "y": sub[1], "button": "left",
                                                           "clickCount": 1})
                time.sleep(3)
        print("bio:", "set" if xy else "box not found")
        pic = brand_art.OUT / cid / "avatar.png"
        if pic.exists():
            doc = await cmd("DOM.getDocument", {"depth": -1})
            q = await cmd("DOM.querySelectorAll", {"nodeId": doc["root"]["nodeId"], "selector": "input[type=file]"})
            if q.get("nodeIds"):
                await cmd("DOM.setFileInputFiles", {"nodeId": q["nodeIds"][0], "files": [str(pic.resolve())]})
                time.sleep(8)
                print("photo: uploaded")
            else:
                print("photo: no upload field")
        text = await js("document.body.innerText") or ""
        print("page says:", " | ".join(x for x in text.split("\n") if "saved" in x.lower() or "updated" in
                                       x.lower() or "couldn" in x.lower())[:200] or "(no message)")


asyncio.run(main(sys.argv[1]))
