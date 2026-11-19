"""Switch the Instagram account in the sign-up window (data/pc/ig_signup_tab.txt) to a Creator profile, all steps
including the final "Switch to a professional profile?" Continue (owner 19 Nov: "do these all by yourself"):
Creator (its round button) > Next > Next > Personal blog (category hidden) > Done > Continue > Not now.
python -m scripts.ig_creator"""
import asyncio
import json
import time
import urllib.request

import websockets

from scripts.ig_signup import TAB

CDP = "http://127.0.0.1:9333"
RADIO_NEAR = r'''((label) => { const leaf = [...document.querySelectorAll("*")].find(e => e.children.length === 0 &&
  (e.textContent || "").trim() === label); let row = leaf; for (let k = 0; k < 7 && row && !row.querySelector(
  "input[type=radio]"); k++) row = row.parentElement; const r = row && row.querySelector("input[type=radio]");
  if (!r) return null; r.scrollIntoView({block: "center"}); const b = r.getBoundingClientRect();
  return [b.x + b.width / 2, b.y + b.height / 2, r.checked]; })(%s)'''
BUTTON = r'''((want, inDialog) => { const root = inDialog ? [...document.querySelectorAll("[role=dialog]")].pop() : document;
  if (!root) return null; const b = [...root.querySelectorAll("button,div[role=button]")].filter(e => (e.innerText || "")
  .trim() === want && e.getBoundingClientRect().width > 0).pop(); if (!b) return null; b.scrollIntoView({block: "center"});
  const r = b.getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; })(%s, %s)'''


async def main():
    tid = TAB.read_text().strip()
    t = next(t for t in json.loads(urllib.request.urlopen(f"{CDP}/json/list").read()) if t["id"] == tid)
    async with websockets.connect(t["webSocketDebuggerUrl"], max_size=2 ** 24) as ws:
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

        async def click(xy):
            for k in ("mouseMoved", "mousePressed", "mouseReleased"):
                await cmd("Input.dispatchMouseEvent", {"type": k, "x": xy[0], "y": xy[1], "button": "left", "clickCount": 1})

        async def wait_text(s, tries=14):
            for _ in range(tries):
                if s in (await js("document.body.innerText") or ""):
                    return True
                time.sleep(1.5)
            return False

        async def radio(label):
            xy = await js(RADIO_NEAR % json.dumps(label))
            if not xy:
                return False
            if not xy[2]:
                time.sleep(0.5)
                xy = await js(RADIO_NEAR % json.dumps(label))
                await click(xy)
                time.sleep(1.2)
            return bool((await js(RADIO_NEAR % json.dumps(label)) or [0, 0, False])[2])

        async def button(label, in_dialog=False):
            xy = await js(BUTTON % (json.dumps(label), json.dumps(in_dialog)))
            if not xy:
                return False
            time.sleep(0.4)
            await click(await js(BUTTON % (json.dumps(label), json.dumps(in_dialog))))
            time.sleep(3.5)
            return True

        await cmd("Page.bringToFront")
        if "Select a category" in (await js("document.body.innerText") or ""):
            steps = [("Creator", True)]                   # resume a switch that stopped at the category page
        else:
            await cmd("Page.navigate", {"url": "https://www.instagram.com/accounts/convert_to_professional_account/"})
            if not await wait_text("Which best describes you"):
                print("Creator chooser did not open")
                return
            steps = [("Creator", await radio("Creator")), ("Next", await button("Next")), ("Next", await button("Next"))]
        await wait_text("Personal blog")
        ok = False
        for _ in range(4):                                # the category list renders late: retry the tick
            time.sleep(1.5)
            ok = await radio("Personal blog")
            if ok:
                break
        steps.append(("Personal blog", ok))
        sw = await js('(() => { const c = [...document.querySelectorAll("input[type=checkbox],[role=switch]")][0]; if (!c) '
                      'return null; const b = c.getBoundingClientRect(); return [b.x + b.width / 2, b.y + b.height / 2, '
                      'c.checked === true || c.getAttribute("aria-checked") === "true"]; })()')
        if sw and sw[2]:                                  # keep the category off the profile
            await click(sw)
            time.sleep(1)
        steps.append(("Done", await button("Done")))
        await wait_text("Switch to a professional profile", 6)
        steps.append(("Continue", await button("Continue", in_dialog=True)))
        time.sleep(4)
        await button("Not now")
        ready = await wait_text("creator profile is ready", 6)
        print(" | ".join(f"{k}: {'ok' if v else 'FAILED'}" for k, v in steps), "| creator:", "ready" if ready else "check")

if __name__ == "__main__":
    asyncio.run(main())
