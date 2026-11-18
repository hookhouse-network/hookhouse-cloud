"""Format 2, "Multiply & Reveal": one ball inside an original silhouette; every wall hit clones it. At 100%
a shockwave recolours the balls into a picture, then everything collapses back to one ball. The last
frame equals the first, so the Short loops seamlessly. 15-20 s."""
from __future__ import annotations

import math

import cv2
import numpy as np
from numba import njit

from . import audio as au
from .canvas import W, H, add_glow, blit, bgr, hue_bgr, radial_bg, text_sprite

CX, CY = 540, 960
COLORS = ["#FF3B6B", "#FFC531", "#3BFF8A", "#31C8FF", "#B44CFF", "#FF7A1A"]
SHAPES = ["heart", "star", "blob", "brain", "donut", "rocket", "bolt", "drop", "letter"]


# ---------- silhouettes and their reveal art (all drawn by code) ----------

def _poly_mask(pts: np.ndarray) -> np.ndarray:
    m = np.zeros((H, W), np.uint8)
    cv2.fillPoly(m, [pts.astype(np.int32)], 255, cv2.LINE_AA)
    return m


def _smooth(m: np.ndarray, k: int = 31) -> np.ndarray:
    return (cv2.GaussianBlur(m, (k, k), 0) > 127).astype(np.uint8) * 255


def silhouette(shape: str, letter: str = "B") -> np.ndarray:
    t = np.linspace(0, 2 * np.pi, 400)
    if shape == "heart":
        x = 16 * np.sin(t) ** 3
        y = -(13 * np.cos(t) - 5 * np.cos(2 * t) - 2 * np.cos(3 * t) - np.cos(4 * t))
        m = _poly_mask(np.stack([CX + x * 28, CY + y * 28 - 40], 1))
    elif shape == "star":
        ang = np.linspace(-np.pi / 2, 1.5 * np.pi, 11)[:-1]
        rad = np.where(np.arange(10) % 2 == 0, 500, 215)
        m = _smooth(_poly_mask(np.stack([CX + rad * np.cos(ang), CY + 40 + rad * np.sin(ang)], 1)), 41)
    elif shape == "blob":                                   # our mascot's body silhouette
        m = np.zeros((H, W), np.uint8)
        cv2.ellipse(m, (CX, CY + 40), (440, 470), 0, 0, 360, 255, -1, cv2.LINE_AA)
        cv2.ellipse(m, (CX - 230, CY + 470), (120, 70), 0, 0, 360, 255, -1, cv2.LINE_AA)
        cv2.ellipse(m, (CX + 230, CY + 470), (120, 70), 0, 0, 360, 255, -1, cv2.LINE_AA)
        m = _smooth(m)
    elif shape == "brain":
        m = np.zeros((H, W), np.uint8)
        for (dx, dy, r) in [(-230, -120, 250), (230, -120, 250), (-300, 130, 230), (300, 130, 230),
                            (0, -230, 230), (0, 160, 260), (-120, 320, 160), (140, 330, 150)]:
            cv2.circle(m, (CX + dx, CY + dy), r, 255, -1, cv2.LINE_AA)
        m = _smooth(m, 51)
    elif shape == "donut":
        m = np.zeros((H, W), np.uint8)
        cv2.circle(m, (CX, CY), 470, 255, -1, cv2.LINE_AA)
        cv2.circle(m, (CX, CY), 170, 0, -1, cv2.LINE_AA)
    elif shape == "rocket":
        body = np.array([[CX, CY - 560], [CX + 170, CY - 300], [CX + 170, CY + 300], [CX + 360, CY + 520],
                         [CX + 150, CY + 470], [CX + 100, CY + 560], [CX - 100, CY + 560], [CX - 150, CY + 470],
                         [CX - 360, CY + 520], [CX - 170, CY + 300], [CX - 170, CY - 300]])
        m = _smooth(_poly_mask(body), 41)
    elif shape == "bolt":
        pts = np.array([[CX + 120, CY - 560], [CX - 330, CY + 60], [CX - 40, CY + 60], [CX - 160, CY + 560],
                        [CX + 330, CY - 80], [CX + 40, CY - 80], [CX + 200, CY - 560]])
        m = _smooth(_poly_mask(pts), 35)
    elif shape == "drop":
        y = np.linspace(-1, 1, 400)
        x = np.sqrt(np.clip(1 - y ** 2, 0, 1)) * (1 + y) / 2 * 1.9
        pts = np.concatenate([np.stack([CX + x * 430, CY + y * 560], 1), np.stack([CX - x[::-1] * 430, CY + y[::-1] * 560], 1)])
        m = _smooth(_poly_mask(pts), 31)
    else:                                                    # a big letter / digit
        from .canvas import text_sprite as ts
        spr = ts(letter, "Poppins Black", 1250, stroke=0, shadow=0)
        a = spr[..., 3]
        m = np.zeros((H, W), np.uint8)
        hh, ww = a.shape
        s = min(980 / ww, 1180 / hh)
        a = cv2.resize(a, (int(ww * s), int(hh * s)))
        y0, x0 = CY - a.shape[0] // 2, CX - a.shape[1] // 2
        m[y0:y0 + a.shape[0], x0:x0 + a.shape[1]] = a
        m = (m > 127).astype(np.uint8) * 255
    return m


