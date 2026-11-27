"""P5 (27 Nov): every resource budget in one place, for the Control Center's Budgets screen and the health digest.
Reads what the system already records (no new counters): AI calls per provider today (engine/brain/router.py usage
file, incl. 'daily_quota' refusals), the picture sources marked used up and until when (storyboard's quota file),
and the PC's local pictures against their daily cap (media/local_sd)."""
from __future__ import annotations

import json
import time
from pathlib import Path

from .config import ROOT


def _read(p: Path) -> dict:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def ai_today(path: Path | None = None, day: str | None = None) -> list[dict]:
    """[{provider, calls, errors, quota_hits}] for today, most used first."""
    d = _read(path or ROOT / "data" / "pc" / "brain_usage.json").get(day or time.strftime("%Y-%m-%d"), {})
    per: dict[str, dict] = {}
    for key, row in d.items():
        prov = key.split("|", 1)[-1]
        p = per.setdefault(prov, {"provider": prov, "calls": 0, "errors": 0, "quota_hits": 0})
        p["calls"] += int(row.get("calls") or 0)
        errs = row.get("errors") or {}
        p["errors"] += sum(int(v) for v in errs.values())
        p["quota_hits"] += int(errs.get("daily_quota") or 0)
    return sorted(per.values(), key=lambda r: -r["calls"])


def pictures(path: Path | None = None, now: float | None = None) -> list[dict]:
    """[{source, open, until}] for the picture sources: used up until a reset, or open."""
    now = now or time.time()
    q = _read(path or ROOT / "data" / "pc" / "image_quota.json")
    out = []
    for k, v in sorted(q.items()):
        if ":" in k:
            continue
        try:
            until = float(v)
        except (TypeError, ValueError):
            continue
        out.append({"source": k, "open": until <= now,
                    "until": time.strftime("%d %b %H:%M", time.localtime(until)) if until > now else ""})
    return out


def local_pictures() -> dict:
    """{used, cap, why_not}: the PC's own pictures today."""
    try:
        from .media import local_sd
        return {"used": local_sd.used_today(), "cap": int(local_sd.cfg().get("max_day") or 0),
                "why_not": local_sd.why_not(start=True) or ""}
    except Exception as e:  # noqa: BLE001 - the screen still shows the other budgets
        return {"used": 0, "cap": 0, "why_not": f"unknown ({type(e).__name__})"}


def summary() -> dict:
    return {"ai": ai_today(), "pictures": pictures(), "local": local_pictures()}
