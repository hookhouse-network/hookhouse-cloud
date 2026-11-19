"""Open a page in a new tab of the hidden HookHouse Chrome, wait, print its visible text (or the lines around keywords),
close the tab. python -m scripts.cdp_read <url> [wait_s] [keyword ...]"""
import asyncio
import json
import sys
import time
import urllib.request

import websockets

CDP = "http://127.0.0.1:9333"


async def read(url: str, wait: float = 10) -> str:
    req = urllib.request.Request(f"{CDP}/json/new?{url}", method="PUT")
    t = json.loads(urllib.request.urlopen(req).read())
    try:
        time.sleep(wait)
        async with websockets.connect(t["webSocketDebuggerUrl"], max_size=2 ** 24) as ws:
            await ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate",
                                      "params": {"expression": "document.body ? document.body.innerText : ''",
                                                 "returnByValue": True}}))
            while True:
                r = json.loads(await ws.recv())
                if r.get("id") == 1:
                    return r.get("result", {}).get("result", {}).get("value") or ""
    finally:
        urllib.request.urlopen(f"{CDP}/json/close/{t['id']}")


def around(text: str, words: list[str], width: int = 260) -> str:
    low, out = text.lower(), []
    for w in words:
        i = low.find(w.lower())
        while i >= 0 and len([o for o in out if o.startswith(f"[{w}]")]) < 3:
            out.append(f"[{w}] ..." + text[max(0, i - width // 2):i + width].replace("\n", " ") + "...")
            i = low.find(w.lower(), i + width)
    return "\n".join(out)


if __name__ == "__main__":
    u = sys.argv[1]
    w = float(sys.argv[2]) if len(sys.argv) > 2 else 10
    txt = asyncio.run(read(u, w))
    out = around(txt, sys.argv[3:]) if len(sys.argv) > 3 else txt[:4000]
    sys.stdout.buffer.write(f"{len(txt)} chars\n{out}\n".encode("utf-8"))
