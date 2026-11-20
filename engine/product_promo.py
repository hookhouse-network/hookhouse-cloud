"""Value-first promo Shorts for our products (owner 20 Nov 2026: "building, checking and listing new products, plus
promo Shorts for them").

Not an ad: a hard-sell video fails the potential gate (originality, shareability) and Meta/YouTube reward videos
people want to send to friends. So each listed product gets a normal, genuinely useful Short on its matching
channel, about the problem the product solves, and the product's public link goes into that video's description
(publish.item_meta). The video is made by the channel's own maker and passes every gate like any other.

- register(pid): called when a product passes the product gate (store_publish._gate_ok). Kids channels are never
  used (no selling to children; YouTube made-for-kids rules).
- plan_week calls promo_for(channel) once per channel per week: a story channel gets the product's value-first angle
  as one Short's topic; other channels keep their topic and only carry the link.
- At most PER_PRODUCT promo Shorts per product, never two in one week on a channel."""
from __future__ import annotations

import json
import time

from .config import ROOT

FILE = ROOT / "data" / "state" / "product_promos.json"
PROD = ROOT / "data" / "products"
PER_PRODUCT = 3
NO_PROMO_TYPES = {"kids"}


def _load() -> dict:
    try:
        return json.loads(FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save(d: dict) -> None:
    from .core.atomic import write_json
    write_json(FILE, d)


def register(pid: str) -> bool:
    if pid.startswith("free_"):
        return False
    try:
        meta = json.loads((PROD / pid / "product.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    ch = meta.get("channel")
    try:
        from .config import channel
        info = channel(ch) if ch else {}
    except Exception as e:  # noqa: BLE001
        print(f"promo: channel {ch} unknown ({type(e).__name__})")
        return False
    if not ch or info.get("type") in NO_PROMO_TYPES or info.get("made_for_kids"):
        return False
    d = _load()
    if pid in d:
        return False
    d[pid] = {"channel": ch, "title": meta["title"], "angles": list(meta.get("promo_angles") or []),
              "added": time.time(), "planned": []}
    _save(d)
    return True


def link(pid: str) -> str:
    """The product's public store link (Payhip first, then Gumroad)."""
    try:
        listed = json.loads((PROD / "listed.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    stores = listed.get(pid) or {}
    for s in ("payhip", "gumroad"):
        url = (stores.get(s) or {}).get("public")
        if url:
            return str(url)
    return ""


def promo_for(channel_id: str, week: str) -> dict | None:
    """{pid, title, angle|None} for one Short of this channel this week, or None. Marks it planned."""
    d = _load()
    for pid, info in sorted(d.items(), key=lambda x: len(x[1].get("planned") or [])):
        if info.get("channel") != channel_id or len(info.get("planned") or []) >= PER_PRODUCT:
            continue
        if week in (info.get("planned") or []) or not link(pid):
            continue
        k = len(info.get("planned") or [])
        angles = info.get("angles") or []
        info.setdefault("planned", []).append(week)
        _save(d)
        return {"pid": pid, "title": info["title"], "angle": angles[k % len(angles)] if angles else None}
    return None


def description_line(it: dict) -> str:
    pid = it.get("product")
    if not pid:
        return ""
    url = link(pid)
    if not url:
        return ""
    title = (_load().get(pid) or {}).get("title") or pid.replace("_", " ").title()
    return f"\n\n🛒 {title}: {url}"
