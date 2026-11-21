"""Named series per story channel (plan P3r creativity workstream, standard S8 A13). config/series.yaml lists 1-2
series per channel; every freshly written video is an episode of one of them, in rotation. The writer gets one rule
(the series promise), the episode's first hashtag is the series tag (description, tags, Reel caption), and long videos
get the series name as a title prefix when it fits (Shorts keep their search-first title so the hook stays first)."""
from __future__ import annotations

import json

import yaml

from .config import ROOT

FILE = ROOT / "config" / "series.yaml"
STATE = ROOT / "data" / "state" / "series_rotation.json"
LONG_TITLE_MAX = 60


def for_channel(cid: str) -> list[dict]:
    try:
        data = yaml.safe_load(FILE.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as e:
        print(f"series: config unreadable ({type(e).__name__}: {e})")
        return []
    return [s for s in (data.get(cid) or []) if isinstance(s, dict) and s.get("name") and s.get("promise")]


def pick(cid: str) -> dict | None:
    """The next series of this channel in rotation (None when the channel has none)."""
    options = for_channel(cid)
    if not options:
        return None
    try:
        state = json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    i = int(state.get(cid, -1)) + 1
    state[cid] = i % len(options)
    from .core.atomic import write_json
    write_json(STATE, state)
    return options[i % len(options)]


def rule(s: dict | None) -> str:
    """The one line the writer gets."""
    if not s:
        return ""
    return (f"SERIES: this video is an episode of \"{s['name']}\": {s['promise']}. Keep that promise: the angle, the "
            "structure and the payoff must fit the series, so a viewer who liked one episode wants the next.")


def apply(script: dict, s: dict | None, fmt: str = "short") -> dict:
    """Series tag first in the hashtags, the series name on the script, the long-title prefix when it fits."""
    if not s:
        return script
    out = dict(script)
    tag = s.get("hashtag") or "#" + "".join(w.capitalize() for w in str(s["name"]).split())
    tags = [t for t in out.get("hashtags") or [] if str(t).lower() != tag.lower()]
    out["hashtags"] = [tag] + tags
    out["series"] = s["name"]
    title = str(out.get("title") or "")
    if fmt == "long" and title and not title.lower().startswith(s["name"].lower()):
        prefixed = f"{s['name']}: {title}"
        if len(prefixed) <= LONG_TITLE_MAX:
            out["title"] = prefixed
    return out
