"""Layout check without AI pictures: a placeholder drawing in every slot. Writes small JPG previews to
data/review/book_layout/. Usage: python -m scripts.book_layout_preview"""
from PIL import Image, ImageDraw

from engine import books_v2
from engine.config import ROOT

out = ROOT / "data" / "review" / "book_layout"
out.mkdir(parents=True, exist_ok=True)


def placeholder(size=(900, 900)) -> Image.Image:
    im = Image.new("L", size, 255)
    d = ImageDraw.Draw(im)
    w, h = size
    d.ellipse((w * .15, h * .2, w * .85, h * .9), outline=0, width=14)            # a simple duck-ish blob
    d.ellipse((w * .55, h * .05, w * .85, h * .38), outline=0, width=14)
    d.ellipse((w * .7, h * .17, w * .74, h * .21), fill=0)
    d.polygon([(w * .85, h * .2), (w * .97, h * .25), (w * .85, h * .29)], outline=0, width=10)
    return im


for n, word, obj in [(3, "Three", "duck"), (7, "Seven", "butterfly"), (18, "Eighteen", "heart")]:
    pages = books_v2.numbers_pages(n, word, obj, placeholder())
    pages[0].convert("RGB").resize((850, 1100)).save(out / f"numbers_{n}_count.jpg", quality=85)
    pages[2].convert("RGB").resize((850, 1100)).save(out / f"numbers_{n}_trace.jpg", quality=85)
art = placeholder(books_v2.ART)
books_v2.design_page(art, "Fun fact: Sea otters hold hands while they sleep so they don't drift apart.") \
    .convert("RGB").resize((850, 1100)).save(out / "fact_page.jpg", quality=85)
print("previews in", out)
