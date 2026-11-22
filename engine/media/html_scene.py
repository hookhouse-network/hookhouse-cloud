"""Animated scenes written as web code (canvas), recorded frame by frame into a video.

Idea from yihui-dev/awesome-opus5-5-videos (MIT; 418 viral videos made by having an AI write the animation as
HTML / Canvas / SVG / Three.js) and heygen-com/hyperframes (Apache-2.0, "write HTML, render video"). Ours is a small
recorder on the Playwright + Chromium already installed for the setup assistant: no new installs, no GPU, no paid
video model, and every picture is our own code (zero copyright risk).

How it records: the page exposes window.draw(t); we call it for t = 0, 1/fps, 2/fps ... and screenshot each frame,
so the result is exact (no dropped frames, same input = same video) however slow the PC is.

Templates live in engine/media/scenes/. chart.html draws compare bars, a timeline, true-to-scale size circles or a
depth dive in each channel's own colours and fonts (story.py visual "chart")."""
from __future__ import annotations

import base64
import json
import re
import subprocess
from pathlib import Path

from . import ffmpeg as ff
from .fonts import font_file

SCENES = Path(__file__).resolve().parent / "scenes"
CHART_TYPES = {"compare": (2, 4), "timeline": (3, 5), "scale": (2, 3), "depth": (1, 1)}
HINDI = re.compile(r"[ऀ-ॿ]")
# Depth dive (23 Nov, P3b picture-free scenes; the viral ocean-depth animations use familiar landmarks as yardsticks).
# Landmarks show NAMES only, so the screen never shows a number the narrator didn't say. Depths: NOAA Ocean
# Exploration (sunlight zone to ~200 m, twilight zone to ~1,000 m, Titanic wreck ~3,800 m, Challenger Deep ~10,935 m);
# 40 m = the recreational scuba limit (PADI).
DEPTH_MARKS = (("Scuba divers' limit", 40), ("Sunlight fades out", 200), ("Last trace of light", 1000),
               ("The Titanic", 3800), ("Challenger Deep", 10935))
DEPTH_UNITS = {"m": 1.0, "meter": 1.0, "metre": 1.0, "km": 1000.0, "kilometer": 1000.0, "kilometre": 1000.0,
               "ft": 0.3048, "foot": 0.3048, "feet": 0.3048, "mile": 1609.344}
DEPTH_TEXT = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(kilomet(?:er|re)s?|km|met(?:er|re)s?|m|feet|foot|ft|miles?)\b", re.I)


def depth_m(text: str) -> float | None:
    """Metres from a spoken depth such as '2,000 feet', '3.8 km' or '200 metres' (None without a unit)."""
    m = DEPTH_TEXT.search(text or "")
    if not m:
        return None
    unit = m.group(2).lower()
    if unit.endswith("s") and unit != "feet":
        unit = unit[:-1]
    return float(m.group(1).replace(",", "")) * DEPTH_UNITS[unit]

