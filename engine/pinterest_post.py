"""Post our product pins to Pinterest (HookHouse Media, @hookhousemedia) through the signed-in co-pilot Chrome
(owner, 14 Nov: "set up pinterest and do all automatically").

Pace (research: steady beats bursts): MAX_PER_RUN pins per run, the PC helper runs it once a day. Boards are
created on the fly from pins.json. What was posted is recorded in data/products/<id>/pins/pins.json ("posted").
No AI label: our pins are drawn by our own code (the form's AI checkbox stays off).
Usage: python cli.py products pin [--max 2]"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from .config import ROOT
from . import store_covers

PROD = ROOT / "data" / "products"
TOOL = "https://www.pinterest.com/pin-creation-tool/"
MAX_PER_RUN = 2


def queue() -> list[tuple[str, int, dict, dict]]:
    """(product id, pin index, pin, plan) not posted yet, alternating products so boards fill evenly."""
    rows = []
    for pid in store_covers.SPECS:
        f = PROD / pid / "pins" / "pins.json"
        if not f.exists():
            continue
        plan = json.loads(f.read_text(encoding="utf-8"))
        for k, pin in enumerate(plan["pins"]):
            if not pin.get("posted"):
                rows.append((k, pid, pin, plan))
    rows.sort(key=lambda r: r[0])                              # all first pins, then all second pins
    return [(pid, k, pin, plan) for k, pid, pin, plan in rows]


def _mark(pid: str, k: int) -> None:
    f = PROD / pid / "pins" / "pins.json"
    plan = json.loads(f.read_text(encoding="utf-8"))
    plan["pins"][k]["posted"] = time.strftime("%Y-%m-%d %H:%M")
    f.write_text(json.dumps(plan, indent=1, ensure_ascii=False), encoding="utf-8")


def _choose_board(p, name: str) -> None:
    p.locator('[data-test-id="board-dropdown-select-button"]').click()
    p.wait_for_timeout(1500)
    search = p.get_by_placeholder(re.compile("Search", re.I)).filter(visible=True).first
    search.fill(name)
    p.wait_for_timeout(2000)
    hit = p.locator(f'[data-test-id="board-row-{name}"], [title="{name}"]').filter(visible=True)
    if not hit.count():
        hit = p.get_by_text(name, exact=True).filter(visible=True)
    if hit.count():
        hit.first.click()
        return
    p.get_by_text("Create board", exact=True).filter(visible=True).first.click()   # first pin on this board
    p.wait_for_timeout(1500)
    p.get_by_placeholder(re.compile("Places to Go", re.I)).fill(name)
    p.locator("button[type=submit]", has_text="Create").filter(visible=True).first.click()
    p.wait_for_timeout(3000)


def post_one(p, pid: str, k: int, pin: dict, plan: dict) -> None:
    if "pin-creation-tool" in p.url:
        p.reload(timeout=120000, wait_until="commit")         # fresh page: no half-open dialogs
    else:
        p.goto(TOOL, timeout=120000, wait_until="commit")
    p.locator("input[type=file]").first.wait_for(state="attached", timeout=90000)
    p.wait_for_timeout(2000)
    new = p.get_by_role("button", name="Create new")
    if new.count() and new.first.is_enabled():                 # the open draft is used: start a fresh one
        new.first.click()
        p.wait_for_timeout(2500)
    p.locator("input[type=file]").first.set_input_files(str(PROD / pid / pin["image"]))
    title = p.locator("#storyboard-selector-title")
    title.wait_for(state="visible", timeout=60000)
    for _ in range(30):
        if title.is_enabled():
            break
        p.wait_for_timeout(1000)
    title.fill(pin["title"])
    p.locator('[data-test-id="storyboard-description-field-container"] [contenteditable=true]').first.click()
    p.keyboard.type(pin["description"], delay=2)
    p.locator("#WebsiteField").fill(plan["link"])
    _choose_board(p, plan["board"])
    p.wait_for_timeout(1500)
    p.locator('[data-test-id="storyboard-creation-nav-done"] button').first.click()
    p.wait_for_timeout(8000)


def post(max_pins: int = MAX_PER_RUN, log=print) -> list[str]:
    from playwright.sync_api import sync_playwright
    from .store_publish import _page
    done = []
    todo = queue()[:max_pins]
    if not todo:
        return ["all pins already posted"]
    with sync_playwright() as pw:
        from .browser_windows import window_for
        from .store_publish import connect
        p = window_for(connect(pw), "pinterest.com", TOOL, "left")        # the shared store window, in front
        for pid, k, pin, plan in todo:
            try:
                post_one(p, pid, k, pin, plan)
                _mark(pid, k)
                done.append(f"pinned {pid} #{k + 1} on '{plan['board']}'")
            except Exception as e:  # noqa: BLE001
                done.append(f"{pid} #{k + 1}: FAILED {type(e).__name__}: {str(e)[:160]}")
            log(done[-1])
    return done
