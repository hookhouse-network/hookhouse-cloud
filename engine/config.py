"""Loads settings, channel files and secret keys."""
from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"


def load_env(path: Path | None = None) -> None:
    """Read KEY=value lines from .env into the environment (does not overwrite existing vars)."""
    path = path or ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if value.startswith("#"):
            value = ""
        elif value[:1] in ('"', "'"):
            value = value[1:].split(value[0], 1)[0]
        else:
            value = re.split(r"\s+#", value, maxsplit=1)[0].strip()
        if value:
            os.environ.setdefault(key.strip(), value)


@lru_cache(maxsize=1)
def settings() -> dict:
    load_env()
    with open(CONFIG_DIR / "settings.yaml", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    try:                                         # P10: the owner's /settings choices (whitelisted switches only)
        from .owner_settings import apply
        return apply(cfg, "settings")
    except Exception as e:  # noqa: BLE001 - the file's own settings still work
        print(f"owner settings not applied: {type(e).__name__}: {e}")
        return cfg


def channels() -> list[dict]:
    """All channel settings, ordered by channel number."""
    result = []
    for path in sorted((CONFIG_DIR / "channels").glob("*.yaml")):
        with open(path, encoding="utf-8") as f:
            ch = yaml.safe_load(f)
        ch["_file"] = path.name
        result.append(ch)
    return sorted(result, key=lambda c: c.get("number", 99))


def channel(channel_id: str) -> dict:
    for ch in channels():
        if ch["id"] == channel_id or str(ch.get("number")) == str(channel_id):
            return ch
    raise KeyError(f"No channel '{channel_id}'. Known: {[c['id'] for c in channels()]}")


def data_path(relative: str) -> Path:
    path = ROOT / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    return path
