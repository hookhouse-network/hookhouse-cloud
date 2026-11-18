"""HookHouse setup assistant (Playwright). Start: double-click scripts/setup_accounts.cmd

One browser window: the first tab is the checklist (served from this PC, 127.0.0.1 only), the second tab is where
each sign-up / key page opens. The assistant opens pages, shows Copy buttons, picks keys up from developer pages
as soon as they appear (never from social apps, never password fields), checks them with each service's own API,
saves them, catches the Google "Download JSON" file, connects channels and ticks the to-do list. The owner signs
in and presses the buttons the sites reserve for people. It uses the installed Chrome (or Edge) with its own
profile in data/browser_profile (git-ignored), with no tricks to hide that it is automated: if a site refuses,
switch "Open pages in" to "my normal browser" and paste keys into the boxes.
"""
from __future__ import annotations

import json
import os
import queue
import secrets
import subprocess
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import setup_steps as ss
from .config import ROOT, load_env

UI = Path(__file__).with_name("setup_ui.html")
PROFILE = ROOT / "data" / "browser_profile"
CMDS: "queue.Queue[tuple]" = queue.Queue()
EVENTS: list[dict] = []
JOBS: dict[str, dict] = {}
STATE: dict = {"active": "", "mode": "assistant", "tried": set(), "token": secrets.token_urlsafe(18),
               "browser": False, "quit": False, "status_at": 0.0, "status": {}}
