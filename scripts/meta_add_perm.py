"""Meta app dashboard, use case 'Permissions and features': click the row's "+ Add" button for a permission.
python -m scripts.meta_add_perm <permission> [<permission> ...]"""
import asyncio
import json
import sys
import time
import urllib.request

import websockets

FIND = '''(() => { const want = %s;
  const leaf = [...document.querySelectorAll("body *")].find(e => e.children.length === 0 && (e.innerText || "").trim() === want);
  if (!leaf) return {err: "row not found"};
  let row = leaf;
  for (let i = 0; i < 10 && row; i++) {
    const b = [...row.querySelectorAll("div[role=button],button,a")].find(x => /^\\+?\\s*A(dd|\\u2026)/.test((x.innerText || "").trim()) || (x.getAttribute("aria-label") || "") === "Add");
    if (b) { b.scrollIntoView({block: "center"}); const r = b.getBoundingClientRect(); return {xy: [r.x + r.width / 2, r.y + r.height / 2], txt: (b.innerText || "").trim()}; }
    if (/Ready for testing/.test(row.innerText || "") && row !== leaf) return {err: "already ready"};
    row = row.parentElement;
  }
  return {err: "no Add button"}; })()'''


async def main(perms):
    tab = [t for t in json.loads(urllib.request.urlopen("http://127.0.0.1:9333/json/list").read())
           if t["type"] == "page"][0]
    async with websockets.connect(tab["webSocketDebuggerUrl"], max_size=2 ** 24) as ws:
        n = 0

        async def cmd(method, params=None):
            nonlocal n
            n += 1
            await ws.send(json.dumps({"id": n, "method": method, "params": params or {}}))
            while True:
                m = json.loads(await ws.recv())
                if m.get("id") == n:
                    return m.get("result", {})
        for p in perms:
            r = await cmd("Runtime.evaluate", {"expression": FIND % json.dumps(p), "returnByValue": True})
            v = (r.get("result") or {}).get("value") or {}
            if not v.get("xy"):
                print(p, ":", v.get("err"))
                continue
            time.sleep(0.6)
            r = await cmd("Runtime.evaluate", {"expression": FIND % json.dumps(p), "returnByValue": True})
            xy = ((r.get("result") or {}).get("value") or {}).get("xy") or v["xy"]
            for t in ("mouseMoved", "mousePressed", "mouseReleased"):
                await cmd("Input.dispatchMouseEvent", {"type": t, "x": xy[0], "y": xy[1], "button": "left",
                                                       "clickCount": 1})
            print(p, ": clicked", v.get("txt"))
            time.sleep(3)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