def reveal_art(shape: str, mask: np.ndarray, seed: int) -> np.ndarray:
    """The picture the balls turn into (BGR, full frame; only inside the mask matters)."""
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    art = np.zeros((H, W, 3), np.uint8)
    if shape == "heart":
        g = ((yy - (CY - 400)) / 900).clip(0, 1)[..., None]
        art[:] = (np.array(bgr("#FF5C8A")) * (1 - g) + np.array(bgr("#C2185B")) * g).astype(np.uint8)
        cv2.ellipse(art, (CX - 200, CY - 250), (90, 140), -30, 0, 360, bgr("#FFD1E0"), -1, cv2.LINE_AA)
    elif shape == "star":
        d = np.hypot(xx - CX, yy - CY - 40)[..., None] / 520
        art[:] = (np.array(bgr("#FFF59D")) * (1 - d.clip(0, 1)) + np.array(bgr("#FFB300")) * d.clip(0, 1)).astype(np.uint8)
        for ex in (-110, 110):                               # a happy star face
            cv2.circle(art, (CX + ex, CY - 10), 38, (40, 30, 30), -1, cv2.LINE_AA)
        cv2.ellipse(art, (CX, CY + 80), (120, 70), 0, 0, 180, (40, 30, 30), 18, cv2.LINE_AA)
    elif shape == "blob":
        art[:] = bgr("#FF7AB8")
        for ex in (-150, 150):
            cv2.circle(art, (CX + ex, CY - 60), 95, (255, 255, 255), -1, cv2.LINE_AA)
            cv2.circle(art, (CX + ex + 15, CY - 50), 48, (40, 30, 30), -1, cv2.LINE_AA)
        cv2.ellipse(art, (CX, CY + 150), (150, 110), 0, 0, 180, bgr("#B0306A"), -1, cv2.LINE_AA)
    elif shape == "brain":
        art[:] = bgr("#FF8FB1")
        for _ in range(26):
            c = (int(CX + rng.uniform(-420, 420)), int(CY + rng.uniform(-420, 420)))
            cv2.ellipse(art, c, (int(rng.uniform(40, 110)), int(rng.uniform(20, 50))), float(rng.uniform(0, 180)),
                        0, 270, bgr("#D9467A"), 14, cv2.LINE_AA)
        cv2.line(art, (CX, CY - 470), (CX, CY + 420), bgr("#C2185B"), 18, cv2.LINE_AA)
    elif shape == "donut":
        art[:] = bgr("#E0A060")
        icing = np.zeros((H, W), np.uint8)
        cv2.circle(icing, (CX, CY), 430, 255, -1, cv2.LINE_AA)
        cv2.circle(icing, (CX, CY), 210, 0, -1, cv2.LINE_AA)
        art[icing > 0] = bgr("#FF69B4")
        for _ in range(140):
            a, r = rng.uniform(0, 2 * np.pi), rng.uniform(230, 410)
            p = (int(CX + r * np.cos(a)), int(CY + r * np.sin(a)))
            q = (int(p[0] + 22 * np.cos(a * 3)), int(p[1] + 22 * np.sin(a * 3)))
            cv2.line(art, p, q, bgr(rng.choice(COLORS)), 12, cv2.LINE_AA)
    elif shape == "rocket":
        art[:] = bgr("#ECEFF1")
        cv2.circle(art, (CX, CY - 160), 110, bgr("#4FC3F7"), -1, cv2.LINE_AA)
        cv2.circle(art, (CX, CY - 160), 110, bgr("#37474F"), 22, cv2.LINE_AA)
        art[(yy > CY + 300)] = bgr("#E53935")
        art[(yy < CY - 380)] = bgr("#E53935")
    elif shape == "bolt":
        g = ((yy - (CY - 560)) / 1120).clip(0, 1)[..., None]
        art[:] = (np.array(bgr("#FFF176")) * (1 - g) + np.array(bgr("#FF9800")) * g).astype(np.uint8)
    elif shape == "drop":
        g = ((yy - (CY - 560)) / 1120).clip(0, 1)[..., None]
        art[:] = (np.array(bgr("#80DEEA")) * (1 - g) + np.array(bgr("#1565C0")) * g).astype(np.uint8)
        cv2.ellipse(art, (CX - 140, CY + 120), (60, 130), 20, 0, 360, (255, 255, 255), -1, cv2.LINE_AA)
    else:
        hue = ((xx + yy) / (W + H) * 1.2 + rng.random()) % 1.0
        hsv = np.stack([hue * 180, np.full_like(hue, 230), np.full_like(hue, 255)], -1).astype(np.uint8)
        art = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
    return art


