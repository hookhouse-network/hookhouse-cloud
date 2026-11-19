"""Instagram sign-up for a channel in a clean private window of the visible HookHouse Chrome (the 4 logged-in accounts
stay untouched). Fills email (+alias of the HookHouse Gmail), full name and username; the OWNER types the password,
the birthday and presses Sign up (Instagram's terms). python -m scripts.ig_signup <channel_id> [username]"""
import asyncio
import json
import sys
import time
import urllib.request

import websockets

from engine.config import ROOT, channel

CDP = "http://127.0.0.1:9333"
TAB = ROOT / "data" / "pc" / "ig_signup_tab.txt"
SETL = r'''((label, v) => { const e = [...document.querySelectorAll("input")].find(i => ((i.closest("label") || {}).innerText
  || i.getAttribute("aria-label") || "").trim().startsWith(label)); if (!e) return "no field " + label;
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(e, v);
  e.dispatchEvent(new Event("input", {bubbles: true})); e.dispatchEvent(new Event("change", {bubbles: true}));
  return e.value === v; })(%s, %s)'''


async def browser(method, params=None):
    ver = json.loads(urllib.request.urlopen(f"{CDP}/json/version").read())
    async with websockets.connect(ver["webSocketDebuggerUrl"], max_size=2 ** 24) as ws:
        await ws.send(json.dumps({"id": 1, "method": method, "params": params or {}}))
        while True:
            m = json.loads(await ws.recv())
            if m.get("id") == 1:
                return m.get("result", {})


async def js(expr):
    tid = TAB.read_text().strip()
    t = next(t for t in json.loads(urllib.request.urlopen(f"{CDP}/json/list").read()) if t["id"] == tid)
    async with websockets.connect(t["webSocketDebuggerUrl"], max_size=2 ** 24) as ws:
        await ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate", "params": {"expression": expr,
                                                                                     "returnByValue": True}}))
        while True:
            m = json.loads(await ws.recv())
            if m.get("id") == 1:
                return m["result"]["result"].get("value")


async def main(cid, user=None):
    ch = channel(cid)
    h = ch.get("handles") or {}
    yt = str(h.get("youtube") or "").lstrip("@").lower()
    cands = [c for c in [user, h.get("instagram"), yt, str(h.get("instagram") or "") + "hq", h.get("instagram_backup")] if c]
    email = f"hookhouse.network+{cid.replace('_', '')}@gmail.com"
    ctx = await browser("Target.createBrowserContext")
    t = await browser("Target.createTarget", {"url": "https://www.instagram.com/accounts/emailsignup/",
                                              "browserContextId": ctx["browserContextId"], "newWindow": True})
    TAB.parent.mkdir(parents=True, exist_ok=True)
    TAB.write_text(t["targetId"])
    for _ in range(25):
        time.sleep(1.5)
        if await js('[...document.querySelectorAll("label")].some(l => l.innerText.includes("Username"))'):
            break
    print("email:", await js(SETL % (json.dumps("Mobile number or email"), json.dumps(email))))
    print("name:", await js(SETL % (json.dumps("Name"), json.dumps(ch["name"]))))
    got = None
    for c in dict.fromkeys(cands):
        await js(SETL % (json.dumps("Username"), json.dumps(c)))
        time.sleep(5)
        txt = await js("document.body.innerText") or ""
        free = not any(k in txt for k in ("is not available", "is invalid"))
        print(f"  @{c}: {'AVAILABLE' if free else 'taken'}")
        if free:
            got = c
            break
    await js('(() => { const e = [...document.querySelectorAll("input")].find(i => ((i.closest("label") || {}).innerText'
             ' || "").trim().startsWith("Password")); if (e) e.focus(); })()')
    await browser("Target.activateTarget", {"targetId": t["targetId"]})
    print(f"ready for the owner: password + birthday + Submit ({ch['name']}, @{got}, {email})" if got
          else "no free handle among the options: pick one")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None))
