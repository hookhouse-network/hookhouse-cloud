"""Join Content Rewards campaigns (owner 19 Nov: "join gta 6 campaigns") in the hidden HookHouse Chrome and report
what their reference materials are: real files (Drive / Dropbox / Frame.io / WeTransfer: clippable) or only stream /
channel links (Twitch / Kick / YouTube: not downloadable for us). python -m scripts.cr_join_check <campaign url> [...]"""
import asyncio
import json
import re
import sys
import time
import urllib.request

import websockets

CDP = "http://127.0.0.1:9333"
FILES = re.compile(r"drive\.google|dropbox|frame\.io|f\.io/|wetransfer|mega\.nz|box\.com|onedrive|1drv", re.I)
STREAMS = re.compile(r"twitch\.tv|kick\.com|youtube\.com|youtu\.be|tiktok\.com|instagram\.com|x\.com|twitter\.com", re.I)


async def one(url: str) -> str:
    req = urllib.request.Request(f"{CDP}/json/new?{url}", method="PUT")
    t = json.loads(urllib.request.urlopen(req).read())
    try:
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
            time.sleep(12)
            name = (await js('(document.querySelector("h1,h2") || {}).innerText || document.title') or "")[:60]
            joined = "Submit clip" in (await js("document.body.innerText") or "")
            if not joined:
                xy = await js("(() => { const b = [...document.querySelectorAll('button')].filter(e => (e.innerText || '').trim() === "
                              "'Join Campaign').map(e => [e, e.getBoundingClientRect()]).filter(([e, r]) => r.width > 0 && r.y > 0"
                              " && r.y < 900).sort((a, b) => a[1].y - b[1].y)[0]; if (!b) return null; return [b[1].x + b[1].width / 2,"
                              " b[1].y + b[1].height / 2]; })()")
                if xy:
                    for k in ("mouseMoved", "mousePressed", "mouseReleased"):
                        await cmd("Input.dispatchMouseEvent", {"type": k, "x": xy[0], "y": xy[1], "button": "left", "clickCount": 1})
                    time.sleep(8)
                    joined = "Submit clip" in (await js("document.body.innerText") or "")
            body = await js("document.body.innerText") or ""
            i = body.find("Reference materials")
            materials = body[i:i + 300].replace("\n", " / ") if i >= 0 else ""
            links = await js('[...new Set([...document.querySelectorAll("a[href]")].map(a => a.href))]') or []
            files = [h for h in links if FILES.search(h)]
            streams = [h for h in links if STREAMS.search(h) and "contentrewards" not in h]
            verdict = ("CLIPPABLE (files shared)" if files else "stream/channel links only (not downloadable for us)"
                       if streams else "no source links visible")
            return (f"{name} | joined: {joined} | {verdict}\n   materials: {materials[:200]}\n   files: {files[:4]}\n"
                    f"   streams: {streams[:4]}")
    finally:
        urllib.request.urlopen(f"{CDP}/json/close/{t['id']}")


async def main(urls):
    for u in urls:
        sys.stdout.buffer.write((await one(u) + "\n").encode("utf-8"))
        sys.stdout.flush()

if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
