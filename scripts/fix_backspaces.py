"""Replace stray backspace characters (a Git-Bash heredoc turns a regex \\b into chr(8)) with a real \\b.
python -m scripts.fix_backspaces <file> [<file> ...]"""
import sys
from pathlib import Path

for name in sys.argv[1:]:
    p = Path(name)
    s = p.read_text(encoding="utf-8")
    n = s.count(chr(8))
    if n:
        p.write_text(s.replace(chr(8), chr(92) + "b"), encoding="utf-8")
    print(f"{name}: {n} fixed")
