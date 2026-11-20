"""20 Nov (owner: the Cloudflare free plan allows 1,000 KV writes a day: "you have to handle this as well with our
system"). Measured 14-20 Nov: writes 15 -> 287/day and rising."""
import json

import pytest

from engine.cloud import kv as kvmod
from engine.cloud import kv_budget as kb

ORIGINAL_FETCH = kb.fetch_real          # captured at import, before conftest replaces it for every test


class Resp:
    def __init__(self, code=200, text="", js=None):
        self.status_code, self.text, self._js = code, text, js or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)

    def json(self):
        return self._js


class Session:
    def __init__(self):
        self.puts, self.deletes, self.lists = [], [], 0

    def put(self, url, **kw):
        self.puts.append(url.rsplit("/", 1)[-1])
        return Resp()

    def delete(self, url, **kw):
        self.deletes.append(url.rsplit("/", 1)[-1])
        return Resp()

    def get(self, url, **kw):
        self.lists += 1
        return Resp(js={"result": [{"name": "upd:1"}], "result_info": {}})


@pytest.fixture
def kv():
    return kvmod.KV(session=Session(), account="a", namespace="n", api_token="t")


def _used(op, n, measured=True):
    d = kb._load()
    d["real"], d["fetched"], d["measured"] = {op: n}, 9e18, measured
    kb._save(d)


def test_priorities_pause_bulk_first_then_normal_never_critical_early(kv, monkeypatch):
    sent = []
    _used("write", 600)                                  # 60 % of the day's writes used
    assert kv.put_bytes("pv:a:0", b"x") is False         # previews pause at 55 %
    assert kv.put("dash:html", "<p>") is True            # the page still updates (pauses at 75 %)
    assert kv.put("res:1", {"text": "ok"}) is True       # owner-facing answers keep going
    _used("write", 800)
    assert kv.put("dash:html", "<p>") is False
    assert kv.put("snapshot", {"a": 1}) is True
    _used("write", 975)
    assert kv.put("snapshot", {"a": 1}) is False         # the last 3 % stay for the Worker's own writes
    assert "pv:a:0" not in kv.s.puts and kv.s.puts.count("snapshot") == 1


def test_alerts_once_per_level(kv, monkeypatch):
    sent = []
    monkeypatch.setattr(kb, "_notify", lambda t: sent.append(t))
    monkeypatch.setattr("engine.heal.report", lambda *a, **k: None)
    _used("write", 720)
    kv.put("res:1", "a")
    kv.put("res:2", "b")
    assert len(sent) == 1 and "720 of 1000 writes" in sent[0] and "Telegram buttons keep working" in sent[0]
    _used("write", 910)
    kv.put("res:3", "c")
    assert len(sent) == 2


def test_put_if_changed_skips_identical_content_but_refreshes(kv, monkeypatch):
    assert kv.put_if_changed("snapshot", {"s": "x", "at": 1}, normalize=lambda t: t.replace('"at": 1', '"at": 2'))
    assert not kv.put_if_changed("snapshot", {"s": "x", "at": 2})          # same content -> no write
    assert kv.put_if_changed("snapshot", {"s": "y", "at": 3})              # changed -> written
    assert kv.s.puts.count("snapshot") == 2
    h = kvmod._hashes()
    h["snapshot"]["at"] = 0                                                # older than refresh_s -> rewritten
    kvmod._save_hashes(h)
    assert kv.put_if_changed("snapshot", {"s": "y", "at": 4}, refresh_s=60)


def test_without_analytics_a_reserve_for_the_worker_is_assumed(kv):
    d = kb._load()
    d["fetched"], d["measured"], d["real"] = 9e18, False, {}
    d["local"] = {"write": 330}
    kb._save(d)
    assert kb.usage("write") == 330 + kb.WORKER_RESERVE
    assert kv.put_bytes("pv:b:0", b"x") is False                           # 580 >= 55 %: previews wait


def test_lists_and_deletes_are_budgeted_too(kv):
    _used("list", 999)
    assert kv.keys("upd:") == []                                           # paused, not an error
    _used("delete", 600)
    assert kv.delete("pv:x:0") is False and kv.delete("upd:1") is True


def test_a_broken_budget_never_blocks_the_owner(kv, monkeypatch):
    monkeypatch.setattr(kb, "allow", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("disk full")))
    assert kv.put("res:9", "x") is True


def test_real_usage_comes_from_cloudflare_analytics(monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "t")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "a")

    class S:
        def post(self, url, **kw):
            return Resp(js={"data": {"viewer": {"accounts": [{"kvOperationsAdaptiveGroups": [
                {"sum": {"requests": 287}, "dimensions": {"actionType": "write"}},
                {"sum": {"requests": 71}, "dimensions": {"actionType": "list"}}]}]}}})
    assert ORIGINAL_FETCH(S()) == {"write": 287, "list": 71}
