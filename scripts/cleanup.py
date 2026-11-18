"""Disk cleanup (runs daily by itself inside the autopilot). Manual use: python scripts/cleanup.py [--apply]
Dry run by default. Rules: engine/cleanup.py (never deletes videos still waiting for approval or posting)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine import cleanup  # noqa: E402

res = cleanup.run(apply="--apply" in sys.argv)
for path, why in res.get("list", [])[:60]:
    print(f"  {why:50} {path}")
