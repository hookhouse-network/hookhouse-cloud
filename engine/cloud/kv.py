"""Cloudflare Workers KV (free, no card): the Telegram inbox the Worker fills and the status snapshot it answers from.
Keys: upd:<update_id> (one Telegram update, JSON), snapshot (texts for instant answers), meta:* (Worker bookkeeping)."""
from __future__ import annotations

import json
import os

import requests

BASE = "https://api.cloudflare.com/client/v4/accounts/{acct}/storage/kv/namespaces/{ns}"


class KV:
    def __init__(self, session=None, account: str | None = None, namespace: str | None = None, api_token: str | None = None):
        self.s = session or requests.Session()
        acct = account or os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")
        ns = namespace or os.environ.get("CF_KV_NAMESPACE_ID", "")
        tok = api_token or os.environ.get("CLOUDFLARE_API_TOKEN", "")
        if not (acct and ns and tok):
            raise RuntimeError("Cloudflare KV not configured (CLOUDFLARE_ACCOUNT_ID, CF_KV_NAMESPACE_ID, CLOUDFLARE_API_TOKEN)")
        self.base = BASE.format(acct=acct, ns=ns)
        self.h = {"Authorization": f"Bearer {tok}"}

    def keys(self, prefix: str = "") -> list[str]:
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

    def put(self, key: str, value: str | dict) -> None:
        body = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        r = self.s.put(f"{self.base}/values/{key}", headers=self.h, data=body.encode("utf-8"), timeout=30)
        r.raise_for_status()

    def delete(self, key: str) -> None:
        r = self.s.delete(f"{self.base}/values/{key}", headers=self.h, timeout=30)
        if r.status_code not in (200, 404):
            r.raise_for_status()
