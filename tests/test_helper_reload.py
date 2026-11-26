"""21 Nov: the PC helper is one long process; pushed fixes never reached the PC maker until someone restarted it.
It now stops between videos when the code moved to a new commit, and scripts/pc_maker.cmd starts it again."""
from engine.cloud import runner


def _repo(tmp_path, head="ref: refs/heads/main", main="abc123", packed=None):
    git = tmp_path / ".git"
    (git / "refs" / "heads").mkdir(parents=True)
    (git / "HEAD").write_text(head + "\n", encoding="utf-8")
    if main is not None:
        (git / "refs" / "heads" / "main").write_text(main + "\n", encoding="utf-8")
    if packed is not None:
        (git / "packed-refs").write_text(packed, encoding="utf-8")
    return tmp_path


def test_code_version_reads_the_commit(tmp_path):
    root = _repo(tmp_path)
    assert runner._code_version(root) == "abc123"
    (root / ".git" / "refs" / "heads" / "main").unlink()
    (root / ".git" / "packed-refs").write_text("# pack-refs\nfff999 refs/heads/main\n", encoding="utf-8")
    assert runner._code_version(root) == "fff999"
    (root / ".git" / "HEAD").write_text("d00d42\n", encoding="utf-8")         # detached HEAD
    assert runner._code_version(root) == "d00d42"
    assert runner._code_version(tmp_path / "nowhere") == ""


def test_new_code_only_on_a_real_change(tmp_path):
    root = _repo(tmp_path)
    assert not runner._new_code("abc123", root)
    assert not runner._new_code("", root)                                      # unknown start: never restart
    (root / ".git" / "refs" / "heads" / "main").write_text("bbb222\n", encoding="utf-8")
    assert runner._new_code("abc123", root)
    assert not runner._new_code("abc123", tmp_path / "nowhere")                # unreadable now: keep going


def test_helper_stops_between_videos_for_new_code(monkeypatch):
    versions = iter(["old", "new"])
    monkeypatch.setattr(runner, "_one_helper", lambda: True)
    monkeypatch.setattr(runner, "_code_version", lambda root=None: next(versions))
    touched = []
    monkeypatch.setattr(runner, "_ensure_chrome", lambda log: touched.append("chrome"))
    lines = []
    runner.helper(videos_only=True, log=lines.append)                         # returns instead of looping forever
    assert touched == [] and any("new code" in ln for ln in lines)


def test_scheduler_on_with_an_empty_answer_still_makes_due_work(monkeypatch):
    """26 Nov (before scheduler: on): the queue handing nothing while work is due here must not idle the PC."""
    from engine import cr_footage, watchdog
    from engine.cloud import pc_outbox, sched, state
    monkeypatch.setattr(runner, "_one_helper", lambda: True)
    monkeypatch.setattr(runner, "_code_version", lambda root=None: "same")
    monkeypatch.setattr(runner, "_ensure_chrome", lambda log: None)
    monkeypatch.setattr(runner, "Store", lambda: object())
    monkeypatch.setattr(watchdog, "helper_heartbeat", lambda *a, **k: None)
    monkeypatch.setattr(cr_footage, "chrome_up", lambda: True)
    monkeypatch.setattr(state, "pull", lambda store: None)
    monkeypatch.setattr(cr_footage, "pc_job", lambda store, log: False)
    monkeypatch.setattr(cr_footage, "ensure_config_campaigns", lambda log=None: None)
    monkeypatch.setattr(cr_footage, "kick_job", lambda store, log: False)
    monkeypatch.setattr(cr_footage, "recover_sources", lambda store, log: None)
    monkeypatch.setattr(pc_outbox, "alerts", lambda: [])
    monkeypatch.setattr(pc_outbox, "flush", lambda store, log: 0)
    monkeypatch.setattr(pc_outbox, "disk_ok", lambda log: True)
    monkeypatch.setattr(pc_outbox, "pending", lambda: [])
    monkeypatch.setattr(pc_outbox, "awaiting_merge", lambda it: False)
    monkeypatch.setattr(runner, "claims", lambda store: {})
    monkeypatch.setattr(runner, "_pc_waiting", lambda iid: False)
    item = {"id": "1127_0500_x_short", "status": "planned", "kind": "short"}
    monkeypatch.setattr(runner, "_due_to_make", lambda kinds, taken: [("s", item)])

    class HB:
        client = None

        def stop(self):
            pass
    monkeypatch.setattr(sched, "start_pc_heartbeat", lambda log: HB())
    monkeypatch.setattr(sched, "top_up", lambda client, due, log=None: {"queued": [], "added": 0})
    monkeypatch.setattr(sched, "next_job", lambda hb, items, log: None)       # the queue gives nothing
    monkeypatch.setattr(sched, "mode", lambda: "on")
    made, lines = [], []

    class Done(KeyboardInterrupt):                # the helper goes straight on to the next video: end it here
        pass

    def make(store, start, it, log):
        made.append(it["id"])
        raise Done()
    monkeypatch.setattr(runner, "_make_and_hand_over", make)
    import pytest
    with pytest.raises(Done):
        runner.helper(once=False, videos_only=True, log=lines.append)
    assert made == ["1127_0500_x_short"] and any("claim files this round" in ln for ln in lines)


def test_the_scheduler_setting_is_a_string():
    """26 Nov: a bare `scheduler: on` is the YAML boolean True, which mode() reads as 'off'."""
    from engine.config import settings
    assert isinstance(settings().get("scheduler"), str)
