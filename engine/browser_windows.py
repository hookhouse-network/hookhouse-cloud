"""Browser windows for the automation jobs (owner, 14 Nov: "until it is loading do other things").

Chrome throttles any tab that is hidden or covered, and a throttled tab makes page loads time out. So:
- ONE store window on the left half: Payhip, Gumroad, Pinterest jobs take turns in it (never stacked windows).
- Amazon KDP gets the right half (its long print checks run while the store window works).
window_for(browser, url_part, start_url, side) -> the page for a job, visible and in front."""
from __future__ import annotations


def _bounds(cdp, target_id: str, side: str, screen_w: int = 1920, screen_h: int = 1040) -> None:
    win = cdp.send("Browser.getWindowForTarget", {"targetId": target_id})["windowId"]
    cdp.send("Browser.setWindowBounds", {"windowId": win, "bounds": {"windowState": "normal"}})
    half = screen_w // 2
    cdp.send("Browser.setWindowBounds", {"windowId": win, "bounds": {
        "left": 0 if side == "left" else half, "top": 0, "width": half, "height": screen_h}})


def _tid(page) -> str:
    return page.context.new_cdp_session(page).send("Target.getTargetInfo")["targetInfo"]["targetId"]


def window_for(browser, url_part: str, start_url: str, side: str = "left"):
    """The page whose URL contains url_part; otherwise the store window (any non-KDP page) is navigated to start_url;
    otherwise a new window is opened for the job. The owner's other tabs are never closed."""
    ctx = browser.contexts[0]
    cdp = browser.new_browser_cdp_session()
    pages = [p for p in ctx.pages if not p.is_closed()]
    kdp = [p for p in pages if "kdp.amazon.com" in p.url]
    others = [p for p in pages if p not in kdp]
    # owner 15 Nov: closing "extra" pages also closed the owner's own tabs (Facebook check, Gmail, PayPal). Never close
    # anything: reuse the job's own page if it is open, else open a new window for the job and bring it to the front.
    page = next((p for p in others if url_part in p.url), None)
    if page is None:
        before = set(ctx.pages)
        cdp.send("Target.createTarget", {"url": start_url, "newWindow": True})
        for _ in range(100):
            new = [p for p in ctx.pages if p not in before]
            if new:
                page = new[0]
                break
            ctx.pages[0].wait_for_timeout(100)
    elif url_part not in page.url:
        page.goto(start_url, timeout=120000, wait_until="commit")
    try:
        _bounds(cdp, _tid(page), side)
        for p in kdp:
            _bounds(cdp, _tid(p), "right")
    except Exception:  # noqa: BLE001 - layout is a nicety
        pass
    page.bring_to_front()
    return page
