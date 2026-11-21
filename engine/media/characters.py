"""Original characters (plan P3r characters workstream; owner 21 Nov: "introduce some humans, animals, real world
stuff"; "is there anything that can build us the characters ... or our system can build this on its own").

Faces come from DiceBear (dicebear/dicebear, MIT code). Each art style has its own licence; the package metadata is
read at EVERY generation and only CC0 1.0 / CC BY 4.0 / MIT art is accepted (Avataaars/Bottts carry a custom licence
and are refused). config/characters.yaml fixes the seed and every option of a character, so it looks the same in
every episode. DiceBear runs in Node (installed pinned in D:/tools_hh/dicebear, @dicebear/core + collection 9.4.2);
the SVGs become transparent PNGs in the Chromium we already use for charts (Playwright), cached in
data/cache/characters/<id>/<height>/<mouth>_<eyes>_<brows>.png."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import yaml

from ..config import ROOT

BIBLE = ROOT / "config" / "characters.yaml"
CACHE = ROOT / "data" / "cache" / "characters"
ALLOWED = {"CC0 1.0", "CC BY 4.0", "MIT"}
SCRIPT = "hh_faces.mjs"
JS = r"""// HookHouse: DiceBear faces for one character (stdin JSON -> stdout JSON). Written by engine/media/characters.py.
import { createAvatar } from "@dicebear/core";
import * as collection from "@dicebear/collection";

let raw = "";
process.stdin.on("data", (d) => (raw += d));
process.stdin.on("end", () => {
  const job = JSON.parse(raw);
  const style = collection[job.style];
  if (!style) { console.log(JSON.stringify({ error: "unknown style " + job.style })); return; }
  const meta = style.meta || {};
  const faces = {};
  for (const st of job.states) {
    const opts = { ...job.options, seed: job.seed, mouth: [st.mouth], eyes: [st.eyes], eyebrows: [st.eyebrows] };
    faces[st.key] = createAvatar(style, opts).toString();
  }
  console.log(JSON.stringify({ license: (meta.license && meta.license.name) || "", creator: meta.creator || "",
                               title: meta.title || "", faces }));
});
"""


class CharacterError(RuntimeError):
    """A character could not be made (missing tools, unknown id, or a licence we may not use)."""


def dicebear_dir() -> Path:
    return Path(os.environ.get("HH_DICEBEAR") or "D:/tools_hh/dicebear")


def available() -> bool:
    """DiceBear (Node) + Playwright (the browser that turns SVGs into PNGs) are on this machine."""
    import importlib.util
    return (bool(shutil.which("node")) and (dicebear_dir() / "node_modules" / "@dicebear" / "core").exists()
            and importlib.util.find_spec("playwright") is not None)


def bible() -> dict:
    return yaml.safe_load(BIBLE.read_text(encoding="utf-8")) or {}


def character(cid: str) -> dict:
    ch = (bible().get("characters") or {}).get(cid)
    if not ch:
        raise CharacterError(f"no character '{cid}' in config/characters.yaml")
    return dict(ch, id=cid)


def credit() -> str:
    return str(bible().get("credit") or "")


def key(state: tuple[str, str, str]) -> str:
    return "_".join(state)


def _node_faces(ch: dict, states: list[tuple[str, str, str]], run=subprocess.run) -> dict[str, str]:
    """SVG per state from DiceBear; refuses any art licence outside ALLOWED."""
    d = dicebear_dir()
    script = d / SCRIPT
    if not script.exists() or script.read_text(encoding="utf-8") != JS:
        script.write_text(JS, encoding="utf-8")
    job = {"style": ch["style"], "seed": ch.get("seed") or ch["id"], "options": ch.get("options") or {},
           "states": [{"key": key(s), "mouth": s[0], "eyes": s[1], "eyebrows": s[2]} for s in states]}
    r = run(["node", SCRIPT], cwd=str(d), input=json.dumps(job), capture_output=True, text=True, timeout=120,
            encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise CharacterError(f"DiceBear failed: {(r.stderr or r.stdout or '')[-300:]}")
    out = json.loads(r.stdout or "{}")
    if out.get("error"):
        raise CharacterError(out["error"])
    if out.get("license") not in ALLOWED:
        raise CharacterError(f"style {ch['style']} has licence '{out.get('license')}': not allowed (owner rule)")
    return out["faces"]


def rasterize(svgs: dict[str, str], height: int) -> dict[str, bytes]:
    """Transparent PNGs, height x height px, in headless Chromium (the chart recorder's browser)."""
    import base64

    from playwright.sync_api import sync_playwright

    from .html_scene import _launch
    out = {}
    with sync_playwright() as pw:
        browser = _launch(pw)
        try:
            page = browser.new_page(viewport={"width": height, "height": height})
            for k, svg in svgs.items():
                uri = "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode("ascii")
                page.set_content("<html><body style='margin:0;background:transparent'>"
                                 f"<img id='a' src='{uri}' style='display:block;width:{height}px;height:{height}px'>"
                                 "</body></html>")
                page.wait_for_function("document.getElementById('a').complete")
                out[k] = page.locator("#a").screenshot(omit_background=True)
        finally:
            browser.close()
    return out


def _sig(ch: dict) -> str:
    """Cache key part: a changed option makes new faces (never a stale look)."""
    return hashlib.sha1(json.dumps([ch.get("style"), ch.get("seed"), ch.get("options")], sort_keys=True)
                        .encode("utf-8")).hexdigest()[:10]


def face_files(cid: str, states: list[tuple[str, str, str]], height: int, node=_node_faces,
               raster=rasterize) -> dict[tuple[str, str, str], Path]:
    """PNG path per state; makes the missing ones in one DiceBear call + one browser session."""
    ch = character(cid)
    folder = CACHE / cid / f"{_sig(ch)}_{height}"
    want = {s: folder / f"{key(s)}.png" for s in states}
    missing = [s for s, p in want.items() if not p.exists()]
    if missing:
        if node is _node_faces and not available():
            raise CharacterError("DiceBear is not installed on this machine (D:/tools_hh/dicebear)")
        svgs = node(ch, missing)
        pngs = raster({key(s): svgs[key(s)] for s in missing}, height)
        folder.mkdir(parents=True, exist_ok=True)
        for s in missing:
            want[s].write_bytes(pngs[key(s)])
    return want
