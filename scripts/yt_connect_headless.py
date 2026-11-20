"""Connect a YouTube channel to HookHouse without a visible window (owner 20 Nov 2026: "do all the steps by
yourself"). Runs the normal connect_youtube OAuth flow (our own Google Cloud app, local 127.0.0.1 redirect) and drives
Google's consent pages in the headless HookHouse Chrome: picks the HookHouse Google account, then the named channel,
then Continue / Allow. Never types a password; stops if Google asks for one.
python -m scripts.yt_connect_headless <channel id in config> "<YouTube channel name>"  """
import asyncio
import json
import sys
import threading

from engine.config import load_env
from engine.connect import connect_youtube
from engine.kick import _Tab
from scripts.yt_create_channel import say

ACCOUNT = "hookhouse.network@gmail.com"


async def drive(url: str, channel_name: str) -> None:
    async with _Tab(url) as tab:
        ticked = False
        for step in range(25):
            await asyncio.sleep(5)
            href = str(await tab.js("location.href"))
            if href.startswith("http://127.0.0.1"):
                say("consent done")
                return
            text = await tab.js("document.body.innerText") or ""
            if await tab.js("!!document.querySelector('input[type=password]')"):
                say("Google asks for the password: the owner must sign in once")
                return
            short = " / ".join(x for x in text.splitlines() if x.strip())[:600]
            say(f"step {step}: {short}")
            if "verified this app" in text:              # our own app's "unverified" notice: Go to <app>, else Advanced
                go = [x.strip() for x in text.splitlines() if x.strip().startswith("Go to ")]
                lab = go[0] if go else "Advanced"
                say(f"  pressed {lab}: {await tab.click_text(lab)}")
                continue
            picks = (channel_name, ACCOUNT) if "Choose your account" in text or "Choose an account" in text else ()
            for label in picks + (() if ticked else ("Select all",)) + ("Continue", "Allow"):
                if label in text and await tab.click_text(label):
                    ticked = ticked or label == "Select all"
                    say(f"  pressed {label}")
                    break
        say("consent did not finish")


def main(cid: str, channel_name: str) -> None:
    load_env()

    def opener(url):
        threading.Thread(target=lambda: asyncio.run(drive(url, channel_name)), daemon=True).start()
    ok = connect_youtube(cid, timeout_s=200, opener=opener)
    say(f"connected: {ok}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
    sys.exit(0)
