"""Colour sort: an oddly-satisfying Brain Snack format (owner 21 Nov, S3: "we need more self satisfactory content";
plan P3r step 3, the first picture-free Short made end to end with HyperFrames).

A grid of shuffled colour tiles sorts itself into a rainbow, one swap at a time: slow at first, faster and faster,
then the last three swaps slow down again ("wait for the last tile"). Every swap is a pluck that climbs with the
progress; the finished rainbow gets a chord and a ripple; then the tiles fly back to the start, so the video loops.

Drawn as HTML + CSS keyframes (no GSAP, no pictures, no AI) and rendered by HyperFrames (Apache-2.0) on the PC; the
sound is our own synth (engine/snack/audio.py). The same spec always gives the same video."""
from __future__ import annotations

import colorsys
import random
from pathlib import Path

from . import audio as au

W, H = 1080, 1920
LAYOUTS = [(6, 9), (7, 11), (8, 13)]
TOP, BOTTOM, SIDE, GAP = 420, 150, 70, 12
INTRO_S, WAVE_S, BACK_S = 0.55, 1.4, 0.7
FAST, SLOW = 0.40, 0.085                        # first and fastest swap length (s)
SUSPENSE = (0.38, 0.55, 0.8)                    # the last three swaps


def _tile_size(cols: int, rows: int) -> int:
    return int(min((W - 2 * SIDE - (cols - 1) * GAP) / cols, (H - TOP - BOTTOM - (rows - 1) * GAP) / rows))


def _xy(pos: int, cols: int, rows: int) -> tuple[float, float]:
    s = _tile_size(cols, rows)
    grid_w, grid_h = cols * s + (cols - 1) * GAP, rows * s + (rows - 1) * GAP
    x0, y0 = (W - grid_w) / 2, TOP + (H - TOP - BOTTOM - grid_h) / 2
    r, c = divmod(pos, cols)
    return round(x0 + c * (s + GAP), 1), round(y0 + r * (s + GAP), 1)


def colour(k: int, n: int, hue_shift: float) -> str:
    """Tile k of n in the finished rainbow (k = its sorted position)."""
    r, g, b = colorsys.hls_to_rgb((hue_shift + 0.86 * k / max(1, n - 1)) % 1.0, 0.58, 0.82)
    return f"#{int(r * 255):02x}{int(g * 255):02x}{int(b * 255):02x}"


def plan(spec: dict) -> dict:
    """Swap sequence and timings. order[p] = the tile standing at position p; tile k belongs at position k."""
    rng = random.Random(spec["seed"])
    cols, rows = LAYOUTS[int(spec.get("layout", 0)) % len(LAYOUTS)]
    n = cols * rows
    order = list(range(n))
    while True:
        rng.shuffle(order)
        if sum(1 for p, k in enumerate(order) if p == k) <= n // 12:        # almost nothing already in place
            break
    start = list(order)
    swaps = []                                       # (position a, position b): selection by position
    cur = list(order)
    where = {k: p for p, k in enumerate(cur)}
    for p in range(n):
        if cur[p] != p:
            q = where[p]
            swaps.append((p, q))
            cur[p], cur[q] = cur[q], cur[p]
            where[cur[q]], where[cur[p]] = q, p
    assert cur == list(range(n))
    m = len(swaps)
    lengths = []
    for i in range(m):
        if i >= m - len(SUSPENSE):
            lengths.append(SUSPENSE[i - (m - len(SUSPENSE))])
        else:
            lengths.append(FAST * (SLOW / FAST) ** (i / max(1, m - len(SUSPENSE) - 1)))
    moves, t = [], INTRO_S
    for (a, b), d in zip(swaps, lengths):
        d = round(d, 3)                              # rounded first, so one move ends exactly where the next starts
        moves.append({"t": round(t, 3), "d": d, "a": a, "b": b})
        t = round(t + d, 3)
    t_done = round(t, 3)
    total = round(t_done + WAVE_S + BACK_S, 3)
    return {"cols": cols, "rows": rows, "n": n, "start": start, "moves": moves, "t_done": t_done, "total": total,
            "hue_shift": float(spec.get("hue_shift", 0.0)), "size": _tile_size(cols, rows)}


