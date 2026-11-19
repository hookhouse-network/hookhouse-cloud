"""Read-only JavaScript in one tab of the visible HookHouse Chrome (port 9333), picked by part of its URL and its index
among matches. python -m scripts.cdp_eval <url-part> <index> "<js expression>"  (prints the value; tokens hidden)"""
import asyncio
import json
import re
import sys
import urllib.request

import websockets


async def main(part: str, idx: int, expr: str):
    tabs = [t for t in json.loads(urllib.request.urlopen("http://127.0.0.1:9333/json/list").read())
            if t["type"] == "page" and part in t["url"]]
    async with websockets.connect(tabs[idx]["webSocketDebuggerUrl"], max_size=2 ** 24) as ws:
        await ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate",
                                  "params": {"expression": expr, "returnByValue": True}}))
        while True:
            m = json.loads(await ws.recv())
            if m.get("id") == 1:
                v = (m.get("result", {}).get("result") or {}).get("value")
                out = re.sub(r"(access_token=|EAA)[A-Za-z0-9_\-]{10,}", r"\1***", str(v))
                sys.stdout.buffer.write((out + "\n").encode("utf-8"))
                return

if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], int(sys.argv[2]), sys.argv[3]))
