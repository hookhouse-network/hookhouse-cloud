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
