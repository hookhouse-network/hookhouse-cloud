"""Channel branding v2 (owner 18 Nov 2026: "the content, profile image or bio is not good and attractive, put some
efforts"). The v1 pictures were the channel name in coloured letters on a dark square: unreadable as a small circle and
they said nothing about the channel.

Per channel, our own FLUX.1-schnell (in-house, drawn on the cloud farm) makes:
  emblem - one bold, recognisable icon illustration (profile pictures work best as a simple picture, no small text)
  scene  - a wide cinematic illustration of the niche (banner background)
and our code lays out (scripts/make_brand_assets.py typography: palettes, wordmarks, Hindi shaping, safe areas):
  avatar.png 1080x1080 (YouTube, Instagram, Facebook), youtube_banner.jpg 2560x1440 (text in the 1546x423 area
  every device shows), facebook_cover.jpg 1640x624 (text in the centre phones keep).
Bios are written for each platform's limit (Instagram 150, Facebook 101 characters).
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from .config import ROOT

OUT = ROOT / "output" / "brand"
TAG = "brand"
EMBLEM_STYLE = ("bold flat vector emblem logo illustration, {subject}, thick clean outlines, vibrant {colours}, "
                "strong simple shapes, centered, perfectly symmetrical composition, solid plain dark background, "
                "high contrast, modern YouTube channel icon, no text, no letters, no words")
SCENE_STYLE = ("cinematic digital illustration, {subject}, dramatic lighting, rich {colours}, wide panoramic "
               "composition, darker calm area in the middle, highly detailed, no text, no letters, no words")

# id: (emblem subject, scene subject, colour words)
ART = {
    "hot_take_hq": ("a retro studio microphone wrapped in bright flames", "a glowing podcast studio at night with "
                    "two microphones, neon signs and smoke", "orange, yellow and red on charcoal"),
    "unsolved_after_dark": ("a vintage magnifying glass revealing a single glowing eye", "a foggy midnight street with a "
                            "lone street lamp, a case file and police tape", "deep red and black"),
    "clutch_tales": ("a golden championship trophy struck by a lightning bolt", "a packed stadium under floodlights at "
                     "the final second, confetti in the air", "gold and royal blue"),
    # 18 Nov review: v1 "film reel + key" read as a telephone dial, "coin + controller" as a gaming channel
    "ending_decoded": ("an open movie clapperboard with a bright glowing question mark rising out of it",
                       "an empty cinema with a glowing screen and film strips floating in the beam", "red, white and black"),
    "money_cheat_codes": ("a tall stack of shiny gold coins with a big glowing green arrow shooting upward",
                          "a futuristic city of stacked gold coins and neon charts", "neon green and gold on dark green"),
    "itihaas_ke_raaz": ("an ancient Indian fort inside an old scroll with a glowing keyhole", "a majestic Rajasthani "
                        "palace at golden hour with lanterns and ancient banners", "saffron, gold and deep maroon"),
    "cricket_ke_kisse": ("a red cricket ball and two crossed bats with sparks", "a cricket stadium at night under "
                         "floodlights, a ball flying over the boundary", "emerald green and bright yellow"),
    "picture_abhi_baaki_hai": ("a vintage film camera under a golden spotlight with stars", "a glamorous old Bollywood "
                               "film set with spotlights, a red carpet and film reels", "magenta, gold and deep purple"),
    "brain_snack": ("a cute cartoon brain mascot holding a cookie, big happy eyes", "a dreamy abstract space of "
                    "floating glossy bouncing balls, glowing maze lines and puzzle pieces, no machines, no signs", "cyan, magenta and violet"),
    "cosmos_unboxed": ("an open cardboard box releasing a glowing ringed planet and stars", "a vast nebula with "
                       "glowing planets, a spaceship and a spiral galaxy", "violet and cyan on deep navy"),
    "deep_blue_files": ("a deep sea diving helmet surrounded by glowing jellyfish", "the deep ocean with a sunken "
                        "ship, a giant whale and bioluminescent creatures", "teal, cyan and deep blue"),
    "wild_instinct": ("a fierce tiger face made of bold geometric shapes", "a misty jungle at dawn with a tiger, an "
                      "eagle and a waterfall", "orange, gold and dark green"),
    "stream_clips": ("a glowing play button with a game controller and neon light trails", "a neon gaming room with "
                     "a streaming setup, glowing screens and RGB lights", "purple and electric green on black"),
}

BIOS = {   # (Instagram <= 150 chars, Facebook Page bio <= 101 chars); 18 Nov v3: hook + promise + reason to follow
    "hot_take_hq": ("🎙️ The 60 seconds of every podcast you actually need\n🔥 Hot takes · wild guests · daily clips\n"
                    "👇 Full videos on YouTube",
                    "🎙️ The 60 seconds of every podcast you actually need. 🔥 Hot takes & wild guests daily."),
    "unsolved_after_dark": ("🕯️ Real mysteries. No answers.\n🔎 True cases & dark history in 60 seconds\n"
                            "👇 A new case every night",
                            "🕯️ Real mysteries. No answers. 🔎 A new true case every night, if you dare."),
    "clutch_tales": ("🏆 Sports' greatest moments, told like movies\n⚡ Comebacks · buzzer-beaters · underdogs\n"
                     "👇 A new story every day",
                     "🏆 Sports' greatest moments, told like movies. ⚡ Comebacks & underdogs daily."),
    "ending_decoded": ("🎬 Every ending explained. Every secret found.\n🔍 Hidden details & film theories\n"
                       "👇 A new breakdown every day",
                       "🎬 Every ending explained. Every secret found. 🔍 A new breakdown daily."),
    "money_cheat_codes": ("💸 Money tricks school never taught you\n🧠 How money, tech & AI really work\n"
                          "📚 Education only, not financial advice",
                          "💸 Money tricks school never taught you. 🧠 How money & AI really work."),
    "itihaas_ke_raaz": ("📜 Har kahani mein chhupa hai ek raaz\n🏰 Itihaas ki ansuni kahaniyan, 60 second mein\n"
                        "👇 Roz nayi kahani",
                        "📜 Har kahani mein chhupa hai ek raaz. 🏰 Itihaas ki ansuni kahaniyan, roz."),
    "cricket_ke_kisse": ("🏏 Cricket ke woh kisse jo rongte khade kar dein\n🔥 Last-ball drama · legends · records\n"
                         "👇 Roz naya kissa",
                         "🏏 Cricket ke woh kisse jo rongte khade kar dein. 🔥 Roz naya kissa."),
    "picture_abhi_baaki_hai": ("🎥 Bollywood ke raaz, ek minute mein\n⭐ Filmy kisse · behind the scenes · trivia\n"
                               "👇 Roz naye raaz",
                               "🎥 Bollywood ke raaz, ek minute mein. ⭐ Filmy kisse & trivia, roz."),
    "brain_snack": ("🧠 Your daily dose of useless genius\n🎯 Satisfying puzzles, quizzes & brain games\n"
                    "👇 Can you beat today's?",
                    "🧠 Your daily dose of useless genius. 🎯 Puzzles, quizzes & brain games."),
    "cosmos_unboxed": ("🌌 The universe, one jaw-dropping fact at a time\n🚀 Space stories, missions & mysteries\n"
                       "👇 A new wonder every day",
                       "🌌 The universe, one jaw-dropping fact at a time. 🚀 New space stories daily."),
    "deep_blue_files": ("🌊 95% of the ocean is unexplored. Let's go.\n🐙 Deep-sea creatures, wrecks & mysteries\n"
                        "👇 Dive in daily",
                        "🌊 95% of the ocean is unexplored. Let's go. 🐙 Deep-sea mysteries daily."),
    "wild_instinct": ("🐾 Nature's most incredible true stories\n🦁 Survival, hunts & animal genius\n"
                      "👇 A new story every day",
                      "🐾 Nature's most incredible true stories. 🦁 Survival & animal genius daily."),
    "stream_clips": ("🎮 The best moments from every stream\n⚡ Clutches · fails · reactions\n👇 Fresh clips daily",
                     "🎮 The best moments from every stream. ⚡ Clutches, fails & reactions daily."),
}


def ig_bio(cid: str) -> str:
    """Instagram bio with a follow line for the channel's YouTube instead of the generic last line (owner 19 Nov: "all
    the cross platform links should be mentioned in the bios and ask to follow"). Instagram allows 150 characters."""
    bio = BIOS[cid][0]
    try:
        from .links import data
        yt = str((data().get(cid) or {}).get("youtube") or "")
    except Exception:  # noqa: BLE001
        yt = ""
    if not yt:
        return bio
    lines = bio.split("\n")
    linked = "\n".join(lines[:2] + [f"▶️ Follow on YouTube: {yt}"])
    return linked if len(linked) <= 150 else bio


