"""Graph API Explorer (visible HookHouse Chrome, port 9333): type each permission into "Add a Permission" and pick it.
The owner still presses Generate Access Token and approves. python -m scripts.meta_explorer_perms"""
import asyncio
import json
import sys
import time
import urllib.request

import websockets

PERMS = ["pages_show_list", "pages_read_engagement", "pages_manage_posts", "pages_manage_metadata", "publish_video",
         "instagram_basic", "instagram_content_publish", "instagram_manage_insights", "instagram_manage_comments",
         "read_insights", "business_management"]


async def main():
    tab = [t for t in json.loads(urllib.request.urlopen("http://127.0.0.1:9333/json/list").read())
           if t["type"] == "page"][0]
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

        def chips():
            return js('[...document.querySelectorAll("span,div")].filter(e => e.children.length === 0)'
                      '.map(e => e.innerText.trim()).filter(t => /^[a-z_]+$/.test(t)).join(" ")')

        for p in PERMS:
            if p in ((await chips()) or "").split():
                continue
            ok = await js('(() => { const i = document.querySelector("input[placeholder=\\"Add a Permission\\"]");'
                          ' if (!i) return false; i.focus(); i.click(); return true; })()')
            if not ok:
                print("permission box not found")
                return
            await cmd("Input.insertText", {"text": p})
            time.sleep(2.5)
            await key("ArrowDown", "ArrowDown", 40)
            time.sleep(0.4)
            await key("Enter", "Enter", 13)
            time.sleep(2.0)
            if p not in ((await chips()) or "").split():
                print("not added:", p)
        text = (await chips()) or ""
        got = [p for p in PERMS if p in text]
        missing = [p for p in PERMS if p not in text]
        sys.stdout.buffer.write(f"in the list now: {len(got)}/{len(PERMS)}; missing: {missing}\n".encode())


if __name__ == "__main__":
    asyncio.run(main())
