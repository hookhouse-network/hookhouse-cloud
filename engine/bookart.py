"""Book art (owner, 17 Nov 2026: "book images are not good, all pages repeated, not attractive, too boring ... make
attractive books that are up to the trends"). Research (17 Nov): the selling kids' style is "bold & easy" (Coco Wyo:
thick lines, big open areas, cute creatures in cozy scenes), every page a different scene, age band in the title,
single-sided pages, 32-60 designs.

Every colouring page here is an AI line drawing turned into clean print art:
  1. draw   - Cloudflare FLUX-schnell (Apache 2.0) when the free quota is open, else the same FLUX on the PC
              (quantised GGUF via stable-diffusion.cpp, MIT) on the CPU, ~1-3 minutes a page
  2. clean  - 4x upscale, pure black/white, specks removed, lines thickened to the age's stroke width
  3. check  - ink amount, colourable areas (enough, not too many for the age), no big black blobs, centred,
              not a near-duplicate of another page; a failed page is drawn again with a new seed
Pages are cached by prompt+seed (data/bookart/), so a rebuild never pays twice.
"""
from __future__ import annotations

import hashlib
import io
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

from .config import ROOT

CACHE = ROOT / "data" / "bookart"
MODELS = ROOT / "data" / "models"
LOCAL_MODEL = "FLUX.1-schnell Q4 GGUF via stable-diffusion.cpp"
DPI = 300
# 18 Nov: FLUX-schnell runs without a negative prompt (cfg 1), so "no color" did little: the first page came out as a
# coloured cartoon with grey shading and a solid black penguin. The look is now described positively and first.
STYLE = ("black and white line art coloring book page: thick clean black ink outlines on plain white paper, "
         "every shape left white inside ready to color, uncolored, monochrome. Subject: {subject}. "
         "Cute kawaii cartoon, bold and easy style, simple big shapes, few details, whole character visible, "
         "centered, plain white background")
# Color by Number (handoff 18 Nov: colours from a flat-colour cartoon, not random): FLUX paints a flat cartoon, the
# cleaner keeps its outlines, and each area's colour (nearest crayon in the key) comes from the painting.
CBN_STYLE = ("cute kawaii cartoon illustration with flat bright solid colors and thick clean black outlines, "
             "simple big shapes, no gradients, no shading, no texture. Subject: {subject}. Whole character visible, "
             "centered, plain white background")
NEGATIVE = ("color, colored, shading, gray, grey, gradient, shadow, text, letters, words, watermark, signature, logo, "
            "blurry, messy sketch lines, hatching, photo, realistic, frame, border, cropped, extra limbs, deformed")
# per age band: stroke width at 300 dpi (px), colourable areas allowed, ink share allowed
AGE = {"toddler": {"stroke": 14, "regions": (3, 60), "ink": (0.03, 0.30)},
       "kids": {"stroke": 9, "regions": (8, 220), "ink": (0.04, 0.32)},
       "older": {"stroke": 6, "regions": (15, 600), "ink": (0.05, 0.38)}}


@dataclass
class Page:
    image: Image.Image
    prompt: str
    seed: int
    source: str
    stats: dict = field(default_factory=dict)
    colour: Image.Image | None = None       # the drawing's own colours, aligned with `image` (Color by Number)


# ---------------- 1. draw ----------------
# Local FLUX (owner approved 17 Nov): FLUX.1-schnell Q4 GGUF (Apache 2.0) on the PC's CPU through stable-diffusion.cpp's
# sd-server (MIT), which keeps the model loaded and answers the standard txt2img call on 127.0.0.1 only.
# 18 Nov (owner: everything in the cloud, in-house generators): the same server runs on the Linux cloud machine of
# the picture farm (.github/workflows/pictures.yml); SD_DIR / FLUX_DIR point at its download folders there.
import os as _os
import sys as _sys
from engine.core.http import HTTP
SD_DIR = Path(_os.environ.get("SD_DIR") or ROOT / "tools" / "sdcpp")
FLUX_DIR = Path(_os.environ.get("FLUX_DIR") or MODELS / "flux")
SD_EXE = "sd-server.exe" if _sys.platform.startswith("win") else "sd-server"
SD_PORT = 1234
SD_URL = f"http://127.0.0.1:{SD_PORT}"


def _threads() -> int:
    """All cores on the cloud farm machine (it does nothing else); two spare on a PC."""
    n = _os.cpu_count() or 4
    return n if _os.environ.get("HOOKHOUSE_CLOUD") else max(1, n - 2)


def sd_server_up() -> bool:
    import requests
    try:
        return HTTP.get(f"{SD_URL}/sdapi/v1/options", timeout=5).ok
    except requests.RequestException:
        return False


