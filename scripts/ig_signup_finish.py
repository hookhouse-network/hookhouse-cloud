"""Finish an Instagram sign-up that scripts/ig_signup started (HookHouse Chrome), without the owner (owner 19 Nov:
"add key for password and birthdate so you can use that and do not have my dependency"):
- password: IG_SIGNUP_PASSWORD from .env, written by the owner, the same for every account (never printed or uploaded);
- birthday: IG_SIGNUP_BIRTHDATE (YYYY-MM-DD) from .env, filled by the owner;
- confirmation code: read from the HookHouse Gmail inbox (the browser is signed in), sent to the account's alias.
python -m scripts.ig_signup_finish <channel_id>"""
import asyncio
import json
import os
import re
import sys
import time
import urllib.request

import websockets

from engine.config import ROOT, channel, load_env
from scripts.ig_signup import SETL, TAB, js

CDP = "http://127.0.0.1:9333"
ACCOUNTS = ROOT / "data" / "secrets" / "ig_accounts.json"
SELECT = r'''((which, v) => { const s = [...document.querySelectorAll("select")].find(x => ((x.getAttribute("title") ||
  x.getAttribute("aria-label") || x.name || "") + " " + ((x.closest("label") || {}).innerText || "")).toLowerCase()
  .includes(which)); if (!s) return null; const opt = [...s.options].find(o => o.value === v || o.text.trim() === v);
  if (!opt) return "no option " + v; Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value").set.call(s, opt.value);
  s.dispatchEvent(new Event("change", {bubbles: true})); return s.value === opt.value; })(%s, %s)'''
CLICK = r'''((want) => { const b = [...document.querySelectorAll("button,div[role=button]")].filter(e => (e.innerText || "")
  .trim() === want && e.getBoundingClientRect().width > 0 && !e.disabled && e.getAttribute("aria-disabled") !== "true").pop();
  if (!b) return false; b.click(); return true; })(%s)'''
CODE_BOX = r'''((v) => { const ins = [...document.querySelectorAll("input[type=text],input[type=number],input[type=tel]")]
  .filter(e => e.offsetParent !== null && !((e.closest("label") || {}).innerText || "").trim()); const e = ins.pop();
  if (!e) return false; Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(e, v);
  e.dispatchEvent(new Event("input", {bubbles: true})); e.dispatchEvent(new Event("change", {bubbles: true}));
  return e.value === v; })(%s)'''
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November",
          "December"]


