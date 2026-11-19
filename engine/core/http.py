"""One network policy for the whole system (owner 19 Nov: "failure free, robust").

`HTTP` is a drop-in for the `requests` module in `session=requests` parameters: HTTP.get(url, timeout=..., ...).
- GET / HEAD / PUT / DELETE (safe to repeat) are retried on connection errors, timeouts and 429 / 5xx answers, with
  growing waits (2, 5, 12 s; a server's Retry-After up to 60 s is respected). The last answer is returned as is, so
  callers keep their raise_for_status() / status checks.
- POST is never retried here: an upload or a Telegram message must not be sent twice.
- It calls requests.<method> at call time, so tests that replace requests.get keep working.
"""
from __future__ import annotations

import time

import requests

RETRY_STATUS = {429, 500, 502, 503, 504}
WAITS = (2.0, 5.0, 12.0)
SAFE = {"get", "head", "put", "delete"}


def _retry_after(resp) -> float | None:
    try:
        v = float(resp.headers.get("Retry-After", ""))
    except (TypeError, ValueError, AttributeError):
        return None
    return min(max(v, 0.0), 60.0)


class _Http:
    def __init__(self, waits=WAITS, sleep=time.sleep):
        self.waits, self.sleep = tuple(waits), sleep

    def request(self, method: str, url: str, **kw):
        method = method.lower()
        call = getattr(requests, method)
        if method not in SAFE:
            return call(url, **kw)
        for i in range(len(self.waits) + 1):
            last = i == len(self.waits)
            try:
                resp = call(url, **kw)
            except (requests.ConnectionError, requests.Timeout):
                if last:
                    raise
                self.sleep(self.waits[i])
                continue
            if getattr(resp, "status_code", 200) in RETRY_STATUS and not last:
                self.sleep(_retry_after(resp) or self.waits[i])
                continue
            return resp
        raise RuntimeError("unreachable")                    # pragma: no cover

    def get(self, url, **kw):
        return self.request("get", url, **kw)

    def head(self, url, **kw):
        return self.request("head", url, **kw)

    def put(self, url, **kw):
        return self.request("put", url, **kw)

    def delete(self, url, **kw):
        return self.request("delete", url, **kw)

    def post(self, url, **kw):
        return self.request("post", url, **kw)


HTTP = _Http()
