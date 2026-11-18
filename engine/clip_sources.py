"""Clip permission gate: no clip is cut from a source without proof we may use it (owner, 12 Nov: "clipping without any
strike"). Proof = a campaign (its brief licenses the footage), a register entry (config/clip_sources.yaml: US-government
public domain, CC BY/BY-SA, or written permission with evidence), or a licence sidecar next to a local file
(<file>.license.json with the same fields)."""
from __future__ import annotations

import json
from pathlib import Path

import yaml

from .config import ROOT

REGISTER = ROOT / "config" / "clip_sources.yaml"
OK_BASIS = {"public_domain_us_gov", "cc_by", "cc_by_sa", "written_permission", "campaign"}


class NoPermission(RuntimeError):
    pass


def register() -> list[dict]:
    return yaml.safe_load(REGISTER.read_text(encoding="utf-8")) or [] if REGISTER.exists() else []


def permission_for(source: str, campaign: dict | None = None) -> dict:
    """The permission record for a source, or raise NoPermission with what is missing."""
    if campaign:
        return {"basis": "campaign", "owner": campaign.get("brand") or campaign.get("name"),
                "evidence": campaign.get("url"), "credit": " ".join(campaign.get("required_tags") or []),
                "may_monetize": False, "notes": "Footage licensed by the campaign brief, for that campaign only."}
    p = Path(source)
    side = p.with_name(p.name + ".license.json")
    if p.exists() and side.exists():
        rec = json.loads(side.read_text(encoding="utf-8"))
        if rec.get("basis") in OK_BASIS and rec.get("evidence"):
            return rec
        raise NoPermission(f"{side.name} needs a valid basis and evidence")
    src = str(source).lower()
    for rec in register():
        if rec.get("match") and str(rec["match"]).lower() in src and rec.get("basis") in OK_BASIS and rec.get("evidence"):
            return rec
    raise NoPermission(
        "No permission on record for this source. Use a campaign's footage, a public-domain/CC BY source listed in "
        "config/clip_sources.yaml, or add the creator's written permission (with evidence) there first. "
        "Fair use is a defence after a claim, not a way to avoid Content ID claims or strikes.")
