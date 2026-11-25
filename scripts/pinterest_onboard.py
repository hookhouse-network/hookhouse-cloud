"""Finish a new Pinterest business account's onboarding from its saved login (hidden, own browser context): "Describe
your business" -> Content creator -> Next, then Next/Skip through the rest. Until this is done the profile edits do
not save (25 Nov: Clutch Tales and Ending Decoded kept the email as their name).
python -m scripts.pinterest_onboard <channel_id> [...]"""
import asyncio
import json
import sys
import time
import urllib.request

import websockets

from engine.config import ROOT

CDP = "http://127.0.0.1:9333"
NEXT = ["Next", "Skip", "Continue", "Done", "Not now", "Get started", "Skip for now", "Finish", "Maybe later"]


async def onboard(cid: str) -> str:
    ver = json.loads(urllib.request.urlopen(f"{CDP}/json/version", timeout=15).read())
    async with websockets.connect(ver["webSocketDebuggerUrl"], max_size=2 ** 24) as ws:
        n = [0]

        async def cmd(m, p=None, sid=None):
            n[0] += 1
            msg = {"id": n[0], "method": m, "params": p or {}}
            if sid:
                msg["sessionId"] = sid
            await ws.send(json.dumps(msg))
            while True:
                r = json.loads(await asyncio.wait_for(ws.recv(), timeout=60))
                if r.get("id") == n[0]:
                    return r.get("result", {})
        ctx = (await cmd("Target.createBrowserContext"))["browserContextId"]
        cookies = json.loads((ROOT / "data" / "secrets" / f"pinterest_session_{cid}.json").read_text(encoding="utf-8"))
        await cmd("Storage.setCookies", {"cookies": cookies, "browserContextId": ctx})
        tid = (await cmd("Target.createTarget", {"url": "https://www.pinterest.com/business/hub/",
                                                  "browserContextId": ctx}))["targetId"]
        s = (await cmd("Target.attachToTarget", {"targetId": tid, "flatten": True}))["sessionId"]

        async def js(e):
            r = await cmd("Runtime.evaluate", {"expression": e, "returnByValue": True}, s)
            return r.get("result", {}).get("value")

        async def click_where(expr) -> bool:
            xy = await js(f"""(() => {{ const el = ({expr}); if (!el) return null; el.scrollIntoView({{block: 'center'}});
              const r = el.getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; }})()""")
            if not xy:
                return False
            for k in ("mouseMoved", "mousePressed", "mouseReleased"):
                await cmd("Input.dispatchMouseEvent", {"type": k, "x": xy[0], "y": xy[1], "button": "left",
                                                       "clickCount": 1}, s)
            return True
        for _ in range(15):                                  # the hub renders late on a new account
            time.sleep(3)
            page = await js("document.body.innerText") or ""
            if any(x in page for x in ("Describe your business", "Next", "Skip")):
                break
        done = []
        for _ in range(10):
            text = await js("document.body.innerText") or ""
            if "Describe your business" in text and "creator" not in done:
                ok = await click_where("[...document.querySelectorAll('label,[role=radio],div,span')].filter(e => "
                                       "(e.innerText || '').trim().startsWith('Content creator') && "
                                       "e.getBoundingClientRect().width > 0).pop()")
                if ok:
                    done.append("creator")
                    time.sleep(1.5)
            pressed = None
            for lbl in NEXT:
                if await click_where(f"[...document.querySelectorAll('button,[role=button]')].find(e => "
                                     f"(e.innerText || '').trim() === {json.dumps(lbl)} && !e.disabled && "
                                     f"e.getBoundingClientRect().width > 0)"):
                    pressed = lbl
                    break
            if not pressed:
                break
            done.append(pressed)
            time.sleep(5)
        left = "Describe your business" in (await js("document.body.innerText") or "")
        await cmd("Target.disposeBrowserContext", {"browserContextId": ctx})
        return f"steps {done}; " + ("onboarding still open" if left else "onboarding done")


if __name__ == "__main__":
    for c in sys.argv[1:]:
        print(f"{c}: {asyncio.run(onboard(c))}", flush=True)
