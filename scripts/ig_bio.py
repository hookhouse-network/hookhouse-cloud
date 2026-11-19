"""Set the Instagram bio of the account logged in on the visible HookHouse Chrome to brand_art.BIOS (native value
setter + input event: typing scrambled the text) and press Submit; reads the saved value back.
python -m scripts.ig_bio <channel_id>"""
import asyncio
import json
import sys
import time
import urllib.request

import websockets

from engine import brand_art

SET = r'''((v) => { const t = document.querySelector("textarea"); if (!t) return "no box";
  Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value").set.call(t, v);
  t.dispatchEvent(new Event("input", {bubbles: true})); t.dispatchEvent(new Event("change", {bubbles: true}));
  return t.value === v ? "set" : "mismatch"; })(%s)'''
SUBMIT = r'''(() => { const b = [...document.querySelectorAll("div[role=button],button")].find(e => (e.innerText || "").trim() === "Submit");
  if (!b) return "no submit"; b.click(); return "submitted"; })()'''


async def main(cid):
    tab = next(t for t in json.loads(urllib.request.urlopen("http://127.0.0.1:9333/json/list").read())
               if t["type"] == "page" and "instagram.com" in t["url"])
    async with websockets.connect(tab["webSocketDebuggerUrl"], max_size=2 ** 24) as ws:
        n = 0

        async def js(e):
            nonlocal n
            n += 1
            await ws.send(json.dumps({"id": n, "method": "Runtime.evaluate", "params": {"expression": e,
                                                                                         "returnByValue": True}}))
            while True:
                r = json.loads(await ws.recv())
                if r.get("id") == n:
                    return r["result"]["result"].get("value")
        bio = brand_art.ig_bio(cid)
        print("bio:", await js(SET % json.dumps(bio)))
        time.sleep(1)
        print(await js(SUBMIT))
        time.sleep(4)
        await js('location.reload()')
        time.sleep(8)
        saved = await js('(document.querySelector("textarea") || {}).value')
        sys.stdout.buffer.write(f"saved bio matches: {saved == bio}\n---\n{saved}\n".encode("utf-8"))


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
