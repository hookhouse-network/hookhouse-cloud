"""Co-pilot browser (owner, 13 Nov 2026: "guide me step by step using playwright, you are typing everything, i set
up the passwords only").

A normal Chrome window (own profile in data/browser_profile) that Claude drives through Playwright: it opens pages,
reads them, clicks and types. The owner types only passwords, phone/email codes and "I'm not a robot" checks.
Safety:
- It never types into a password field and never reads one (refused in code).
- Keys shown on a page never leave this process: they are checked with the service's own API and saved straight
  into .env; everything Claude reads (text and screenshots) has key-like strings hidden.
- Listens on 127.0.0.1 only, with a random token kept in data/state.

Start (keeps running):   python -m engine.copilot serve
Commands (one-shot):     python -m engine.copilot goto URL | look | click N|"text" | type N "text" | press Key |
                         shot | tabs | tab N | grab [KEY] | scroll [down|up] | wait SECONDS | back
"""
from __future__ import annotations

import json
import os
import queue
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .config import ROOT, load_env

PROFILE = ROOT / "data" / "browser_profile"
STATE = ROOT / "data" / "state" / "copilot.json"
SHOT = ROOT / "data" / "review" / "copilot.png"
CDP_PORT = 9333
JOBS: "queue.Queue[tuple[dict, queue.Queue]]" = queue.Queue()

# Everything Claude reads goes through this: key-like strings are hidden (over-hiding is fine)
_SECRET_RES = [re.compile(p) for p in (
    r"\b\d{8,10}:[A-Za-z0-9_-]{35}\b", r"\bAIza[0-9A-Za-z_\-]{35}\b", r"\bgsk_[A-Za-z0-9]{30,}\b",
    r"\bsk-or-v1-[0-9a-f]{20,}\b", r"\bnvapi-[A-Za-z0-9_\-]{20,}\b", r"\bhf_[A-Za-z0-9]{20,}\b",
    r"\bGOCSPX-[A-Za-z0-9_\-]{10,}\b", r"\bEAA[A-Za-z0-9]{40,}\b", r"\bghp_[A-Za-z0-9]{20,}\b",
    r"\bgithub_pat_[A-Za-z0-9_]{20,}\b", r"\b[A-Za-z0-9_\-]{40,}\b", r"\b[0-9a-f]{32}\b")]
_BLUR_JS = r"""(pats) => {
  const res = pats.map(p => new RegExp(p));
  const hit = s => res.some(r => r.test(s || ''));
  const out = [];
  const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let n; while ((n = w.nextNode())) { if (hit(n.nodeValue) && n.parentElement) out.push(n.parentElement); }
  document.querySelectorAll('input, textarea').forEach(e => { if (e.type === 'password' || hit(e.value)) out.push(e); });
  out.forEach(e => { e.dataset.cpBlur = e.style.filter || ''; e.style.filter = 'blur(9px)'; });
  return out.length; }"""
_UNBLUR_JS = """() => document.querySelectorAll('[data-cp-blur]').forEach(e => { e.style.filter = e.dataset.cpBlur;
  delete e.dataset.cpBlur; })"""
# Numbered list of what can be clicked or typed into (visible only); password fields are listed but never readable
_LOOK_JS = r"""() => {
  document.querySelectorAll('[data-cp]').forEach(e => e.removeAttribute('data-cp'));
  const sel = 'a[href], button, input, textarea, select, [role=button], [role=link], [role=tab], [role=menuitem],' +
              '[role=option], [role=checkbox], [role=radio], [role=switch], [role=combobox], [contenteditable=true],' +
              '[contenteditable=""], summary, label';
  const vis = e => { const r = e.getBoundingClientRect(); const s = getComputedStyle(e);
    return r.width > 2 && r.height > 2 && r.bottom > 0 && r.right > 0 && r.top < innerHeight && r.left < innerWidth &&
           s.visibility !== 'hidden' && s.display !== 'none' && s.opacity !== '0'; };
  const items = []; let i = 0;
  for (const e of document.querySelectorAll(sel)) {
    if (!vis(e) || items.length >= 160) continue;
    const tag = e.tagName.toLowerCase(); const type = (e.getAttribute('type') || '').toLowerCase();
    if (tag === 'input' && type === 'hidden') continue;
    let label = (e.getAttribute('aria-label') || e.innerText || e.getAttribute('title') || e.getAttribute('placeholder') ||
                 e.getAttribute('name') || e.getAttribute('alt') || '').replace(/\s+/g, ' ').trim().slice(0, 90);
    if (!label && e.id) { const l = document.querySelector('label[for="' + e.id + '"]'); if (l) label = l.innerText.trim(); }
    let kind = tag + (type ? ':' + type : '');
    if (e.getAttribute('role')) kind += '[' + e.getAttribute('role') + ']';
    if (e.isContentEditable) kind = 'textbox';
    let value = '';
    if (type === 'password') value = '(password: owner types)';
    else if (tag === 'input' || tag === 'textarea') value = (e.value || '').slice(0, 60);
    else if (tag === 'select') value = e.options[e.selectedIndex] ? e.options[e.selectedIndex].text : '';
    if (type === 'checkbox' || type === 'radio') value = e.checked ? 'checked' : 'unchecked';
    if (e.getAttribute('aria-checked')) value = 'aria-checked=' + e.getAttribute('aria-checked');
    if (e.disabled || e.getAttribute('aria-disabled') === 'true') kind += ' (disabled)';
    e.setAttribute('data-cp', String(++i));
    items.push([i, kind, label, value]);
  }
  const text = (document.body ? document.body.innerText : '').replace(/\n{3,}/g, '\n\n').slice(0, 6000);
  return {items, text}; }"""


