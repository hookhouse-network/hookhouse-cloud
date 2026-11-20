"""KV daily budget (owner 20 Nov 2026: the Cloudflare free plan allows 1,000 KV writes / deletes / lists a day; "you
have to handle this as well with our system").

Measured 14-20 Nov (Cloudflare analytics): writes 15 -> 287 a day and rising with volume (previews, dashboard, Telegram
taps); lists peaked at 813 on 18 Nov. Past the cap every further write FAILS until 00:00 UTC, which would break the
Telegram buttons and the Studio.

How the budget works:
  - The real count comes from Cloudflare's own analytics (GraphQL kvOperationsAdaptiveGroups, the Worker's writes
    included), refreshed at most every REFRESH_S; between refreshes our own writes are added locally.
  - Every key belongs to a class. When the day's usage of an operation passes the class's share of the cap, writes
    of that class pause until the reset (they are skipped, never errors):
        bulk     (pv: review previews)              pauses at 55 %  (TTL cleans old ones; they retry next run)
        normal   (dash: the Studio page)            pauses at 75 %
        critical (everything Telegram/owner-facing) pauses at 97 %  (the Worker's own writes need the rest)
  - Crossing ALERT_AT tells the owner once a day (and the heal queue), crossing 90 % again.
  - No analytics access -> local counts plus a reserve for the Worker's writes (fail safe: pauses earlier).
The structural fix (Telegram state in a Durable Object's SQLite, 100,000 writes/day free) is phase 1 of
docs/MASTER_PLAN_2026-11-20.md."""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone

from ..config import ROOT

FILE = ROOT / "data" / "state" / "kv_usage.json"
CAPS = {"write": 1000, "delete": 1000, "list": 1000}
SHARE = {"bulk": 0.55, "normal": 0.75, "critical": 0.97}
ALERT_AT = 0.70
REFRESH_S = 1200
WORKER_RESERVE = 250          # writes the Worker may make that we can't see without analytics
GRAPHQL = "https://api.cloudflare.com/client/v4/graphql"


def klass(key: str) -> str:
    if key.startswith("pv:"):
        return "bulk"
    if key.startswith("dash:"):
        return "normal"
    return "critical"


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _load() -> dict:
    try:
        d = json.loads(FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        d = {}
    if d.get("day") != _today():
        d = {"day": _today(), "real": {}, "local": {}, "fetched": 0, "alerts": [], "measured": False,
             "skipped": {}}
    return d


def _save(d: dict) -> None:
    try:
        from ..core.atomic import write_json
        write_json(FILE, d)
    except OSError as e:
        print(f"kv budget: could not save ({e})")


def fetch_real(session=None, now: float | None = None) -> dict | None:
    """Today's KV operations from Cloudflare analytics: {"write": n, "delete": n, "list": n, "read": n} or None."""
    import requests
    tok, acc = os.environ.get("CLOUDFLARE_API_TOKEN", ""), os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")
    if not (tok and acc):
        return None
    q = ("query($acc: String!, $d: Date!) { viewer { accounts(filter: {accountTag: $acc}) { "
         "kvOperationsAdaptiveGroups(filter: {date: $d}, limit: 20) { sum { requests } dimensions { actionType } } } } }")
    try:
        r = (session or requests).post(GRAPHQL, headers={"Authorization": f"Bearer {tok}"}, timeout=20,
                                       json={"query": q, "variables": {"acc": acc, "d": _today()}})
        js = r.json()
        if js.get("errors"):
            return None
        rows = js["data"]["viewer"]["accounts"][0]["kvOperationsAdaptiveGroups"]
    except Exception as e:  # noqa: BLE001 - no analytics -> local counts with a reserve
        print(f"kv budget: analytics unavailable ({type(e).__name__})")
        return None
    out: dict[str, int] = {}
    for x in rows:
        out[x["dimensions"]["actionType"]] = out.get(x["dimensions"]["actionType"], 0) + int(x["sum"]["requests"])
    return out


def usage(op: str, d: dict | None = None, session=None, now: float | None = None) -> int:
    """Best estimate of today's count for one operation (analytics + our writes since the last fetch)."""
    d = d if d is not None else _load()
    now = now or time.time()
    if now - float(d.get("fetched") or 0) > REFRESH_S:
        real = fetch_real(session, now)
        d["fetched"] = now
        if real is not None:
            d["real"], d["local"], d["measured"] = real, {}, True
        _save(d)
    base = int((d.get("real") or {}).get(op, 0))
    reserve = 0 if d.get("measured") or op != "write" else WORKER_RESERVE
    return base + int((d.get("local") or {}).get(op, 0)) + reserve


def allow(op: str, key: str, session=None, now: float | None = None, notify=None) -> bool:
    """May we spend one `op` on `key` now? Counts it when yes; records a skip when no."""
    if op not in CAPS:
        return True
    d = _load()
    used = usage(op, d, session, now)
    cap = CAPS[op]
    ok = used < SHARE[klass(key)] * cap
    if ok:
        d.setdefault("local", {})[op] = int(d["local"].get(op, 0)) + 1
    else:
        sk = d.setdefault("skipped", {})
        sk[f"{op}:{klass(key)}"] = int(sk.get(f"{op}:{klass(key)}", 0)) + 1
    level = 0.9 if used >= 0.9 * cap else ALERT_AT if used >= ALERT_AT * cap else 0
    tag = f"{op}:{level}"
    if level and tag not in d.setdefault("alerts", []):
        d["alerts"].append(tag)
        msg = (f"⚠️ Cloudflare free storage: {used} of {cap} {op}s used today (resets 05:30 IST). "
               f"Previews and page refreshes pause first; Telegram buttons keep working.")
        try:
            (notify or _notify)(msg)
            from .. import heal
            heal.report("kv", f"KV {op}s at {used}/{cap} today")
        except Exception as e:  # noqa: BLE001 - the budget decision matters more than the message
            print(f"kv budget alert failed: {type(e).__name__}: {e}")
    _save(d)
    return ok


def _notify(text: str) -> None:
    from ..telegram_bot import notify
    notify(text)


def status() -> str:
    d = _load()
    real = d.get("real") or {}
    parts = [f"{op}s {int(real.get(op, 0)) + int((d.get('local') or {}).get(op, 0))}/{cap}" for op, cap in CAPS.items()]
    skipped = sum(int(v) for v in (d.get("skipped") or {}).values())
    return "🗄 Cloudflare KV today: " + ", ".join(parts) + (f" · {skipped} low-priority writes paused" if skipped else "")