# Per-channel looks, matching the still graphics (graphics.STYLE_BY_CHANNEL)
THEMES = {
    "casefile": {"bg": "#0E0C0B", "bg2": "#2A1E19", "ink": "#F2EDE4", "ink2": "#BFB3A5", "accent": "#C62F24",
                 "accent2": "#F06A55", "accent_ink": "#FF6B5A", "muted": "#5A4A42", "muted2": "#8A776C", "rule": "#7A6A60",
                 "sheen": "rgba(255,220,200,0.05)", "grain": "rgba(255,255,255,0.05)",
                 "title_font": "Bebas Neue", "num_font": "Bebas Neue", "label_font": "Oswald"},
    "scoreboard": {"bg": "#05080F", "bg2": "#15233D", "ink": "#F5F7FA", "ink2": "#AEB8C8", "accent": "#FFB000",
                   "accent2": "#FFD566", "accent_ink": "#FFC53D", "muted": "#34445E", "muted2": "#55688A", "rule": "#55688A",
                   "sheen": "rgba(255,200,80,0.05)", "grain": "rgba(255,255,255,0.04)",
                   "title_font": "Bebas Neue", "num_font": "Teko", "label_font": "Oswald"},
    "proof": {"bg": "#040B14", "bg2": "#0E2A3F", "ink": "#EEF6FF", "ink2": "#A9C1D6", "accent": "#22C55E",
              "accent2": "#86EFAC", "accent_ink": "#4ADE80", "muted": "#284459", "muted2": "#46708C", "rule": "#46708C",
              "sheen": "rgba(120,220,255,0.05)", "grain": "rgba(255,255,255,0.04)",
              "title_font": "Bebas Neue", "num_font": "Bebas Neue", "label_font": "Oswald"},
    "parchment": {"bg": "#C9AE7E", "bg2": "#F1E2BF", "ink": "#2E1C0E", "ink2": "#5C4128", "accent": "#8B1E1E",
                  "accent2": "#C2452D", "accent_ink": "#8B1E1E", "muted": "#9C8058", "muted2": "#BFA275", "rule": "#6E5232",
                  "sheen": "rgba(255,250,230,0.10)", "grain": "rgba(60,30,10,0.06)",
                  "title_font": "Rozha One", "num_font": "Rozha One", "label_font": "Mukta ExtraBold"},
    "poster": {"bg": "#12060A", "bg2": "#3A0D17", "ink": "#FFF4F0", "ink2": "#E2B9B9", "accent": "#E63946",
               "accent2": "#FF8A8A", "accent_ink": "#FF5A66", "muted": "#5E2A33", "muted2": "#8E4A55", "rule": "#8E4A55",
               "sheen": "rgba(255,180,190,0.05)", "grain": "rgba(255,255,255,0.05)",
               "title_font": "Khand", "num_font": "Anton", "label_font": "Mukta ExtraBold"},
}
HINDI_FONTS = {"title_font": "Khand", "num_font": "Khand", "label_font": "Mukta ExtraBold"}   # Devanagari-safe


def _lighter(hex_colour: str, k: float = 0.45) -> str:
    h = hex_colour.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return "#" + "".join(f"{round(c + (255 - c) * k):02X}" for c in (r, g, b))


def theme_for(channel: dict) -> dict:
    from .graphics import STYLE_BY_CHANNEL
    style = (channel.get("style") or {}).get("graphics") or STYLE_BY_CHANNEL.get(channel.get("id", ""), "casefile")
    th = dict(THEMES.get(style, THEMES["casefile"]))
    accent = (channel.get("style") or {}).get("highlight_color")
    if accent and style in ("scoreboard", "proof", "poster"):
        th["accent"] = th["accent_ink"] = accent
        th["accent2"] = _lighter(accent)
    if channel.get("language") == "hi" and style not in ("parchment",):
        th.update(HINDI_FONTS)
    return th


# ---------- the script's chart: checked before anything is drawn ----------
def _numbers(s: str) -> list[float]:
    return [float(x.replace(",", "")) for x in re.findall(r"\d[\d,]*(?:\.\d+)?", s or "")]


def check_chart(chart: dict | None, narration: str) -> tuple[dict | None, str]:
    """(clean chart, "") or (None, reason). Every number shown must be one the narrator says (on-screen numbers must
    match the spoken ones), compare/scale values must be positive, item counts stay readable."""
    if not isinstance(chart, dict):
        return None, "no chart data"
    kind = str(chart.get("type") or "").lower()
    if kind not in CHART_TYPES:
        return None, f"unknown chart type {kind!r}"
    items = [i for i in (chart.get("items") or []) if isinstance(i, dict) and str(i.get("label") or "").strip()]
    lo, hi = CHART_TYPES[kind]
    if not lo <= len(items) <= hi:
        return None, f"{kind} needs {lo}-{hi} items, got {len(items)}"
    spoken = set(_numbers(narration))
    if kind == "depth":                       # one place and its depth, as spoken (the metres come from the words)
        label, text = str(items[0]["label"]).strip()[:28], str(items[0].get("text") or "").strip()[:32]
        metres = depth_m(text)
        if metres is None:
            return None, f"{label}: the depth needs its unit as spoken (e.g. '2,000 feet')"
        missing = [n for n in _numbers(text) + _numbers(label) if n not in spoken]
        if missing:
            return None, f"{label}: {missing[0]:g} is shown but never said"
        if not 1 <= metres <= 11000:
            return None, f"{label}: {metres:,.0f} m is not an ocean depth"
        return {"type": "depth", "title": "", "items": [{"label": label, "text": text, "value": round(metres, 1)}],
                "marks": [{"label": a, "m": b} for a, b in DEPTH_MARKS]}, ""
    clean = []
    for it in items:
        label, text = str(it["label"]).strip()[:28], str(it.get("text") or "").strip()[:32]
        if kind == "timeline":
            shown = _numbers(label) + _numbers(text)
            value = 0.0
        else:
            try:
                value = float(str(it.get("value")).replace(",", ""))
            except (TypeError, ValueError):
                return None, f"{label}: value is not a number"
            if value <= 0:
                return None, f"{label}: value must be above 0"
            shown = _numbers(text) + _numbers(label)
        missing = [n for n in shown if n not in spoken]
        if missing:
            return None, f"{label}: {missing[0]:g} is shown but never said"
        clean.append({"label": label, "text": text, "value": value})
    if kind == "scale" and max(i["value"] for i in clean) / min(i["value"] for i in clean) > 60:
        return None, "sizes too far apart to draw to scale"
    return {"type": kind, "title": str(chart.get("title") or "").strip()[:40], "items": clean}, ""


