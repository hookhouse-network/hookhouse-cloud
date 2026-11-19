"""Screenshot of the visible HookHouse Chrome tab -> data/review/cdp_shot.png. python -m scripts.cdp_shot"""
import asyncio
import base64
import json
import sys
import urllib.request

import websockets

from engine.config import ROOT


async def main():
    want = sys.argv[1] if len(sys.argv) > 1 else ""          # optional: part of the tab's URL, e.g. youtube.com
    tab = [t for t in json.loads(urllib.request.urlopen("http://127.0.0.1:9333/json/list").read())
           if t["type"] == "page" and want in t["url"]][0]
    async with websockets.connect(tab["webSocketDebuggerUrl"], max_size=2 ** 26) as ws:
        await ws.send(json.dumps({"id": 1, "method": "Page.captureScreenshot", "params": {"format": "png"}}))
        while True:
            m = json.loads(await ws.recv())
            if m.get("id") == 1:
                out = ROOT / "data" / "review" / "cdp_shot.png"
                out.write_bytes(base64.b64decode(m["result"]["data"]))
                print(out)
                return


asyncio.run(main())
