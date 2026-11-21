"""HyperFrames (heygen-com/hyperframes, Apache-2.0, credited): HTML + CSS rendered frame by frame into a deterministic
MP4 on the PC. Plan P3r creation workstream (standard S9): picture-free formats (quiz, countdown, kinetic type, number
reveals), character puppet scenes and title cards that need no AI picture quota at all.

Rules for our compositions (checked by `lint_html`, tested 21 Nov on the PC):
- CSS @keyframes / WAAPI only, never GSAP (GSAP's own licence is not on the owner's list); the root carries
  `data-no-timeline` so the renderer does not wait 45 s for a GSAP timeline;
- every timed element has class "clip", data-start and data-duration; no Date.now(), unseeded random, timers or network;
- the root declares data-width, data-height and data-duration; the output is checked against them (ffprobe).

The CLI is installed pinned (D:/tools_hh/hyperframes, `npm i hyperframes@0.9.77`, telemetry disabled); override the path
with HH_HYPERFRAMES. Renders run at below-normal priority so the PC stays usable; a 3 s 1080x1920 test took 20 s."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

VERSION = "0.9.77"
DEFAULT_CLI = Path("D:/tools_hh/hyperframes/node_modules/.bin/hyperframes.cmd")
BELOW_NORMAL = 0x00004000 | 0x08000000            # BELOW_NORMAL_PRIORITY_CLASS | CREATE_NO_WINDOW (Windows)
ROOT_TAG = re.compile(r"<[^>]*\bdata-composition-id=\"main\"[^>]*>", re.S)
FORBIDDEN = re.compile(r"\bgsap\.|<script[^>]*gsap|Date\.now\(|Math\.random\(|setTimeout\(|setInterval\(|fetch\("
                       r"|XMLHttpRequest|repeat:\s*-1|animation[^;{}<>]*\binfinite\b", re.I)   # CSS only, not words


class RenderError(RuntimeError):
    """The render failed or its output does not match the composition."""


def cli() -> Path | None:
    p = Path(os.environ.get("HH_HYPERFRAMES") or DEFAULT_CLI)
    return p if p.exists() else None


def available() -> bool:
    return cli() is not None


def spec(index_html: str) -> dict:
    """{"w", "h", "dur"} from the root composition element (data-width / data-height / data-duration)."""
    m = ROOT_TAG.search(index_html or "")
    if not m:
        raise RenderError("no root composition (data-composition-id=\"main\")")
    tag = m.group(0)

    def num(name: str) -> float:
        a = re.search(rf'\bdata-{name}="([\d.]+)"', tag)
        if not a:
            raise RenderError(f"the root composition has no data-{name}")
        return float(a.group(1))
    return {"w": int(num("width")), "h": int(num("height")), "dur": num("duration")}


def lint_html(index_html: str) -> list[str]:
    """Our own house rules, checked before the CLI runs (cheap, no browser)."""
    problems = []
    try:
        spec(index_html)
    except RenderError as e:
        problems.append(str(e))
    m = ROOT_TAG.search(index_html or "")
    if m and "data-no-timeline" not in m.group(0):
        problems.append("root lacks data-no-timeline (CSS-only compositions; otherwise every render waits 45 s)")
    for hit in sorted({h.group(0) for h in FORBIDDEN.finditer(index_html or "")}):
        problems.append(f"not deterministic or not allowed in our compositions: {hit}")
    for el in re.finditer(r"<[^>]*\bclass=\"[^\"]*\bclip\b[^\"]*\"[^>]*>", index_html or ""):
        if "data-start=" not in el.group(0) or "data-duration=" not in el.group(0):
            problems.append(f"timed element without data-start/data-duration: {el.group(0)[:60]}")
    return problems


def write_project(work: Path, index_html: str, assets: dict[str, Path] | None = None) -> Path:
    """A HyperFrames project folder: index.html + assets/<name> copies. Returns the folder."""
    problems = lint_html(index_html)
    if problems:
        raise RenderError("composition breaks the house rules: " + "; ".join(problems[:4]))
    work.mkdir(parents=True, exist_ok=True)
    (work / "index.html").write_text(index_html, encoding="utf-8")
    if assets:
        (work / "assets").mkdir(exist_ok=True)
        for name, src in assets.items():
            data = Path(src).read_bytes()
            (work / "assets" / name).write_bytes(data)
    return work


def _probe(video: Path) -> dict:
    from ..reach_gate import probe
    return probe(video)


def render(project: Path, out_mp4: Path, quality: str = "looks", timeout_s: int = 900, log=print,
           run=subprocess.run, probe=_probe) -> Path:
    """Render project/index.html to out_mp4 and check the result against the composition. Raises RenderError."""
    exe = cli()
    if exe is None:
        raise RenderError("HyperFrames is not installed on this machine (D:/tools_hh/hyperframes)")
    want = spec((project / "index.html").read_text(encoding="utf-8"))
    out_mp4 = Path(out_mp4).resolve()
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    if out_mp4.exists():
        out_mp4.unlink()
    cmd = [str(exe), "render", "--quality", quality, "-o", str(out_mp4)]
    kw = {"cwd": str(project), "capture_output": True, "text": True, "timeout": timeout_s,
          "encoding": "utf-8", "errors": "replace"}
    if sys.platform == "win32":
        kw["creationflags"] = BELOW_NORMAL
    try:
        r = run(cmd, **kw)
    except subprocess.TimeoutExpired as e:
        raise RenderError(f"render took longer than {timeout_s}s") from e
    tail = " | ".join([ln.strip() for ln in (r.stdout or "").splitlines() + (r.stderr or "").splitlines()
                       if ln.strip()][-4:])
    if r.returncode != 0:
        raise RenderError(f"render failed (exit {r.returncode}): {tail[:300]}")
    if not out_mp4.exists() or out_mp4.stat().st_size < 1024:
        raise RenderError(f"render wrote no video ({tail[:200]})")
    got = probe(out_mp4)
    if (int(got.get("w") or 0), int(got.get("h") or 0)) != (want["w"], want["h"]):
        raise RenderError(f"rendered {got.get('w')}x{got.get('h')}, the composition is {want['w']}x{want['h']}")
    if abs(float(got.get("dur") or 0) - want["dur"]) > 0.15:
        raise RenderError(f"rendered {got.get('dur')}s, the composition is {want['dur']}s")
    m = re.search(r"rendered in ([\d.]+)s", r.stdout or "")
    log(f"  HyperFrames: {out_mp4.name} {want['w']}x{want['h']} {want['dur']:g}s"
        + (f" in {m.group(1)}s" if m else ""))
    return out_mp4


def card_html(lines: list[tuple[str, float, float]], size: tuple[int, int] = (1080, 1920), dur: float | None = None,
              theme: dict | None = None) -> str:
    """The smallest useful composition: kinetic text cards (text, start, duration) that rise in and settle, on the
    channel's colours. Used as the smoke test of the toolchain and as a title-card block for other formats."""
    th = {"bg": "#0f1226", "bg2": "#2b3a8f", "ink": "#ffffff", "accent": "#ffcc33", "font": "Montserrat"}
    th.update(theme or {})
    w, h = size
    total = dur if dur is not None else max((s + d for _, s, d in lines), default=1.0)
    esc = lambda s: (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;"))  # noqa: E731
    cards = "\n".join(
        f'    <h1 id="card{i}" class="clip card" data-start="{s:.3f}" data-duration="{d:.3f}" '
        f'data-track-index="1">{esc(t)}</h1>' for i, (t, s, d) in enumerate(lines))
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <style>
    html, body {{ margin: 0; background: {th['bg']}; }}
    #root {{ position: relative; width: {w}px; height: {h}px; overflow: hidden; background: {th['bg']}; }}
    #bg {{ position: absolute; inset: 0;
          background: radial-gradient(circle at 50% 40%, {th['bg2']} 0%, {th['bg']} 72%); }}
    .card {{ position: absolute; left: {int(w * 0.08)}px; right: {int(w * 0.08)}px; top: {int(h * 0.36)}px; margin: 0;
            font-family: "{th['font']}", sans-serif; font-weight: 900; font-size: {int(w * 0.1)}px; line-height: 1.05;
            color: {th['ink']}; text-align: center; animation: rise 0.45s cubic-bezier(.2,.9,.2,1.15) 0s 1 both; }}
    .card::after {{ content: ""; display: block; margin: {int(w * 0.03)}px auto 0; height: {int(w * 0.012)}px;
                   width: 0; background: {th['accent']}; animation: bar 0.5s ease-out 0.25s 1 both; }}
    @keyframes rise {{ from {{ opacity: 0; transform: translateY({int(h * 0.04)}px) scale(.92); }}
                      to {{ opacity: 1; transform: none; }} }}
    @keyframes bar {{ from {{ width: 0; }} to {{ width: 40%; }} }}
  </style>
</head>
<body>
  <div id="root" data-composition-id="main" data-no-timeline data-start="0" data-duration="{total:.3f}"
       data-width="{w}" data-height="{h}">
    <div id="bg" class="clip" data-start="0" data-duration="{total:.3f}" data-track-index="0"></div>
{cards}
  </div>
</body>
</html>
"""


def smoke(work: Path, log=print) -> Path:
    """Render a 2-card, 3 s test video (toolchain check on a PC)."""
    html = card_html([("HookHouse", 0.0, 1.5), ("motion check", 1.5, 1.5)], dur=3.0)
    return render(write_project(work, html), work / "smoke.mp4", quality="draft", log=log)


if __name__ == "__main__":                            # python -m engine.media.hyperframes <work dir>
    out = smoke(Path(sys.argv[1] if len(sys.argv) > 1 else "data/tmp/hf_smoke"))
    print(json.dumps({"ok": True, "video": str(out)}))
