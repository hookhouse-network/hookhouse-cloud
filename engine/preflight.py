"""Connection test BEFORE posting time (owner, 18 Nov 2026: "no testing before upload time to check the connection
for different platforms; this causes us missed opportunities").

Every cloud run: if an approved video is due in the next LEAD_H hours, the logins of the platforms it will go to
are tested with read-only calls (engine/doctor.py checks, at most once per CACHE_H per platform). A broken login is
reported to the owner while there is still time to fix it (one message per problem per day, with the exact step),
and counted in the heal queue (owner kind; a failure that isn't a login problem becomes a code item there).
Nothing is posted or changed on any platform here.
"""
from __future__ import annotations

import json
import time
from datetime import timedelta

from .config import ROOT

STATE = ROOT / "data" / "state" / "preflight.json"
LEAD_H = 3
CACHE_H = 2
TELL_EVERY_H = 20
CHECKS = {"youtube": "youtube", "instagram": "meta", "facebook": "meta", "threads": "threads",
          "dailymotion": "dailymotion", "telegram": "telegram"}


def _load() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"checked": {}, "told": {}}


def _save(s: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(s, indent=1), encoding="utf-8")


def _platform_of(area: str) -> str:
    a = area.lower()
    for p in ("youtube", "instagram", "facebook", "threads", "dailymotion", "telegram"):
        if a.startswith(p):
            return p
    return ""


def _channel_of(area: str) -> str:
    parts = area.split(" ", 1)
    return parts[1].strip() if len(parts) == 2 else ""


def due_targets(now=None) -> dict[str, set[str]]:
    """platform -> channels with an approved video due within LEAD_H hours (connected platforms only)."""
    from . import autopilot, platforms
    from .config import channel as get_channel

    def connected_platforms(cid: str) -> list[str]:
        ch = get_channel(cid)
        return [p for p in platforms.by_mode(ch, "auto") if p in CHECKS]

    now = now or autopilot._now()
    out: dict[str, set[str]] = {}
    for _, it in autopilot.items(0, 1):
        if it.get("status") != "approved":
            continue
        w = autopilot._when(it)
        if not (now - timedelta(minutes=30) <= w <= now + timedelta(hours=LEAD_H)):
            continue
        try:
            plats = connected_platforms(it["channel"])
        except Exception:  # noqa: BLE001
            plats = ["youtube"]
        for p in plats:
            out.setdefault(p, set()).add(it["channel"])
    return out


def run(session=None, send=None, log=print, now: float | None = None) -> list[str]:
    """Returns the problems found this time (plain text)."""
    import requests
    from . import doctor, heal
    session = session or requests
    now = now or time.time()
    targets = due_targets()
    if not targets:
        return []
    s = _load()
    checks = {CHECKS[p] for p in targets if p in CHECKS
              and now - float(s["checked"].get(CHECKS[p], 0)) >= CACHE_H * 3600}
    problems = []
    for name in sorted(checks):
        try:
            results = getattr(doctor, name)(session)
        except Exception as e:  # noqa: BLE001
            results = [{"area": name, "status": "bad", "seen": f"check failed: {type(e).__name__}: {e}", "fix": ""}]
        s["checked"][name] = now
        for r in results:
            if r["status"] != "bad":
                if r["status"] == "good":
                    heal.resolve(f"preflight:{r['area']}:")
                continue
            plat, ch = _platform_of(r["area"]), _channel_of(r["area"])
            if plat and plat in targets and ch and ch not in targets[plat]:
                continue                              # nothing due there soon: the doctor/morning check covers it
            text = f"{r['area']}: {r['seen']}" + (f" → {r['fix']}" if r.get("fix") else "")
            problems.append(text)
            heal.report(f"preflight:{r['area']}", r["seen"], channel=ch, platform=plat)
    _save(s)
    if problems:
        fresh = [p for p in problems if now - float(s["told"].get(p[:80], 0)) >= TELL_EVERY_H * 3600]
        if fresh:
            if send is None:
                from .telegram_bot import notify as send
            send(f"🔌 Connection test before the next posts (due within {LEAD_H} h) found a problem. Fix it now and "
                 "the posts go out on time:\n• " + "\n• ".join(fresh[:6]))
            for p in fresh:
                s["told"][p[:80]] = now
            _save(s)
    log(f"preflight: {len(checks)} platform check(s), {len(problems)} problem(s)")
    return problems
