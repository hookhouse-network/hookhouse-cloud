"""YouTube channel branding by the official API (owner, 12 Nov 2026: "replace all the manual processes").

Once a channel is connected, the system writes its About text, keywords, country, language and banner itself
(channels.list + channelBanners.insert + channels.update, about 101 quota units once) and does it again whenever
the texts in config/channels/*.yaml or the banner file change. YouTube has no API for the profile picture: the
setup assistant shows the ready file (output/brand/<channel>/avatar.png) to upload by hand once.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

import requests

from .config import ROOT, channels as all_channels
from .publish import SECRETS, YT_API, add_quota, quota_ok, yt_access_token, yt_token_path
from engine.core.http import HTTP

STATE = ROOT / "data" / "state" / "branding.json"
BRAND = ROOT / "output" / "brand"
BANNER_MAX = 6 * 1024 * 1024            # channelBanners.insert limit


def social_lines(cid: str) -> list[str]:
    """The channel's own accounts on other platforms (config/links.yaml + its connected Facebook Page), one line each."""
    import yaml
    try:
        links = (yaml.safe_load((ROOT / "config" / "links.yaml").read_text(encoding="utf-8")) or {}).get(cid) or {}
    except (OSError, yaml.YAMLError):
        links = {}
    out = []
    from .links import _ig_connected
    ig = str(links.get("instagram") or "").lstrip("@") if _ig_connected(cid) else ""
    if ig:
        out.append(f"📸 Instagram: https://www.instagram.com/{ig}")
    fb = str(links.get("facebook") or "")
    if not fb:
        try:
            page = json.loads((SECRETS / f"meta_{cid}.json").read_text(encoding="utf-8")).get("page_id")
            fb = f"https://www.facebook.com/{page}" if page else ""
        except (OSError, ValueError):
            fb = ""
    if fb:
        out.append(f"📘 Facebook: {fb}")
    return out


def about_text(ch: dict) -> str:
    """YouTube About (max 1,000 characters): the channel's About text, then the contact page (never an email)."""
    text = str(ch.get("about") or ch.get("bio") or "").strip()
    social = social_lines(ch["id"]) if ch.get("id") else []
    if social:                         # owner 19 Nov: link the same brand across platforms (Meta <-> YouTube)
        text += "\n\nFollow us:\n" + "\n".join(social)
    url = os.environ.get("CONTACT_URL", "").strip()
    if url and "@" not in url.split("//")[-1].split("/")[0]:
        text += f"\n\nBusiness enquiries: {url}"
    return text[:1000]


def keywords_text(ch: dict) -> str:
    """Channel keywords: space separated, multi-word ones in quotes, max 500 characters."""
    out = ""
    for k in ch.get("keywords") or []:
        k = str(k).replace('"', "").strip()
        part = f'"{k}"' if " " in k else k
        if k and len(out) + len(part) + 1 <= 500:
            out = f"{out} {part}".strip()
    return out


def banner_path(ch: dict) -> Path | None:
    p = BRAND / ch["id"] / "youtube_banner.jpg"
    return p if p.exists() and p.stat().st_size <= BANNER_MAX else None


def fingerprint(ch: dict) -> str:
    """Changes when the texts or the banner change -> branding is written again."""
    b = banner_path(ch)
    raw = json.dumps([about_text(ch), keywords_text(ch), ch.get("language"),
                      hashlib.sha1(b.read_bytes()).hexdigest() if b else ""], ensure_ascii=False)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save(st: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(st, indent=1), encoding="utf-8")


def merged_settings(current: dict, ch: dict, banner_url: str = "") -> dict:
    """channels.update replaces the whole brandingSettings part: keep every existing value, change only ours."""
    bs = json.loads(json.dumps(current or {}))
    chan = bs.setdefault("channel", {})
    chan["description"] = about_text(ch)
    kw = keywords_text(ch)
    if kw:
        chan["keywords"] = kw
    chan["country"] = "IN"                                          # the owner lives in India (payments, YPP)
    chan["defaultLanguage"] = "hi" if ch.get("language") == "hi" else "en"
    if banner_url:
        bs.setdefault("image", {})["bannerExternalUrl"] = banner_url
    for k in ("watchIconImageUrl", "trackingImageUrl"):              # read-only leftovers would fail the update
        bs.get("watch", {}).pop(k, None)
    return bs


