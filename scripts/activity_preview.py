"""Preview the activity-book page makers with already drawn FLUX pages (no new pictures needed).
python -m scripts.activity_preview  ->  data/review/activity/*.jpg"""
from PIL import Image

from engine import activity_v2 as av, bookart
from engine.config import ROOT
from engine.digital_products import maze, maze_path

SRC = ROOT / "data" / "products" / "christmas_colouring_book" / "v2"
OUT = ROOT / "data" / "review" / "activity"
OUT.mkdir(parents=True, exist_ok=True)


def art(n: int, box) -> Image.Image:
    """A drawn page re-fitted into the picture box the activity book uses (like clean() would)."""
    im = Image.open(SRC / f"page_{n:02d}.png").convert("L")
    bb = Image.eval(im, lambda v: 255 - v).getbbox()
    im = im.crop(bb)
    f = min(box[0] / im.width, box[1] / im.height) * 0.94
    im = im.resize((int(im.width * f), int(im.height * f)), Image.LANCZOS).point(lambda v: 0 if v < 128 else 255)
    canvas = Image.new("L", box, 255)
    canvas.paste(im, ((box[0] - im.width) // 2, (box[1] - im.height) // 2))
    return canvas


def save(p: Image.Image, name: str) -> None:
    p.convert("RGB").resize((850, 1100), Image.LANCZOS).save(OUT / f"{name}.jpg", quality=88)


cells = maze(9, 8, seed=7)
save(av.maze_page(cells, "penguin", "present", art(1, av.SMALL), art(2, av.SMALL)), "maze")
save(av.maze_page(cells, "penguin", "present", art(1, av.SMALL), art(2, av.SMALL), path=maze_path(cells)), "maze_answer")
save(av.dots_page(art(2, av.DOTS), "Polar bear", 30), "dots")
scene = art(3, av.SCENE)
changed, circles = av.differences(scene, 5, seed=3)
print("changes:", circles)
save(av.spot_page(scene, changed, len(circles)), "spot")
save(av.spot_page(scene, changed, len(circles), circles), "spot_answer")
save(av.word_search_page("Snow day", ["SLED", "SNOW", "HAT", "SCARF", "COLD", "ICE", "MITTEN", "COCOA"], 9,
                         art(1, av.SMALL)), "word_search")
print("stats dots art:", bookart.stats(art(2, av.DOTS)))
print("saved to", OUT)