def start_sd_server(wait_s: int = 900) -> bool:
    """Start the local FLUX server once (hidden window) and wait until the model is loaded."""
    import subprocess
    if sd_server_up():
        return True
    exe = SD_DIR / SD_EXE
    files = {k: FLUX_DIR / v for k, v in (("diffusion-model", "flux1-schnell-Q4_0.gguf"), ("vae", "ae-f16.gguf"),
                                          ("clip_l", "clip_l-Q8_0.gguf"), ("t5xxl", "t5xxl-Q4_0.gguf"))}
    if not exe.exists() or not all(p.exists() for p in files.values()):
        return False
    args = [str(exe), "--listen-ip", "127.0.0.1", "--listen-port", str(SD_PORT), "--cfg-scale", "1.0",
            "--sampling-method", "euler", "--steps", "4", "-t", str(_threads())]
    for k, p in files.items():
        args += [f"--{k}", str(p)]
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    log_f = open(CACHE.parent / "sd_server.log", "ab")
    env = dict(_os.environ, LD_LIBRARY_PATH=str(SD_DIR) + ":" + _os.environ.get("LD_LIBRARY_PATH", ""))   # Linux .so
    subprocess.Popen(args, cwd=str(SD_DIR), stdout=log_f, stderr=log_f, creationflags=flags, env=env)
    t0 = time.time()
    while time.time() - t0 < wait_s:
        if sd_server_up():
            return True
        time.sleep(5)
    return False


