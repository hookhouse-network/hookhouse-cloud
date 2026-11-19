"""Campaign footage on Frame.io shares (17 Nov 2026: Wa-Chaa x RZA and SEGA put their "content folder" on f.io links).

PC only (headless HookHouse Chrome, port 9333): open the share, open a folder, open each wanted video, and catch the
video file address the player loads (Network events), then download it with plain HTTP. Read-only on Frame.io: no
sign-in, no clicks on anything but folders and files. Brand footage shared for clipping = permission (campaign brief).
"""
from __future__ import annotations

import asyncio
import json
import re
import time
import urllib.request
from pathlib import Path


CDP = "http://127.0.0.1:9333"
VIDEO = re.compile(r"\.(mp4|mov|m4v)$", re.I)
FOLDERS_JS = r"""(() => { const out = [];
  document.querySelectorAll('*').forEach(e => { const t = (e.innerText || '').trim();
    const m = /^([^\n]{2,80})\n+(\d+) Items?$/.exec(t);
    if (m && e.children.length <= 4) out.push([m[1].trim(), parseInt(m[2])]); });
  return out; })()"""
FILES_JS = r"""[...document.querySelectorAll('*')].filter(e => e.children.length <= 3 &&
  /^[^\n]{3,140}\.(mp4|mov|m4v)$/i.test((e.innerText || '').trim())).map(e => e.innerText.trim())"""


def _new_tab() -> dict:
    req = urllib.request.Request(CDP + "/json/new?about:blank", method="PUT")
    return json.loads(urllib.request.urlopen(req, timeout=10).read())


def _close(t: dict) -> None:
    try:
        urllib.request.urlopen(f"{CDP}/json/close/{t['id']}", timeout=10).read()
    except Exception:  # noqa: BLE001
        pass


async def _run(share: str, prefer: list[str], limit: int, dest: Path, log) -> list[Path]:
    import websockets
    t = _new_tab()
    got: list[Path] = []
    try:
        async with websockets.connect(t["webSocketDebuggerUrl"], max_size=2 ** 26) as ws:
            n, events = [0], []

            async def call(m, **p):
                n[0] += 1
                await ws.send(json.dumps({"id": n[0], "method": m, "params": p}))
                while True:
                    r = json.loads(await asyncio.wait_for(ws.recv(), 60))
                    if r.get("id") == n[0]:
                        return r.get("result", {})
                    if r.get("method"):
                        events.append(r)

            async def js(e):
                r = await call("Runtime.evaluate", expression=e, returnByValue=True, userGesture=True)
                return (r.get("result") or {}).get("value")

            async def drain(secs):
                t0 = time.time()
                while time.time() - t0 < secs:
                    try:
                        m = json.loads(await asyncio.wait_for(ws.recv(), 1))
                        if m.get("method"):
                            events.append(m)
                    except asyncio.TimeoutError:
                        pass

            await call("Network.enable")
            await call("Emulation.setFocusEmulationEnabled", enabled=True)
            await call("Page.navigate", url=share)
            await drain(18)
            names = await js(FILES_JS) or []
            if not names and not prefer:                   # no folder named: the biggest main-content folder
                folders = await js(FOLDERS_JS) or []
                folders = [f for f in folders if not re.search(r"reaction|bts|behind|logo|still|photo|thumb", f[0], re.I)]
                if folders:
                    prefer = [max(folders, key=lambda f: f[1])[0]]
            for fname in prefer if not names else []:      # top level shows folders: open the wanted one
                ok = await js("(() => { const e=[...document.querySelectorAll('*')].find(x=>x.children.length<3 && "
                              f"(x.innerText||'').trim()==={json.dumps(fname)}); if(!e) return false;"
                              " (e.closest('a,[role=button],[role=gridcell],div[tabindex]')||e).click(); return true; })()")
                log(f"  frame.io folder {fname}: {'opened' if ok else 'not found'}")
                if ok:
                    await drain(14)
                    break
            if not names:
                names = await js(FILES_JS) or []
            names = list(dict.fromkeys(names))
            vertical = [x for x in names if re.search(r"9x16|vertical|reel|story|stories", x, re.I) and x.lower().endswith(".mp4")]
            pick = (vertical + [x for x in names if x.lower().endswith(".mp4") and x not in vertical])[:limit]
            log(f"  frame.io files: {len(names)}, taking {pick}")
            folder_url = await js("location.href")
            for name in pick:
                events.clear()
                await js("(() => { const e=[...document.querySelectorAll('*')].find(x=>x.children.length<=3 && "
                         f"(x.innerText||'').trim()==={json.dumps(name)}); if(!e) return; const c=e.closest('a,[role=button],div[tabindex]')||e;"
                         " c.dispatchEvent(new MouseEvent('dblclick',{bubbles:true})); c.click(); })()")
                await drain(15)
                reqs = [e["params"]["request"]["url"] for e in events if e.get("method") == "Network.requestWillBeSent"]
                hls = [u for u in reqs if "sahls.frame.io" in u and ".m3u8" in u]
                master = next((u for u in hls if "master" in u or "index" in u), hls[0] if hls else None)
                out = dest / re.sub(r"[^\w.-]+", "_", name)
                if master:                                 # full-quality stream -> one MP4 (no re-encoding)
                    import subprocess
                    from .media import ffmpeg
                    r = subprocess.run([ffmpeg.ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-y", "-i", master,
                                        "-c", "copy", "-bsf:a", "aac_adtstoasc", str(out)], capture_output=True, text=True,
                                       timeout=600)
                    if r.returncode == 0 and out.exists() and out.stat().st_size > 200_000:
                        got.append(out)
                        log(f"  frame.io: {name} -> {out.stat().st_size // 1024} KB")
                    else:
                        log(f"  frame.io {name}: stream save failed {r.stderr[-200:]}")
                else:
                    log(f"  frame.io {name}: no stream address seen ({len(reqs)} requests)")
                await call("Page.navigate", url=folder_url)
                await drain(12)
    finally:
        _close(t)
    return got


def download(share: str, dest: Path, prefer: list[str] | None = None, limit: int = 3, log=print) -> list[Path]:
    dest.mkdir(parents=True, exist_ok=True)
    return asyncio.run(_run(share, prefer or [], limit, dest, log))