# ---------- recording ----------
def _font_css(th: dict) -> str:
    out = []
    for fam in sorted({th["title_font"], th["num_font"], th["label_font"]}):
        data = base64.b64encode(Path(font_file(fam)).read_bytes()).decode()
        out.append(f'@font-face {{ font-family: "{fam}"; src: url(data:font/ttf;base64,{data}); }}')
    return "\n".join(out)


def _launch(pw):
    """Installed Chrome, then Edge, then Playwright's own build, then any older Playwright build on this PC (a
    Playwright update can leave its browser out of date)."""
    errors = []
    for chan in ("chrome", "msedge", None):
        try:
            return pw.chromium.launch(headless=True, **({"channel": chan} if chan else {}))
        except Exception as e:  # noqa: BLE001
            errors.append(str(e).splitlines()[0])
    home = Path.home() / "AppData" / "Local" / "ms-playwright"
    for exe in sorted(home.glob("chromium*/chrome-*win64/*.exe"), reverse=True) if home.exists() else []:
        if exe.stem in ("chrome", "chrome-headless-shell"):
            try:
                return pw.chromium.launch(headless=True, executable_path=str(exe))
            except Exception as e:  # noqa: BLE001
                errors.append(str(e).splitlines()[0])
    raise RuntimeError("no browser for scene recording: " + " | ".join(errors[:3]))


def render(template: str, data: dict, theme: dict, size: tuple[int, int], seconds: float, out_mp4: Path,
           fps: int = 30) -> Path:
    """Record SCENES/<template>.html for `seconds` at `size` into out_mp4 (H.264, yuv420p)."""
    from playwright.sync_api import sync_playwright
    w, h = size
    payload = dict(data, width=w, height=h, seconds=seconds, theme=theme)
    html = (SCENES / f"{template}.html").read_text(encoding="utf-8")
    html = html.replace("/*FONTS*/", _font_css(theme)).replace("/*DATA*/{}", json.dumps(payload, ensure_ascii=False))
    out_mp4 = Path(out_mp4).resolve()
    page_file = out_mp4.with_suffix(".html")
    page_file.write_text(html, encoding="utf-8")
    n = max(1, round(seconds * fps))
    proc = subprocess.Popen([ff.ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-y", "-f", "image2pipe",
                             "-framerate", str(fps), "-c:v", "mjpeg", "-i", "-", "-vf", "format=yuv420p",
                             "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-r", str(fps), str(out_mp4)],
                            stdin=subprocess.PIPE)
    try:
        with sync_playwright() as pw:
            browser = _launch(pw)
            try:
                page = browser.new_page(viewport={"width": w, "height": h})
                page.goto(page_file.as_uri())
                page.evaluate("window.ready")
                for k in range(n):
                    page.evaluate(f"window.draw({k / fps:.5f})")
                    proc.stdin.write(page.screenshot(type="jpeg", quality=93))
            finally:
                browser.close()
    finally:
        proc.stdin.close()
        code = proc.wait(timeout=300)
        page_file.unlink(missing_ok=True)
    if code != 0 or not out_mp4.exists():
        raise RuntimeError(f"scene recording failed ({template})")
    return out_mp4


def chart_video(channel: dict, chart: dict, size: tuple[int, int], seconds: float, out_mp4: Path,
                fps: int = 30) -> Path:
    """The animated chart for one story beat (chart already passed check_chart)."""
    return render("chart", chart, theme_for(channel), size, max(2.5, seconds), out_mp4, fps=fps)
