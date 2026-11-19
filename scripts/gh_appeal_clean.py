"""GitHub reinstatement request from a clean (cookie-free) browser context in the visible HookHouse Chrome: the
suspended account's half-session made the anonymous support form answer 401. Steps:
  python -m scripts.gh_appeal_clean start          -> new private window, email + reason, asks GitHub for a code
  python -m scripts.gh_appeal_clean code <code>    -> enters the code, picks Reinstatement > GitHub account, fills form
  python -m scripts.gh_appeal_clean submit         -> after the owner ticked the policy box: Continue, name, Submit
The private window's target id is kept in data/pc/gh_appeal_tab.txt."""
import asyncio
import json
import sys
import time
import urllib.request

import websockets

from engine.config import ROOT
from scripts.gh_appeal_fill import BODY, SUBJECT

CDP = "http://127.0.0.1:9333"
TAB_FILE = ROOT / "data" / "pc" / "gh_appeal_tab.txt"


async def browser_cmd(method, params=None):
    ver = json.loads(urllib.request.urlopen(f"{CDP}/json/version").read())
    async with websockets.connect(ver["webSocketDebuggerUrl"], max_size=2 ** 24) as ws:
        await ws.send(json.dumps({"id": 1, "method": method, "params": params or {}}))
        while True:
            m = json.loads(await ws.recv())
            if m.get("id") == 1:
                return m.get("result", {})


def tab_ws():
    tid = TAB_FILE.read_text().strip()
    t = next(t for t in json.loads(urllib.request.urlopen(f"{CDP}/json/list").read()) if t["id"] == tid)
    return t["webSocketDebuggerUrl"]


async def js(expr, wait=0):
    async with websockets.connect(tab_ws(), max_size=2 ** 24) as ws:
        await ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate", "params": {"expression": expr,
                                                                                     "returnByValue": True}}))
        while True:
            m = json.loads(await ws.recv())
            if m.get("id") == 1:
                v = m["result"]["result"].get("value")
                break
    if wait:
        time.sleep(wait)
    return v


async def text():
    t = await js("document.body.innerText") or ""
    return "\n".join(x for x in t.split("\n") if x.strip())


SETV = r'''(el, v) => { const p = el.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  Object.getOwnPropertyDescriptor(p, "value").set.call(el, v); el.dispatchEvent(new Event("input", {bubbles: true}));
  el.dispatchEvent(new Event("change", {bubbles: true})); }'''


async def click_text(prefix, wait=7):
    return await js('(() => { const el = [...document.querySelectorAll("a,button,div[role=button],label,li,input[type=submit]")]'
                    '.find(e => (e.innerText || e.value || "").trim().startsWith(%s)); if (!el) return "not found: " + %s; '
                    'el.click(); return "clicked"; })()' % (json.dumps(prefix), json.dumps(prefix)), wait)


async def start():
    ctx = await browser_cmd("Target.createBrowserContext")
    t = await browser_cmd("Target.createTarget", {"url": "https://help.github.com/contact/cannot_sign_in",
                                                  "browserContextId": ctx["browserContextId"], "newWindow": True})
    TAB_FILE.parent.mkdir(parents=True, exist_ok=True)
    TAB_FILE.write_text(t["targetId"])
    time.sleep(10)
    print(await js('(() => { const set = %s; const e = document.querySelector("input[type=email],input[name*=email i]");'
                   ' if (!e) return "no email field"; set(e, "hookhouse.network@gmail.com");'
                   ' const l = [...document.querySelectorAll("label")].find(x => /Account locked/.test(x.innerText));'
                   ' if (l) l.click(); return "email + reason set"; })()' % SETV))
    print(await click_text("Submit", 9))
    print((await text())[:400])


async def code(c):
    print(await js('(() => { const set = %s; const e = [...document.querySelectorAll("input")].find(i => i.type !== "hidden");'
                   ' if (!e) return "no code field"; set(e, %s); return "code set"; })()' % (SETV, json.dumps(c)), 1))
    print(await click_text("Verify", 9) if "Verify" in await text() else await click_text("Submit", 9))
    for step in ("Reinstatement request", "GitHub account or content"):
        print(step, await click_text(step, 8))
    print(await js(r'''(() => { const set = %s; const q = n => document.querySelector(`[name="${n}"]`);
      set(q("contact_next[subject]"), %s); set(q("contact_next[description]"), %s);
      set(q("contact_next[impacted-username]"), "hookhouse-network (repositories: hookhouse-network/hookhouse, hookhouse-network/hookhouse-cloud)");
      const pick = (name, rx) => { const r = [...document.querySelectorAll(`input[name="${name}"]`)].find(i =>
        rx.test((document.querySelector(`label[for="${i.id}"]`) || {}).innerText || "")); if (!r) return false;
        (document.querySelector(`label[for="${r.id}"]`) || r).click(); return r.checked; };
      const cb = document.querySelector("input[type=checkbox]"); if (cb) cb.scrollIntoView({block: "center"});
      return JSON.stringify({platform: pick("contact_next[platform]", /^GitHub$/), reason: pick("contact_next[reinstatement-reason]", /disabled/),
        contacted: pick("contact_next[previously-contacted]", /^No$/)}); })()''' % (SETV, json.dumps(SUBJECT), json.dumps(BODY))))
    await browser_cmd("Target.activateTarget", {"targetId": TAB_FILE.read_text().strip()})


async def submit():
    if not await js('(document.querySelector("input[type=checkbox]") || {}).checked'):
        print("the policy box is not ticked yet")
        return
    print(await click_text("Continue", 9))
    print(await js(r'''(() => { const set = %s; const l = [...document.querySelectorAll("label")].find(x => x.innerText.trim().startsWith("Name"));
      const e = l ? (document.getElementById(l.htmlFor) || l.parentElement.querySelector("input")) : null;
      if (!e) return "no name field"; set(e, "HookHouse Media"); return "name set"; })()''' % SETV, 1))
    print(await click_text("Submit", 10))
    t = await text()
    print("\n".join(x for x in t.split("\n") if any(k in x.lower() for k in ("error", "ticket", "thank", "received",
                                                                             "submitted", "request")))[:600])


cmd = sys.argv[1]
if __name__ == "__main__":
    asyncio.run(start() if cmd == "start" else code(sys.argv[2]) if cmd == "code" else submit())
