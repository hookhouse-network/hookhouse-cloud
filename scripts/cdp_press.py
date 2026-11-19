"""Real mouse click on a button/link by its exact visible text, in the tab whose URL contains <url-part>.
python -m scripts.cdp_press <url-part> "<text>" [index]   (prints what it clicked, then the tab's first lines)"""
import asyncio
import json
import sys
import time
import urllib.request

import websockets

FIND = r'''((want, idx) => { const all = []; const w = r => r.querySelectorAll("*").forEach(e => { all.push(e);
  if (e.shadowRoot) w(e.shadowRoot); }); w(document);
  const hits = all.filter(e => e.getBoundingClientRect().width > 0 && (e.matches("button,a,[role=button],[role=link],"
    + "[role=checkbox],[role=radio],[role=switch],label,input[type=checkbox]") ) && ((e.innerText || e.getAttribute(
    "aria-label") || "").trim() === want));
  const b = hits[idx]; if (!b) return null; b.scrollIntoView({block: "center"}); const r = b.getBoundingClientRect();
  return [r.x + r.width / 2, r.y + r.height / 2, hits.length]; })(%s, %d)'''


async def main(part, text, idx):
    tab = next(t for t in json.loads(urllib.request.urlopen("http://127.0.0.1:9333/json/list").read())
               if t["type"] == "page" and part in t["url"])
    async with websockets.connect(tab["webSocketDebuggerUrl"], max_size=2 ** 24) as ws:
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
        await js(FIND % (json.dumps(text), idx))
        time.sleep(0.6)
        xy = await js(FIND % (json.dumps(text), idx))
        if not xy:
            print(f"not found: {text!r}")
            return
        for t in ("mouseMoved", "mousePressed", "mouseReleased"):
            await cmd("Input.dispatchMouseEvent", {"type": t, "x": xy[0], "y": xy[1], "button": "left", "clickCount": 1})
        time.sleep(4)
        try:
            body = await js("document.body.innerText.slice(0, 700)")
        except Exception:  # noqa: BLE001 - the window may have closed
            body = "(window closed)"
        sys.stdout.buffer.write(f"clicked {text!r} ({xy[2]} match(es))\n{body}\n".encode("utf-8"))

if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 0))
