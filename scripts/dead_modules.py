"""Which engine modules are imported by nobody (not by other modules, cli.py, tests or the cloud workflows)?
Usage: python -m scripts.dead_modules"""
import re
from pathlib import Path

from engine.config import ROOT

mods = {p.relative_to(ROOT).with_suffix("").as_posix().replace("/", "."): p
        for p in (ROOT / "engine").rglob("*.py") if p.name != "__init__.py"}
texts = {p: p.read_text(encoding="utf-8", errors="ignore") for p in
         list((ROOT / "engine").rglob("*.py")) + [ROOT / "cli.py"] + list((ROOT / "scripts").glob("*.py"))
         + list((ROOT / "cloud").rglob("*.yml")) + list((ROOT / "cloud").rglob("*.js"))}
tests = {p: p.read_text(encoding="utf-8", errors="ignore") for p in (ROOT / "tests").glob("*.py")}
for mod, path in sorted(mods.items()):
    short = mod.split(".")[-1]
    pat = re.compile(rf"(\b{re.escape(mod)}\b|from \.+\S* import [^\n]*\b{short}\b|import {short}\b|"
                     rf"\.{short}\b|\b{short}\.)")
    users = [p.name for p, t in texts.items() if p != path and pat.search(t)]
    tusers = [p.name for p, t in tests.items() if pat.search(t)]
    if not users:
        print(f"{mod:40} code users: none   tests: {', '.join(tusers[:3]) or 'none'}   ({len(path.read_text(encoding='utf-8').splitlines())} lines)")
