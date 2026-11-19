"""PC stand-in (GitHub down): never double-posts (cutoff, live YouTube check, own file only), dashboard buttons
reach the same decisions as Telegram, the handover pushes the PC's memory before the cloud takes over."""
import json
import time
from datetime import datetime, timedelta, timezone

import pytest

from engine import pc_fallback as pf


class FakeKV:
    def __init__(self, data=None):
        self.d = dict(data or {})

    def keys(self, prefix=""):
        return sorted(k for k in self.d if k.startswith(prefix))

    def get(self, k):
        return self.d.get(k)

    def put(self, k, v, ttl=None):
        self.d[k] = v if isinstance(v, str) else json.dumps(v)

    def delete(self, k):
        self.d.pop(k, None)


def item(tmp_path, slot, **kw):
    folder = tmp_path / "out"
    folder.mkdir(exist_ok=True)
    (folder / "video.mp4").write_bytes(b"x")
    it = {"id": "i1", "channel": "cosmos_unboxed", "channel_name": "Cosmos Unboxed", "status": "made",
          "publish_at": slot.isoformat(), "out_dir": str(folder), "file": "video.mp4", "made_at": 1.0,
          "meta": {"title": "The Moon Is Leaving Us"}}
    it.update(kw)
    return it


def test_cutoff_saved_once(tmp_path, monkeypatch):
    monkeypatch.setattr(pf, "CUTOFF_FILE", tmp_path / "c.txt")
    kv = FakeKV({"meta:last_dispatch": str(1_000_000 * 1000)})
    assert pf.cutoff(kv) == 1_000_000 + 3600
    kv.d["meta:last_dispatch"] = str(2_000_000 * 1000)
    assert pf.cutoff(kv) == 1_000_000 + 3600                 # fixed at the first run


def test_yt_taken_by_title_or_slot(tmp_path):
    slot = datetime.now(timezone.utc) + timedelta(days=1)
    it = item(tmp_path, slot)
    assert pf.yt_taken(it, uploads=[]) == ""
    same_title = [{"id": "abc", "title": "The moon is leaving us!", "at": 0}]
    assert "already on YouTube" in pf.yt_taken(it, uploads=same_title)
    same_slot = [{"id": "def", "title": "Other", "at": slot.timestamp() + 600}]
    assert "scheduled" in pf.yt_taken(it, uploads=same_slot)
    far = [{"id": "ghi", "title": "Other", "at": slot.timestamp() + 7200}]
    assert pf.yt_taken(it, uploads=far) == ""
    own = [{"id": "own1", "title": "The Moon Is Leaving Us", "at": slot.timestamp()}]
    assert pf.yt_taken(dict(it, youtube_id="own1"), uploads=own) == ""   # its own upload doesn't count


def test_yt_check_failure_counts_as_taken(tmp_path, monkeypatch):
    def boom(cid, session=None):
        raise ConnectionError("offline")
    monkeypatch.setattr(pf, "yt_uploads", boom)
    assert "couldn't check" in pf.yt_taken(item(tmp_path, datetime.now(timezone.utc)))


def test_allow_post_rules(tmp_path, monkeypatch):
    monkeypatch.setattr(pf, "yt_uploads", lambda cid, session=None: [])
    future = datetime.now(timezone.utc) + timedelta(hours=5)
    it = item(tmp_path, future)
    assert pf.allow_post(it, cut=time.time())
    assert not pf.allow_post(it, cut=future.timestamp() + 60)             # slot before the cutoff
    assert not pf.allow_post(dict(it, file="missing.mp4"), cut=time.time())  # file not on this PC