def apply(ch: dict, session=HTTP, force: bool = False, log=print) -> str:
    """Write one channel's branding. Returns a short result line."""
    cid = ch["id"]
    if not yt_token_path(cid).exists():
        return f"{ch['name']}: not connected yet"
    fp, st = fingerprint(ch), _state()
    if not force and st.get(cid, {}).get("fingerprint") == fp:
        return f"{ch['name']}: already up to date"
    if not quota_ok(101):
        return f"{ch['name']}: waiting for tomorrow's YouTube quota"
    token = yt_access_token(cid, session)
    if not token:
        return f"{ch['name']}: sign-in expired (reconnect)"
    auth = {"Authorization": f"Bearer {token}"}
    r = session.get(f"{YT_API}/channels", params={"part": "brandingSettings,snippet", "mine": "true"}, headers=auth,
                    timeout=30)
    r.raise_for_status()
    items = r.json().get("items") or []
    add_quota(1)
    if not items:
        return f"{ch['name']}: this Google account has no YouTube channel"
    yt_id, current = items[0]["id"], items[0].get("brandingSettings") or {}
    handle = (items[0].get("snippet") or {}).get("customUrl", "")
    try:                                                         # the real @handle -> cross-links go live
        from . import links
        links.set_link(cid, youtube=("@" + handle.lstrip("@")) if handle else None, live=True)
    except Exception as e:  # noqa: BLE001 - links are a nice-to-have
        log(f"links {cid}: {e}")
    banner_url, b = "", banner_path(ch)
    old = st.get(cid, {})
    if b and (force or old.get("banner_sha") != hashlib.sha1(b.read_bytes()).hexdigest()):
        rb = session.post("https://www.googleapis.com/upload/youtube/v3/channelBanners/insert",
                          params={"uploadType": "media"}, headers={**auth, "Content-Type": "image/jpeg"},
                          data=b.read_bytes(), timeout=120)
        rb.raise_for_status()
        banner_url = rb.json().get("url", "")
        add_quota(50)
    body = {"id": yt_id, "brandingSettings": merged_settings(current, ch, banner_url)}
    ru = session.put(f"{YT_API}/channels", params={"part": "brandingSettings"},
                     headers={**auth, "Content-Type": "application/json"}, data=json.dumps(body), timeout=30)
    if not ru.ok:
        log(f"branding {cid}: {ru.status_code} {ru.text[:300]}")
        ru.raise_for_status()
    add_quota(50)
    st[cid] = {"fingerprint": fp, "at": time.time(), "youtube_id": yt_id,
               "banner_sha": hashlib.sha1(b.read_bytes()).hexdigest() if b else old.get("banner_sha", "")}
    _save(st)
    return f"{ch['name']}: About, keywords, country, language" + (" and banner" if banner_url else "") + " written"


def apply_all(session=HTTP, log=print) -> list[str]:
    """Daily (09:00 job) and right after connecting: every connected channel whose branding is missing or old."""
    out = []
    for ch in all_channels():
        if not yt_token_path(ch["id"]).exists():
            continue
        if _state().get(ch["id"], {}).get("fingerprint") == fingerprint(ch):
            continue
        try:
            out.append(apply(ch, session, log=log))
        except Exception as e:  # noqa: BLE001 - try again tomorrow
            out.append(f"{ch['name']}: branding failed ({str(e)[:120]})")
    return out


def done_count() -> int:
    """Connected channels with up-to-date branding (to-do auto-tick)."""
    st = _state()
    return sum(1 for ch in all_channels()
               if (SECRETS / f"youtube_{ch['id']}.json").exists() and st.get(ch["id"], {}).get("fingerprint") == fingerprint(ch))