def tracks(p: dict) -> dict[int, list[tuple[float, float, float, float]]]:
    """Per tile: keyframes (time, x, y, scale), starting and ending at its start position (the loop)."""
    cols, rows, n = p["cols"], p["rows"], p["n"]
    pos = {k: i for i, k in enumerate(p["start"])}           # tile -> position
    keys = {k: [(0.0, *_xy(pos[k], cols, rows), 1.0)] for k in range(n)}
    for mv in p["moves"]:
        ka = next(k for k, v in pos.items() if v == mv["a"])
        kb = next(k for k, v in pos.items() if v == mv["b"])
        for k, src, dst in ((ka, mv["a"], mv["b"]), (kb, mv["b"], mv["a"])):
            keys[k].append((mv["t"], *_xy(src, cols, rows), 1.0))
            keys[k].append((round(mv["t"] + mv["d"] * 0.5, 3), *_mid(src, dst, cols, rows), 1.12))
            keys[k].append((round(mv["t"] + mv["d"], 3), *_xy(dst, cols, rows), 1.0))
        pos[ka], pos[kb] = mv["b"], mv["a"]
    for k in range(n):                                       # ripple across the finished rainbow
        r, c = divmod(k, cols)
        t0 = round(p["t_done"] + 0.05 + 0.6 * (r + c) / max(1, rows + cols - 2), 3)
        x, y = _xy(k, cols, rows)
        keys[k] += [(t0, x, y, 1.0), (round(t0 + 0.18, 3), x, y, 1.16), (round(t0 + 0.4, 3), x, y, 1.0)]
        back = round(p["total"] - BACK_S, 3)
        if keys[k][-1][0] < back:
            keys[k].append((back, x, y, 1.0))
        keys[k].append((p["total"], *_xy(p["start"].index(k), cols, rows), 1.0))
    return keys


def _mid(a: int, b: int, cols: int, rows: int) -> tuple[float, float]:
    (xa, ya), (xb, yb) = _xy(a, cols, rows), _xy(b, cols, rows)
    return round((xa + xb) / 2, 1), round((ya + yb) / 2 - 18, 1)     # a small hop over the grid


def html(p: dict, hook: str = "Watch it sort itself") -> str:
    total, s = p["total"], p["size"]
    css, tiles = [], []
    for k, keys in tracks(p).items():
        frames, last = [], -1.0
        for t, x, y, sc in keys:
            pct = round(100.0 * t / total, 4)
            if pct <= last:                                     # keyframes must move forward in time
                pct = round(last + 0.0001, 4)
            last = pct
            frames.append(f"{pct}%{{transform:translate({x}px,{y}px) scale({sc});"
                          "animation-timing-function:cubic-bezier(.45,0,.25,1)}")
        css.append(f"@keyframes k{k}{{{''.join(frames)}}}")
        tiles.append(f'<div id="t{k}" class="clip tile" data-start="0" data-duration="{total}" '
                     f'style="background:{colour(k, p["n"], p["hue_shift"])};animation:k{k} {total}s linear 0s 1 both">'
                     "</div>")
    m = len(p["moves"])
    bar = " ".join(f"{round(100.0 * (mv['t'] + mv['d']) / total, 4)}%{{width:{round(100.0 * (i + 1) / m, 2)}%}}"
                   for i, mv in enumerate(p["moves"]))
    done_pct = round(100.0 * p["t_done"] / total, 4)
    back_pct = round(100.0 * (total - BACK_S) / total, 4)            # loop: the last frame = the first frame
    gone_pct = round(100.0 * (total - BACK_S / 2) / total, 4)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <style>
    html, body {{ margin: 0; background: #101321; }}
    #root {{ position: relative; width: {W}px; height: {H}px; overflow: hidden; background: #101321; }}
    #bg {{ position: absolute; inset: 0; background: radial-gradient(circle at 50% 55%, #22284a 0%, #101321 70%); }}
    .tile {{ position: absolute; left: 0; top: 0; width: {s}px; height: {s}px; border-radius: {int(s * 0.2)}px;
             box-shadow: inset 0 -{max(3, s // 18)}px 0 rgba(0,0,0,.18), 0 6px 14px rgba(0,0,0,.35); }}
    #hook {{ position: absolute; left: 60px; right: 60px; top: 150px; margin: 0; text-align: center; color: #fff;
             font-family: "Montserrat", sans-serif; font-weight: 900; font-size: 92px; line-height: 1.05; }}
    /* the hook shows from frame 0 (readable at once) and stays: the last frame equals the first (loop) */
    #track {{ position: absolute; left: 140px; right: 140px; bottom: 70px; height: 16px; border-radius: 8px;
              background: rgba(255,255,255,.12); overflow: hidden; }}
    #fill {{ height: 100%; width: 0; border-radius: 8px; background: linear-gradient(90deg,#ff5e7e,#ffd23f,#3ee08f,#4cc3ff,#a46bff);
             animation: bar {total}s steps(1, end) 0s 1 both; }}
    #done {{ position: absolute; left: 0; right: 0; top: 300px; text-align: center; color: #ffd23f; margin: 0;
             font-family: "Montserrat", sans-serif; font-weight: 900; font-size: 64px;
             animation: pop {total}s linear 0s 1 both; }}
    @keyframes bar {{ 0%{{width:0%}} {bar} {back_pct}%{{width:100%;animation-timing-function:linear}} 100%{{width:0%}} }}
    @keyframes pop {{ 0%{{opacity:0;transform:scale(.6)}} {done_pct}%{{opacity:0;transform:scale(.6)}}
                     {round(done_pct + 2.5, 4)}%{{opacity:1;transform:scale(1.08)}} {round(done_pct + 4.5, 4)}%{{opacity:1;transform:scale(1)}}
                     {back_pct}%{{opacity:1;transform:scale(1)}} {gone_pct}%{{opacity:0;transform:scale(1)}}
                     100%{{opacity:0;transform:scale(.6)}} }}
    {''.join(css)}
  </style>
