"""Create the Threads profile of an Instagram account (owner 19 Nov: link insta, facebook, threads, youtube), hidden:
temporary private window with the saved Instagram login -> threads.com 'Join using your Meta Account <user>' ->
import the Instagram profile (picture + bio) -> public -> Join Threads. python -m scripts.threads_join <ig user> [...]"""
import asyncio
import json
import sys
import time

from engine.config import ROOT
from scripts.ig_context_login import Browser

PREFER = ["Join using your Meta Account", "Import from Instagram", "Continue as", "Next", "Public profile", "Join Threads",
          "Continue", "Done", "Skip", "Not now", "OK"]


async def join(b: Browser, user: str) -> str:
    f = ROOT / "data" / "secrets" / f"ig_session_{user}.json"
    if not f.exists():
        return f"@{user}: no saved Instagram login"
    ctx = (await b.cmd("Target.createBrowserContext"))["browserContextId"]
    try:
        await b.cmd("Storage.setCookies", {"cookies": json.loads(f.read_text(encoding="utf-8")), "browserContextId": ctx})
        t = await b.cmd("Target.createTarget", {"url": "https://www.threads.com/login", "browserContextId": ctx})
        s = (await b.cmd("Target.attachToTarget", {"targetId": t["targetId"], "flatten": True}))["sessionId"]

        async def js(e):
            return ((await b.cmd("Runtime.evaluate", {"expression": e, "returnByValue": True}, s)).get("result") or {}).get("value")

        async def press(label) -> bool:
            q = ('((want) => { const b = [...document.querySelectorAll("button,div[role=button],a[role=link],a")].filter(e => '
                 '(e.innerText || "").trim().startsWith(want) && e.getBoundingClientRect().width > 0 && e.getAttribute('
                 '"aria-disabled") !== "true").pop(); if (!b) return null; b.scrollIntoView({block: "center"}); const r = '
                 'b.getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; })(%s)' % json.dumps(label))
            xy = await js(q)
            if not xy:
                return False
            time.sleep(0.4)
            xy = await js(q)
            for k in ("mouseMoved", "mousePressed", "mouseReleased"):
                await b.cmd("Input.dispatchMouseEvent", {"type": k, "x": xy[0], "y": xy[1], "button": "left",
                                                         "clickCount": 1}, s)
            return True
        time.sleep(10)
        done, steps = False, []
        for _ in range(12):
            url = await js("location.href") or ""
            if "onboarding_complete=1" in url:          # Threads' own "you're in" address
                done = True
                break
            if "/login" not in url and "/onboarding" not in url and (await js('!!document.querySelector("[aria-label=Home], '
                                                                             'a[href=\\"/\\"] svg, [aria-label=Create]")')):
                done = True
                break
            pressed = None
            for lbl in PREFER:
                if await press(lbl):
                    pressed = lbl
                    break
            if not pressed:
                break
            steps.append(pressed)
            time.sleep(7)
        url = await js("location.href") or ""
        return f"@{user}: {'Threads profile ready' if done else 'stopped'} (steps: {', '.join(steps) or 'none'}; at {url[:60]})"
    finally:
        await b.cmd("Target.disposeBrowserContext", {"browserContextId": ctx})


async def main(users):
    async with Browser() as b:
        for u in users:
            print(await join(b, u), flush=True)

if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
