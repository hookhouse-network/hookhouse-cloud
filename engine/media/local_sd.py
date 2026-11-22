"""Local pictures on the PC: the fallback when the free cloud pictures are used up.

Owner 20 Nov: "SD1.5-family models only as a fallback, idle + plugged in, low priority, capped, benchmarked first".
22 Nov: Cloudflare retired its two unbilled picture models on 20 Nov (the day posting stopped), so FLUX's 10,000 free
daily neurons (~170 pictures) are all the cloud gives, and story videos waited a whole day for them. This draws with
DreamShaper 8 LCM (Lykon, an SD1.5 fine-tune, CreativeML OpenRAIL-M: commercial use of the pictures allowed; the same
model Cloudflare hosted for us until 20 Nov) through stable-diffusion.cpp (MIT, CPU build in tools/sdcpp).

The rules, all from settings `local_pictures`:
- only on the PC (never on GitHub Actions: no model inference there) and only when switched on;
- a video STARTS on local pictures only while the PC is idle (no keyboard/mouse for `idle_min` minutes) and plugged
  in; once started, its pictures finish at below-normal priority (a half-drawn video would only become word cards);
- at most `max_day` pictures a day; `threads` CPU threads, one picture at a time.

Benchmark 22 Nov on this PC (i5-10210U, 4 cores/8 threads, no usable GPU), 512x896, 4 LCM steps, below-normal
priority: full VAE decode 262 s a picture (sampling 129 s + decode 124 s); with TAESD (madebyollin, MIT; looks the
same at this size) 148 s; + 8-bit weights 135 s; + 6 threads 121 s (8 threads 120 s, flash attention slower). Looked
at by eye: a lit tent in snow at night, a courtyard ceremony with three people, a cricket batsman under floodlights:
clean, cinematic, no stray letters (a shirt number can appear; the eyes check judges every picture as usual).
"""
from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from ..config import ROOT

MODEL = ROOT / "data" / "models" / "sd15" / "DreamShaper8_LCM.safetensors"
TAESD = ROOT / "data" / "models" / "sd15" / "taesd" / "diffusion_pytorch_model.safetensors"   # fast decoder (MIT)
EXE = ROOT / "tools" / "sdcpp" / ("sd-cli.exe" if sys.platform.startswith("win") else "sd-cli")
COUNT = ROOT / "data" / "pc" / "local_sd_count.json"
SOURCE = "ai_sd15_local"
CREDIT = "Own (DreamShaper 8 LCM, CreativeML OpenRAIL-M; drawn on our PC)"
DEFAULTS = {"enabled": False, "max_day": 60, "idle_min": 3, "threads": 6, "steps": 4, "timeout_s": 600}
_LOCK = threading.Lock()                     # one picture at a time: two would only fight for the same CPU cores
_SAID: set[str] = set()                      # reasons already written to the log (once each until it draws again)


def cfg() -> dict:
    from ..config import settings
    try:
        return {**DEFAULTS, **(settings().get("local_pictures") or {})}
    except Exception as e:  # noqa: BLE001 - unreadable settings: the fallback stays off
        print(f"local pictures: settings unreadable ({type(e).__name__})", flush=True)
        return dict(DEFAULTS)


def idle_s() -> float:
    """Seconds since the last keyboard/mouse input on this PC (Windows); elsewhere 'always idle'."""
    if not sys.platform.startswith("win"):
        return 1e9
    import ctypes

    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]
    info = LASTINPUTINFO()
    info.cbSize = ctypes.sizeof(info)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
        return 0.0
    return ((ctypes.windll.kernel32.GetTickCount() - info.dwTime) & 0xFFFFFFFF) / 1000.0


def plugged_in() -> bool:
    """False only when Windows says the PC runs on its battery (desktops and unknown states count as plugged in)."""
    if not sys.platform.startswith("win"):
        return True
    import ctypes

    class POWER(ctypes.Structure):
        _fields_ = [("ACLineStatus", ctypes.c_ubyte), ("BatteryFlag", ctypes.c_ubyte),
                    ("BatteryLifePercent", ctypes.c_ubyte), ("SystemStatusFlag", ctypes.c_ubyte),
                    ("BatteryLifeTime", ctypes.c_ulong), ("BatteryFullLifeTime", ctypes.c_ulong)]
    st = POWER()
    if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(st)):
        return True
    return st.ACLineStatus != 0


def _today() -> str:
    return dt.date.today().isoformat()


def used_today() -> int:
    try:
        return int(json.loads(COUNT.read_text(encoding="utf-8")).get(_today(), 0))
    except (OSError, ValueError, AttributeError):
        return 0


def _count_one() -> None:
    n = used_today() + 1
    COUNT.parent.mkdir(parents=True, exist_ok=True)
    COUNT.write_text(json.dumps({_today(): n}), encoding="utf-8")


