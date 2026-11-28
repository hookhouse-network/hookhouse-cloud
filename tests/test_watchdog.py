"""Owner 17 Nov 2026: "i don't want the system to break again ever". Every silent break of that day must alert."""
import json
import time

from engine import watchdog


class Store:
    def __init__(self, assets=None):
        self.a = dict(assets or {})

    def get(self, tag, name):
        return self.a.get(name)

    def put(self, tag, name, data, *a):
        self.a[name] = data


def _iso(monkeypatch, tmp_path):
    monkeypatch.setattr(watchdog, "STATE", tmp_path / "w.json")
    monkeypatch.setattr(watchdog, "_campaigns_waiting", lambda now: {})
    monkeypatch.setattr(watchdog, "_videos", lambda now: {})


def test_helper_off_and_chrome_closed_alert_then_all_clear(monkeypatch, tmp_path):
    _iso(monkeypatch, tmp_path)
    sent = []
    st = Store()
    assert watchdog.run(st, send=sent.append) == ["helper"] and "PC helper is off" in sent[0]
    watchdog.helper_heartbeat(st, chrome=False)
    watchdog.run(st, send=sent.append)
    assert any("Chrome window" in m for m in sent) and any(m.startswith("✅ Fixed: the PC helper") for m in sent)
    watchdog.helper_heartbeat(st, chrome=True)
    watchdog.run(st, send=sent.append)
    assert sent[-1].startswith("✅ Fixed: the HookHouse Chrome")


def test_alerts_repeat_only_every_12_hours(monkeypatch, tmp_path):
    _iso(monkeypatch, tmp_path)
    sent = []
    t = time.time()
    watchdog.run(Store(), send=sent.append, now=t)
    watchdog.run(Store(), send=sent.append, now=t + 3600)
    assert len(sent) == 1
    watchdog.run(Store(), send=sent.append, now=t + 13 * 3600)
    assert len(sent) == 2


def test_a_step_failing_three_runs_in_a_row_alerts(monkeypatch, tmp_path):
    _iso(monkeypatch, tmp_path)
    st = Store({watchdog.HELPER_ASSET: json.dumps({"at": time.time(), "chrome": True}).encode()})
    sent = []
    for _ in range(2):
        watchdog.record_steps({"inbox": "KeyError: x"}, ["inbox", "post"])
    assert watchdog.run(st, send=sent.append) == []
    watchdog.record_steps({"inbox": "KeyError: x"}, ["inbox", "post"])
    assert watchdog.run(st, send=sent.append) == ["step:inbox"] and "inbox" in sent[0]
    watchdog.record_steps({}, ["inbox", "post"])                    # works again
    watchdog.run(st, send=sent.append)
    assert sent[-1].startswith("✅ Fixed: the cloud job inbox")


def test_picked_but_not_joined_reminds_with_links(monkeypatch, tmp_path):
    from engine import db
    conn = db.connect(tmp_path / "s.db")
    db.save_campaign(conn, {"id": "a", "name": "Vi City", "status": "picked", "url": "https://cr/a", "board": "Content Rewards",
                            "picked_at": time.time() - 13 * 3600})
    db.save_campaign(conn, {"id": "b", "name": "New", "status": "picked", "url": "https://cr/b", "board": "Content Rewards", "picked_at": time.time()})
    monkeypatch.setattr(db, "connect", lambda *a, **k: conn)
    out = watchdog._campaigns_waiting(time.time())
    assert "Vi City" in out["campaigns"] and "New" not in out["campaigns"]
    assert "Confirm" in out["campaigns"] and "press Join" not in out["campaigns"]   # 28 Nov: our system joins
