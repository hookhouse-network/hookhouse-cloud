"""License checker: makes sure every tool and model we use allows commercial use."""
from __future__ import annotations

from importlib import metadata

import yaml

from .config import CONFIG_DIR


def load_registry() -> dict:
    with open(CONFIG_DIR / "licenses.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def check(registry: dict | None = None, installed: set[str] | None = None) -> list[str]:
    """Returns a list of problems. Empty list = all good."""
    reg = registry or load_registry()
    allowed = set(reg["allowed_licenses"]) | set(reg.get("tool_only_licenses", []))
    problems = []
    for comp in reg["components"]:
        if comp["license"] not in allowed:
            problems.append(f"{comp['name']}: license '{comp['license']}' does not allow commercial use")
    denied_names = {d["name"].lower() for d in reg.get("denied", [])}
    for comp in reg["components"]:
        if comp["name"].lower() in denied_names:
            problems.append(f"{comp['name']}: is on the denied list")
    if installed is None:
        installed = {(d.metadata["Name"] or "").lower() for d in metadata.distributions()}
    for pkg in reg.get("denied_packages", []):
        if pkg.lower() in installed:
            problems.append(f"Python package '{pkg}' is installed but not allowed (non-commercial models)")
    return problems
