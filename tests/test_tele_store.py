"""Phase 1 last step (21 Nov): the Telegram bot's working keys (upd:/cmd:/res:/dec:/meta:) move from KV (1,000 free
writes a day) to the LedgerDO table tkv, in stages kv -> dual -> do, Worker and Python together."""
import json
import re
import time
from pathlib import Path

import pytest
import yaml

from engine.cloud import kv as kvmod

TELE = re.compile(r"^(upd|cmd|res|dec|meta):[A-Za-z0-9_:.\-]{1,120}$")   # = ledger_do.js TELE_PREFIX


class FakeKV:
    def __init__(self):
        self.d, self.writes = {}, 0

    def keys(self, prefix=""):
        return sorted(k for k in self.d if k.startswith(prefix))

    def get(self, key):
        return self.d.get(key)

    def put(self, key, value, ttl=None):
        self.writes += 1
        self.d[key] = value if isinstance(value, str) else json.dumps(value)
        return True

    def delete(self, key):
        self.writes += 1
        self.d.pop(key, None)
        return True

    def put_bytes(self, key, data, ttl=None):
        self.d[key] = data
        return True


class TwinDO:
    """Python twin of LedgerDO.tele(): allow-listed keys, values with a time-to-live, prefix lists."""
    def __init__(self, fail=False):
        self.rows, self.fail, self.calls = {}, fail, []

    def call(self, b):
        self.calls.append(b)
        if self.fail:
            raise RuntimeError("DO down")
        now = time.time()
        if b["op"] == "tlist":
            assert re.match(r"^(upd|cmd|res|dec|meta):", b["prefix"])
            return {"keys": sorted(k for k, (v, exp) in self.rows.items()
                                   if k.startswith(b["prefix"]) and (exp is None or exp >= now))}
        assert TELE.match(b["k"]), b["k"]
        if b["op"] == "tget":
            v = self.rows.get(b["k"])
            return {"v": v[0] if v and (v[1] is None or v[1] >= now) else None}
        if b["op"] == "tput":
            self.rows[b["k"]] = (b["v"], now + b["ttl"] if b.get("ttl") else None)
            return {"ok": 1}
        if b["op"] == "tdel":
            self.rows.pop(b["k"], None)
            return {"ok": 1}
        raise AssertionError(b)


def test_dual_writes_both_and_reads_kv():
    kv, do = FakeKV(), TwinDO()
    t = kvmod.TeleKV(kv, do, "dual", log=lambda *_: None)
    t.put("upd:000000000001", {"update_id": 1}, ttl=600)
    t.put("res:abc", {"state": "queued"})
    assert kv.get("upd:000000000001") == do.rows["upd:000000000001"][0] == '{"update_id": 1}'
    do.rows["res:abc"] = ('{"state": "other"}', None)
    assert t.get("res:abc") == '{"state": "queued"}'                     # dual reads KV
    assert t.keys("upd:") == ["upd:000000000001"]
    t.delete("upd:000000000001")
    assert "upd:000000000001" not in kv.d and "upd:000000000001" not in do.rows
    t.put("snapshot", {"texts": {}})                                      # dashboard keys never touch the DO
    t.put_bytes("pv:x:0", b"..")
    assert "snapshot" in kv.d and all(c.get("k") != "snapshot" for c in do.calls)


def test_do_mode_saves_kv_writes_and_falls_back_when_the_do_fails():
    kv, do = FakeKV(), TwinDO()
    t = kvmod.TeleKV(kv, do, "do", log=lambda *_: None)
    for i in range(5):
        t.put(f"upd:{i:012d}", {"update_id": i}, ttl=600)
    assert kv.writes == 0 and t.keys("upd:") == [f"upd:{i:012d}" for i in range(5)]
    assert json.loads(t.get("upd:000000000003"))["update_id"] == 3
    t.delete("upd:000000000003")
    assert kv.writes == 0 and "upd:000000000003" not in t.keys("upd:")
    lines = []
    down = kvmod.TeleKV(kv, TwinDO(fail=True), "do", log=lines.append)
    assert down.put("cmd:x1", {"a": 1}) and kv.get("cmd:x1") == '{"a": 1}'   # the bot keeps working on KV
    assert down.keys("cmd:") == ["cmd:x1"] and down.get("cmd:x1") == '{"a": 1}'
    assert lines and all("tele store" in ln for ln in lines)                # said, never silent


def test_expired_rows_read_as_missing():
    do = TwinDO()
    t = kvmod.TeleKV(FakeKV(), do, "do", log=lambda *_: None)
    t.put("dec:abc123", "ap", ttl=60)
    do.rows["dec:abc123"] = ("ap", time.time() - 1)
    assert t.get("dec:abc123") is None and t.keys("dec:") == []


def test_factory_follows_the_setting(monkeypatch):
    plain = FakeKV()
    monkeypatch.setattr("engine.config.settings", lambda: {"tele_store": "kv"})
    assert kvmod.tele_store(plain) is plain
    monkeypatch.setattr("engine.config.settings", lambda: {"tele_store": "dual"})
    assert kvmod.tele_store(plain) is plain                               # tests: the signed API is never set up
    monkeypatch.setattr("engine.core.d1.Client.configured", lambda self: True)
    t = kvmod.tele_store(plain)
    assert isinstance(t, kvmod.TeleKV) and t.mode == "dual"


ROOT = Path(__file__).resolve().parents[1]


def test_worker_never_touches_telegram_keys_on_kv_directly():
    src = (ROOT / "cloud" / "worker" / "worker.js").read_text(encoding="utf-8")
    direct = re.findall(r"env\.HH\.(?:get|put|delete|list)\(\s*\{?\s*(?:prefix:\s*)?[`\"](?:upd|cmd|res|dec|meta):", src)
    assert direct == [], direct
    assert "TELE_STORE" in src and "doTele" in src
    do = (ROOT / "cloud" / "worker" / "ledger_do.js").read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS tkv" in do and all(op in do for op in ('"tget"', '"tput"', '"tdel"', '"tlist"'))
    assert "^(upd|cmd|res|dec|meta):" in do


def test_worker_and_python_modes_move_together():
    toml = (ROOT / "cloud" / "worker" / "wrangler.toml").read_text(encoding="utf-8")
    worker_mode = re.search(r'^TELE_STORE\s*=\s*"(\w+)"', toml, re.M).group(1)
    py_mode = yaml.safe_load((ROOT / "config" / "settings.yaml").read_text(encoding="utf-8"))["tele_store"]
    assert worker_mode == py_mode in ("kv", "dual", "do")
