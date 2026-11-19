"""Draw missing brand art with Cloudflare's free FLUX.1-schnell (API call; the GitHub farm is gone) and compose the
avatar / YouTube banner / Facebook cover locally. python -m scripts.brand_cf <channel>[:emblem|:scene] ..."""
import io
import sys

from dotenv import load_dotenv
from PIL import Image

load_dotenv()
from engine import brand_art  # noqa: E402
from engine.storyboard import _cloudflare  # noqa: E402

for arg in sys.argv[1:]:
    cid, _, only = arg.partition(":")
    for c, kind, prompt, size in brand_art.jobs():
        if c != cid or (only and kind != only):
            continue
        data = _cloudflare(prompt, seed=7 + len(cid) + 211, size=size)
        if not data:
            print(f"{cid} {kind}: Cloudflare gave no picture (quota?)")
            continue
        p = brand_art.OUT / cid / f"{kind}.png"
        p.parent.mkdir(parents=True, exist_ok=True)
        Image.open(io.BytesIO(data)).convert("RGB").save(p)
        print(f"{cid} {kind}: drawn")
    e, s = brand_art.OUT / cid / "emblem.png", brand_art.OUT / cid / "scene.png"
    if e.exists() and s.exists():
        brand_art.compose(cid, Image.open(e), Image.open(s))
        print(f"{cid}: avatar, YouTube banner, Facebook cover composed")