def fb_description(cid: str, about: str = "") -> str:
    """Facebook Page description (255 characters): the channel line + where else to follow it."""
    try:
        from .links import data, _ig_connected
        row = data().get(cid) or {}
    except Exception:  # noqa: BLE001
        return about[:255]
    parts = []
    if row.get("youtube"):
        parts.append(f"YouTube: youtube.com/{row['youtube']}")
    if row.get("instagram") and _ig_connected(cid):
        parts.append(f"Instagram: instagram.com/{str(row['instagram']).lstrip('@')}")
    follow = ("Follow us. " + " | ".join(parts)) if parts else ""
    room = 255 - len(follow) - 2
    if not follow:
        return about[:255]
    head = about if len(about) <= room else about[:room].rsplit(" ", 1)[0]
    return (head + "\n\n" + follow).strip()


def jobs() -> list[tuple[str, str, str, tuple[int, int]]]:
    """(channel, kind, prompt, size) for every picture to draw."""
    out = []
    for cid, (emblem, scene, colours) in ART.items():
        out.append((cid, "emblem", EMBLEM_STYLE.format(subject=emblem, colours=colours), (768, 768)))
        out.append((cid, "scene", SCENE_STYLE.format(subject=scene, colours=colours), (1344, 768)))
    return out


def _cover(img: Image.Image, w: int, h: int) -> Image.Image:
    """Scale to cover w x h and centre-crop."""
    f = max(w / img.width, h / img.height)
    im = img.resize((int(img.width * f + 0.5), int(img.height * f + 0.5)), Image.LANCZOS)
    x, y = (im.width - w) // 2, (im.height - h) // 2
    return im.crop((x, y, x + w, y + h))


