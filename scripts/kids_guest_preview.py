"""Render one kids Short with a guest friend (template story, no AI call) and save a still for review.
python -m scripts.kids_guest_preview [seed]   (seed % 6: 0 Pip, 1 Mo, 2 Dee, 3 Kiki, 4 Hop, 5 Zip)"""
import json
import subprocess
import sys

from engine import kids
from engine.config import ROOT, channels


class NoBrain:
    def ask_json(self, *a, **k):
        raise RuntimeError("preview: template story")


seed = int(sys.argv[1]) if len(sys.argv) > 1 else 3
ch = next(c for c in channels() if c["id"] == "bloop_and_friends")
out, meta = kids.make(NoBrain(), ch, fmt="short", seed=seed, log=print)
print(meta["title"], meta["duration_s"], "s", json.dumps(meta["qa"]))
still = ROOT / "data" / "review" / "activity" / f"kids_guest_{seed}.jpg"
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", "8", "-i", str(out / "video.mp4"), "-frames:v", "1",
                "-vf", "scale=540:-1", str(still)], check=True)
print("video:", out / "video.mp4", "still:", still)