</head>
<body>
  <div id="root" data-composition-id="main" data-no-timeline data-start="0" data-duration="{total}"
       data-width="{W}" data-height="{H}">
    <div id="bg" class="clip" data-start="0" data-duration="{total}"></div>
    <h1 id="hook" class="clip" data-start="0" data-duration="{total}">{hook}</h1>
    <p id="done" class="clip" data-start="0" data-duration="{total}">100% sorted</p>
    {''.join(tiles)}
    <div id="track" class="clip" data-start="0" data-duration="{total}"><div id="fill"></div></div>
  </div>
</body>
</html>
"""


def render(spec: dict, work: Path, log=print, hf=None) -> dict:
    """Silent video at work/anim.mp4 (HyperFrames); returns the info the soundtrack and the maker need."""
    if hf is None:
        from ..media import hyperframes as hf
    p = plan(spec)
    project = hf.write_project(work / "hf", html(p, spec.get("hook") or "Watch it sort itself"))
    hf.render(project, work / "anim.mp4", log=log)
    log(f"  colour sort: {p['n']} tiles, {len(p['moves'])} swaps, sorted at {p['t_done']}s of {p['total']}s")
    return {"total": p["total"], "t_done": p["t_done"], "swaps": len(p["moves"]), "tiles": p["n"],
            "moves": [(mv["t"], (i + 1) / len(p["moves"])) for i, mv in enumerate(p["moves"])],
            "cover_at": round(p["t_done"] + 0.9, 2), "ai_voice": False}


def soundtrack(info: dict, spec: dict):
    """A pluck per swap climbing the pentatonic scale with the progress; chord + sweep when the rainbow is done;
    a whoosh as the tiles fly back (the loop)."""
    total = info["total"]
    scale = au.pentatonic(60, 96)
    events = [(t, scale[min(len(scale) - 1, int(frac * (len(scale) - 1)))], 0.5 + 0.3 * frac)
              for t, frac in info["moves"]]
    mix = au.render_notes(events, total, spec.get("instrument", "marimba"), min_gap=1 / 24, dur=0.5)
    at = info["t_done"]
    au.place(mix, au.sweep_up(0.5), max(0.0, at - 0.4), 0.4)
    au.place(mix, au.chord([60, 64, 67, 72, 76], 1.6, "bell", 0.85), at, 0.7)
    au.place(mix, au.whoosh(0.5), max(0.0, total - BACK_S), 0.5)
    mix += au.pad(total, root=48, vol=0.05)[: len(mix)]
    return mix
