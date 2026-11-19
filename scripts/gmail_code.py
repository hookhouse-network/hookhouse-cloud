"""Read the newest GitHub Support verification code from the HookHouse Gmail tab (visible HookHouse Chrome), waiting up
to ~3 minutes for one newer than `--not <old code>`. python -m scripts.gmail_code --not 42604656"""
import asyncio
import json
import re
import sys
import time
import urllib.request

import websockets

old = sys.argv[sys.argv.index("--not") + 1] if "--not" in sys.argv else ""


async def run(ws_url, expr):
    async with websockets.connect(ws_url, max_size=2 ** 24) as ws:
        await ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate", "params": {"expression": expr,
                                                                                     "returnByValue": True}}))
        while True:
            r = json.loads(await ws.recv())
            if r.get("id") == 1:
                return r["result"]["result"].get("value")


tab = next(t for t in json.loads(urllib.request.urlopen("http://127.0.0.1:9333/json/list").read())
           if t["type"] == "page" and "mail.google" in t["url"])
for _ in range(12):
    asyncio.run(run(tab["webSocketDebuggerUrl"], 'location.hash = "#inbox"'))
    time.sleep(3)
    asyncio.run(run(tab["webSocketDebuggerUrl"],
                    'location.hash = "#search/" + encodeURIComponent("from:github verification code")'))
    time.sleep(8)
    rows = asyncio.run(run(tab["webSocketDebuggerUrl"], r'[...document.querySelectorAll("tr.zA")].slice(0, 3)'
                                                          r'.map(r => r.innerText).join("\n")')) or ""
    codes = [c for c in re.findall(r"\b(\d{8})\b", rows) if c != old]
    if codes:
        print(codes[0])
        sys.exit(0)
print("no new code yet")
