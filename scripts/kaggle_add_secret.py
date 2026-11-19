"""Add the Hugging Face key as a secret of the open hookhouse-gpu Kaggle notebook editor (HookHouse Chrome), owner
19 Nov: "do all the things by yourself". Boxes are picked by their exact placeholders ("Enter label" / "Enter value"):
19 Nov the first version typed into the first text box on the page, which was the notebook TITLE. The key is read from
.env and never printed. python -m scripts.kaggle_add_secret"""
import asyncio
import json
import os
import time
import urllib.request

import websockets

from engine.config import load_env

CDP = "http://127.0.0.1:9333"


async def main():
    load_env()
    key = os.environ.get("HF_TOKEN", "")
    t = next(t for t in json.loads(urllib.request.urlopen(f"{CDP}/json/list").read())
             if t["type"] == "page" and "hookhouse-gpu/edit" in t["url"])
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

        async def put(placeholder, text):
            sel = json.dumps(f'input[placeholder="{placeholder}"]')
            if not await js(f"(() => {{ const e = document.querySelector({sel}); if (!e) return false; e.focus(); return true; }})()"):
                return False
            await cmd("Input.insertText", {"text": text})
            time.sleep(0.5)
            return (await js(f"document.querySelector({sel}).value")) == text
        if not await js('!!document.querySelector("input[placeholder=\\"Enter label\\"]")'):
            print("open Add-ons > Secrets > Add Secret first (the label/value boxes are not on the page)")
            return
        if not (await put("Enter label", "HF_TOKEN") and await put("Enter value", key)):
            print("could not fill the secret form")
            return
        xy = await js('(() => { let box = document.querySelector("input[placeholder=\\"Enter value\\"]"); for (let k = 0; k < 7 && box; k++) {'
                      ' box = box.parentElement; const b = [...(box ? box.querySelectorAll("button") : [])].find(e => /^(save|add)$/i'
                      '.test((e.innerText || "").trim())); if (b) { const r = b.getBoundingClientRect(); return [r.x + r.width / 2,'
                      ' r.y + r.height / 2]; } } return null; })()')
        if not xy:
            print("the secret form's Save button was not found")
            return
        for k in ("mouseMoved", "mousePressed", "mouseReleased"):
            await cmd("Input.dispatchMouseEvent", {"type": k, "x": xy[0], "y": xy[1], "button": "left", "clickCount": 1})
        time.sleep(4)
        body = await js("document.body.innerText") or ""
        print("HF_TOKEN listed:", "HF_TOKEN" in body, "| key visible on the page:", key in body)

if __name__ == "__main__":
    asyncio.run(main())
