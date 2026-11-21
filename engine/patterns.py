"""Viral pattern library (plan P3r creativity, standard S8 A1): config/patterns.yaml lists proven story structures;
every fresh story video uses one, in rotation per channel. The writer gets one rule; the pattern name is saved on the
script ("pattern") so the learning loop can compare structures by channel later (P8)."""
from __future__ import annotations

import json

import yaml

from .config import ROOT

FILE = ROOT / "config" / "patterns.yaml"
STATE = ROOT / "data" / "state" / "pattern_rotation.json"


def _data() -> dict:
    try:
        return yaml.safe_load(FILE.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as e:
        print(f"patterns: config unreadable ({type(e).__name__}: {e})")
        return {}


def pick(cid: str) -> dict | None:
    d = _data()
    if cid in (d.get("skip") or []):
        return None
    pats = [p for p in d.get("patterns") or [] if isinstance(p, dict) and p.get("name") and p.get("shape")]
    if not pats:
        return None
    try:
        state = json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    i = int(state.get(cid, -1)) + 1
    state[cid] = i % len(pats)
    from .core.atomic import write_json
    write_json(STATE, state)
    return pats[i % len(pats)]


def rule(p: dict | None) -> str:
    if not p:
        return ""
    return (f"STRUCTURE for this video: \"{p['name']}\": {p['shape']}. Use it only as far as the true story allows; "
            "the hook in the first second comes first.")


def apply(script: dict, p: dict | None) -> dict:
    if not p:
        return script
    return {**script, "pattern": p["name"]}