# ---------- physics ----------

@njit(cache=True)
def _seed(s):
    np.random.seed(s)


@njit(cache=True)
def _run(px, py, vx, vy, col, cool, n0, r, sd, gx, gy, steps, dt, t_start, target, ev_t, ev_y, counts):
    n = n0
    ne = 0
    cell = 2.0 * r
    gw, gh = int(1080 / cell) + 2, int(1920 / cell) + 2
    head = np.empty(gw * gh, np.int64)
    nxt = np.empty(px.shape[0], np.int64)
    filled_step = -1
    for step in range(steps):
        # move + walls (signed distance field: positive inside the shape)
        n_now = n
        for i in range(n_now):
            px[i] += vx[i] * dt
            py[i] += vy[i] * dt
            ix, iy = int(px[i]), int(py[i])
            if ix < 1 or iy < 1 or ix >= 1079 or iy >= 1919:
                ix, iy = min(max(ix, 1), 1078), min(max(iy, 1), 1918)
            d = sd[iy, ix]
            if d < r:
                nx, ny = gx[iy, ix], gy[iy, ix]
                ln = math.sqrt(nx * nx + ny * ny)
                if ln > 1e-6:
                    nx, ny = nx / ln, ny / ln
                    px[i] += nx * (r - d)
                    py[i] += ny * (r - d)
                    dot = vx[i] * nx + vy[i] * ny
                    if dot < 0:
                        vx[i] -= 2 * dot * nx
                        vy[i] -= 2 * dot * ny
                        tnow = t_start + step * dt
                        if n < target and n < px.shape[0] and tnow - cool[i] >= 0.45:   # a fresh wall hit clones
                            a = (np.random.random() * 2 - 1) * 0.314
                            ca, sa = math.cos(a), math.sin(a)
                            px[n], py[n] = px[i], py[i]
                            vx[n] = vx[i] * ca - vy[i] * sa
                            vy[n] = vx[i] * sa + vy[i] * ca
                            col[n] = np.random.randint(0, 6)
                            cool[i] = tnow
                            cool[n] = tnow
                            px[n] += nx * 2.0
                            py[n] += ny * 2.0
                            n += 1
                            if ne < ev_t.shape[0]:
                                ev_t[ne] = step * dt
                                ev_y[ne] = py[i]
                                ne += 1
        # ball-ball collisions with a uniform grid
        head[:] = -1
        for i in range(n):
            cx_, cy_ = int(px[i] / cell) + 1, int(py[i] / cell) + 1
            cx_, cy_ = min(max(cx_, 0), gw - 1), min(max(cy_, 0), gh - 1)
            c = cy_ * gw + cx_
            nxt[i] = head[c]
            head[c] = i
        for i in range(n):
            cx_, cy_ = int(px[i] / cell) + 1, int(py[i] / cell) + 1
            for oy in range(-1, 2):
                for ox in range(-1, 2):
                    qx, qy = cx_ + ox, cy_ + oy
                    if qx < 0 or qy < 0 or qx >= gw or qy >= gh:
                        continue
                    j = head[qy * gw + qx]
                    while j != -1:
                        if j > i:
                            dx, dy = px[j] - px[i], py[j] - py[i]
                            dd = dx * dx + dy * dy
                            if 1e-9 < dd < 4 * r * r:
                                dist = math.sqrt(dd)
                                nx, ny = dx / dist, dy / dist
                                over = (2 * r - dist) / 2
                                px[i] -= nx * over
                                py[i] -= ny * over
                                px[j] += nx * over
                                py[j] += ny * over
                                rel = (vx[j] - vx[i]) * nx + (vy[j] - vy[i]) * ny
                                if rel < 0:
                                    imp = -(1 + 0.97) * rel / 2
                                    vx[i] -= imp * nx
                                    vy[i] -= imp * ny
                                    vx[j] += imp * nx
                                    vy[j] += imp * ny
                        j = nxt[j]
        counts[step] = n
        if n >= target and filled_step < 0:
            filled_step = step
            return n, ne, filled_step
    return n, ne, filled_step


