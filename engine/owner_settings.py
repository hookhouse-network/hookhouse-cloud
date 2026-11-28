"""P10 owner settings (28 Nov): a few owner-level switches the owner changes safely in three taps (Telegram /settings
-> a switch -> its value), honoured by the cloud from its next run.

Safe by construction: only the switches listed in SWITCHES can be overridden, only with their listed values, and each
value says in plain words what it changes (the impact preview). The choice lives in the cloud memory
(data/state/owner_settings.json), so no code push is needed; config.settings() and content_gate.config() merge it."""
from __future__ import annotations

import copy
import json
import time
from pathlib import Path

from .config import ROOT

STATE = ROOT / "data" / "state" / "owner_settings.json"

SWITCHES: dict[str, dict] = {
    "data_story": {
        "label": "Chart Shorts when pictures run out", "file": "settings", "path": ["data_story"],
        "values": {"on": ("on", "Money Cheat Codes, Cosmos Unboxed and Deep Blue Files still post a Short told with "
                                "charts when the free pictures are used up"),
                   "off": ("off", "those channels wait for pictures instead (fewer videos on low-picture days)")}},
    "local_pictures": {
        "label": "The PC draws its own pictures", "file": "settings", "path": ["local_pictures", "enabled"],
        "values": {"on": (True, "the PC draws pictures when it is idle and plugged in (up to its daily cap)"),
                   "off": (False, "the PC never draws pictures; story videos wait for the free cloud pictures")}},
    "auto_approve": {
        "label": "Automatic approval", "file": "gates", "path": ["auto_approve", "enabled"],
        "values": {"on": (True, "a video that passes every gate is approved by the system; you get a Stop it button"),
                   "off": (False, "every video waits for your Approve tap before it posts")}},
}


def load(path: Path | None = None) -> dict:
    try:
        d = json.loads((path or STATE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in d.items() if k in SWITCHES and isinstance(v, dict)
            and v.get("value") in SWITCHES[k]["values"]}


def choose(key: str, value: str, by: str = "owner", path: Path | None = None) -> str:
    """Save the owner's choice. Raises ValueError for anything not on the list."""
    sw = SWITCHES.get(key)
    if not sw or value not in sw["values"]:
        raise ValueError(f"not a setting choice: {key}={value}")
    p = path or STATE
    d = load(p)
    d[key] = {"value": value, "at": time.strftime("%Y-%m-%d %H:%M"), "by": by}
    p.parent.mkdir(parents=True, exist_ok=True)
    from .core.atomic import write_json
    write_json(p, d)
    return sw["values"][value][1]


def apply(cfg: dict, file: str, path: Path | None = None) -> dict:
    """cfg with the owner's choices for this config file merged in (a copy; cfg is never changed)."""
    chosen = {k: v for k, v in load(path).items() if SWITCHES[k]["file"] == file}
    if not chosen:
        return cfg
    out = copy.deepcopy(cfg)
    for key, rec in chosen.items():
        sw = SWITCHES[key]
        node = out
        for part in sw["path"][:-1]:
            if not isinstance(node.get(part), dict):
                node[part] = {}
            node = node[part]
        node[sw["path"][-1]] = sw["values"][rec["value"]][0]
    return out


def current(key: str, cfgs: dict[str, dict]) -> str:
    """'on'/'off' (the value name) as it is in effect now, read from the merged config."""
    sw = SWITCHES[key]
    node = cfgs.get(sw["file"]) or {}
    for part in sw["path"]:
        node = node.get(part) if isinstance(node, dict) else None
    for name, (stored, _why) in sw["values"].items():
        if node == stored:
            return name
    return next(iter(sw["values"]))


def rows() -> list[dict]:
    """[{key, label, now, why, other, other_why}] for the screens (Telegram /settings, Control Center)."""
    from . import content_gate
    from .config import settings
    cfgs = {"settings": settings() or {}, "gates": content_gate.config() or {}}
    out = []
    for key, sw in SWITCHES.items():
        now = current(key, cfgs)
        other = next(n for n in sw["values"] if n != now)
        out.append({"key": key, "label": sw["label"], "now": now, "why": sw["values"][now][1],
                    "other": other, "other_why": sw["values"][other][1]})
    return out
