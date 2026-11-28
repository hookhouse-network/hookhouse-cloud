"""Watchdog (owner 17 Nov 2026: "i don't want the system to break again ever").

Runs at the end of every cloud run. It checks the things that broke silently before and sends ONE plain-language
Telegram alert per problem (repeated at most every ALERT_EVERY_H hours), plus an "all clear" when it is fixed:

- the PC helper stopped (no heartbeat) or its HookHouse Chrome window is closed (campaign joins and pins need it)
- the same cloud step failed on 3 runs in a row
- no video was made for a connected channel for a day
- campaigns picked but not joined after 12 hours (one reminder a day, with the Join links)
- free pictures used up (once a day, with the reset time)
- videos stuck at 3 failed tries
The Worker itself alerts when it cannot start a cloud run (cloud/worker/worker.js).
"""
from __future__ import annotations
from engine.core.quiet import noted

import json
import time

from .config import ROOT

STATE = ROOT / "data" / "state" / "watchdog.json"
ALERT_EVERY_H = 12
HELPER_ASSET = "helper-heartbeat.json"
HELPER_LATE_H = 3


def _load() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"sent": {}, "steps": {}}


def _save(s: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(s, indent=1), encoding="utf-8")


# ---------------- inputs ----------------
def record_steps(errors: dict[str, str], all_steps: list[str]) -> None:
    """Cloud tick: which steps failed this run (consecutive failure count per step)."""
    s = _load()
    from . import heal
    for name in all_steps:
        if name in errors:
            st = s["steps"].setdefault(name, {"n": 0})
            st["n"], st["error"] = st.get("n", 0) + 1, str(errors[name])[:200]
            heal.report(f"step:{name}", errors[name])              # repeats -> code-fix queue (18 Nov)
        else:
            if s["steps"].pop(name, None):
                heal.resolve(f"step:{name}:")
    _save(s)


def helper_heartbeat(store, chrome: bool, doing: str = "", alerts: dict | None = None) -> None:
    """PC helper, every loop: alive + whether its Chrome is open + its own alerts (stuck uploads, low disk: plan P0
    4b/4c). The PC never messages the owner itself; the cloud watchdog does."""
    from .cloud import media
    store.put(media.TAG, HELPER_ASSET, json.dumps({"at": time.time(), "chrome": chrome, "doing": doing,
                                                   "alerts": alerts or {}}, ensure_ascii=False).encode())


# ---------------- checks ----------------
def problems(store=None, now: float | None = None) -> dict[str, str]:
    """key -> plain-language alert text (what is wrong + what happens / what to do)."""
    now = now or time.time()
    out: dict[str, str] = {}
    s = _load()
    for name, st in s.get("steps", {}).items():
        if st.get("n", 0) >= 3:
            out[f"step:{name}"] = (f"The cloud job '{name}' failed {st['n']} times in a row ({st.get('error', '')}). "
                                   "I keep retrying; tell Claude if this stays.")
    if store is not None:
        try:
            from .cloud import media
            raw = store.get(media.TAG, HELPER_ASSET)
            hb = json.loads(raw) if raw else None
        except Exception:  # noqa: BLE001
            hb = None
        if hb is None or now - float(hb.get("at") or 0) > HELPER_LATE_H * 3600:
            out["helper"] = ("The PC helper is off. Long videos, campaign footage, Pinterest pins and books wait "
                             "until it runs. Fix: turn the PC on and double-click scripts\\helper.cmd.")
        elif not hb.get("chrome"):
            out["chrome"] = ("The HookHouse Chrome window on the PC is closed, so I can't see your campaign joins or "
                             "post pins. Fix: double-click scripts\\chrome.cmd on the PC (don't close that window).")
        if hb is not None and now - float(hb.get("at") or 0) <= HELPER_LATE_H * 3600:
            for k, text in (hb.get("alerts") or {}).items():
                out[f"pc:{k}"] = str(text)
    out.update(_campaigns_waiting(now))
    out.update(_videos(now))
    return out