def test_upload_refuses_without_file_or_when_slot_taken(tmp_path, monkeypatch):
    slot = datetime.now(timezone.utc) + timedelta(hours=5)
    it = item(tmp_path, slot)
    monkeypatch.setattr(pf, "_find", lambda iid: ("2026-11-16", dict(it)))
    from engine import autopilot
    monkeypatch.setattr(autopilot, "token", lambda *a: "tok")
    called = []
    monkeypatch.setattr(autopilot, "decide", lambda *a: called.append(a) or "✅ Approved")
    monkeypatch.setattr(pf, "cutoff", lambda kv=None: 0.0)
    monkeypatch.setattr(pf, "yt_uploads", lambda cid, session=None: [{"id": "x", "title": "The Moon Is Leaving Us", "at": 0}])
    assert pf.do_command({"op": "approve", "item": "i1"}).startswith("🛑")
    assert not called
    monkeypatch.setattr(pf, "_find", lambda iid: ("2026-11-16", dict(it, file="gone.mp4")))
    assert "not on this PC" in pf.do_command({"op": "upload", "item": "i1"})
    assert not called


def test_old_slot_needs_force(tmp_path, monkeypatch):
    slot = datetime.now(timezone.utc) - timedelta(hours=3)
    it = item(tmp_path, slot)
    monkeypatch.setattr(pf, "_find", lambda iid: ("2026-11-16", dict(it)))
    from engine import autopilot
    monkeypatch.setattr(autopilot, "token", lambda *a: "tok")
    monkeypatch.setattr(autopilot, "decide", lambda *a: "✅ Approved: x")
    monkeypatch.setattr(pf, "cutoff", lambda kv=None: time.time())
    monkeypatch.setattr(pf, "yt_uploads", lambda cid, session=None: [])
    assert "confirm" in pf.do_command({"op": "approve", "item": "i1"})
    assert pf.do_command({"op": "approve", "item": "i1", "force": True}).startswith("✅")


def test_reject_and_change_use_the_telegram_decisions(tmp_path, monkeypatch):
    it = item(tmp_path, datetime.now(timezone.utc) + timedelta(hours=5))
    monkeypatch.setattr(pf, "_find", lambda iid: ("2026-11-16", dict(it)))
    from engine import autopilot
    monkeypatch.setattr(autopilot, "token", lambda *a: "tok")
    got = []
    monkeypatch.setattr(autopilot, "decide", lambda tok, action, note="": got.append((action, note)) or "ok")
    pf.do_command({"op": "reject", "item": "i1"})
    pf.do_command({"op": "change", "item": "i1", "note": "scarier hook"})
    assert got == [("reject", ""), ("change", "scarier hook")]
    assert pf.do_command({"op": "change", "item": "i1"}) == "Type what should change."
    assert pf.do_command({"op": "hack", "item": "i1"}) == "Unknown button."


def test_process_commands_writes_results(monkeypatch):
    kv = FakeKV({"cmd:1-a": json.dumps({"op": "reject", "item": "i1"}), "cmd:2-b": "{bad json"})
    monkeypatch.setattr(pf, "do_command", lambda cmd, log=None, maker=None: "❌ Rejected.")
    assert pf.process_commands(kv, log=lambda *_: None) == 2
    assert not kv.keys("cmd:")
    assert json.loads(kv.d["res:1-a"]) ["text"] == "❌ Rejected."
    assert json.loads(kv.d["res:2-b"])["state"] == "error"


def test_handover_pushes_memory_before_clearing_the_flag(monkeypatch, tmp_path):
    from engine.cloud import state
    monkeypatch.setattr(pf, "HANDED_FILE", tmp_path / "handed.txt")
    order = []
    monkeypatch.setattr(state, "push", lambda store: order.append("push") or 2048)
    monkeypatch.setattr("engine.cloud.store.Store", lambda *a, **k: object())
    kv = FakeKV({"meta:pc_primary": "{}"})
    real_delete = kv.delete
    kv.delete = lambda k: order.append(f"delete {k}") or real_delete(k)
    monkeypatch.setattr("engine.telegram_bot.notify", lambda t: True)
    assert pf.handover(kv, log=lambda *_: None)
    assert order == ["push", "delete meta:pc_primary"]
    assert (tmp_path / "handed.txt").exists()


