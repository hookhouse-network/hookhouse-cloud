"""Which platforms each channel's videos go to (config/platforms.yaml), with the safety rules in one place:
- Made-for-Kids videos never go to 13+ social apps.
- Campaign clips go only to platforms the campaign's brief lists (the footage licence covers those platforms only).
- A platform can be limited to some channels (e.g. Pinterest only for evergreen explainer channels).
"""
from __future__ import annotations

from functools import lru_cache

import yaml

from .config import ROOT

FILE = ROOT / "config" / "platforms.yaml"
KIDS_OK = {"youtube", "dailymotion", "spotify_music", "amazon_kdp"}
OPEN_BASIS = {"public_domain_us_gov", "cc_by", "cc_by_sa"}         # footage anyone may reuse with credit
OWN_ONLY = {"dailymotion"}                                      # platforms for our own / openly licensed material
CAMPAIGN_NAMES = {"youtube": "youtube_shorts", "instagram": "instagram_reels", "facebook": "facebook_reels",
                  "snapchat": "snapchat", "x": "x", "threads": "threads", "pinterest": "pinterest"}


@lru_cache(maxsize=1)
def registry() -> dict:
    return yaml.safe_load(FILE.read_text(encoding="utf-8")) or {} if FILE.exists() else {}


def _campaign_platforms(campaign_id: str | None) -> list[str] | None:
    if not campaign_id:
        return None
    try:
        from . import db
        c = db.get_campaign(db.connect(), campaign_id) or {}
        return [str(p) for p in c.get("platforms") or []] or None
    except Exception:  # noqa: BLE001
        return None


def allowed(ch: dict, platform: str, meta: dict | None = None) -> bool:
    """May this channel's video (meta = its upload metadata) go to this platform?"""
    spec = registry().get(platform)
    if not spec:
        return platform == "youtube"
    meta = meta or {}
    if ch.get("type") not in (spec.get("content") or []):
        return False
    if spec.get("channels") and ch.get("id") not in spec["channels"]:
        return False
    if (meta.get("made_for_kids") or ch.get("made_for_kids") or ch.get("type") == "kids") and platform not in KIDS_OK:
        return False
    if ch.get("type") == "clips" and platform in OWN_ONLY and meta:
        basis = (meta.get("permission") or {}).get("basis")
        if meta.get("campaign") or basis not in OPEN_BASIS:     # campaign / permission-only footage: not here
            return False
    if meta.get("campaign"):                                   # campaign clip: only where the brief allows
        names = _campaign_platforms(meta["campaign"])
        if names is not None and CAMPAIGN_NAMES.get(platform, platform) not in names:
            return False
    return True


def campaign_allows(platform: str, meta: dict | None) -> bool:
    """A campaign clip may only go where its brief lists (20 Nov: YouTube was exempt from this check, so a brief
    without YouTube Shorts would still have been posted there, outside the footage licence)."""
    if not (meta or {}).get("campaign"):
        return True
    names = _campaign_platforms(meta["campaign"])
    return names is None or CAMPAIGN_NAMES.get(platform, platform) in names


def connected(ch: dict, platform: str) -> bool:
    """An 'auto' platform that needs a one-time connection (needs: in platforms.yaml) only posts by itself once
    that connection exists for this channel; until then it stays in the evening winners pack."""
    need = (registry().get(platform) or {}).get("needs")
    if not need:
        return True
    if need == "threads_login":
        from .threads import creds
        return bool(creds(ch["id"]))
    if need == "pinterest_claim":
        from . import todo
        return any(t.get("id") == "pinterest_claim" and t.get("done") for t in todo.items())
    return True


def mode(ch: dict, platform: str) -> str:
    spec = registry().get(platform) or {}
    m = spec.get("post", "")
    return "winners" if m == "auto" and not connected(ch, platform) else m


def by_mode(ch: dict, mode_: str, meta: dict | None = None) -> list[str]:
    """Platforms of one posting mode (auto / winners / later) this channel's video may use."""
    return [p for p in registry() if mode(ch, p) == mode_ and allowed(ch, p, meta)]


EXTRA = {
    "story": ["Affiliate links in descriptions (Amazon Associates; only where a product really fits)",
              "YouTube Hype once monetized (viewers push new long videos up a leaderboard)",
              "Brand deals later (sponsor reads in long videos, clearly labelled)"],
    "brainrot": ["Shorts ad share once monetized", "Brand deals later (quiz sponsors)"],
    "kids": ["Count with Bloop! activity book: Amazon KDP + printable PDF on Gumroad / Teachers Pay Teachers",
             "3 sung songs (data/products/music): Spotify, Apple Music, JioSaavn, YouTube Music via RouteNote",
             "Licensing the library to kids' streaming apps later (as ChuChu TV does)"],
    "clips": ["Clipping campaigns: paid per 1,000 views (median about $1.20; daily finder + /campaigns)",
              "Creator retainers: free trial, then $500-2,000/month per creator (Monday pitches + /trial)"],
}
MODE_LABEL = {"auto": "✅ auto (the system posts)", "winners": "📲 winners (you post our best videos)",
              "later": "⏳ later (after a one-time step)"}
NEEDS_LABEL = {"threads_login": "the channel's Threads is connected (setup assistant); winners pack until then",
               "pinterest_claim": "Pinterest claims the Instagram (Pinterest makes the Pins); winners pack until then"}


def money_map(chans: list[dict]) -> list[dict]:
    """Per channel: every platform it uses, how it is posted and how it earns (dashboard + docs)."""
    out = []
    for ch in chans:
        rows = [{"platform": p, "post": spec.get("post"), "money": spec.get("money", ""), "needs": spec.get("needs", "")}
                for p, spec in registry().items() if allowed(ch, p)]
        out.append({"channel": ch["id"], "name": ch.get("name", ch["id"]), "platforms": rows})
    return out