def accounts() -> dict:
    try:
        return json.loads(ACCOUNTS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def password_for(cid: str) -> str:
    """The owner's chosen password from .env (IG_SIGNUP_PASSWORD), the same for every new account (owner 19 Nov)."""
    return os.environ.get("IG_SIGNUP_PASSWORD", "")


async def _real_click(xy) -> None:
    import websockets as _ws
    tid = TAB.read_text().strip()
    t = next(t for t in json.loads(urllib.request.urlopen(f"{CDP}/json/list").read()) if t["id"] == tid)
    async with _ws.connect(t["webSocketDebuggerUrl"], max_size=2 ** 24) as ws:
        for i, k in enumerate(("mouseMoved", "mousePressed", "mouseReleased")):
            await ws.send(json.dumps({"id": i + 1, "method": "Input.dispatchMouseEvent", "params": {
                "type": k, "x": xy[0], "y": xy[1], "button": "left", "clickCount": 1}}))
            while json.loads(await ws.recv()).get("id") != i + 1:
                pass


async def _combo(label: str, value: str) -> bool:
    """Instagram's custom drop-downs (div role=combobox aria-label 'Select Month'): open, then click the option."""
    xy = await js('(() => { const c = document.querySelector(%s); if (!c) return null; c.scrollIntoView({block: "center"});'
                  ' const r = c.getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; })()'
                  % json.dumps(f'[role=combobox][aria-label="{label}"]'))
    if not xy:
        return False
    await _real_click(xy)
    time.sleep(1.2)
    oxy = await js('((v) => { const o = [...document.querySelectorAll("[role=option]")].find(e => (e.innerText || "")'
                   '.trim() === v && e.getBoundingClientRect().width > 0); if (!o) return null; o.scrollIntoView({block: '
                   '"center"}); const r = o.getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; })(%s)'
                   % json.dumps(value))
    if not oxy:
        return False
    await _real_click(oxy)
    time.sleep(0.8)
    return value in (await js('(document.querySelector(%s) || {}).innerText || ""'
                               % json.dumps(f'[role=combobox][aria-label="{label}"]')) or "")


async def birthday(y: str, m: str, d: str) -> bool:
    month = MONTHS[int(m) - 1]
    if await js('!!document.querySelector(' + json.dumps('[role=combobox][aria-label="Select Month"]') + ')'):
        return all([await _combo("Select Month", month), await _combo("Select Day", str(int(d))),
                    await _combo("Select Year", y)])
    if not await js('document.querySelectorAll("select").length >= 3'):
        return False
    ok = [await js(SELECT % (json.dumps("month"), json.dumps(str(int(m))))) or
          await js(SELECT % (json.dumps("month"), json.dumps(month))),
          await js(SELECT % (json.dumps("day"), json.dumps(str(int(d))))),
          await js(SELECT % (json.dumps("year"), json.dumps(y)))]
    return all(v is True for v in ok)


async def gmail_code(alias: str, since: float, wait_s: int = 180) -> str | None:
    """Newest 'NNNNNN is your Instagram code' mail to this alias, from the HookHouse Gmail tab (main profile)."""
    tabs = [t for t in json.loads(urllib.request.urlopen(f"{CDP}/json/list").read()) if t["type"] == "page"]
    t = next((t for t in tabs if "mail.google.com" in t["url"]), None)
    if t is None:
        req = urllib.request.Request(f"{CDP}/json/new?https://mail.google.com/mail/u/0/", method="PUT")
        t = json.loads(urllib.request.urlopen(req).read())
        time.sleep(10)
    # 19 Nov: Gmail search can't match these mails by the +alias address; sign-ups run one at a time, so the newest
    # Instagram code from the last 15 minutes belongs to the account being made
    q = urllib.parse.quote("from:instagram newer_than:15m")
    async with websockets.connect(t["webSocketDebuggerUrl"], max_size=2 ** 24) as ws:
        n = 0

        async def ev(e):
            nonlocal n
            n += 1
            await ws.send(json.dumps({"id": n, "method": "Runtime.evaluate", "params": {"expression": e,
                                                                                         "returnByValue": True}}))
            while True:
                r = json.loads(await ws.recv())
                if r.get("id") == n:
                    return (r.get("result", {}).get("result") or {}).get("value")
        while time.time() - since < wait_s:
            await ev(f'location.href = "https://mail.google.com/mail/u/0/#search/{q}"')
            time.sleep(8)
            m = re.search(r"(\d{6})\s+is\s+your\s+Instagram\s+code",
                          await ev('(document.querySelector("[role=main]") || document.body).innerText') or "")
            if m:
                return m.group(1)
            time.sleep(7)
    return None


async def press_any(labels) -> bool:
    """Real mouse click on the first visible, enabled button with one of these labels."""
    for lbl in labels:
        q = (r'''((want) => { const b = [...document.querySelectorAll("button,div[role=button]")].filter(e => (e.innerText
          || "").trim() === want && e.getBoundingClientRect().width > 0 && !e.disabled && e.getAttribute("aria-disabled")
          !== "true").pop(); if (!b) return null; b.scrollIntoView({block: "center"}); const r = b.getBoundingClientRect();
          return [r.x + r.width / 2, r.y + r.height / 2]; })(%s)''' % json.dumps(lbl))
        if await js(q):
            time.sleep(0.5)
            await _real_click(await js(q))
            return True
    return False


async def main(cid: str):
    load_env()
    born = os.environ.get("IG_SIGNUP_BIRTHDATE", "").strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", born) or len(password_for(cid)) < 6:
        print("Fill IG_SIGNUP_PASSWORD and IG_SIGNUP_BIRTHDATE (YYYY-MM-DD) in .env once, then run this again")
        return
    y, m, d = born.split("-")
    ch = channel(cid)
    alias = f"hookhouse.network+{cid.replace('_', '')}@gmail.com"
    user = await js('([...document.querySelectorAll("input")].find(i => ((i.closest("label") || {}).innerText || "")'
                    '.trim().startsWith("Username")) || {}).value || ""')
    print("password set:", await js(SETL % (json.dumps("Password"), json.dumps(password_for(cid)))))
    if await birthday(y, m, d):                       # newer form: birthday on the same page
        print("birthday set")
    since = time.time()
    if not await press_any(("Submit", "Sign up", "Next")):       # 19 Nov: only a real click registers
        print("Sign up button not found / not enabled")
        return
    time.sleep(8)
    if await birthday(y, m, d):                       # older form: birthday on the next page
        print("birthday set (2nd page)")
        await js(CLICK % json.dumps("Next"))
        time.sleep(8)
    page = await js("document.body.innerText") or ""        # 19 Nov: the hidden old form stays at the top of the text
    if "confirmation code" not in page.lower():
        print("no confirmation-code step yet; page says:", page.replace("\n", " / ")[:200])
        return
    code = await gmail_code(alias, since)
    if not code:
        print("no Instagram code in the HookHouse Gmail yet")
        return
    ok = await js(r'''((v) => { const e = [...document.querySelectorAll("input")].find(i => /code/i.test((i.name || "") +
      (i.getAttribute("aria-label") || "") + (i.placeholder || ""))); if (!e) return false;
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(e, v);
      e.dispatchEvent(new Event("input", {bubbles: true})); return true; })(%s)''' % json.dumps(code))
    if not ok:                                         # 19 Nov: the code box has no label: the last visible text box
        ok = await js(CODE_BOX % json.dumps(code)) is True
    print("code entered:", ok)
    await press_any(("Continue", "Next", "Confirm"))
    time.sleep(12)
    acc = accounts()
    acc.setdefault(cid, {}).update(username=user, email=alias, created=time.strftime("%Y-%m-%d %H:%M"),
                                   name=ch["name"])
    ACCOUNTS.write_text(json.dumps(acc, indent=1), encoding="utf-8")
    page = (await js("document.body.innerText") or "")[:200].replace("\n", " / ")
    print(f"{cid}: @{user} submitted; page now: {page}")

import urllib.parse  # noqa: E402

if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