def why_not(start: bool = False) -> str | None:
    """None when a local picture may be drawn now, else the plain reason. start=True is the check before a video
    starts (adds 'the PC is idle'); single pictures of a started video skip that one."""
    from ..core.where import in_runner
    c = cfg()
    if not c.get("enabled"):
        return "local pictures are switched off"
    if in_runner():
        return "local pictures are drawn only on the PC"
    if not (EXE.exists() and MODEL.exists()):
        return "the local picture model or stable-diffusion.cpp is missing"
    if used_today() >= int(c["max_day"]):
        return f"today's {c['max_day']} local pictures are drawn"
    if not plugged_in():
        return "the PC runs on its battery"
    if start and idle_s() < float(c["idle_min"]) * 60:
        return "the PC is in use"
    return None


def available() -> bool:
    """May a story video start on local pictures now?"""
    return why_not(start=True) is None


def _size(size: tuple[int, int]) -> tuple[int, int]:
    """SD1.5 draws best near 512 px: 512x896 for a 9:16 Short (the maker scales it up), 896x512 for 16:9."""
    return (512, 896) if size[1] > size[0] else (896, 512)


def draw(prompt: str, seed: int, size: tuple[int, int] = (1080, 1920)) -> bytes | None:
    """One local picture as PNG bytes, or None (not allowed now, or the drawing failed)."""
    reason = why_not()
    if reason:
        if reason not in _SAID:                       # 22 Nov: the PC went on battery mid-video and every scene
            _SAID.add(reason)                         # became a graphic without a word in the log
            print(f"local pictures: not now ({reason})", flush=True)
        return None
    _SAID.clear()
    c = cfg()
    w, h = _size(size)
    with _LOCK, tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "pic.png"
        args = [str(EXE), "-m", str(MODEL), "-p", prompt[:1500], "--sampling-method", "lcm",
                "--steps", str(int(c["steps"])), "--cfg-scale", "1.0", "-W", str(w), "-H", str(h),
                "-t", str(int(c["threads"])), "-s", str(int(seed) % 2_000_000_000), "-o", str(out),
                "--type", "q8_0"]                                     # 8-bit weights: ~10 % faster, same look
        if TAESD.exists():
            args += ["--taesd", str(TAESD)]                           # decode in 9 s instead of 124 s
        else:
            print("local pictures: TAESD missing; using the full decoder (about two minutes slower)", flush=True)
        flags = getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0) | getattr(subprocess, "CREATE_NO_WINDOW", 0)
        t = time.time()
        try:
            p = subprocess.run(args, capture_output=True, text=True, errors="replace", cwd=str(EXE.parent),
                               timeout=int(c["timeout_s"]), creationflags=flags)
        except (subprocess.TimeoutExpired, OSError) as e:
            print(f"local picture failed: {type(e).__name__}", flush=True)
            return None
        if p.returncode != 0 or not out.exists() or out.stat().st_size < 10_000:
            tail = ((p.stderr or "") + (p.stdout or "")).strip().splitlines()[-1:] or [""]
            print(f"local picture failed (exit {p.returncode}): {tail[0][:160]}", flush=True)
            return None
        _count_one()
        print(f"AI pictures: drew one on this PC in {time.time() - t:.0f}s ({used_today()} today)", flush=True)
        return _enlarge(out.read_bytes())


SHORT_SIDE = 1080


def _enlarge(png: bytes) -> bytes:
    """22 Nov: the renderer shows a picture whose short side is under 650 px as a small framed 'document' card on a
    dark blur (story._v3_frame): every 512 px PC picture of the first Itihaas video became a card and its frames went
    dark. Cloudflare's 1024x1024 FLUX pictures are cropped to ~576x1024 for a Short, about the same detail, and get the
    full-screen motion; so the PC picture is enlarged once (Lanczos + a light sharpen) to 1080 px on its short side."""
    import io
    from PIL import Image, ImageFilter
    img = Image.open(io.BytesIO(png)).convert("RGB")
    k = SHORT_SIDE / min(img.size)
    if k > 1:
        img = img.resize((round(img.width * k), round(img.height * k)), Image.LANCZOS)
        img = img.filter(ImageFilter.UnsharpMask(radius=1.6, percent=55, threshold=2))
    b = io.BytesIO()
    img.save(b, "PNG")
    return b.getvalue()


def status() -> str:
    """One line for logs and the owner: can the PC draw, and how many pictures today."""
    reason = why_not(start=True)
    return f"local pictures: {'ready' if reason is None else reason}; {used_today()} drawn today"


if __name__ == "__main__":                  # python -m engine.media.local_sd: the line the owner/Claude can check
    print(status())
    print(f"idle {idle_s():.0f}s, plugged in {plugged_in()}, model {MODEL.exists()}, sd-cli {EXE.exists()}, "
          f"settings {json.dumps(cfg())}, pid {os.getpid()}")