def draw_local(prompt: str, seed: int, size=(640, 832), negative: str = NEGATIVE, steps: int = 4) -> Image.Image:
    """One picture from the PC's own FLUX (no quota; ~1-3 minutes on this CPU)."""
    import base64
    import requests
    if not start_sd_server():
        raise RuntimeError("local FLUX is not available (model files or sd-server missing)")
    w, h = (size[0] // 64) * 64, (size[1] // 64) * 64
    r = requests.post(f"{SD_URL}/sdapi/v1/txt2img", timeout=3600,     # ~31 min a page on this CPU
                      json={"prompt": prompt, "negative_prompt": "", "steps": steps, "cfg_scale": 1.0,
                            "width": w, "height": h, "seed": seed, "sampler_name": "euler", "batch_size": 1})
    r.raise_for_status()
    img = (r.json().get("images") or [None])[0]
    if not img:
        raise RuntimeError(f"local FLUX gave no picture: {r.text[:200]}")
    return Image.open(io.BytesIO(base64.b64decode(img.split(",")[-1]))).convert("RGB")


HF_BOOK_MAX = 30                         # book pictures a day from the free Hugging Face FLUX.1-schnell Space
HF_COUNT = CACHE.parent / "hf_book_count.json"


def _hf_room() -> bool:
    """18 Nov: ~630 pictures are queued and the PC draws ~10 a night, so the books also take leftover Hugging Face
    ZeroGPU time (same free FLUX.1-schnell, Apache 2.0). Capped per UTC day: videos made at night keep their share."""
    try:
        d = json.loads(HF_COUNT.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        d = {}
    return d.get("day") != time.strftime("%Y-%m-%d", time.gmtime()) or d.get("n", 0) < HF_BOOK_MAX


def _hf_used() -> None:
    day = time.strftime("%Y-%m-%d", time.gmtime())
    try:
        d = json.loads(HF_COUNT.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        d = {}
    d = {"day": day, "n": (d.get("n", 0) if d.get("day") == day else 0) + 1}
    HF_COUNT.parent.mkdir(parents=True, exist_ok=True)
    HF_COUNT.write_text(json.dumps(d), encoding="utf-8")


def draw_cloud(prompt: str, seed: int, size=(640, 832)) -> tuple[Image.Image | None, str]:
    """Cloudflare FLUX first, then the Hugging Face FLUX Space (within HF_BOOK_MAX). (picture or None, source)."""
    try:
        from .storyboard import _cloudflare
        b = _cloudflare(prompt, seed=seed, size=(1024, 1024))
    except Exception:  # noqa: BLE001
        b = None
    if b:
        return Image.open(io.BytesIO(b)).convert("RGB"), "flux"
    if _hf_room():
        try:
            from .storyboard import _hf
            b = _hf(prompt, seed, size)
        except Exception:  # noqa: BLE001
            b = None
        if b:
            _hf_used()
            return Image.open(io.BytesIO(b)).convert("RGB"), "hf"
    return None, ""


SKIP_CLOUD = False                       # the night worker's local phase: don't spend the day's cloud quota


class NoPicture(RuntimeError):
    """The cloud quota is used up and local drawing is off: try again later."""


def draw(prompt: str, seed: int, prefer_cloud: bool = True, size=(640, 832),
         allow_local: bool = True) -> tuple[Image.Image, str]:
    """A raw drawing, cached by (prompt, seed, size)."""
    from .ip_guard import scrub                     # 20 Nov: books and brand art never show franchise characters
    prompt, _ = scrub(prompt)
    key = hashlib.sha1(json.dumps([prompt, seed, size]).encode()).hexdigest()[:20]
    CACHE.mkdir(parents=True, exist_ok=True)
    hit = next(iter(CACHE.glob(f"{key}_*.png")), None)
    if hit:
        return Image.open(hit).convert("RGB"), hit.stem.split("_", 1)[1]
    img, src = None, ""
    if prefer_cloud and not SKIP_CLOUD:
        img, src = draw_cloud(prompt, seed, size)
    if img is None:
        if not allow_local:
            raise NoPicture("cloud picture quota used up")
        img, src = draw_local(prompt, seed, size), "local"
    img.save(CACHE / f"{key}_{src}.png")
    return img, src


# ---------------- 2. clean ----------------
INK_MAX = 110                 # grey level above which nothing is ink (pastel colours and soft shading drop out)
FILL_KEEP = 0.0012            # solid black areas smaller than this share of the page stay (pupils, noses)


def hollow(ink: np.ndarray, stroke: int) -> np.ndarray:
    """Solid black areas -> their outline (18 Nov: the penguin's black body was a blob a child can't colour).
    A 'fill' is ink thicker than a line: pixels farther than r from any white. Big fills keep a ring of about
    `stroke` px at their edge; small ones (pupils, a nose) stay solid, as in real colouring books."""
    import cv2
    dist = cv2.distanceTransform(ink, cv2.DIST_L2, 5)
    thin = dist[(dist > 0) & (dist < 25)]          # the fills' own interiors must not inflate the line width
    line_half = float(np.median(thin)) if thin.size else 2.0
    r = max(stroke * 1.3, line_half * 2.5)
    core = (dist > r).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(core, connectivity=8)
    big = np.zeros(n, dtype=bool)
    big[1:] = st[1:, cv2.CC_STAT_AREA] >= FILL_KEEP * ink.size
    if not big.any():
        return ink
    core = big[lab].astype(np.uint8)
    region = (cv2.distanceTransform(1 - core, cv2.DIST_L2, 5) <= r).astype(np.uint8) & ink   # the fill itself
    ring = max(3, int(stroke))
    inner = (cv2.distanceTransform(region, cv2.DIST_L2, 5) > ring).astype(np.uint8)
    return ink & (1 - inner)


def clean(img: Image.Image, page_px=(2250, 2850), stroke: int = 9, with_colour: bool = False):
    """AI drawing -> print line art: upscale 4x, pure black/white, specks removed, lines at least `stroke` px,
    fitted (keeping proportions) into page_px with white margins. with_colour=True also returns the drawing's own
    colours warped exactly like the line art (Color by Number takes each area's colour from it)."""
    import cv2
    g = np.asarray(ImageOps.grayscale(img), dtype=np.uint8)
    scale = max(page_px[0] / g.shape[1], page_px[1] / g.shape[0])
    big = (int(g.shape[1] * scale), int(g.shape[0] * scale))
    g = cv2.resize(g, big, interpolation=cv2.INTER_CUBIC)
    g = cv2.GaussianBlur(g, (5, 5), 0)
    otsu, _ = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    # 18 Nov (first FLUX page): FLUX often draws a coloured cartoon. Otsu then also inked pastel shading (stray marks
    # on the hat), so the cut-off is capped: only real dark lines and dark fills count as ink.
    ink = (g < min(otsu, INK_MAX)).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    min_area = int(0.00004 * ink.size)                                        # specks
    keep = np.zeros(n, dtype=bool)
    keep[1:] = st[1:, cv2.CC_STAT_AREA] >= min_area
    ink = keep[lab].astype(np.uint8)
    ink = hollow(ink, stroke)
    dist = cv2.distanceTransform(ink, cv2.DIST_L2, 3)
    cur = 2 * float(np.median(dist[dist > 0])) if np.any(dist > 0) else stroke
    if cur < stroke:                                                          # bold & easy: thicken thin lines
        k = max(1, int(round((stroke - cur) / 2)))
        ink = cv2.dilate(ink, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * k + 1, 2 * k + 1)))
    ink = cv2.morphologyEx(ink, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
    ys, xs = np.nonzero(ink)
    box = (ys.min(), ys.max() + 1, xs.min(), xs.max() + 1) if len(xs) else (0, ink.shape[0], 0, ink.shape[1])
    ink = ink[box[0]:box[1], box[2]:box[3]]
    h, w = ink.shape
    f = min(page_px[0] / w, page_px[1] / h) * 0.94
    size = (max(1, int(w * f)), max(1, int(h * f)))
    ink = cv2.resize(ink * 255, size, interpolation=cv2.INTER_AREA)
    ink = (ink > 127).astype(np.uint8)
    canvas = np.full((page_px[1], page_px[0]), 255, dtype=np.uint8)
    y0, x0 = (page_px[1] - ink.shape[0]) // 2, (page_px[0] - ink.shape[1]) // 2
    canvas[y0:y0 + ink.shape[0], x0:x0 + ink.shape[1]][ink > 0] = 0
    art = Image.fromarray(canvas, "L")
    if not with_colour:
        return art
    rgb = cv2.resize(np.asarray(img.convert("RGB")), big, interpolation=cv2.INTER_CUBIC)[box[0]:box[1], box[2]:box[3]]
    col = np.full((page_px[1], page_px[0], 3), 255, dtype=np.uint8)
    col[y0:y0 + size[1], x0:x0 + size[0]] = cv2.resize(rgb, size, interpolation=cv2.INTER_AREA)
    return art, Image.fromarray(col, "RGB")


# ---------------- 3. check ----------------
def stats(page: Image.Image) -> dict:
    import cv2
    a = np.asarray(page)
    ink = (a < 128).astype(np.uint8)
    white = 1 - ink
    n, lab, st, _ = cv2.connectedComponentsWithStats(white, connectivity=4)
    h, w = a.shape
    border = set(np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]]))) - {0}
    min_area = int(0.0006 * a.size)                       # a crayon-sized area at least
    regions = [i for i in range(1, n) if i not in border and st[i, cv2.CC_STAT_AREA] >= min_area]
    ni, labi, sti, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    # biggest solid black blob: its area vs its outline (a filled shape has a small perimeter-to-area ratio)
    blob = 0.0
    if ni > 1:
        big = 1 + int(np.argmax(sti[1:, cv2.CC_STAT_AREA]))
        m = (labi == big).astype(np.uint8)
        er = cv2.erode(m, np.ones((25, 25), np.uint8))
        blob = float(er.sum()) / a.size
    return {"ink": float(ink.mean()), "regions": len(regions), "blob": blob}


