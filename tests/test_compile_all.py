"""Every tracked Python file must compile.

20 Nov 2026: a Git-Bash heredoc turned a "\\n" inside an f-string in cli.py into a real line break. The test suite
still passed (no test imports cli.py), the commit was pushed, and every cloud tick failed for hours with a
SyntaxError. This test compiles every tracked .py file so a broken entry point can never ship again.
"""
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _tracked_py():
    out = subprocess.run(["git", "ls-files", "*.py"], cwd=ROOT, capture_output=True, text=True, check=True)
    return [ROOT / p for p in out.stdout.splitlines() if p.strip()]


def test_every_tracked_python_file_compiles():
    files = _tracked_py()
    assert files, "git ls-files found no Python files"
    broken = []
    for f in files:
        if not f.exists():  # deleted in the worktree but not yet committed
            continue
        try:
            compile(f.read_bytes(), str(f), "exec")  # bytes: honours a UTF-8 BOM like the interpreter does
        except SyntaxError as e:
            broken.append(f"{f.relative_to(ROOT)}:{e.lineno}: {e.msg}")
    assert not broken, "files that do not compile:\n" + "\n".join(broken)


def test_cli_entry_point_compiles():
    compile((ROOT / "cli.py").read_bytes(), "cli.py", "exec")