def avatar(cid: str, emblem: Image.Image) -> Image.Image:
    """The emblem, full bleed, with a soft vignette and a thin ring in the channel's accent inside the circle crop."""
    from scripts.make_brand_assets import BRANDS, rgb
    S = 1080
    img = _cover(emblem.convert("RGB"), S, S)
    shade = Image.new("L", (S, S), 0)
    d = ImageDraw.Draw(shade)
    d.ellipse([S * 0.04, S * 0.04, S * 0.96, S * 0.96], fill=255)
    shade = shade.filter(ImageFilter.GaussianBlur(S * 0.06))
    dark = Image.new("RGB", (S, S), rgb(BRANDS[cid]["bg"][1]))
    img = Image.composite(img, dark, shade)
    ring = ImageDraw.Draw(img)
    accent = rgb(BRANDS[cid]["lines"][-1][1])
    ring.ellipse([S * 0.035, S * 0.035, S * 0.965, S * 0.965], outline=accent, width=int(S * 0.018))
    return img


def banner(cid: str, scene: Image.Image, emblem: Image.Image, W: int, H: int, safe: tuple[int, int]) -> Image.Image:
    """Scene background, a dark band behind the safe area, the emblem + wordmark + tagline inside the safe area."""
    from scripts.make_brand_assets import BRANDS, POP, fit, rgb, row
    b = BRANDS[cid]
    img = _cover(scene.convert("RGB"), W, H).convert("RGBA")
    sw, sh = safe
    x0, y0 = (W - sw) / 2, (H - sh) / 2
    band = Image.new("L", (W, H), 0)
    ImageDraw.Draw(band).rounded_rectangle([x0 - sh * 0.15, y0 - sh * 0.12, x0 + sw + sh * 0.15, y0 + sh * 1.12],
                                           radius=int(sh * 0.2), fill=170)
    band = band.filter(ImageFilter.GaussianBlur(sh * 0.12))
    img = Image.composite(Image.new("RGBA", (W, H), (*rgb(b["bg"][1]), 255)), img, band)
    e = 0.86 * sh                                                       # the emblem, round, on the left of the name
    em = _cover(emblem.convert("RGB"), int(e), int(e)).convert("RGBA")
    mask = Image.new("L", em.size, 0)
    ImageDraw.Draw(mask).ellipse([0, 0, em.width - 1, em.height - 1], fill=255)
    em.putalpha(mask)
    img.alpha_composite(em, (int(x0), int(y0 + (sh - e) / 2)))
    tx = x0 + e + sh * 0.12
    tw = sw - (tx - x0)
    parts = b.get("banner_lines") or [(t + " ", c) for t, c in b["lines"][:-1]] + [b["lines"][-1]]
    bottom = row(img, parts, b.get("banner_font", b["font"]), (tx, y0 + sh * 0.08, tw, sh * 0.5))
    g = fit(b["tag"], b.get("tag_font", POP), b.get("ink", "#FFFFFF"), tw, sh * 0.15)
    img.alpha_composite(g, (int(tx + (tw - g.width) / 2), int(bottom + sh * 0.08)))
    return img.convert("RGB")


def compose(cid: str, emblem: Image.Image, scene: Image.Image, out: Path | None = None) -> dict[str, Path]:
    out = (out or OUT) / cid
    out.mkdir(parents=True, exist_ok=True)
    files = {"avatar.png": avatar(cid, emblem),
             "youtube_banner.jpg": banner(cid, scene, emblem, 2560, 1440, (1546, 423)),
             "facebook_cover.jpg": banner(cid, scene, emblem, 1640, 624, (1100, 300))}
    paths = {}
    for name, im in files.items():
        p = out / name
        im.save(p, quality=92) if name.endswith(".jpg") else im.save(p)
        paths[name] = p
    return paths