class Sim:
    def __init__(self, mask: np.ndarray, seed: int, r: float = 9.0, speed: float = 760.0, fps: int = 60,
                 sub: int = 2, max_s: float = 16.0):
        self.mask, self.r, self.fps, self.sub = mask, r, fps, sub
        inside = cv2.distanceTransform(mask, cv2.DIST_L2, 5).astype(np.float32)
        outside = cv2.distanceTransform(255 - mask, cv2.DIST_L2, 5).astype(np.float32)
        self.sd = inside - outside
        sm = cv2.GaussianBlur(self.sd, (9, 9), 0)
        self.gx = cv2.Sobel(sm, cv2.CV_32F, 1, 0, ksize=3)
        self.gy = cv2.Sobel(sm, cv2.CV_32F, 0, 1, ksize=3)
        area = float((mask > 0).sum())
        self.target = int(min(2400, 0.80 * area / (math.pi * r * r)))
        rng = np.random.default_rng(seed)
        cap = 2600
        self.px, self.py = np.zeros(cap), np.zeros(cap)
        self.vx, self.vy = np.zeros(cap), np.zeros(cap)
        self.col = np.zeros(cap, np.int64)
        self.cool = np.full(cap, -1.0)
        ys, xs = np.where(self.sd > 60)                     # start well inside the shape, near its middle
        k = int(np.argmin(np.hypot(xs - CX, ys - CY)))
        self.start = (float(xs[k]), float(ys[k]))
        self.px[0], self.py[0] = self.start
        a = rng.uniform(0, 2 * np.pi)
        self.vx[0], self.vy[0] = speed * math.cos(a), speed * math.sin(a)
        self.col[0] = int(rng.integers(0, 6))
        _seed(int(seed) % (2 ** 31))
        self.dt = 1.0 / (fps * sub)
        self.max_steps = int(max_s * fps * sub)

    def run(self):
        """Whole simulation at once (fast, numba). Returns per-frame snapshots of ball positions."""
        ev_t, ev_y = np.zeros(20000), np.zeros(20000)
        counts = np.zeros(self.max_steps, np.int64)
        frames = []
        steps_per_frame = self.sub
        n, total_events, filled = 1, 0, -1
        for f in range(int(self.max_steps / steps_per_frame)):
            frames.append((self.px[:n].copy(), self.py[:n].copy(), self.col[:n].copy()))
            n, ne, filled = _run(self.px, self.py, self.vx, self.vy, self.col, self.cool, n, self.r, self.sd,
                                 self.gx, self.gy, steps_per_frame, self.dt, f / self.fps, self.target, ev_t, ev_y, counts)
            t0 = f / self.fps
            for k in range(ne):
                self.events.append((t0 + ev_t[k], ev_y[k]))
            if n >= self.target:
                frames.append((self.px[:n].copy(), self.py[:n].copy(), self.col[:n].copy()))
                break
        return frames

    events: list


