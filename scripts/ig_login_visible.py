"""Instagram login that needs the owner's 'I'm not a robot' tick: opens a VISIBLE private window of the HookHouse
Chrome, types the username and the .env password, presses Log in, then waits (up to 10 min) for the owner to pass the
check; the login is saved to data/secrets/ig_session_<user>.json and the window closes.
python -m scripts.ig_login_visible <username>"""
import asyncio
import json
import os
import sys
import time

from engine.config import ROOT, load_env
from scripts.ig_context_login import Browser

KEEP = ("name", "value", "domain", "path", "secure", "httpOnly", "sameSite", "expires")


async def main(user: str):
    load_env()
    pw = os.environ.get("IG_SIGNUP_PASSWORD", "")
    async with Browser() as b:
        ctx = (await b.cmd("Target.createBrowserContext"))["browserContextId"]
        t = await b.cmd("Target.createTarget", {"url": "https://www.instagram.com/accounts/login/", "browserContextId": ctx,
                                                "newWindow": True})
        s = (await b.cmd("Target.attachToTarget", {"targetId": t["targetId"], "flatten": True}))["sessionId"]

        async def js(e):
            return ((await b.cmd("Runtime.evaluate", {"expression": e, "returnByValue": True}, s)).get("result") or {}).get("value")

        async def click(xy):
            for k in ("mouseMoved", "mousePressed", "mouseReleased"):
                await b.cmd("Input.dispatchMouseEvent", {"type": k, "x": xy[0], "y": xy[1], "button": "left", "clickCount": 1}, s)
        for _ in range(20):
            time.sleep(1.5)
            if await js('!!document.querySelector("input[name=pass], input[type=password]")'):
                break
        for sel, text in (('input[name="email"], input[name="username"]', user),
                          ('input[name="pass"], input[type="password"]', pw)):
            xy = await js('(() => { const r = document.querySelector(%s).getBoundingClientRect(); return [r.x + 12, r.y + r.height / 2]; })()'
                          % json.dumps(sel))
            await click(xy)
            await b.cmd("Input.insertText", {"text": text}, s)
            time.sleep(0.4)
        xy = await js('(() => { const b = [...document.querySelectorAll("button,input[type=submit],div[role=button]")].find(e => '
                      '/^log in$/i.test((e.innerText || e.value || "").trim())); if (!b) return null; const r = b.getBoundingClientRect();'
                      ' return [r.x + r.width / 2, r.y + r.height / 2]; })()')
        await click(xy)
        await b.cmd("Target.activateTarget", {"targetId": t["targetId"]})
        print(f"@{user}: window open: tick 'I'm not a robot' if Instagram asks", flush=True)
        for _ in range(120):
            time.sleep(5)
            ck = (await b.cmd("Storage.getCookies", {"browserContextId": ctx})).get("cookies", [])
            if any(c["name"] == "sessionid" and c["domain"].endswith("instagram.com") for c in ck):
                ck = [{k: c[k] for k in KEEP if k in c and not (k == "expires" and c[k] in (-1, None))}
                      for c in ck if c["domain"].endswith("instagram.com")]
                (ROOT / "data" / "secrets" / f"ig_session_{user}.json").write_text(json.dumps(ck), encoding="utf-8")
                print(f"@{user}: logged in, login saved", flush=True)
                time.sleep(3)
                break
        else:
            print(f"@{user}: no login within 10 minutes", flush=True)
        await b.cmd("Target.disposeBrowserContext", {"browserContextId": ctx})

if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