def dhash(page: Image.Image, n: int = 16) -> int:
    g = np.asarray(page.convert("L").resize((n + 1, n), Image.BILINEAR), dtype=np.int16)
    bits = (g[:, 1:] > g[:, :-1]).flatten()
    return int("".join("1" if b else "0" for b in bits), 2)


def near(h1: int, h2: int, n: int = 16) -> bool:
    return bin(h1 ^ h2).count("1") < n * n * 0.12


def qa(page: Image.Image, age: str) -> list[str]:
    spec = AGE[age]
    s = stats(page)
    out = []
    if not spec["ink"][0] <= s["ink"] <= spec["ink"][1]:
        out.append(f"ink {s['ink']:.0%} (allowed {spec['ink'][0]:.0%}-{spec['ink'][1]:.0%})")
    if not spec["regions"][0] <= s["regions"] <= spec["regions"][1]:
        out.append(f"{s['regions']} colourable areas (allowed {spec['regions'][0]}-{spec['regions'][1]})")
    if s["blob"] > 0.01:
        out.append(f"big solid black area ({s['blob']:.1%} of the page)")
    return out


def page(subject: str, age: str = "kids", seed: int = 1, used: list[int] | None = None, tries: int = 5,
         prefer_cloud: bool = True, page_px=(2250, 2850), style: str = STYLE, log=print,
         allow_local: bool = True) -> Page | None:
    """One checked colouring page for `subject` (e.g. "a baby penguin hanging a star on a christmas tree").
    `used` holds the hashes of the book's other pages (no near-duplicates)."""
    prompt = style.format(subject=subject)
    for k in range(tries):
        sd = seed + k * 7919
        raw, src = draw(prompt, sd, prefer_cloud=prefer_cloud, allow_local=allow_local)
        art, colour = clean(raw, page_px=page_px, stroke=AGE[age]["stroke"], with_colour=True)
        probs = qa(art, age)
        h = dhash(art)
        if used and any(near(h, u) for u in used):
            probs.append("looks like another page")
        if not probs:
            if used is not None:
                used.append(h)
            return Page(art, prompt, sd, src, stats(art), colour)
        log(f"  page '{subject[:40]}' try {k + 1}: {'; '.join(probs)}")
    return None


def benchmark(n: int = 2) -> float:
    t = time.time()
    for i in range(n):
        draw_local(STYLE.format(subject="a cute baby elephant holding a balloon"), seed=100 + i)
    return (time.time() - t) / n
