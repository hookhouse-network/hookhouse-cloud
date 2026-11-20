"""Cloudflare Workers KV (free, no card): the Telegram inbox the Worker fills and the status snapshot it answers from.
Keys: upd:<update_id> (one Telegram update, JSON), snapshot (texts for instant answers), meta:* (Worker bookkeeping)."""
from __future__ import annotations

import json
import os

import requests

BASE = "https://api.cloudflare.com/client/v4/accounts/{acct}/storage/kv/namespaces/{ns}"


def _toml_ns() -> str:
    """The PC (no CF_KV_NAMESPACE_ID in .env) reads the namespace id from the Worker's wrangler.toml."""
    import re
    from pathlib import Path
    p = Path(__file__).resolve().parents[2] / "cloud" / "worker" / "wrangler.toml"
    try:
        m = re.search(r'\[\[kv_namespaces\]\][^\[]*?\bid\s*=\s*"([0-9a-f]+)"', p.read_text(encoding="utf-8"), re.S)
        return m.group(1) if m else ""
    except OSError:
        return ""


class KV:
    def __init__(self, session=None, account: str | None = None, namespace: str | None = None, api_token: str | None = None):
        self.s = session or requests.Session()
        acct = account or os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")
        ns = namespace or os.environ.get("CF_KV_NAMESPACE_ID", "") or _toml_ns()
        tok = api_token or os.environ.get("CLOUDFLARE_API_TOKEN", "")
        if not (acct and ns and tok):
            raise RuntimeError("Cloudflare KV not configured (CLOUDFLARE_ACCOUNT_ID, CF_KV_NAMESPACE_ID, CLOUDFLARE_API_TOKEN)")
        self.base = BASE.format(acct=acct, ns=ns)
        self.h = {"Authorization": f"Bearer {tok}"}

    budget = True                 # 20 Nov: every write/delete/list goes through engine/cloud/kv_budget.py

    def _ok(self, op: str, key: str) -> bool:
        if not self.budget:
            return True
        try:
            from .kv_budget import allow
            return allow(op, key)
        except Exception as e:  # noqa: BLE001 - a broken budget check must not block the owner's buttons
            print(f"kv budget check failed ({type(e).__name__}: {e}); writing anyway")
            return True

    def keys(self, prefix: str = "") -> list[str]:
        if not self._ok("list", prefix or "list"):
            print(f"kv: list {prefix!r} paused (daily budget)")
            return []
        out, cursor = [], None
        while True:
            params = {"prefix": prefix, "limit": 1000}
            if cursor:
                params["cursor"] = cursor
            r = self.s.get(f"{self.base}/keys", headers=self.h, params=params, timeout=30)
            r.raise_for_status()
            js = r.json()
            out += [k["name"] for k in js.get("result", [])]
            cursor = (js.get("result_info") or {}).get("cursor")
            if not cursor:
                return sorted(out)

    def get(self, key: str) -> str | None:
        r = self.s.get(f"{self.base}/values/{key}", headers=self.h, timeout=30)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.text

    def put(self, key: str, value: str | dict, ttl: int | None = None) -> bool:
        """False = paused by the daily budget (nothing written)."""
        if not self._ok("write", key):
            return False
        body = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        r = self.s.put(f"{self.base}/values/{key}", headers=self.h, data=body.encode("utf-8"), timeout=60,
                       params={"expiration_ttl": max(60, int(ttl))} if ttl else None)
        r.raise_for_status()
        return True

    def put_if_changed(self, key: str, value: str | dict, ttl: int | None = None, refresh_s: float = 3600,
                       normalize=None) -> bool:
        """Write only when the content changed (or the stored copy is older than refresh_s): the snapshot and the
        Studio page were rewritten every run even when nothing changed. normalize(text) drops volatile parts
        (timestamps) before comparing. Returns True when written."""
        import hashlib
        import time
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True)
        h = hashlib.sha1((normalize(text) if normalize else text).encode("utf-8")).hexdigest()
        seen = _hashes()
        old = seen.get(key) or {}
        if old.get("h") == h and time.time() - float(old.get("at") or 0) < refresh_s:
            return False
        if not self.put(key, value, ttl):
            return False
        seen[key] = {"h": h, "at": time.time()}
        _save_hashes(seen)
        return True

    def put_bytes(self, key: str, data: bytes, ttl: int | None = None) -> bool:
        """Binary value (video preview pieces). KV allows up to 25 MiB per value. False = paused by the budget."""
        if not self._ok("write", key):
            return False
        r = self.s.put(f"{self.base}/values/{key}", headers={**self.h, "Content-Type": "application/octet-stream"},
                       data=data, timeout=300, params={"expiration_ttl": max(60, int(ttl))} if ttl else None)
        r.raise_for_status()
        return True

    def delete(self, key: str) -> bool:
        """False = paused by the daily budget (keys with a TTL expire by themselves)."""
        if not self._ok("delete", key):
            return False
        r = self.s.delete(f"{self.base}/values/{key}", headers=self.h, timeout=30)
        if r.status_code not in (200, 404):
            r.raise_for_status()
        return True


def _hashes_file():
    from pathlib import Path
    return Path(__file__).resolve().parents[2] / "data" / "state" / "kv_hashes.json"


def _hashes() -> dict:
    try:
        return json.loads(_hashes_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_hashes(d: dict) -> None:
    from ..core.atomic import write_json
    write_json(_hashes_file(), d)