LOCK = threading.Lock()
FORMAT_ONLY = {"YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "CLOUDFLARE_ACCOUNT_ID", "META_APP_ID"}
SPECIAL = {"META_USER_TOKEN": (r"\bEAA[A-Za-z0-9]{60,}\b", ["developers.facebook.com"])}
SCAN_JS = ("() => { const t = [document.body ? document.body.innerText : '']; "
           "document.querySelectorAll('input, textarea').forEach(e => { if (e.type !== 'password') t.push(e.value || ''); }); "
           "return t.join('\\n').slice(0, 400000); }")
SERVE_DIRS = ("output/brand", "data/products")


def event(msg: str, ok: bool = True) -> None:
    with LOCK:
        EVENTS.append({"t": time.time(), "msg": str(msg)[:600], "ok": ok})
        del EVENTS[:-80]


def open_url(url: str) -> None:
    if not str(url).startswith(("https://", "http://")):
        return
    if STATE["mode"] == "assistant" and STATE["browser"]:
        CMDS.put(("open", url))
    else:
        webbrowser.open(url)


def run_job(name: str, fn) -> None:
    def wrap():
        JOBS[name] = {"state": "running", "msg": "Working…", "t": time.time()}
        try:
            res = fn()
            msg = "\n".join(res) if isinstance(res, list) else str(res)
            JOBS[name] = {"state": "done", "msg": msg, "t": time.time()}
            event(msg, ok=not msg.startswith(("Not ", "No ", "Timed out", "Instagram refused")))
        except Exception as e:  # noqa: BLE001 - shown to the owner, the assistant keeps running
            JOBS[name] = {"state": "error", "msg": f"{type(e).__name__}: {str(e)[:240]}", "t": time.time()}
            event(JOBS[name]["msg"], ok=False)
        STATE["status_at"] = 0
    threading.Thread(target=wrap, daemon=True).start()


def _step(sid: str) -> dict | None:
    return next((s for s in ss.steps() if s["id"] == sid), None)


def _show(rel: str) -> tuple[bool, str]:
    p = (ROOT / rel).resolve()
    if ROOT.resolve() not in p.parents and p != ROOT.resolve() or not p.exists():
        return False, "not found"
    if p.is_file():
        subprocess.Popen(["explorer", "/select,", str(p)])
    else:
        os.startfile(str(p))  # noqa: S606 - opens a folder of this project in Explorer
    return True, f"Opened {p.name} in Explorer"


def do_action(aid: str, value: str = "", values: dict | None = None) -> tuple[bool, str]:
    """A button in the checklist."""
    values = values or {}
    if aid == "pair":
        from . import telegram_bot as tb
        if not (os.environ.get("TELEGRAM_BOT_TOKEN") or ss.env_file_value("TELEGRAM_BOT_TOKEN")):
            return False, "Do the bot token step first"
        code = tb.new_pair_code()
        run_job("pair", lambda: ss.pair_poll(tb.PAIR))
        return True, f"Send this code to your bot from your phone: {code}"
    if aid.startswith("connect_youtube:"):
        cid = aid.split(":", 1)[1]
        if not (os.environ.get("YOUTUBE_CLIENT_ID") and os.environ.get("YOUTUBE_CLIENT_SECRET")):
            return False, "Do the 'Google sign-in key' step first (Google & Gmail)"

        def job():
            from . import branding, connect
            from .config import channel
            ch = channel(cid)
            if not connect.connect_youtube(cid, opener=open_url):
                return f"Not connected: no sign-in came back for {ch['name']}. Press Connect again."
            ss.mark(f"yt_{cid}", "created")
            try:
                page = branding.apply(ch)
            except Exception as e:  # noqa: BLE001 - the 09:00 job retries
                page = f"the channel page follows at 09:00 ({str(e)[:80]})"
            return f"✅ {ch['name']} connected. {page}"
        run_job(aid, job)
        return True, "Google's page opens in the other tab: pick this channel and press Allow."
    if aid.startswith("connect_threads:"):
        cid = aid.split(":", 1)[1]
        if not (os.environ.get("THREADS_APP_ID") and os.environ.get("THREADS_APP_SECRET")):
            return False, "Do the 'Threads posting' step first (app ID + secret)"
        from . import threads
        STATE["threads_wait"] = {"channel": cid, "since": time.time()}
        open_url(threads.auth_url(state=cid))
        return True, ("Threads' page opens in the other tab: log in as this channel and press Allow. "
                      "The code is picked up from the address bar.")
    if aid.startswith("threads_code:"):
        cid = aid.split(":", 1)[1]
        from . import threads
        code = threads.code_from_url(value)
        if not code:
            return False, "Paste the whole address shown after pressing Allow (it contains code=...)"
        run_job(aid, lambda: threads.connect(code, cid))
        return True, "Connecting Threads…"
    if aid == "connect_gmail":
        if not os.environ.get("YOUTUBE_CLIENT_ID"):
            return False, "Do the 'Google sign-in key' step first (Google & Gmail)"

        def gjob():
            from . import connect
            return ("✅ HookHouse Gmail connected (send only)" if connect.connect_gmail(opener=open_url)
                    else "Not connected: no sign-in came back. Press Connect again.")
        run_job(aid, gjob)
        return True, "Google's page opens in the other tab: sign in with the HookHouse Gmail and press Allow."
    if aid == "meta_token":
        if not value.strip():
            return False, "Paste the token first (or leave it on the Graph API Explorer page)"
        run_job(aid, lambda: ss.meta_connect(value))
        return True, "Connecting every Page and Instagram account…"
    if aid.startswith("tg:"):
        return True, ss.telegram_channel(aid[3:], value)
    if aid == "dailymotion":
        return True, ss.dailymotion(values.get("dm_key"), values.get("dm_secret"), values.get("dm_profile"))
    if aid.startswith("show:"):
        return _show(aid[5:])
    if aid == "doctor":
        from . import doctor
        run_job("doctor", lambda: doctor.text(doctor.run()))
        return True, "Checking every connection…"
    if aid.startswith("created:"):
        ss.mark(aid[8:], "created")
        STATE["status_at"] = 0
        return True, "Noted. It counts towards today's 3."
    if aid.startswith("done:"):
        sid = aid[5:]
        ss.mark(sid, "done")
        st = _step(sid)
        if st and st.get("todo"):
            from . import todo
            t = next((x for x in todo.items() if x.get("id") == st["todo"]), None)
            if t and t.get("manual"):
                todo.tick(st["todo"], True)
        STATE["status_at"] = 0
        return True, "Ticked ✓"
    return False, "Unknown button"


def threads_return(url: str) -> None:
    """The Threads sign-in came back to its return link: take the code from the address bar and connect."""
    w = STATE.get("threads_wait")
    if not w or time.time() - w["since"] > 900:
        return
    from . import threads
    if not threads.is_return_page(url):
        return
    code = threads.code_from_url(url)
    if not code or code in STATE["tried"]:
        return
    STATE["tried"].add(code)
    STATE["threads_wait"] = None
    cid = w["channel"]
    run_job(f"threads:{cid}", lambda: threads.connect(code, cid))


def snapshot() -> dict:
    """Status of every step (cached 3 s: some checks ask Windows)."""
    if time.time() - STATE["status_at"] > 3:
        st = {}
        for s in ss.steps():
            try:
                st[s["id"]] = list(ss.status(s))
            except Exception as e:  # noqa: BLE001
                st[s["id"]] = [False, f"check failed: {type(e).__name__}"]
        fams = {s["family"] for s in ss.steps() if s["family"]}
        STATE["status"] = {"steps": st, "pace": {f: ss.created_today(f) for f in fams}}
        STATE["status_at"] = time.time()
    with LOCK:
        ev = list(EVENTS[-40:])
    return {**STATE["status"], "events": ev, "jobs": JOBS, "mode": STATE["mode"], "browser": STATE["browser"],
            "limit": ss.PACE_PER_DAY, "active": STATE["active"]}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def _send(self, code: int, body: bytes, ctype: str = "application/json") -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def _authed(self, q: dict) -> bool:
        return secrets.compare_digest(self.headers.get("X-Token") or (q.get("t") or [""])[0], STATE["token"])

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path == "/":
            return self._send(200, UI.read_bytes(), "text/html; charset=utf-8")
        if not self._authed(q):
            return self._json({"error": "forbidden"}, 403)
        if u.path == "/api/steps":
            return self._json({"steps": ss.steps()})
        if u.path == "/api/state":
            return self._json(snapshot())
        if u.path == "/file":
            rel = (q.get("p") or [""])[0].replace("\\", "/")
            p = (ROOT / rel).resolve()
            if (any(str(p).startswith(str((ROOT / d).resolve())) for d in SERVE_DIRS) and p.is_file()
                    and p.suffix.lower() in (".png", ".jpg", ".jpeg")):
                return self._send(200, p.read_bytes(), "image/png" if p.suffix.lower() == ".png" else "image/jpeg")
            return self._json({"error": "not found"}, 404)
        return self._json({"error": "not found"}, 404)

    def do_POST(self):
        u = urlparse(self.path)
        if not self._authed({}) or "json" not in (self.headers.get("Content-Type") or ""):
            return self._json({"error": "forbidden"}, 403)
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0) or 0) or b"{}")
        except ValueError:
            return self._json({"error": "bad request"}, 400)
        if u.path == "/api/active":
            STATE["active"] = str(body.get("step") or "")
            return self._json({"ok": True})
        if u.path == "/api/open":
            open_url(str(body.get("url") or ""))
            return self._json({"ok": True})
        if u.path == "/api/mode":
            STATE["mode"] = "normal" if body.get("mode") == "normal" else "assistant"
            return self._json({"ok": True, "mode": STATE["mode"]})
        if u.path == "/api/key":
            name, value = str(body.get("name") or ""), str(body.get("value") or "")
            ok, msg = ss.submit_key(name, value)
            label = ss.KEYS.get(name, (name,))[0]
            event(f"{'✅ Saved' if ok else '❌ Not saved'}: {label} ({msg})", ok)
            STATE["status_at"] = 0
            return self._json({"ok": ok, "msg": msg})
        if u.path == "/api/action":
            try:
                ok, msg = do_action(str(body.get("id") or ""), str(body.get("value") or ""), body.get("values") or {})
            except Exception as e:  # noqa: BLE001
                ok, msg = False, f"{type(e).__name__}: {str(e)[:200]}"
            if msg:
                event(msg, ok)
            return self._json({"ok": ok, "msg": msg})
        if u.path == "/api/quit":
            STATE["quit"] = True
            return self._json({"ok": True})
        return self._json({"error": "not found"}, 404)


