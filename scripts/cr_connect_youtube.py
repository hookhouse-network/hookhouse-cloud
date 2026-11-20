"""Connect a YouTube channel in Content Rewards (Settings > Accounts > Connect account > YouTube), owner 20 Nov 2026
"do all the steps by yourself". Drives the Google pop-up in the HookHouse Chrome: picks the HookHouse account, the named
channel, then Continue/Allow. Never types a password.  python -m scripts.cr_connect_youtube "Stream Clips GTA" """
import asyncio
import json
import sys
import urllib.request

import websockets

from engine.kick import CDP, _Tab
from scripts.yt_create_channel import say

ACCOUNT = "hookhouse.network@gmail.com"


class _Attach(_Tab):
    def __init__(self, target: dict):            # an already-open window (the pop-up)
        self.t, self.n, self.url = target, 0, ""

    async def __aexit__(self, *a):                # the pop-up closes itself when Google is done
        try:
            await self.ws.close()
        except Exception:
            pass


def pages() -> list:
    return [t for t in json.loads(urllib.request.urlopen(f"{CDP}/json/list", timeout=10).read()) if t["type"] == "page"]


async def main(channel: str) -> None:
    async with _Tab("https://contentrewards.com/c/settings") as tab:
        await asyncio.sleep(10)
        for lab in ("Accounts", "Connect account", "YouTube"):
            say(f"{lab}: {await tab.click_text(lab)}")
            await asyncio.sleep(4)
        before = {t["id"] for t in pages()}
        say(f"Open YouTube: {await tab.click_text('Open YouTube')}")
        pop = None
        for _ in range(15):
            await asyncio.sleep(2)
            new = [t for t in pages() if t["id"] not in before]
            if new:
                pop = new[0]
                break
        if not pop:
            say("no pop-up window opened")
            return
        try:
            async with _Attach(pop) as p:
                ticked = False
                for step in range(20):
                    await asyncio.sleep(5)
                    try:
                        href = str(await p.js("location.href"))
                        text = await p.js("document.body.innerText") or ""
                    except Exception:
                        say("pop-up closed")
                        break
                    if "accounts.google" not in href:
                        say(f"pop-up left Google: {href[:90]}")
                        if "contentrewards" in href:
                            break
                    if await p.js("!!document.querySelector('input[type=password]')"):
                        say("Google asks for the password: owner must sign in")
                        return
                    say(f"step {step}: " + " / ".join(x for x in text.splitlines() if x.strip())[:300])
                    if "Select what" in text:          # tick every unticked permission box, then Continue
                        boxes = await p.js("""[...document.querySelectorAll('input[type=checkbox]')].map(b => {
                          const r = (b.closest('label') || b.parentElement).getBoundingClientRect();
                          return [b.checked, r.x + 12, r.y + r.height / 2, b.getAttribute('aria-label') || ''];
                        })""") or []
                        say(f"  boxes: {[(c, n[:30]) for c, _, _, n in boxes]}")
                        for checked, x, y, _ in boxes:
                            if not checked:
                                for k in ("mouseMoved", "mousePressed", "mouseReleased"):
                                    await p.cmd("Input.dispatchMouseEvent", {"type": k, "x": x, "y": y,
                                                                             "button": "left", "clickCount": 1})
                                await asyncio.sleep(0.5)
                        await asyncio.sleep(1)
                        now = await p.js("[...document.querySelectorAll('input[type=checkbox]')].map(b => b.checked)")
                        say(f"  ticked now: {now}")
                        if now and all(now):
                            say(f"  pressed Continue: {await p.click_text('Continue')}")
                        continue
                    picks = (channel, ACCOUNT) if "Choose" in text else ()
                    for lab in picks + (() if ticked else ("Select all",)) + ("Continue", "Allow"):
                        if lab in text and await p.click_text(lab):
                            ticked = ticked or lab == "Select all"   # a second press would untick them again
                            say(f"  pressed {lab}")
                            break
        except websockets.exceptions.ConnectionClosed:
            say("pop-up closed")
        for _ in range(3):
            await asyncio.sleep(4)
            txt = (await tab.js("document.body.innerText") or "").replace("\n", " / ")
            i = txt.find("Agencies you work with")
            say("right after: " + txt[i + 50:i + 650])
        await tab.js("location.reload()")
        await asyncio.sleep(10)
        await tab.click_text("Accounts")
        await asyncio.sleep(4)
        txt = (await tab.js("document.body.innerText") or "").replace("\n", " / ")
        i = txt.find("Connect account")
        say("accounts now: " + txt[i:i + 600])


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
