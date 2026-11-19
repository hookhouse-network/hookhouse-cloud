"""On every open 'Create a Page' tab: pick 'Digital creator' from the category suggestions (keyboard) and set the bio;
report whether the Create Page button is enabled. python -m scripts.fb_page_category"""
import asyncio
import json
import time
import urllib.request

import websockets

from engine.config import channels

BIOS = {c["name"]: c.get("about", "") for c in channels()}


def bio_for(name):
    from engine import brand_art                       # the v2 bios written for Facebook (<= 101 characters)
    cid = next((c["id"] for c in channels() if c["name"] == name), "")
    if cid in brand_art.BIOS:
        return brand_art.BIOS[cid][1]
    s = BIOS.get(name, "")
    out = ""
    for part in s.split(". "):
        nxt = (out + " " + part.strip().rstrip(".") + ".").strip()
        if len(nxt) > 101:
            break
        out = nxt
    return out or s[:100]


async def fix(tab):
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

        async def key(k, code, vk):
            for t in ("keyDown", "keyUp"):
                await cmd("Input.dispatchKeyEvent", {"type": t, "key": k, "code": code, "windowsVirtualKeyCode": vk})

        async def click_xy(xy):
            for t in ("mouseMoved", "mousePressed", "mouseReleased"):
                await cmd("Input.dispatchMouseEvent", {"type": t, "x": xy[0], "y": xy[1], "button": "left",
                                                       "clickCount": 1})

        def field(label):
            return ('(() => { const e = [...document.querySelectorAll("input,textarea")].find(x => (x.closest("label") '
                    '? x.closest("label").innerText : "").startsWith(%s)); if (!e) return null; e.scrollIntoView('
                    '{block: "center"}); const b = e.getBoundingClientRect(); return [b.x + 30, b.y + b.height / 2]; '
                    '})()' % json.dumps(label))
        await cmd("Page.bringToFront")
        name = await js('(() => { const e = [...document.querySelectorAll("input")].find(x => (x.closest("label") ? '
                        'x.closest("label").innerText : "").startsWith("Page name")); return e ? e.value : ""; })()')
        if not name:
            return None
        xy = await js(field("Category"))
        if xy:
            await click_xy(xy)
            time.sleep(0.4)
            await cmd("Input.dispatchKeyEvent", {"type": "keyDown", "key": "a", "code": "KeyA", "modifiers": 2,
                                                 "commands": ["selectAll"]})
            await cmd("Input.dispatchKeyEvent", {"type": "keyUp", "key": "a", "code": "KeyA", "modifiers": 2})
            await key("Backspace", "Backspace", 8)
            for ch in "Digital creat":
                await cmd("Input.dispatchKeyEvent", {"type": "keyDown", "key": ch, "text": ch})
                await cmd("Input.dispatchKeyEvent", {"type": "keyUp", "key": ch})
                time.sleep(0.05)
            time.sleep(2.5)
            opt = await js('(() => { const o = [...document.querySelectorAll("[role=option]")].find(e => '
                           '/^Digital creator/i.test((e.innerText || "").trim())); if (!o) return null; const b = '
                           'o.getBoundingClientRect(); return [b.x + b.width / 2, b.y + b.height / 2]; })()')
            if opt:
                await click_xy(opt)
            else:
                await key("ArrowDown", "ArrowDown", 40)
                await key("Enter", "Enter", 13)
            time.sleep(1.5)
        # 19 Nov: a simulated Ctrl+A selects nothing in Chrome, so insertText pasted the bio a SECOND time into the box
        # (owner saw it doubled on every Page form). Now the box is REPLACED through the native value setter, only when
        # it isn't already exactly right, and read back.
        from scripts.fb_page_bio_fix import GET, SET
        want = bio_for(name)
        if want and await js(GET % json.dumps("Bio")) != want:
            await js(SET % (json.dumps("Bio"), json.dumps(want)))
        time.sleep(1)
        enabled = await js('(() => { const b = [...document.querySelectorAll("div[role=button],button")].find(e => '
                           '(e.innerText || "").trim() === "Create Page"); return b ? b.getAttribute("aria-disabled") '
                           '!== "true" && !b.disabled : null; })()')
        return name, enabled


async def main():
    tabs = [t for t in json.loads(urllib.request.urlopen("http://127.0.0.1:9333/json/list").read())
            if t["type"] == "page" and "pages/creation" in t["url"]]
    for t in tabs:
        r = await fix(t)
        if r:
            print(f"{r[0]}: Create Page button {'READY' if r[1] else 'not ready'}")


asyncio.run(main())
