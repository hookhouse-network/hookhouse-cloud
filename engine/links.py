"""Cross-links between our channels and platforms (config/links.yaml): a short footer on YouTube descriptions that
sends viewers to related sibling channels and to the channel's Instagram, plus a plan of what to put in each YouTube
"Links" section and Instagram bio. Only channels marked live are linked; Made-for-Kids videos get no cross-links."""
from __future__ import annotations

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


def _ig_connected(channel_id: str) -> bool:
    from .publish import SECRETS
    return (SECRETS / f"meta_{channel_id}.json").exists()


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
    except Exception:  # noqa: BLE001 - a missing store record never breaks a description
        pass
    return "\n".join(lines)


def plan_md(chans: list[dict]) -> str:
    """What to add by hand in YouTube Studio > Customization > Links, and in each Instagram bio."""
    d = data()
    out = ["# Links plan (YouTube channel links + Instagram bios)", "",
           "YouTube Studio > Customization > Basic info > Links (up to 14). Instagram: Edit profile > Links (up to 5).",
           "Set live: true in config/links.yaml when a channel's accounts exist, so descriptions start linking them.", ""]
    for ch in chans:
        me = d.get(ch["id"]) or {}
        sibs = [d.get(s, {}).get("youtube", s) for s in (d.get("siblings") or {}).get(ch["id"], [])]
        out.append(f"## {ch['name']} ({'live' if me.get('live') else 'not live yet'})")
        if ch.get("made_for_kids"):
            out.append("- Made for Kids: no social links (YouTube rule); optional link: the counting activity book once "
                       "it is published.")
            out.append("")
            continue
        if me.get("instagram"):
            out.append(f"- YouTube links: Instagram @{me['instagram']}" + (f"; sister channels {', '.join(sibs)}" if sibs else ""))
            out.append(f"- Instagram bio link: the YouTube channel {me.get('youtube', '')} (or its full-episodes playlist)")
        else:
            out.append(f"- YouTube links: sister channels {', '.join(sibs)}")
        out.append("")
    return "\n".join(out)
