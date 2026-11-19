"""Logged-in browser jobs in the cloud (owner approved 18 Nov 2026: "no PC dependency"; "Yes, move sessions").

Chrome encrypts its cookie store with a Windows-only key, so the PC profile folder cannot simply be copied to the Linux
cloud machine. Instead:
  PC helper  -> reads the HookHouse Chrome's cookies over its DevTools port (only the sites below), encrypts them with
                the cloud memory key (STATE_KEY, Fernet) and stores them in the PRIVATE repo (asset browser-session.enc)
                every few hours while the PC is on (and after the owner logs in somewhere).
  cloud tick -> starts the runner's preinstalled Chrome headless on port 9333 with a fresh profile, loads the cookies,
                and the same read-only code as on the PC runs (campaign pages, Frame.io footage).
No passwords are stored or typed. If a site logs the session out, the owner logs in once in the PC's HookHouse
Chrome and the next export carries the new session.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import tempfile
import time

from ..config import ROOT

SESSION_ASSET = "browser-session.enc"
DOMAINS = ("contentrewards.com", "frame.io", "f.io", "vyro.com", "whop.com", "pinterest.com", "amazon.com")
EXPORT_EVERY_S = 6 * 3600
STAMP = ROOT / "data" / "pc" / "session_exported.txt"
COOKIE_KEYS = ("name", "value", "domain", "path", "secure", "httpOnly", "sameSite", "expires")


async def _browser_call(method: str, params: dict | None = None) -> dict:
    """One DevTools command on the browser itself (not a tab)."""
    import websockets
    from ..cr_footage import _cdp_json
    ws_url = _cdp_json("/json/version")["webSocketDebuggerUrl"]
    async with websockets.connect(ws_url, max_size=2 ** 26) as ws:
        await ws.send(json.dumps({"id": 1, "method": method, "params": params or {}}))
        while True:
            msg = json.loads(await ws.recv())
            if msg.get("id") == 1:
                if msg.get("error"):
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result") or {}


def _ours(cookie: dict) -> bool:
    d = str(cookie.get("domain", "")).lstrip(".").lower()
    return any(d == x or d.endswith("." + x) for x in DOMAINS)


def clean(cookies: list[dict]) -> list[dict]:
    """Only our sites, only the fields Storage.setCookies accepts; session cookies keep no expiry."""
    out = []
    for c in cookies:
        if not _ours(c):
            continue
        row = {k: c[k] for k in COOKIE_KEYS if k in c}
        if c.get("session") or (row.get("expires") or 0) <= 0:
            row.pop("expires", None)
        out.append(row)
    return out


def _fernet():
    from .state import _fernet as f
    return f()


def export(store, log=print, force: bool = False, now: float | None = None) -> int:
    """PC: send the HookHouse Chrome's session for our sites to the private store (encrypted). Returns cookies sent."""
    from ..cr_footage import chrome_up
    from . import media
    now = now or time.time()
    try:
        last = float(STAMP.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        last = 0.0
    if not force and now - last < EXPORT_EVERY_S:
        return 0
    if not chrome_up():
        return 0
    cookies = clean(asyncio.run(_browser_call("Storage.getCookies")).get("cookies") or [])
    if not cookies:
        return 0
    store.put(media.TAG, SESSION_ASSET, _fernet().encrypt(json.dumps(cookies).encode()), "application/octet-stream")
    STAMP.parent.mkdir(parents=True, exist_ok=True)
    STAMP.write_text(str(now), encoding="utf-8")
    log(f"browser session sent to the cloud ({len(cookies)} cookies, {len({c['domain'] for c in cookies})} sites)")
    return len(cookies)


def _chrome_exe() -> str | None:
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome"):
        p = shutil.which(name)
        if p:
            return p
    return None


def start_cloud_chrome(store, log=print, wait_s: float = 25) -> bool:
    """Cloud: headless Chrome on port 9333 with the owner's session loaded. False when there is no session yet."""
    from ..cr_footage import chrome_up
    from . import media
    if chrome_up():
        return True
    blob = store.get(media.TAG, SESSION_ASSET)
    exe = _chrome_exe()
    if not blob or not exe:
        return False
    cookies = json.loads(_fernet().decrypt(blob))
    from .runner import CHROME_UA
    profile = tempfile.mkdtemp(prefix="hh-chrome-")
    subprocess.Popen([exe, "--headless=new", "--remote-debugging-port=9333", f"--user-data-dir={profile}",
                      "--no-first-run", "--no-default-browser-check", "--no-sandbox", "--window-size=1280,900",
                      f"--user-agent={CHROME_UA}", "about:blank"],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    t0 = time.time()
    while time.time() - t0 < wait_s and not chrome_up():
        time.sleep(1)
    if not chrome_up():
        log("cloud chrome did not start")
        return False
    asyncio.run(_browser_call("Storage.setCookies", {"cookies": cookies}))
    log(f"cloud chrome ready with the owner's session ({len(cookies)} cookies)")
    return True


def cloud_jobs(store, log=print) -> int:
    """Cloud tick: the logged-in jobs that used to need the PC. Campaign pages + Frame.io footage for now (KDP and
    pins need the book/pin files in the cloud first)."""
    from ..core.where import in_runner
    if not in_runner():               # 20 Nov: the PC also has HOOKHOUSE_CLOUD=1
        return 0
    if not start_cloud_chrome(store, log):
        return 0
    from .. import cr_footage
    return cr_footage.pc_job(store, log)
