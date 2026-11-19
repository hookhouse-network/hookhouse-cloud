"""Connect a Threads profile for automatic posting (Threads API key), hidden: a temporary private window with the
account's saved Instagram login opens our app's Threads authorisation page, presses Allow / Continue, catches the
return code and stores the key (engine.threads.connect). python -m scripts.threads_connect <channel_id> [...]"""
import asyncio
import json
import sys
import time

from engine.config import ROOT, load_env
from engine.links import data as links
from scripts.ig_context_login import Browser

PREFER = ["Allow", "Continue as", "Continue", "Log in with Instagram", "Accept", "Done"]


async def connect_one(b: Browser, cid: str) -> str:
    from engine import threads
    user = str((links().get(cid) or {}).get("instagram") or "").lstrip("@")
    f = ROOT / "data" / "secrets" / f"ig_session_{user}.json"
    if not (user and f.exists()):
        return f"{cid}: no saved Instagram login"
    ctx = (await b.cmd("Target.createBrowserContext"))["browserContextId"]
    try:
        await b.cmd("Storage.setCookies", {"cookies": json.loads(f.read_text(encoding="utf-8")), "browserContextId": ctx})
        t = await b.cmd("Target.createTarget", {"url": "https://www.threads.com/login", "browserContextId": ctx})
        s = (await b.cmd("Target.attachToTarget", {"targetId": t["targetId"], "flatten": True}))["sessionId"]

        async def js(e):
            return ((await b.cmd("Runtime.evaluate", {"expression": e, "returnByValue": True}, s)).get("result") or {}).get("value")

        async def press(label):
            q = ('((w) => { const b = [...document.querySelectorAll("button,div[role=button],a[role=button],input[type=submit]")]'
                 '.filter(e => (e.innerText || e.value || "").trim().startsWith(w) && e.getBoundingClientRect().width > 0).pop();'
                 ' if (!b) return null; b.scrollIntoView({block: "center"}); const r = b.getBoundingClientRect();'
                 ' return [r.x + r.width / 2, r.y + r.height / 2]; })(%s)' % json.dumps(label))
            xy = await js(q)
            if not xy:
                return False
            time.sleep(0.4)
            xy = await js(q)
            for k in ("mouseMoved", "mousePressed", "mouseReleased"):
                await b.cmd("Input.dispatchMouseEvent", {"type": k, "x": xy[0], "y": xy[1], "button": "left",
                                                         "clickCount": 1}, s)
            return True
        steps, page = [], ""
        time.sleep(10)                                   # 1) a Threads session from the Instagram login
        acct = await js('((u) => { const b = [...document.querySelectorAll("button,div[role=button],a")].filter(e => (e.innerText'
                        ' || "").includes(u) && e.getBoundingClientRect().width > 0).pop(); if (!b) return null; const r ='
                        ' b.getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; })(%s)' % json.dumps(user))
        if acct:
            for k in ("mouseMoved", "mousePressed", "mouseReleased"):
                await b.cmd("Input.dispatchMouseEvent", {"type": k, "x": acct[0], "y": acct[1], "button": "left",
                                                         "clickCount": 1}, s)
            steps.append("Threads login as @" + user)
            time.sleep(10)
        await b.cmd("Page.navigate", {"url": threads.auth_url(state=cid)}, s)   # 2) our app's authorisation page
        for _ in range(10):
            time.sleep(6)
            url = await js("location.href") or ""
            code = threads.code_from_url(url) if threads.is_return_page(url) else None
            if code:
                return f"{cid}: {threads.connect(code, channel_hint=cid)} (steps: {', '.join(steps)})"
            page = (await js("document.body.innerText") or "")[:300]
            pressed = None
            for lbl in PREFER:
                if await press(lbl):
                    pressed = lbl
                    break
            if not pressed:
                break
            steps.append(pressed)
        return f"{cid}: not connected (steps: {', '.join(steps) or 'none'}); page: {page.replace(chr(10), ' / ')[:200]}"
    finally:
        await b.cmd("Target.disposeBrowserContext", {"browserContextId": ctx})


async def main(cids):
    load_env()
    async with Browser() as b:
        for cid in cids:
            print(await connect_one(b, cid), flush=True)

if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