def start_server() -> tuple[ThreadingHTTPServer, str]:
    for port in range(47621, 47641):
        try:
            srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
            break
        except OSError:
            continue
    else:
        raise RuntimeError("no free local port between 47621 and 47640")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}/?t={STATE['token']}"


# ------------------------------------------------------------------------------------------- browser side
def _check_and_save(name: str, value: str) -> None:
    ok, msg = ss.submit_key(name, value)
    if ok:
        event(f"✅ Got your {ss.KEYS[name][0]} from the page and saved it ({msg})")
        STATE["status_at"] = 0


def scan_text(step: dict | None, url: str, text: str) -> None:
    """Look for this step's keys on one page; check + save new ones in the background."""
    host = urlparse(url or "").hostname or ""
    if host == "console.cloud.google.com" and not ss.progress().get("gcloud_project"):
        pid = (parse_qs(urlparse(url).query).get("project") or [""])[0]
        if pid:
            ss.set_project(pid)
            event(f"✅ Google Cloud project noted: {pid} (the next links open inside it)")
            STATE["status_at"] = 0
    if not step:
        return
    for name in step.get("scan") or []:
        if name in SPECIAL:
            import re
            pat, hosts = SPECIAL[name]
            if host in hosts:
                for tok in re.findall(pat, text or "")[:1]:
                    if (name, tok) not in STATE["tried"]:
                        STATE["tried"].add((name, tok))
                        event("Found the access token on the page: connecting every Page…")
                        run_job("meta_token", lambda tok=tok: ss.meta_connect(tok))
            continue
        spec = ss.KEYS.get(name)
        if not spec or host not in spec[3] or os.environ.get(name):
            continue
        if name == "META_APP_SECRET" and not os.environ.get("META_APP_ID"):
            continue                                    # a secret is only trusted once Meta can check the pair
        cands = ss.candidates(name, text, url)
        if name in FORMAT_ONLY and len(cands) != 1:
            continue                                    # two lookalikes on the page: let the owner paste the right one
        for c in cands:
            if (name, c) in STATE["tried"]:
                continue
            STATE["tried"].add((name, c))
            threading.Thread(target=_check_and_save, args=(name, c), daemon=True).start()