def test_handover_keeps_standing_in_if_push_fails(monkeypatch, tmp_path):
    from engine.cloud import state
    monkeypatch.setattr(pf, "HANDED_FILE", tmp_path / "handed.txt")

    def fail(store):
        raise RuntimeError("403")
    monkeypatch.setattr(state, "push", fail)
    monkeypatch.setattr("engine.cloud.store.Store", lambda *a, **k: object())
    kv = FakeKV({"meta:pc_primary": "{}"})
    assert not pf.handover(kv, log=lambda *_: None)
    assert "meta:pc_primary" in kv.d
    assert not (tmp_path / "handed.txt").exists()


def test_studio_buttons_follow_status(tmp_path):
    from engine import dashboard_studio as st
    now = datetime.now(st.IST)
    made = item(tmp_path, now + timedelta(hours=3))
    cloud_only = dict(made, id="i2", file="not_here.mp4")
    planned = dict(made, id="i3", status="planned")
    html = st.content_card({"id": "cosmos_unboxed"}, {"items": [made, cloud_only, planned]})
    assert "hhAct('upload','i1')" in html and "hhAct('approve','i1')" in html
    # 20 Nov: a file that isn't on this machine still gets the decisions (the cloud fetches it to post); only
    # "Upload now" needs the file here. The old GitHub-outage "Make a PC version" is gone.
    assert "hhAct('upload','i2')" not in html and "Make a PC version" not in html
    assert all(f"hhAct('{op}','i2')" in html for op in ("approve", "change", "reject"))
    assert "hhAct('make','i3')" in html


def test_live_ids_has_no_tokens(monkeypatch):
    monkeypatch.setattr("engine.stats_fetch.live_stats", lambda: {
        "channels": {"brain_snack": {"yt_id": "UC1", "subs": 3}, "x": {}}, "videos": {"v1": {"channel": "brain_snack"}}})
    monkeypatch.setattr("engine.stats_fetch.posted_videos", lambda: [{"platform": "youtube", "id": "v2", "channel": "x"}])
    monkeypatch.setattr("engine.dashboard._followers", lambda: {"brain_snack": {"youtube": 3, "instagram": 1}})
    d = pf.live_ids()
    assert d["channels"] == {"brain_snack": "UC1"}
    assert set(d["videos"]) == {"v1", "v2"}
    assert d["meta"] == {"brain_snack": {"instagram": 1}}
    assert "token" not in json.dumps(d).lower()


def test_open_dashboard_starts_the_system_only_when_needed(monkeypatch, tmp_path):
    monkeypatch.setattr(pf, "HANDED_FILE", tmp_path / "handed.txt")
    monkeypatch.setattr(pf, "dash_link", lambda: "https://example/d?k=x")
    opened, started = [], []
    monkeypatch.setattr("webbrowser.open", lambda u: opened.append(u))
    monkeypatch.setattr("subprocess.Popen", lambda *a, **k: started.append(a))
    makers = []                                          # 19 Nov, option A: the icon starts the PC video maker

    class Done:
        stdout = "PC video maker started (hidden)."
    monkeypatch.setattr("subprocess.run", lambda *a, **k: makers.append(a) or Done())
    monkeypatch.setattr("engine.cleanup.due_on_pc", lambda: False)
    monkeypatch.setattr(pf, "standin_running", lambda port=47615: True)
    assert pf.open_dashboard() == "Dashboard opened in your browser." and not started
    monkeypatch.setattr(pf, "standin_running", lambda port=47615: False)
    assert pf.open_dashboard().startswith("System started.") and len(started) == 1
    assert not makers                                    # before the handover the stand-in did everything
    (tmp_path / "handed.txt").write_text("1")
    msg = pf.open_dashboard()
    assert len(started) == 1 and len(opened) == 3        # after the handover: the stand-in is never restarted
    assert len(makers) == 1 and "Video maker started" in msg
