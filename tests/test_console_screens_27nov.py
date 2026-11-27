"""27 Nov (P2b acceptance): every Control Center screen renders at phone (390x844) and desktop (1280x800) sizes
without sideways scrolling; screenshots land in the test's temp folder. Uses the installed Chrome (its own temporary
profile); skipped where starlette, uvicorn or Chrome is missing (CI runs the cloud requirements only)."""
import socket
import threading
import time

import pytest

pytest.importorskip("starlette")
uvicorn = pytest.importorskip("uvicorn")
sync_api = pytest.importorskip("playwright.sync_api")

from engine import autopilot  # noqa: E402
from engine.console import app as console  # noqa: E402

SIZES = {"phone": (390, 844), "desktop": (1280, 800)}


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def server(monkeypatch):
    items = [("s", {"id": f"1127_0{h}00_brain_snack_short", "channel": "brain_snack", "channel_name": "Brain Snack",
                    "kind": "short", "status": st, "publish_at": f"2026-11-27T0{h}:00:00+05:30",
                    "topic": "A long topic title that keeps going to test wrapping on a small phone screen " * 2})
             for h, st in ((5, "posted"), (6, "made"), (8, "failed"))]
    monkeypatch.setattr(autopilot, "items", lambda back=3, ahead=9: items)
    monkeypatch.setattr(autopilot, "gate_held", lambda: {"1127_0600_brain_snack_short": {
        "problems": ["potential: below 8/10 on shareability 5 " * 6], "channel": "Brain Snack", "at": 1}})
    monkeypatch.setattr(console, "_sched", lambda: ({"online": [{"id": "pc-sys221", "kind": "pc"}]}, ""))
    monkeypatch.setattr(console, "_dash", lambda: "https://example.invalid/d")
    port = _free_port()
    srv = uvicorn.Server(uvicorn.Config(console.app, host="127.0.0.1", port=port, log_level="error"))
    t = threading.Thread(target=srv.run, daemon=True)
    t.start()
    for _ in range(50):
        if srv.started:
            break
        time.sleep(0.1)
    yield f"http://127.0.0.1:{port}"
    srv.should_exit = True
    t.join(timeout=5)


def test_every_screen_fits_phone_and_desktop(server, tmp_path):
    with sync_api.sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel="chrome", headless=True)
        except Exception as e:  # noqa: BLE001 - no Chrome on this machine
            pytest.skip(f"Chrome not available: {type(e).__name__}")
        try:
            for size, (w, h) in SIZES.items():
                page = browser.new_page(viewport={"width": w, "height": h})
                for path in ("/", "/pipeline", "/gates", "/queue", "/workers", "/budgets"):
                    page.goto(server + path)
                    over = page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
                    page.screenshot(path=str(tmp_path / f"{size}{path.replace('/', '_') or '_home'}.png"),
                                    full_page=True)
                    assert over <= 1, f"{path} scrolls sideways by {over}px at {size} size"
                page.close()
        finally:
            browser.close()