def _download(d) -> None:
    name = (d.suggested_filename or "").lower()
    if not name.endswith(".json"):
        return
    tmp = ROOT / "data" / "tmp_download.json"
    d.save_as(str(tmp))
    raw = tmp.read_text(encoding="utf-8", errors="replace")
    tmp.unlink(missing_ok=True)
    pair = ss.google_client_from_json(raw)
    if pair:
        ss.save_env("YOUTUBE_CLIENT_ID", pair[0])
        ss.save_env("YOUTUBE_CLIENT_SECRET", pair[1])
        ss.SECRETS.mkdir(parents=True, exist_ok=True)
        (ss.SECRETS / "google_oauth_client.json").write_text(raw, encoding="utf-8")
        event("✅ Got the Google sign-in key from the downloaded file (Client ID + secret saved)")
        STATE["status_at"] = 0


def _launch(pw):
    last = None
    for chan in ("chrome", "msedge", None):
        try:
            kw = {"headless": False, "no_viewport": True, "accept_downloads": True, "args": ["--start-maximized"]}
            if chan:
                kw["channel"] = chan
            return pw.chromium.launch_persistent_context(str(PROFILE), **kw)
        except Exception as e:  # noqa: BLE001 - try the next browser
            last = e
    raise RuntimeError(f"no browser could be opened ({last})")


