"""YouTube Studio (visible HookHouse Chrome): open Customisation > Branding of a channel, upload the v2 profile picture
(output/brand/<channel>/avatar.png), confirm the crop and press Publish. python -m scripts.yt_avatar <channel_id>"""
import asyncio
import json
import sys
import time
import urllib.request

import websockets

from engine import brand_art

CDP = "http://127.0.0.1:9333"
IDS = json.loads((brand_art.ROOT / "data" / "state" / "branding.json").read_text(encoding="utf-8"))


async def main(cid):
    yt = IDS[cid]["youtube_id"]
    tab = next(t for t in json.loads(urllib.request.urlopen(f"{CDP}/json/list").read())
               if t["type"] == "page" and "youtube.com" in t["url"])
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

        async def press(rx):
            xy = await js('(() => { const rx = new RegExp(%s, "i"); const b = [...document.querySelectorAll('
                          '"ytcp-button,button,tp-yt-paper-button,div[role=button]")].filter(e => e.offsetParent && '
                          'rx.test((e.innerText || e.getAttribute("aria-label") || "").trim())).pop(); if (!b) return null;'
                          ' const r = b.getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; })()'
                          % json.dumps(rx))
            if not xy:
                return False
            for t in ("mouseMoved", "mousePressed", "mouseReleased"):
                await cmd("Input.dispatchMouseEvent", {"type": t, "x": xy[0], "y": xy[1], "button": "left",
                                                       "clickCount": 1})
            return True
        await cmd("Page.bringToFront")
        from engine.config import channel                    # each channel is its own brand account: switch first
        handle = str((channel(cid).get("handles") or {}).get("youtube") or "").lower()
        await js('location.href = "https://www.youtube.com/channel_switcher"')
        for _ in range(20):                                  # the list loads in steps: wait for all channels
            time.sleep(1.5)
            if (await js('document.querySelectorAll("ytd-account-item-renderer").length') or 0) >= 14:
                break
        sw = await js('(() => { const h = %s; const it = [...document.querySelectorAll("ytd-account-item-renderer")]'
                      '.find(e => (e.innerText || "").toLowerCase().includes(h)); if (!it) return "not in switcher";'
                      ' (it.querySelector("a, tp-yt-paper-icon-item, #contentIcon") || it).click(); return "switched"; })()'
                      % json.dumps(handle))
        if sw != "switched":
            print(f"{cid}: {sw} ({handle})")
            return
        time.sleep(8)
        await js('location.href = "https://studio.youtube.com/"')       # Studio opens the channel we switched to
        for _ in range(20):
            time.sleep(1.5)
            cur = await js("location.href") or ""
            if "/channel/UC" in cur:
                break
        import re as _re
        m = _re.search(r"/channel/(UC[\w-]+)", cur)
        if not m:
            print(f"{cid}: Studio did not open a channel ({cur[:80]})")
            return
        if m.group(1) != yt:
            print(f"{cid}: switched to {m.group(1)}, expected {yt} - not uploading")
            return
        await js(f'location.href = "https://studio.youtube.com/channel/{yt}/editing/images"')
        for _ in range(20):                                  # wait until the Branding page has its upload fields
            time.sleep(1.5)
            if await js('(() => { const all = []; const w = r => { r.querySelectorAll("*").forEach(e => { all.push(e);'
                        ' if (e.shadowRoot) w(e.shadowRoot); }); }; w(document);'
                        ' return all.filter(e => e.tagName === "INPUT" && e.type === "file").length >= 2; })()'):
                break
        here = await js("location.href")
        if yt not in here:
            print(f"{cid}: Studio did not open this channel ({here[:80]}) - account switch needed")
            return
        await cmd("DOM.enable")
        doc = await cmd("DOM.getDocument", {"depth": -1, "pierce": True})
        q = await cmd("DOM.querySelectorAll", {"nodeId": doc["root"]["nodeId"], "selector": "input[type=file]"})
        ids = q.get("nodeIds") or []
        if not ids:
            print(f"{cid}: no upload field found")
            return
        if len(ids) < 2:                                   # the first upload is the BANNER, the second the picture
            print(f"{cid}: picture upload field not found ({len(ids)} upload fields)")
            return
        await cmd("DOM.setFileInputFiles", {"nodeId": ids[1], "files": [str((brand_art.OUT / cid / "avatar.png").resolve())]})
        time.sleep(6)
        from scripts.yt_press import JS as PRESS            # dialog buttons need a real element click (shadow DOM)
        done = "pressed" in str(await js(PRESS % json.dumps("Done")))
        time.sleep(4)
        pub = "pressed" in str(await js(PRESS % json.dumps("Publish")))
        time.sleep(10)
        msg = await js('document.body.innerText.split("\\n").filter(l => /published|saved|changes/i.test(l)).slice(0,3).join(" | ")')
        print(f"{cid}: picture uploaded, crop {'done' if done else 'n/a'}, publish {'pressed' if pub else 'NOT found'} {msg or ''}")


asyncio.run(main(sys.argv[1]))