def render(spec: dict, writer, fps: int, log=print) -> dict:
    shape = spec["shape"]
    mask = silhouette(shape, spec.get("letter", "B"))
    speed = 760.0
    for _attempt in range(4):                     # tune speed so the fill takes ~11-13 s
        sim = Sim(mask, spec["seed"], speed=speed, fps=fps)
        sim.events = []
        frames = sim.run()
        t_fill = len(frames) / fps
        if 10.5 <= t_fill <= 13.5 or _attempt == 3:
            break
        speed *= max(0.55, min(1.8, t_fill / 12.0))
    log(f"Multiply: shape {shape}, {sim.target} balls, fill in {t_fill:.1f}s (speed {speed:.0f})")
    art = reveal_art(shape, mask, spec["seed"])
    bg = radial_bg("#1E1660", "#08061C")   # deep indigo keeps the glow, adds colour
    contours, _ = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
    colors = [bgr(c) for c in COLORS]
    base_hue = 0.70                                   # violet outline (#9B8CFF), drifting +-20 degrees
    shock_v, cross, hold, collapse = 2600.0, 0.5, 1.6, 0.45
    max_r = float(np.hypot(*np.subtract(mask.shape[::-1], (CX, CY))))
    t_shock = max_r / shock_v
    total = t_fill + t_shock + cross + hold + collapse
    n_frames = int(round(total * fps))
    label = text_sprite("1 bounce = 2 balls", "Poppins Black", 56, stroke=7)
    art_masked = np.zeros_like(art)
    art_masked[mask > 0] = art[mask > 0]

    def outline(layer, t):
        hue = base_hue + 0.055 * math.sin(2 * math.pi * t / max(total, 1))
        cv2.drawContours(layer, contours, -1, hue_bgr(hue, 0.45, 1.0), 14, cv2.LINE_AA)

    def meter(frame, pct):
        blit(frame, text_sprite(f"{pct}%", "Poppins Black", 120, stroke=10), W / 2, 245)

    first = None
    last_frame = None
    for fi in range(n_frames):
        t = fi / fps
        frame = bg.copy()
        layer = np.zeros_like(frame)
        if fi >= n_frames - 1 and first is not None:
            writer.write(first)                       # seamless loop: the last frame IS the first frame
            last_frame = first
            continue
        if t < t_fill:
            px, py, col = frames[min(fi, len(frames) - 1)]
            outline(layer, t)
            for x, y, c in zip(px.astype(np.int32), py.astype(np.int32), col):
                cv2.circle(layer, (int(x), int(y)), 9, colors[c], -1, cv2.LINE_AA)
            add_glow(frame, layer, passes=((6, 0.5), (22, 0.3)))
            meter(frame, min(99, int(100 * len(px) / sim.target)))
            if t < 1.2:
                blit(frame, label, W / 2, 118, alpha=min(1.0, (1.2 - t) / 0.3))
        else:
            px, py, col = frames[-1]
            tt = t - t_fill
            radius = tt * shock_v
            outline(layer, t)
            if tt < t_shock + cross:
                inside_ring = np.hypot(px - CX, py - CY) < radius
                fade = 0.0 if tt < t_shock else (tt - t_shock) / cross
                for x, y, c, hit in zip(px.astype(np.int32), py.astype(np.int32), col, inside_ring):
                    color = tuple(int(v) for v in art[min(max(y, 0), H - 1), min(max(x, 0), W - 1)]) if hit else colors[c]
                    cv2.circle(layer, (int(x), int(y)), 9, color, -1, cv2.LINE_AA)
                if tt < t_shock:
                    cv2.circle(layer, (CX, CY), int(radius), (255, 255, 255), 10, cv2.LINE_AA)
                add_glow(frame, layer, passes=((6, 0.45), (22, 0.25)))
                if fade > 0:
                    cv2.addWeighted(frame, 1 - fade, np.maximum(frame, art_masked), fade, 0, dst=frame)
                meter(frame, 100)
            elif tt < t_shock + cross + hold:
                np.maximum(frame, art_masked, out=frame)
                add_glow(frame, layer)
                meter(frame, 100)
            else:                                     # collapse back to one ball
                p = min(1.0, (tt - t_shock - cross - hold) / collapse)
                k = 1 - p
                if k > 0.02:
                    small = cv2.resize(art_masked, None, fx=k, fy=k)
                    sh, sw = small.shape[:2]
                    y0, x0 = int(CY - CY * k), int(CX - CX * k)
                    roi = frame[y0:y0 + sh, x0:x0 + sw]
                    np.maximum(roi, small[:roi.shape[0], :roi.shape[1]], out=roi)
                sx, sy = sim.start
                cv2.circle(layer, (int(sx), int(sy)), max(1, int(9 * p)), colors[int(frames[0][2][0])], -1, cv2.LINE_AA)
                add_glow(frame, layer, passes=((6, 0.5), (22, 0.3)))
                meter(frame, int(100 * k))
        if fi == 0:
            first = frame.copy()
        writer.write(frame)
    clone_events = sim.events
    return {"total": total, "clones": clone_events, "t_fill": t_fill, "t_shock": t_shock, "balls": sim.target,
            "cover_at": t_fill + t_shock + cross + 0.5}


def soundtrack(info: dict, spec: dict) -> np.ndarray:
    total = info["total"]
    scale = au.pentatonic(72, 96)
    events = []
    for t, y in info["clones"]:
        k = int((1 - (y - 360) / 1200) * (len(scale) - 1))
        events.append((t, scale[min(max(k, 0), len(scale) - 1)], 0.55))
    mix = au.render_notes(events, total, spec["instrument"], min_gap=1 / 28, dur=0.6)
    at = info["t_fill"]
    au.place(mix, au.sweep_up(0.6), at - 0.45, 0.5)
    au.place(mix, au.chord([60, 64, 67, 72, 76], 2.4, "bell", 0.9), at, 0.7)
    mix += au.pad(total, root=48, vol=0.06)[: len(mix)]
    return mix
