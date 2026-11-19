"""Fill Facebook's "Create a Page" form, one new tab per channel, in the visible HookHouse Chrome: Page name, category
"Digital creator", the v2 Facebook bio (brand_art.BIOS). Fields are set through the native value setter + input
event (typing into React fields scrambled the text, 18 Nov). The OWNER presses "Create Page" (Facebook's terms).
python -m scripts.fb_page_fill <channel_id> [...]     |     --close   closes all open 'Create a Page' tabs first"""
import asyncio
import json
import sys
import time
import urllib.request

import websockets

from engine import brand_art
from engine.config import channels

CDP = "http://127.0.0.1:9333"
SET = r'''((label, value) => {
  const e = [...document.querySelectorAll("input,textarea")].find(x => (x.closest("label") ? x.closest("label").innerText : "").startsWith(label));
  if (!e) return false;
  const proto = e.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  Object.getOwnPropertyDescriptor(proto, "value").set.call(e, value);
  e.dispatchEvent(new Event("input", {bubbles: true}));
  e.dispatchEvent(new Event("change", {bubbles: true}));
  return e.value === value; })(%s, %s)'''


def tabs():
    return [t for t in json.loads(urllib.request.urlopen(f"{CDP}/json/list").read()) if t["type"] == "page"]


async def fill(tab, name, bio):
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

        async def js(expr):
            r = await cmd("Runtime.evaluate", {"expression": expr, "returnByValue": True})
            return (r.get("result") or {}).get("value")

        async def click(xy):
            for t in ("mouseMoved", "mousePressed", "mouseReleased"):
                await cmd("Input.dispatchMouseEvent", {"type": t, "x": xy[0], "y": xy[1], "button": "left",
                                                       "clickCount": 1})
        for _ in range(25):
            if await js('[...document.querySelectorAll("label")].some(l => l.innerText.startsWith("Page name"))'):
                break
            time.sleep(1)
        await cmd("Page.bringToFront")
        ok_name = await js(SET % (json.dumps("Page name"), json.dumps(name)))
        xy = await js('(() => { const e = [...document.querySelectorAll("input")].find(x => (x.closest("label") ? '
                      'x.closest("label").innerText : "").startsWith("Category")); if (!e) return null; '
                      'e.scrollIntoView({block: "center"}); const b = e.getBoundingClientRect(); '
                      'return [b.x + 40, b.y + b.height / 2]; })()')
        picked = False
        if xy:
            await click(xy)
            for ch in "Digital creat":
                await cmd("Input.dispatchKeyEvent", {"type": "keyDown", "key": ch, "text": ch})
                await cmd("Input.dispatchKeyEvent", {"type": "keyUp", "key": ch})
                time.sleep(0.06)
            for _ in range(10):
                time.sleep(0.8)
                opt = await js('(() => { const o = [...document.querySelectorAll("[role=option]")].find(e => '
                               '/^Digital creator/i.test((e.innerText || "").trim())); if (!o) return null; '
                               'const b = o.getBoundingClientRect(); return [b.x + b.width / 2, b.y + b.height / 2]; })()')
                if opt:
                    await click(opt)
                    picked = True
                    break
        time.sleep(1)
        ok_bio = await js(SET % (json.dumps("Bio"), json.dumps(bio)))
        time.sleep(1)
        ready = await js('(() => { const b = [...document.querySelectorAll("div[role=button],button")].find(e => '
                         '(e.innerText || "").trim() === "Create Page"); return b ? b.getAttribute("aria-disabled") '
                         '!== "true" : false; })()')
        return {"name": ok_name, "category": picked, "bio": ok_bio, "Create Page ready": ready}


async def main(args):
    if "--close" in args:
        for t in tabs():
            if "pages/creation" in t["url"]:
                urllib.request.urlopen(f"{CDP}/json/close/{t['id']}")
        args = [a for a in args if a != "--close"]
    chans = {c["id"]: c for c in channels()}
    for cid in args:
        c = chans[cid]
        bio = brand_art.BIOS.get(cid, ("", c.get("about", "")[:100]))[1]
        req = urllib.request.Request(f"{CDP}/json/new?https://www.facebook.com/pages/creation/", method="PUT")
        tab = json.loads(urllib.request.urlopen(req, timeout=15).read())
        time.sleep(5)
        print(f"{c['name']}: {await fill(tab, c['name'], bio)}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
