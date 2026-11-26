"""Cross-links between our channels and platforms (config/links.yaml): a short footer on YouTube descriptions that
sends viewers to related sibling channels and to the channel's Instagram, plus a plan of what to put in each YouTube
"Links" section and Instagram bio. Only channels marked live are linked; Made-for-Kids videos get no cross-links."""
from __future__ import annotations
from engine.core.quiet import noted

from functools import lru_cache

import yaml

from .config import ROOT

FILE = ROOT / "config" / "links.yaml"
LABEL_HI = {"more": "Aur kahaniyan", "insta": "Instagram"}


@lru_cache(maxsize=1)
def data() -> dict:
    return yaml.safe_load(FILE.read_text(encoding="utf-8")) or {} if FILE.exists() else {}


def set_link(channel_id: str, **fields) -> bool:
    """Change one channel's row in config/links.yaml in place (comments and layout kept), e.g. after the setup
    assistant connected an account: set_link("deep_blue_files", youtube="@DeepBlueFiles", live=True)."""
    import json
    import re
    if not FILE.exists():
        return False
    lines = FILE.read_text(encoding="utf-8").splitlines()
    for i, ln in enumerate(lines):
        m = re.match(r"^(\s*" + re.escape(channel_id) + r":\s*)\{(.*)\}\s*$", ln)
        if not m:
            continue
        row = yaml.safe_load("{" + m.group(2) + "}") or {}
        for k, v in fields.items():
            if v not in (None, ""):
                row[k] = v
        order = ["youtube", "instagram", "telegram"] + [k for k in row if k not in ("youtube", "instagram", "telegram", "live")] + ["live"]
        parts = [f"{k}: {json.dumps(row[k], ensure_ascii=False) if not isinstance(row[k], bool) else str(row[k]).lower()}"
                 for k in order if k in row]
        lines[i] = m.group(1) + "{" + ", ".join(parts) + "}"
        FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
        data.cache_clear()
        return True
    return False


def hold_note(channel_id: str, platform: str) -> str:
    """Why posting to this channel's account on this platform is on hold ("" = post normally). Set in links.yaml as
    `<platform>_hold: "<reason>"` (25 Nov: Instagram hid @brainsnackdose until the owner confirms it's human; Threads
    posts through the same Instagram account, so an Instagram hold holds Threads too). Remove the field to resume."""
    try:
        row = data().get(channel_id) or {}
    except Exception as e:  # noqa: BLE001 - an unreadable links file never stops posting
        print(f"hold check: {type(e).__name__}: {e}")
        return ""
    note = row.get(f"{platform}_hold") or (row.get("instagram_hold") if platform == "threads" else "")
    return str(note or "")


def _ig_connected(channel_id: str) -> bool:
    """The Instagram account really exists and is ours: connected to Meta, or marked instagram_live in links.yaml
    (created, not connected yet). A planned handle alone may belong to a stranger."""
    from .publish import SECRETS
    if (SECRETS / f"meta_{channel_id}.json").exists():
        return True
    try:
        return bool((data().get(channel_id) or {}).get("instagram_live"))
    except Exception as _swallowed:  # noqa: BLE001
        noted("links.py:68", _swallowed)
        return False


def footer(channel_id: str, language: str = "en", kids: bool = False) -> str:
    """Two or three lines for the end of a YouTube description ("" if nothing is live yet)."""
    d = data()
    me = d.get(channel_id) or {}
    if kids or not me.get("live"):
        return ""
    sibs = [d[s]["youtube"] for s in (d.get("siblings") or {}).get(channel_id, [])
            if (d.get(s) or {}).get("live") and d[s].get("youtube")]
    lines = []
    if sibs:
        lines.append(("▶ " + (LABEL_HI["more"] if language == "hi" else "More stories you'll like") + ": " +
                      " · ".join(sibs)))
    if me.get("instagram") and _ig_connected(channel_id):   # 17 Nov: only accounts we really own (a planned handle
        lines.append(f"📸 Instagram: @{me['instagram']}")   # may belong to a stranger until we create it)
    try:                                          # owner, 14 Nov: link our store products to increase selling
        from .store_publish import shop_link
        free = shop_link(channel_id, free=True)       # owner, 16 Nov (articles): free sample first, it converts
        if free:                                      # cold viewers; its last page sells the full version
            lines.append(f"🎁 {free[0]}: {free[1]}")
        shop = shop_link(channel_id)
        if shop:
            lines.append(f"🛍️ {shop[0]}: {shop[1]}")
    except Exception as _swallowed:  # noqa: BLE001 - a missing store record never breaks a description
        noted("links.py:94", _swallowed)
        pass
    return "\n".join(lines)