def _campaigns_waiting(now: float) -> dict[str, str]:
    from . import db
    try:
        picked = db.list_campaigns(db.connect(), "picked")
    except Exception as _swallowed:  # noqa: BLE001
        noted("watchdog.py:98", _swallowed)
        return {}
    from .telegram_bot import joinable
    late = [c for c in picked if now - float(c.get("picked_at") or now) > 12 * 3600 and joinable(c)]
    if late:
        try:                                        # paused/ended meanwhile: close them, don't ask to join
            from . import discover
            late = discover.refresh_states(late)
        except Exception as _swallowed:  # noqa: BLE001
            noted("watchdog.py:106", _swallowed)
            pass
    if not late:
        return {}
    names = "\n".join(f"• {c.get('name', '')[:50]}" for c in late[:8])
    # 28 Nov: joins go through our system (owner 20 Nov): the owner's Confirm is the consent, campaign_join joins
    return {"campaigns": (f"{len(late)} campaign(s) you ticked are not joined yet, so no clips can be made. Open "
                          f"💰 Campaigns in Telegram and tap ✅ Confirm: the system checks the footage and joins each "
                          f"one for you (a campaign without usable footage is skipped, with the reason):\n{names}")}


def _videos(now: float) -> dict[str, str]:
    from . import autopilot, storyboard
    out = {}
    try:
        items = [it for _, it in autopilot.items(14, 9)]
    except Exception:  # noqa: BLE001
        return out
    dead = [it for it in items if it.get("status") in ("failed", "redo") and (it.get("attempts") or 0) >= 3
            and autopilot._when(it).timestamp() > now]
    if dead:
        out["dead"] = (f"{len(dead)} upcoming video(s) failed 3 times and are skipped: "
                       + "; ".join(f"{it.get('channel_name')}: {str(it.get('error'))[:80]}" for it in dead[:4]))
    try:
        if storyboard.images_blocked():
            reset = time.strftime("%H:%M", time.localtime(storyboard.reset_at()))
            out["pictures"] = (f"Today's free cloud pictures are used up (next try {reset}). While the PC is on and "
                               "idle it draws story pictures itself (about 2 minutes each, capped per day); Brain "
                               "Snack, kids and clip videos keep going. Nothing to do.")
    except Exception as _swallowed:  # noqa: BLE001
        noted("watchdog.py:133", _swallowed)
        pass
    made = [float(it.get("made_at") or 0) for it in items if it.get("made_at")]
    if items and made and now - max(made) > 24 * 3600:
        out["stalled"] = ("No new video was made in the last 24 hours. I'm checking the makers; tell Claude "
                          "'no videos made' if this stays.")
    return out


# ---------------- alerts ----------------
INFO_ONLY = {"pictures"}                         # once a day, no "fixed" message


def run(store=None, send=None, log=print, now: float | None = None) -> list[str]:
    """Send new/repeated alerts and 'fixed' notes. Returns the keys alerted this time."""
    if send is None:
        from .telegram_bot import notify as send
    now = now or time.time()
    s = _load()
    sent = s.setdefault("sent", {})
    found = problems(store, now)
    alerted = []
    for key, text in found.items():
        every = 20 if key in INFO_ONLY else ALERT_EVERY_H
        if now - float(sent.get(key, 0)) >= every * 3600:
            send(("ℹ️ " if key in INFO_ONLY else "⚠️ ") + text)
            sent[key] = now
            alerted.append(key)
    for key in [k for k in sent if k not in found]:
        if key not in INFO_ONLY and not key.startswith("campaigns"):
            send(f"✅ Fixed: {_label(key)} is working again.")
        sent.pop(key)
    _save(s)
    if alerted:
        log(f"watchdog: alerted {', '.join(alerted)}")
    return alerted


def _label(key: str) -> str:
    return {"helper": "the PC helper", "chrome": "the HookHouse Chrome window", "dead": "the skipped videos",
            "stalled": "video making"}.get(key, key.replace("step:", "the cloud job "))
