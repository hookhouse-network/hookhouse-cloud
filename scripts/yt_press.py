"""Press a button by its exact text in YouTube Studio (searches shadow DOM, prefers dialogs).
python -m scripts.yt_press Done   |   python -m scripts.yt_press Publish"""
import asyncio
import json
import sys
import urllib.request

import websockets

JS = r'''((label) => {
  const all = []; const walk = r => { r.querySelectorAll("*").forEach(e => { all.push(e); if (e.shadowRoot) walk(e.shadowRoot); }); };
  walk(document);
  const btns = all.filter(e => /^(ytcp-button|button|tp-yt-paper-button)$/i.test(e.tagName) && e.offsetParent &&
                               (e.innerText || "").trim() === label && !e.disabled && e.getAttribute("aria-disabled") !== "true");
  const dlg = btns.filter(b => b.closest("ytcp-dialog, tp-yt-paper-dialog, [role=dialog]"));
  const b = (dlg.length ? dlg : btns).pop(); if (!b) return "not found / disabled: " + label;
  b.click(); return "pressed " + label + (dlg.length ? " (dialog)" : ""); })(%s)'''


async def main(label):
    tab = next(t for t in json.loads(urllib.request.urlopen("http://127.0.0.1:9333/json/list").read())
               if t["type"] == "page" and "studio.youtube" in t["url"])
    async with websockets.connect(tab["webSocketDebuggerUrl"], max_size=2 ** 24) as ws:
        await ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate",
                                  "params": {"expression": JS % json.dumps(label), "returnByValue": True}}))
        while True:
            r = json.loads(await ws.recv())
            if r.get("id") == 1:
                print(r["result"]["result"].get("value"))
                return


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
