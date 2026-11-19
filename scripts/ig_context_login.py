"""Instagram accounts created in private windows of the HookHouse Chrome (scripts/ig_signup) stay logged in there only.
Facebook's Page <-> Instagram link window uses the MAIN browser profile's Instagram login, so this copies one account's
Instagram session cookies from its private window into the main profile (same browser, same PC; no password is typed
or stored anywhere else). python -m scripts.ig_context_login --list | python -m scripts.ig_context_login <username>"""
import asyncio
import json
import sys
import time
import urllib.request

import websockets

CDP = "http://127.0.0.1:9333"


class Browser:
    def __init__(self):
        self.n = 0

    async def __aenter__(self):
        ver = json.loads(urllib.request.urlopen(f"{CDP}/json/version").read())
        self.ws = await websockets.connect(ver["webSocketDebuggerUrl"], max_size=2 ** 25)
        return self

    async def __aexit__(self, *a):
        await self.ws.close()

    async def cmd(self, m, p=None, session=None):
        self.n += 1
        msg = {"id": self.n, "method": m, "params": p or {}}
        if session:
            msg["sessionId"] = session
        await self.ws.send(json.dumps(msg))
        while True:
            r = json.loads(await self.ws.recv())
            if r.get("id") == self.n:
                return r.get("result", {})


async def username(b: Browser, ctx: str) -> str:
    t = await b.cmd("Target.createTarget", {"url": "https://www.instagram.com/", "browserContextId": ctx})
    s = (await b.cmd("Target.attachToTarget", {"targetId": t["targetId"], "flatten": True}))["sessionId"]
    name = ""
    for _ in range(12):
        time.sleep(2)
        r = await b.cmd("Runtime.evaluate", {"expression": '([...document.querySelectorAll("a[href]")].map(a => '
                                             'a.getAttribute("href")).filter(h => /^\\/[a-z0-9._]+\\/$/.test(h) && '
                                             '!/^\\/(reels|explore|direct|accounts)\\/$/.test(h))[0] || "").replace(/\\//g, "")',
                                             "returnByValue": True}, s)
        name = (r.get("result") or {}).get("value") or ""
        if name:
            break
    await b.cmd("Target.closeTarget", {"targetId": t["targetId"]})
    return name


async def main(arg: str):
    async with Browser() as b:
        ctxs = (await b.cmd("Target.getBrowserContexts")).get("browserContextIds", [])
        found = {}
        for c in ctxs:
            found[await username(b, c)] = c
        if arg == "--list":
            print("private Instagram sessions:", [u or "(not logged in)" for u in found])
            return
        ctx = found.get(arg)
        if not ctx:
            print(f"{arg}: no private window is logged in as it ({list(found)})")
            return
        cookies = [c for c in (await b.cmd("Storage.getCookies", {"browserContextId": ctx})).get("cookies", [])
                   if c["domain"].endswith("instagram.com")]
        keep = ("name", "value", "domain", "path", "secure", "httpOnly", "sameSite", "expires")
        cookies = [{k: c[k] for k in keep if k in c and not (k == "expires" and c[k] in (-1, None))} for c in cookies]
        await b.cmd("Storage.setCookies", {"cookies": cookies})            # main profile
        print(f"{arg}: Instagram session copied into the main browser profile ({len(cookies)} cookies)")

if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
