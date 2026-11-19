"""Type one permission into Graph Explorer's box (clearing it first) and leave the dropdown open.
python -m scripts.meta_type_one <permission>"""
import asyncio
import json
import sys
import time
import urllib.request

import websockets


async def main(word: str):
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
        r = await cmd("Runtime.evaluate", {"returnByValue": True, "expression":
            '(() => { const i = document.querySelector("input[placeholder=\\"Add a Permission\\"]"); if (!i) return null;'
            ' i.scrollIntoView({block: "center"}); const b = i.getBoundingClientRect();'
            ' return [b.x + b.width / 2, b.y + b.height / 2]; })()'})
        xy = (r.get("result") or {}).get("value")
        if not xy:
            print("box not found")
            return
        for t in ("mousePressed", "mouseReleased"):
            await cmd("Input.dispatchMouseEvent", {"type": t, "x": xy[0], "y": xy[1], "button": "left", "clickCount": 1})
        await cmd("Input.dispatchKeyEvent", {"type": "keyDown", "key": "a", "code": "KeyA", "modifiers": 2,
                                                 "commands": ["selectAll"]})
        await cmd("Input.dispatchKeyEvent", {"type": "keyUp", "key": "a", "code": "KeyA", "modifiers": 2})
        await cmd("Input.dispatchKeyEvent", {"type": "keyDown", "key": "Backspace", "code": "Backspace",
                                             "windowsVirtualKeyCode": 8})
        await cmd("Input.dispatchKeyEvent", {"type": "keyUp", "key": "Backspace", "code": "Backspace",
                                             "windowsVirtualKeyCode": 8})
        for ch in word:
            await cmd("Input.dispatchKeyEvent", {"type": "keyDown", "key": ch, "text": ch})
            await cmd("Input.dispatchKeyEvent", {"type": "keyUp", "key": ch})
        time.sleep(2)
        print("typed", word, "at", xy)


asyncio.run(main(sys.argv[1]))