def work(store, shard: int = 0, shards: int = 1, log=print) -> int:
    """Cloud farm machine: draw this shard's channels with our own FLUX, compose, store everything (tag 'brand')."""
    from . import bookart
    import os
    only = [c for c in os.environ.get("BRAND_ONLY", "").split(",") if c]      # redraw just these (review fixes)
    todo = [c for c in ART if not only or c in only]
    mine = [cid for i, cid in enumerate(todo) if i % shards == shard]
    bookart.SKIP_CLOUD = True
    n = 0
    try:
        for cid in mine:
            pics = {}
            for c, kind, prompt, size in jobs():
                if c != cid:
                    continue
                img, src = bookart.draw(prompt, seed=7 + len(cid) + (101 if only else 0), size=size, allow_local=True)
                pics[kind] = img
                p = OUT / cid / f"{kind}.png"
                p.parent.mkdir(parents=True, exist_ok=True)
                img.save(p)
                store.put(TAG, f"{cid}__{kind}.png", p.read_bytes(), "image/png")
                log(f"{cid}: {kind} drawn ({src})")
            for name, p in compose(cid, pics["emblem"], pics["scene"]).items():
                store.put(TAG, f"{cid}__{name}", p.read_bytes(), "image/png" if name.endswith(".png") else "image/jpeg")
                n += 1
            log(f"{cid}: avatar, YouTube banner and Facebook cover stored")
    finally:
        bookart.SKIP_CLOUD = False
    return n


def pull(store=None) -> int:
    """Fetch the stored brand files (avatar, banners) into output/brand/<channel>/ (cloud runs start empty)."""
    from .cloud.store import Store
    store = store or Store()
    n = 0
    for name in store.assets(TAG):
        if "__" not in name:
            continue
        cid, fname = name.split("__", 1)
        dest = OUT / cid / fname
        data = store.get(TAG, name)
        if data and (not dest.exists() or dest.read_bytes() != data):
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            n += 1
    return n


def page_preview(cid: str, out: Path | None = None) -> Path:
    """A Facebook-style mock-up of the finished Page (cover, round profile picture, name, category, bio, buttons)
    for the owner to approve before anything goes live."""
    from PIL import ImageFont
    from scripts.make_brand_assets import BRANDS, FONTS, rgb
    from .config import channel
    W = 1200
    cover = Image.open(OUT / cid / "facebook_cover.jpg").convert("RGB").resize((W, int(W * 624 / 1640)))
    av = Image.open(OUT / cid / "avatar.png").convert("RGB").resize((230, 230))
    H = cover.height + 330
    img = Image.new("RGB", (W, H), (240, 242, 245))
    img.paste(cover, (0, 0))
    d = ImageDraw.Draw(img)
    cx, cy = 60, cover.height - 90
    d.ellipse([cx - 6, cy - 6, cx + 236, cy + 236], fill="white")
    m = Image.new("L", av.size, 0)
    ImageDraw.Draw(m).ellipse([0, 0, 229, 229], fill=255)
    img.paste(av, (cx, cy), m)
    big = ImageFont.truetype(str(FONTS / "Poppins-ExtraBold.ttf"), 46)
    small = ImageFont.truetype(str(FONTS / "Poppins-ExtraBold.ttf"), 22)
    x, y = cx + 260, cover.height + 18
    d.text((x, y), channel(cid)["name"], font=big, fill=(5, 5, 5))
    d.text((x, y + 62), "Digital creator", font=small, fill=(101, 103, 107))
    try:
        emo = ImageFont.truetype("seguiemj.ttf", 24)
    except OSError:
        emo = small
    d.text((x, y + 100), BIOS[cid][1], font=emo, fill=(28, 30, 33), embedded_color=True)
    accent = rgb(BRANDS[cid]["lines"][-1][1])
    for i, (label, fill, ink) in enumerate((("Follow", (8, 102, 255), "white"), ("Watch on YouTube", accent, "black"))):
        bx = x + i * 230
        d.rounded_rectangle([bx, y + 160, bx + 210, y + 210], radius=10, fill=fill)
        tw = d.textlength(label, font=small)
        d.text((bx + (210 - tw) / 2, y + 170), label, font=small, fill=ink)
    p = (out or OUT / cid) / "page_preview.jpg"
    p.parent.mkdir(parents=True, exist_ok=True)
    img.save(p, quality=90)
    return p
