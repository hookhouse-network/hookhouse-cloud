"""ClippingAlpha MCP client (read tools only, no sign-in): the interface ClippingAlpha itself asks tools to use instead
of reading campaign pages one by one (clippingalpha.com/llms.txt; robots.txt welcomes crawlers). Polite: one session,
a pause between calls, a clear User-Agent."""
from __future__ import annotations

import json
import time

import requests

URL = "https://clippingalpha.com/mcp"
HEADERS = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
           "User-Agent": "ClipFactory/1.0 (campaign discovery; once a day)"}


class MCP:
    def __init__(self, pause: float = 1.5):
        self.s = requests.Session()
        self.sid = None
        self.pause = pause
        self.n = 10
        self._rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                 "clientInfo": {"name": "clipfactory", "version": "1.0"}})
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def _post(self, body: dict) -> requests.Response:
        h = dict(HEADERS)
        if self.sid:
            h["Mcp-Session-Id"] = self.sid
        r = self.s.post(URL, json=body, headers=h, timeout=90)
        self.sid = r.headers.get("Mcp-Session-Id") or self.sid
        return r

    def _rpc(self, method: str, params: dict) -> dict:
        self.n += 1
        r = self._post({"jsonrpc": "2.0", "id": self.n, "method": method, "params": params})
        r.raise_for_status()
        txt = r.text
        if "data:" in txt[:40] or txt.startswith("event:"):
            txt = "\n".join(ln[5:].strip() for ln in txt.splitlines() if ln.startswith("data:"))
        data = json.loads(txt)
        if "error" in data:
            raise RuntimeError(data["error"])
        time.sleep(self.pause)
        return data.get("result") or {}

    def tool(self, name: str, **args) -> dict | str:
        """Call a read tool. Returns structuredContent when present, else the joined text."""
        res = self._rpc("tools/call", {"name": name, "arguments": {k: v for k, v in args.items() if v is not None}})
        if res.get("structuredContent"):
            return res["structuredContent"]
        texts = [c.get("text", "") for c in res.get("content") or [] if c.get("type") == "text"]
        joined = "\n".join(texts)
        try:
            return json.loads(joined)
        except (ValueError, TypeError):
            return joined
