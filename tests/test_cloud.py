"""Cloud mode (owner, 13 Nov 2026: "Cloud now, PC as helper"): encrypted memory bundle, repo file storage, the
Telegram inbox, PC/cloud hand-over, workflows and the Worker. All offline with fakes."""
import json
import subprocess
import time
from pathlib import Path

import pytest
import yaml

from engine.cloud import media, runner, setup, state


@pytest.fixture
def key(monkeypatch):
    monkeypatch.setenv("STATE_KEY", state.new_key())


class FakeStore:
    def __init__(self):
        self.files: dict[tuple[str, str], bytes] = {}
        self.created: dict[tuple[str, str], str] = {}

    def assets(self, tag):
        return {n: {"name": n, "created_at": self.created.get((t, n), "2099-01-01T00:00:00Z")}
                for (t, n) in self.files if t == tag}

    def get(self, tag, name):
        return self.files.get((tag, name))

    def put(self, tag, name, data, content_type=""):
        self.files[(tag, name)] = data
        self.created[(tag, name)] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        return {"name": name}

    def delete(self, tag, name):
        return self.files.pop((tag, name), None) is not None


def test_state_bundle_round_trip_is_encrypted(tmp_path, key):
    src = tmp_path / "a"
    (src / "data" / "weeks").mkdir(parents=True)
    (src / "data" / "weeks" / "2026-11-16.json").write_text('{"items": []}', encoding="utf-8")
    (src / "data" / "system.db").write_bytes(b"SQLITE-DATA")
    (src / "data" / "state").mkdir()
    (src / "data" / "state" / "render.lock").write_text("x")                   # never travels
    (src / "data" / "cache").mkdir()
    (src / "data" / "cache" / "big.bin").write_bytes(b"0" * 100)                # not memory: not bundled
    blob = state.pack(src)
    assert b"SQLITE-DATA" not in blob and b"items" not in blob                  # unreadable without the key
    dst = tmp_path / "b"
    assert state.unpack(blob, dst) == 2
    assert (dst / "data" / "system.db").read_bytes() == b"SQLITE-DATA"
    assert not (dst / "data" / "state" / "render.lock").exists() and not (dst / "data" / "cache").exists()


def test_state_push_keeps_a_backup(tmp_path, key):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "system.db").write_bytes(b"v1")
    st = FakeStore()
    state.push(st, tmp_path)
    (tmp_path / "data" / "system.db").write_bytes(b"v2")
    state.push(st, tmp_path)
    assert ("state", "state.prev.bin") in st.files
    out = tmp_path / "restore"
    assert state.pull(st, out) >= 1 and (out / "data" / "system.db").read_bytes() == b"v2"


def test_wrong_key_cannot_read(tmp_path, monkeypatch):
    monkeypatch.setenv("STATE_KEY", state.new_key())
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "system.db").write_bytes(b"x")
    blob = state.pack(tmp_path)
    monkeypatch.setenv("STATE_KEY", state.new_key())
    with pytest.raises(Exception):
        state.unpack(blob, tmp_path / "o")


def test_paths_work_on_windows_and_linux():
    assert media.rel_out(r"D:\clipping-system\output\cricket_ke_kisse\20261112_x") == "output/cricket_ke_kisse/20261112_x"
    assert media.rel_out("/home/runner/work/hookhouse/hookhouse/output/a/b/") == "output/a/b"
    assert media.rel_out("output/a/b") == "output/a/b"


def test_video_folder_travels_without_work_files(tmp_path, monkeypatch):
    folder = tmp_path / "output" / "ch" / "v1"
    (folder / "work").mkdir(parents=True)
    (folder / "video.mp4").write_bytes(b"MP4")
    (folder / "upload.json").write_text("{}")
    (folder / "work" / "huge.wav").write_bytes(b"0" * 1000)
    st = FakeStore()
    media.upload(st, "item1", folder)
    monkeypatch.setattr(media, "ROOT", tmp_path / "cloud")
    got = media.ensure_local(st, {"id": "item1", "out_dir": r"D:\clipping-system\output\ch\v1"})
    assert got == tmp_path / "cloud" / "output" / "ch" / "v1"
    assert (got / "video.mp4").read_bytes() == b"MP4" and not (got / "work").exists()


class FakeKV:
    def __init__(self, items):
        self.d = dict(items)

    def keys(self, prefix=""):
        return sorted(k for k in self.d if k.startswith(prefix))

    def get(self, k):
        return self.d.get(k)

    def delete(self, k):
        self.d.pop(k, None)

    def put(self, k, v):
        self.d[k] = v


