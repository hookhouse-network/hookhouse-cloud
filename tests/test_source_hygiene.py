"""Guard: shell heredoc patches once turned regex "\b" into a backspace character (chr 8) inside engine code."""
from pathlib import Path


def test_no_control_characters_in_engine_code():
    bad = []
    for p in list(Path("engine").rglob("*.py")) + [Path("cli.py")]:
        text = p.read_text(encoding="utf-8")
        if any(ch in text for ch in (chr(8), chr(0), chr(7))):
            bad.append(str(p))
    assert not bad, f"control characters in {bad}"