def redact(s: str) -> str:
    for r in _SECRET_RES:
        s = r.sub("[hidden key]", s)
    return s


def _chrome() -> str:
    cands = [shutil.which("chrome"), shutil.which("msedge")]
    for base in (os.environ.get("PROGRAMFILES", ""), os.environ.get("PROGRAMFILES(X86)", ""),
                 os.environ.get("LOCALAPPDATA", "")):
        cands += [os.path.join(base, "Google", "Chrome", "Application", "chrome.exe"),
                  os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe")]
    for c in cands:
        if c and os.path.exists(c):
            return c
    raise RuntimeError("Chrome or Edge not found")


# ------------------------------------------------------------------------------------------------ the browser
class Pilot:
    def __init__(self, ctx):
        self.ctx = ctx
        self.page = ctx.pages[0] if ctx.pages else ctx.new_page()
        self.tried: set = set()

    def _live(self):
        if self.page.is_closed():
            pages = [p for p in self.ctx.pages if not p.is_closed()]
            self.page = pages[-1] if pages else self.ctx.new_page()
        return self.page

    def _el(self, target: str):
        p = self._live()
        if str(target).isdigit():
            return p.locator(f'[data-cp="{target}"]').first
        loc = p.get_by_role("button", name=target, exact=False).filter(visible=True)
        if loc.count() == 0:
            loc = p.get_by_text(target, exact=False).filter(visible=True)
        return loc.last

    def autosave(self) -> list[str]:
        """Keys visible on a developer page: checked with the service, saved to .env. Never returned."""
        from . import setup_steps as ss
        p = self._live()
        host = urlparse(p.url).hostname or ""
        try:
            text = p.evaluate("() => { const t = [document.body ? document.body.innerText : ''];"
                              "document.querySelectorAll('input, textarea').forEach(e => { if (e.type !== 'password')"
                              " t.push(e.value || ''); }); return t.join('\\n'); }")
        except Exception:  # noqa: BLE001 - page navigating
            return []
        saved = []
        for name, spec in ss.KEYS.items():
            have = [v for v in (os.environ.get(name), ss.env_file_value(name)) if v and not str(v).lstrip().startswith("#")]
            if not spec[2] or host not in spec[3] or have:   # "# placeholder" counts as empty
                continue
            for c in ss.candidates(name, text, p.url):
                if (name, c) in self.tried:
                    continue
                self.tried.add((name, c))
                ok, msg = ss.submit_key(name, c)
                if ok:
                    os.environ[name] = c
                    saved.append(f"{name} saved to .env ({msg})")
                    break
        return saved

    def do(self, cmd: dict) -> dict:
        op, a, b = cmd.get("op"), cmd.get("a", ""), cmd.get("b", "")
        p = self._live()
        if op == "goto":
            try:
                p.goto(a if "://" in a else "https://" + a, wait_until="domcontentloaded", timeout=45000)
            except Exception as e:  # noqa: BLE001 - slow pages keep loading
                return {"ok": True, "note": f"still loading ({type(e).__name__})", "url": p.url}
            p.wait_for_timeout(1500)
            p.bring_to_front()
            return {"ok": True, "url": p.url, "title": p.title()}
        if op == "look":
            data = p.evaluate(_LOOK_JS)
            rows = [f"[{i}] {kind} '{redact(label)}'" + (f" = {redact(val)}" if val else "")
                    for i, kind, label, val in data["items"]]
            return {"ok": True, "url": redact(p.url), "title": redact(p.title()), "saved": self.autosave(),
                    "elements": rows, "text": redact(data["text"])}
        if op == "click":
            el = self._el(a)
            el.scroll_into_view_if_needed(timeout=8000)
            el.click(timeout=10000)
            p.wait_for_timeout(1200)
            return {"ok": True, "url": redact(p.url), "saved": self.autosave()}
        if op == "clickxy":                       # x, y in screenshot pixels
            p.mouse.click(float(a), float(b))
            p.wait_for_timeout(1200)
            return {"ok": True, "url": redact(p.url), "saved": self.autosave()}
        if op == "type":
            el = self._el(a)
            kind = (el.get_attribute("type") or "").lower()
            auto = (el.get_attribute("autocomplete") or "").lower()
            if kind == "password" or "password" in auto:
                return {"ok": False, "error": "password field: the owner types this one"}
            if el.evaluate("e => e.isContentEditable"):
                el.click(timeout=10000)
                p.keyboard.type(b, delay=25)
            else:
                el.fill(b, timeout=10000)
            return {"ok": True}
        if op == "press":
            p.keyboard.press(a)
            p.wait_for_timeout(900)
            return {"ok": True, "url": redact(p.url), "saved": self.autosave()}
        if op == "shot":
            pats = [r.pattern for r in _SECRET_RES]
            try:
                p.evaluate(_BLUR_JS, pats)
                p.screenshot(path=str(SHOT))
            finally:
                p.evaluate(_UNBLUR_JS)
            return {"ok": True, "file": str(SHOT)}
        if op == "tabs":
            return {"ok": True, "tabs": [f"[{i}] {redact(t.url)}" + (" (current)" if t == p else "")
                                         for i, t in enumerate(self.ctx.pages)]}
        if op == "tab":
            self.page = self.ctx.pages[int(a)]
            self.page.bring_to_front()
            return {"ok": True, "url": redact(self.page.url)}
        if op == "newtab":                                # keep the current tab (e.g. a form the owner is filling)
            self.page = self.ctx.new_page()
            if a:
                self.page.goto(a, timeout=60000)
            self.page.bring_to_front()
            return {"ok": True, "url": redact(self.page.url)}
        if op == "grab":
            return {"ok": True, "saved": self.autosave() or ["nothing new found on this page"]}
        if op == "scroll":
            p.mouse.wheel(0, -700 if a == "up" else 700)
            p.wait_for_timeout(600)
            return {"ok": True}
        if op == "wait":
            p.wait_for_timeout(int(float(a or 2) * 1000))
            return {"ok": True, "url": redact(p.url), "saved": self.autosave()}
        if op == "back":
            p.go_back()
            return {"ok": True, "url": redact(p.url)}
        if op == "upload":                         # click the element that opens a file picker, give it a file
            path = str(Path(b).resolve())
            if not path.startswith(str(ROOT.resolve())):
                return {"ok": False, "error": "only files inside the project can be uploaded"}
            with p.expect_file_chooser(timeout=15000) as fc:
                self._el(a).click(timeout=10000)
            fc.value.set_files(path)
            p.wait_for_timeout(2000)
            return {"ok": True}
        if op == "select":
            self._el(a).select_option(label=b)
            return {"ok": True}
        return {"ok": False, "error": f"unknown op {op}"}


def serve() -> None:
    from playwright.sync_api import sync_playwright
    load_env()
    PROFILE.mkdir(parents=True, exist_ok=True)
    STATE.parent.mkdir(parents=True, exist_ok=True)
    SHOT.parent.mkdir(parents=True, exist_ok=True)
    import socket
    with socket.socket() as so:
        running = so.connect_ex(("127.0.0.1", CDP_PORT)) == 0      # the window is already open: reconnect to it
    chrome = None if running else subprocess.Popen(
        [_chrome(), f"--remote-debugging-port={CDP_PORT}", f"--user-data-dir={PROFILE}", "--no-first-run",
         "--no-default-browser-check", "--start-maximized", "about:blank"])
    token = secrets.token_urlsafe(18)

    class H(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            if self.headers.get("X-Token") != token:
                self.send_response(403)
                self.end_headers()
                return
            cmd = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            box: queue.Queue = queue.Queue()
            JOBS.put((cmd, box))
            body = json.dumps(box.get(timeout=120), ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    STATE.write_text(json.dumps({"port": srv.server_address[1], "token": token}), encoding="utf-8")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    with sync_playwright() as pw:
        browser = None
        for _ in range(40):
            try:
                browser = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{CDP_PORT}")
                break
            except Exception:  # noqa: BLE001 - Chrome still starting
                time.sleep(0.5)
        if browser is None:
            raise RuntimeError("couldn't connect to Chrome")
        pilot = Pilot(browser.contexts[0])
        print("co-pilot ready", flush=True)
        while browser.is_connected() and (chrome is None or chrome.poll() is None):
            try:
                cmd, box = JOBS.get(timeout=0.3)
            except queue.Empty:
                continue
            try:
                box.put(pilot.do(cmd))
            except Exception as e:  # noqa: BLE001 - report, keep running
                box.put({"ok": False, "error": redact(f"{type(e).__name__}: {e}")[:600]})
    srv.shutdown()
    STATE.unlink(missing_ok=True)


def send(op: str, a: str = "", b: str = "") -> dict:
    import requests
    st = json.loads(STATE.read_text(encoding="utf-8"))
    r = requests.post(f"http://127.0.0.1:{st['port']}/", json={"op": op, "a": a, "b": b},
                      headers={"X-Token": st["token"]}, timeout=130)
    return r.json()


def main(argv=None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] == "serve":
        serve()
        return
    res = send(argv[0], argv[1] if len(argv) > 1 else "", argv[2] if len(argv) > 2 else "")
    if argv[0] == "look" and res.get("ok"):
        print(f"URL: {res['url']}\nTITLE: {res['title']}")
        for s in res.get("saved") or []:
            print("SAVED:", s)
        print("--- elements ---\n" + "\n".join(res["elements"]))
        print("--- text ---\n" + res["text"])
    else:
        print(json.dumps(res, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