def test_inbox_feeds_the_existing_bot_handler_in_order(monkeypatch):
    from engine import telegram_bot
    seen = []
    monkeypatch.setattr(telegram_bot, "handle", lambda u: seen.append(u["update_id"]))
    kv = FakeKV({"upd:000000000002": json.dumps({"update_id": 2}), "upd:000000000001": json.dumps({"update_id": 1}),
                 "snapshot": "{}"})
    assert runner.process_inbox(kv, log=lambda m: None) == 2
    assert seen == [1, 2] and kv.keys("upd:") == [] and "snapshot" in kv.d


def test_bad_update_does_not_block_the_rest(monkeypatch):
    from engine import telegram_bot

    def boom(u):
        if u["update_id"] == 1:
            raise ValueError("bad")
    monkeypatch.setattr(telegram_bot, "handle", boom)
    kv = FakeKV({"upd:1": json.dumps({"update_id": 1}), "upd:2": json.dumps({"update_id": 2})})
    assert runner.process_inbox(kv, log=lambda m: None) == 1 and kv.keys("upd:") == []


def test_pc_claims_are_honoured_until_stale():
    st = FakeStore()
    st.put("videos", "claim-a.json", b"{}")
    st.files[("videos", "claim-old.json")] = b"{}"
    st.created[("videos", "claim-old.json")] = "2020-01-01T00:00:00Z"
    assert set(runner.claims(st)) == {"a"}


def test_merge_marks_pc_videos_made_once(monkeypatch):
    from engine import autopilot
    plan = {"x1": {"id": "x1", "status": "planned"}, "x2": {"id": "x2", "status": "approved"}}
    updates = []
    monkeypatch.setattr(autopilot, "items", lambda a, b: [("2026-11-16", it) for it in plan.values()])
    monkeypatch.setattr(autopilot, "update_item", lambda s, i, **f: updates.append((i, f)))
    st = FakeStore()
    for i in ("x1", "x2"):
        st.put("videos", f"done-{i}.json", json.dumps({"id": i, "start": "2026-11-16", "out_rel": f"output/c/{i}",
                                                         "file": "video.mp4"}).encode())
        st.put("videos", f"claim-{i}.json", b"{}")
    assert runner.merge_helper(st, log=lambda m: None) == 1                   # x2 was already approved: untouched
    assert updates[0][0] == "x1" and updates[0][1]["status"] == "made" and updates[0][1]["made_by"] == "pc"
    assert not [n for (_, n) in st.files if n.startswith(("done-", "claim-"))]


def test_cloud_env_never_carries_pc_only_settings():
    txt = setup.cloud_env_text({"TELEGRAM_BOT_TOKEN": "t", "HOOKHOUSE_CLOUD": "1", "GH_TOKEN": "g", "EMPTY": ""})
    assert txt == "TELEGRAM_BOT_TOKEN=t\n"


def test_gitignore_keeps_secrets_and_data_out(tmp_path, monkeypatch):
    monkeypatch.setattr(setup, "ROOT", tmp_path)
    (tmp_path / ".gitignore").write_text(".env\n")
    setup.ensure_gitignore()
    setup.ensure_gitignore()                                                    # safe to run again
    lines = (tmp_path / ".gitignore").read_text().splitlines()
    for need in ("data/", "output/", ".env", "*.mp4"):
        assert lines.count(need) == 1


def test_env_file_read_and_write(tmp_path):
    p = tmp_path / ".env"
    p.write_text("# comment\nA=1\nB = 'two'\n")
    setup.set_env("A", "9", p)
    assert setup.read_env(p) == {"B": "two", "A": "9"}


def test_workflows_are_valid_and_share_one_state_lock():
    root = Path(__file__).resolve().parents[1]
    for name in ("tick", "render", "worker", "tests"):
        wf = yaml.safe_load((root / ".github" / "workflows" / f"{name}.yml").read_text(encoding="utf-8"))
        assert "jobs" in wf
        if name in ("tick", "render"):
            assert wf["concurrency"]["group"] == "state" and wf["concurrency"]["cancel-in-progress"] is False
    act = yaml.safe_load((root / ".github" / "actions" / "setup" / "action.yml").read_text(encoding="utf-8"))
    assert act["runs"]["using"] == "composite"


def test_worker_script_parses():
    root = Path(__file__).resolve().parents[1]
    js = (root / "cloud" / "worker" / "worker.js").read_text(encoding="utf-8")
    r = subprocess.run(["node", "--input-type=module", "--check"], input=js, capture_output=True, text=True,
                       encoding="utf-8")
    if r.returncode != 0 and "not found" in (r.stderr or "").lower():
        pytest.skip("node not installed")
    assert r.returncode == 0, r.stderr
    assert "OWNER_CHAT" in js and "x-telegram-bot-api-secret-token" in js       # only the owner, only Telegram
