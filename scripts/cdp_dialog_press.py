"""Real click on a button INSIDE the open dialog of a tab (URL part), by exact text; prints the dialog afterwards and
any new windows (login pop-ups). python -m scripts.cdp_dialog_press <url-part> "<text>" """
import asyncio
import json
import sys
import time
import urllib.request

import websockets

CDP = "http://127.0.0.1:9333"
FIND = r'''((want) => { const ds = [...document.querySelectorAll("[role=dialog]")].filter(e => e.getBoundingClientRect().width > 0);
  const d = ds[ds.length - 1]; if (!d) return null;
  const b = [...d.querySelectorAll("[role=button],button,a")].filter(e => (e.innerText || e.getAttribute("aria-label") || "")
    .trim() === want && e.getBoundingClientRect().width > 0).pop();
  if (!b) return null; b.scrollIntoView({block: "center"}); const r = b.getBoundingClientRect();
  return [r.x + r.width / 2, r.y + r.height / 2]; })(%s)'''


def targets():
    return {t["id"]: t["url"] for t in json.loads(urllib.request.urlopen(f"{CDP}/json/list").read()) if t["type"] == "page"}


async def main(part, text):
    before = targets()
    tab = next(t for t in json.loads(urllib.request.urlopen(f"{CDP}/json/list").read())
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
        await cmd("Page.bringToFront")
        await js(FIND % json.dumps(text))
        time.sleep(0.5)
        xy = await js(FIND % json.dumps(text))
        if not xy:
            print(f"not in dialog: {text!r}")
            return
        for t in ("mouseMoved", "mousePressed", "mouseReleased"):
            await cmd("Input.dispatchMouseEvent", {"type": t, "x": xy[0], "y": xy[1], "button": "left", "clickCount": 1})
        time.sleep(6)
        d = await js('[...document.querySelectorAll("[role=dialog]")].filter(e => e.getBoundingClientRect().width > 0)'
                     '.map(e => e.innerText.slice(0, 400)).join(" ||| ")')
    new = {k: v for k, v in targets().items() if k not in before}
    sys.stdout.buffer.write(f"clicked {text!r}\ndialog: {(d or 'none')[:500]}\nnew windows: {list(new.values())}\n"
                            .replace("\n\n", "\n").encode("utf-8"))

if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], sys.argv[2]))