def browser_loop(url: str) -> bool:
    """The assistant window. False if Playwright or a browser isn't available (then the normal browser is used)."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        event("Playwright isn't installed, so pages open in your normal browser (paste keys into the boxes)", ok=False)
        return False
    with sync_playwright() as pw:
        try:
            ctx = _launch(pw)
        except Exception as e:  # noqa: BLE001
            event(f"{e}; using your normal browser", ok=False)
            return False
        STATE["browser"] = True
        hook = lambda p: p.on("download", lambda d: CMDS.put(("download", d)))  # noqa: E731
        for p in ctx.pages:
            hook(p)
        ctx.on("page", hook)
        helper = ctx.pages[0] if ctx.pages else ctx.new_page()
        helper.goto(url)
        work, last_scan = None, 0.0
        while not STATE["quit"]:
            if helper.is_closed():
                break
            try:
                cmd = CMDS.get_nowait()
            except queue.Empty:
                cmd = None
            if cmd and cmd[0] == "open":
                if work is None or work.is_closed():
                    work = ctx.new_page()
                try:
                    work.goto(cmd[1], wait_until="domcontentloaded", timeout=45000)
                except Exception as e:  # noqa: BLE001 - slow pages still finish loading
                    event(f"The page is slow to open ({type(e).__name__}); it may still finish", ok=False)
                try:
                    work.bring_to_front()
                except Exception:  # noqa: BLE001
                    pass
            elif cmd and cmd[0] == "download":
                try:
                    _download(cmd[1])
                except Exception as e:  # noqa: BLE001
                    event(f"Couldn't read the downloaded file ({type(e).__name__}); paste the values instead", ok=False)
            if time.time() - last_scan > 1.5:
                last_scan = time.time()
                step = _step(STATE["active"]) if STATE["active"] else None
                for page in list(ctx.pages):
                    if page is helper or page.is_closed():
                        continue
                    threads_return(page.url)               # works even when the return page doesn't load
                    try:
                        scan_text(step, page.url, page.evaluate(SCAN_JS))
                    except Exception:  # noqa: BLE001 - page navigating; next round
                        pass
            try:
                helper.wait_for_timeout(250)
            except Exception:  # noqa: BLE001 - window closed
                break
        try:
            ctx.close()
        except Exception:  # noqa: BLE001
            pass
    STATE["browser"] = False
    return True


def check(url: str, shot: Path) -> None:
    """Self-test: render the checklist without a visible window and save screenshots."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        b = None
        for chan in ("chrome", "msedge", None):
            try:
                b = pw.chromium.launch(headless=True, **({"channel": chan} if chan else {}))
                break
            except Exception:  # noqa: BLE001
                continue
        page = b.new_page(viewport={"width": 1440, "height": 900})
        page.goto(url)
        page.wait_for_selector(".step-row", timeout=15000)
        page.screenshot(path=str(shot))
        rows = page.locator(".step-row")
        for i in range(rows.count()):
            if "Deep Blue Files: YouTube" in rows.nth(i).inner_text():
                rows.nth(i).click()
                break
        page.wait_for_timeout(800)
        page.screenshot(path=str(shot.with_name(shot.stem + "_step.png")))
        b.close()


def main(argv=None) -> None:
    import argparse
    ap = argparse.ArgumentParser(description="HookHouse setup assistant")
    ap.add_argument("--normal-browser", action="store_true", help="open pages in your normal browser (no Playwright)")
    ap.add_argument("--check", action="store_true", help="self-test: render the checklist and save screenshots")
    args = ap.parse_args(argv)
    load_env()                                     # keys already in .env count as done
    srv, url = start_server()
    if args.check:
        out = ROOT / "data" / "review" / "setup_assistant.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        check(url, out)
        print("screenshots:", out)
        srv.shutdown()
        return
    print("HookHouse setup assistant is running. Keep this window open; close the browser window to stop.")
    if args.normal_browser or not browser_loop(url):
        STATE["mode"] = "normal"
        webbrowser.open(url)
        print(f"Checklist: {url}\nPress Ctrl+C here (or 'Stop' on the page) when you're done.")
        try:
            while not STATE["quit"]:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
    srv.shutdown()
    try:
        from . import todo
        done, total = todo.progress()
        print(f"To-do list: {done}/{total} done. Run the assistant again any time to continue.")
    except Exception:  # noqa: BLE001
        pass


if __name__ == "__main__":
    main()
