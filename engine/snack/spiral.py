"""Format 1, "Attempt Spiral": a ball carves through a breakable rainbow spiral. Each attempt changes ONE
stated rule (start speed, ball size or boost per break). The early attempts fail and the last one reaches
the center. It is a real physics simulation; we only pick the random seeds that tell that story."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import cv2
import numpy as np
from numba import njit

from . import audio as au
from .canvas import W, add_glow, blit, hue_bgr, radial_bg, rounded_rect, text_sprite, zoom

CX, CY = 540.0, 960.0
R_GUIDE, R_WIN = 486.0, 62.0
THICK = 24.0
SUB = 240                     # physics steps per second


def build_spiral(n_target: int = 260, r0: float = 70.0, pitch: float = 58.0, r_max: float = 470.0) -> np.ndarray:
    """Segments [x0, y0, x1, y1, hue] along r = r0 + pitch*theta/2pi, roughly equal arc length."""
    th_max = (r_max - r0) / pitch * 2 * math.pi
    ths = np.linspace(0, th_max, 6000)
    r = r0 + pitch * ths / (2 * math.pi)
    xs, ys = CX + r * np.cos(ths), CY + r * np.sin(ths)
    arc = np.concatenate([[0], np.cumsum(np.hypot(np.diff(xs), np.diff(ys)))])
    marks = np.linspace(0, arc[-1], n_target + 1)
    idx = np.searchsorted(arc, marks).clip(0, len(xs) - 1)
    segs = np.zeros((n_target, 5))
    for i in range(n_target):
        a, b = idx[i], idx[i + 1]
        segs[i] = (xs[a], ys[a], xs[b], ys[b], (i / n_target) * 1.5 % 1.0)
    return segs


@njit(cache=True)
def _simulate(segs, alive, x, y, vx, vy, r, mult, vcap, cap_s, stuck_s, traj, breaks_t, breaks_i):
    dt = 1.0 / 240.0
    n_steps = int(cap_s * 240)
    nb = 0
    last_break = 0.0
    half = 14.0 + r                       # half thickness + ball radius (segment drawn 24 px; slightly generous)
    for step in range(n_steps):
        t = step * dt
        x += vx * dt
        y += vy * dt
        # outer guide circle
        dx, dy = x - 540.0, y - 960.0
        d = math.sqrt(dx * dx + dy * dy)
        if d + r > 486.0:
            nx, ny = dx / d, dy / d
            dot = vx * nx + vy * ny
            if dot > 0:
                vx -= 2 * dot * nx
                vy -= 2 * dot * ny
            x, y = 540.0 + nx * (486.0 - r), 960.0 + ny * (486.0 - r)
        # breakable segments (one break per step)
        for j in range(segs.shape[0]):
            if not alive[j]:
                continue
            ax, ay, bx, by = segs[j, 0], segs[j, 1], segs[j, 2], segs[j, 3]
            ex, ey = bx - ax, by - ay
            ll = ex * ex + ey * ey
            u = ((x - ax) * ex + (y - ay) * ey) / ll if ll > 0 else 0.0
            u = min(1.0, max(0.0, u))
            px, py = ax + u * ex, ay + u * ey
            qx, qy = x - px, y - py
            dd = math.sqrt(qx * qx + qy * qy)
            if dd < half and dd > 1e-6:
                nx, ny = qx / dd, qy / dd
                dot = vx * nx + vy * ny
                if dot < 0:
                    vx -= 2 * dot * nx
                    vy -= 2 * dot * ny
                x, y = px + nx * (half + 0.01), py + ny * (half + 0.01)
                alive[j] = False
                if nb < breaks_t.shape[0]:
                    breaks_t[nb] = t
                    breaks_i[nb] = j
                    nb += 1
                sp = math.sqrt(vx * vx + vy * vy)
                ns = min(sp * mult, vcap)
                vx, vy = vx / sp * ns, vy / sp * ns
                last_break = t
                break
        traj[step, 0], traj[step, 1] = x, y
        dx, dy = x - 540.0, y - 960.0
        if math.sqrt(dx * dx + dy * dy) < 62.0:
            return nb, step + 1, 1
        if t - last_break > stuck_s:
            return nb, step + 1, -1
    return nb, n_steps, 0


@dataclass
class Attempt:
    rule_value: float
    outcome: int                          # 1 reached center, 0 time cap, -1 stuck
    traj: np.ndarray                      # ball position per physics step
    breaks: list[tuple[float, int]]       # (time in attempt, segment index)
    radius: float
    start: float = 0.0                    # start time in the video
    speeds: list[float] = field(default_factory=list)

    @property
    def duration(self) -> float:
        return len(self.traj) / SUB


RULES = {
    "speed": {"label": "start speed", "unit": "px/s", "values": (300, 900),
              "hook": "Each try, the ball starts FASTER.\nWhich try reaches the center?"},
    "size": {"label": "ball size", "unit": "px", "values": (26, 10),
             "hook": "Each try, the ball gets SMALLER.\nWhich try reaches the center?"},
    "boost": {"label": "boost per break", "unit": "%", "values": (1.0, 4.0),
              "hook": "Every break makes it faster,\nand the boost grows each try."},
}


def run_attempt(segs: np.ndarray, rule: str, value: float, seed: int, cap_s: float = 12.0) -> Attempt:
    rng = np.random.default_rng(seed)
    speed, r, mult = 520.0, 13.0, 1.025
    if rule == "speed":
        speed = value
    elif rule == "size":
        r = value / 2 + 4
    else:
        mult = 1 + value / 100
    ang = rng.uniform(0, 2 * math.pi)
    start_a = rng.uniform(-0.4, 0.4)
    x, y = CX + 455 * math.cos(start_a), CY + 455 * math.sin(start_a)
    traj = np.zeros((int(cap_s * SUB) + 2, 2))
    bt, bi = np.zeros(4000), np.zeros(4000, np.int64)
    alive = np.ones(len(segs), np.bool_)
    nb, steps, outcome = _simulate(segs, alive, x, y, speed * math.cos(ang), speed * math.sin(ang), r, mult,
                                   1900.0, cap_s, 4.0, traj, bt, bi)
    return Attempt(value, int(outcome), traj[:steps].copy(), [(float(bt[k]), int(bi[k])) for k in range(nb)], r)


def plan_attempts(segs: np.ndarray, rule: str, n: int, seed: int, tries: int = 60) -> list[Attempt]:
    """Fails for attempts 1..n-1 (at least 6 s each) and a success on attempt n (5-12 s)."""
    lo, hi = RULES[rule]["values"]
    values = [lo + (hi - lo) * k / (n - 1) for k in range(n)]
    out = []
    for k, v in enumerate(values):
        last = k == n - 1
        best = None
        for s in range(tries):
            a = run_attempt(segs, rule, v, seed * 1000 + k * 100 + s)
            good = (a.outcome == 1 and 5.0 <= a.duration <= 12.0) if last else (a.outcome != 1 and a.duration >= 6.0)
            if good:
                best = a
                break
            if last and a.outcome == 1 and (best is None or abs(a.duration - 8) < abs(best.duration - 8)):
                best = a
        if best is None:
            best = a                         # very unlikely; keep the story going with whatever happened
        out.append(best)
    return out


@dataclass
class Particles:
    pos: np.ndarray = field(default_factory=lambda: np.zeros((0, 2), np.float32))
    vel: np.ndarray = field(default_factory=lambda: np.zeros((0, 2), np.float32))
    life: np.ndarray = field(default_factory=lambda: np.zeros(0, np.float32))
    col: np.ndarray = field(default_factory=lambda: np.zeros((0, 3), np.uint8))
    size: np.ndarray = field(default_factory=lambda: np.zeros(0, np.float32))

    def burst(self, x, y, n, color, rng, speed=(250, 600), life=1.1, size=(5, 9)):
        ang = rng.uniform(0, 2 * math.pi, n)
        sp = rng.uniform(*speed, n)
        self.pos = np.vstack([self.pos, np.stack([np.full(n, x), np.full(n, y)], 1)]).astype(np.float32)
        self.vel = np.vstack([self.vel, np.stack([np.cos(ang) * sp, np.sin(ang) * sp], 1)]).astype(np.float32)
        self.life = np.concatenate([self.life, np.full(n, life, np.float32) * rng.uniform(0.7, 1.0, n)])
        cols = np.array([color] * n, np.uint8) if not callable(color) else np.array([color(i) for i in range(n)], np.uint8)
        self.col = np.vstack([self.col, cols]).astype(np.uint8)
        self.size = np.concatenate([self.size, rng.uniform(*size, n).astype(np.float32)])
        if len(self.life) > 3500:
            keep = slice(len(self.life) - 3500, None)
            self.pos, self.vel, self.life, self.col, self.size = (self.pos[keep], self.vel[keep], self.life[keep],
                                                                  self.col[keep], self.size[keep])

    def step(self, dt, gravity=1600.0):
        if not len(self.life):
            return
        self.vel[:, 1] += gravity * dt
        self.pos += self.vel * dt
        self.life -= dt
        m = self.life > 0
        self.pos, self.vel, self.life, self.col, self.size = self.pos[m], self.vel[m], self.life[m], self.col[m], self.size[m]

    def draw(self, layer):
        for (x, y), c, s in zip(self.pos.astype(np.int32), self.col, self.size.astype(np.int32)):
            pts = np.array([[x, y - s], [x - s, y + s], [x + s, y + s // 2]], np.int32)
            cv2.fillConvexPoly(layer, pts, (int(c[0]), int(c[1]), int(c[2])), cv2.LINE_AA)


def render(spec: dict, writer, fps: int, mascot_sprite: np.ndarray | None, log=print) -> dict:
    """spec: rule, attempts, seed, hue_shift, melody, instrument. Returns timeline info for audio + meta."""
    rng = np.random.default_rng(spec["seed"])
    segs = build_spiral()
    segs[:, 4] = (segs[:, 4] + spec.get("hue_shift", 0.0)) % 1.0
    rule = spec["rule"]
    attempts = plan_attempts(segs, rule, spec["attempts"], spec["seed"])
    gap = 1.0                                              # flash + rebuild between attempts
    t = 0.0
    for a in attempts:
        a.start = t
        t += a.duration + gap
    win = attempts[-1]
    slow_len, slow_rate = 0.4, 0.35                        # last 0.4 s of the winning run in slow motion
    win_end = win.start + win.duration
    total = win_end + slow_len / slow_rate - slow_len + 1.1
    log(f"Spiral: {len(attempts)} attempts, outcomes {[a.outcome for a in attempts]}, {total:.1f}s")

    bg = radial_bg("#1E1660", "#08061C")   # deep indigo keeps the glow, adds colour
    cv2.circle(bg, (int(CX), int(CY)), int(R_GUIDE), (150, 150, 150), 3, cv2.LINE_AA)
    seg_cols = [hue_bgr(h) for h in segs[:, 4]]
    ends = []
    for x0, y0, x1, y1, _h in segs:                        # shortened pieces leave thin dark gaps
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        ends.append(((int(mx + (x0 - mx) * 0.86), int(my + (y0 - my) * 0.86)),
                     (int(mx + (x1 - mx) * 0.86), int(my + (y1 - my) * 0.86))))
    static_cache: dict = {"key": None, "img": None}

    def static_frame(alive: np.ndarray) -> np.ndarray:
        key = alive.tobytes()
        if key != static_cache["key"]:
            img = bg.copy()
            layer = np.zeros_like(img)
            for j in np.flatnonzero(alive):
                cv2.line(layer, ends[j][0], ends[j][1], seg_cols[j], 22, cv2.LINE_AA)
            add_glow(img, layer)
            static_cache["key"], static_cache["img"] = key, img
        return static_cache["img"]

    parts = Particles()
    events, sfx_events = [], []
    melody = au.MELODIES[spec["melody"]]
    note_i = 0
    label = RULES[rule]
    rule_small = text_sprite(label["hook"], "Poppins Black", 50, stroke=7)
    hook_big = text_sprite(label["hook"], "Poppins ExtraBold", 42, stroke=0, shadow=0, align="left")
    win_banner = text_sprite(f"MADE IT ON TRY {len(attempts)}!", "Poppins Black", 96, fill="#22C55E", stroke=10)
    n_frames = int(total * fps)
    prev_alive = None
    win_started = False
    for fi in range(n_frames):
        tv = fi / fps
        cur = attempts[0]
        for a in attempts:
            if tv >= a.start:
                cur = a
        local = tv - cur.start
        is_win = cur is win
        if is_win and tv > win_end - slow_len:             # slow motion near the end of the winning run
            local = (win.duration - slow_len) + (tv - (win_end - slow_len)) * slow_rate
        in_gap = local > cur.duration and not is_win
        step = min(int(local * SUB), len(cur.traj) - 1)
        alive = np.ones(len(segs), bool)
        for bt, bi in cur.breaks:
            if bt <= local:
                alive[bi] = False
        broken_now = list(np.flatnonzero(prev_alive & ~alive)) if prev_alive is not None and not in_gap else []
        prev_alive = None if in_gap else alive.copy()
        if in_gap:                                          # rebuild ripple: pieces return from the center out
            g = (local - cur.duration) / gap
            shown = int(len(segs) * min(1.0, max(0.0, (g - 0.35) / 0.6)))
            alive = np.zeros(len(segs), bool)
            alive[:shown] = True
        frame = static_frame(alive).copy()
        dyn = np.zeros_like(frame)
        for j in broken_now:
            x0, y0, x1, y1, _h = segs[j]
            parts.burst((x0 + x1) / 2, (y0 + y1) / 2, int(rng.integers(8, 15)), seg_cols[j], rng)
            events.append((tv, melody[note_i % len(melody)], min(1.0, 0.45 + note_i * 0.004)))
            note_i += 1
        parts.step(1.0 / fps)
        parts.draw(dyn)
        if not in_gap:
            bx, by = cur.traj[step]
            hue = segs[int(np.argmin(np.hypot(segs[:, 0] - bx, segs[:, 1] - by))), 4]
            cv2.circle(dyn, (int(bx), int(by)), int(cur.radius + 7), hue_bgr(hue, 0.7, 0.9), -1, cv2.LINE_AA)
        add_glow(frame, dyn, passes=((8, 0.6), (24, 0.3)))
        if not in_gap:
            cv2.circle(frame, (int(bx), int(by)), int(cur.radius), (255, 255, 255), -1, cv2.LINE_AA)
        if in_gap:                                          # fail moment: white flash, then rebuild
            g = local - cur.duration
            if g < 1.0 / fps + 1e-6:
                sfx_events.append((tv, "fail"))
            if g < 0.35:
                a = 1 - g / 0.35
                cv2.addWeighted(frame, 1 - 0.6 * a, np.full_like(frame, 255), 0.6 * a, 0, dst=frame)
            if abs(g - 0.35) < 0.5 / fps:
                sfx_events.append((tv, "rebuild"))
        if is_win and tv >= win_end - slow_len:             # win: burst + camera push-in + banner
            if not win_started:
                win_started = True
                sfx_events.append((tv, "win"))
                parts.burst(CX, CY, 1200, lambda i: hue_bgr(i / 1200), rng, speed=(300, 1400), life=1.6, size=(4, 10))
            p = min(1.0, (tv - (win_end - slow_len)) / 0.8)
            frame = zoom(frame, 1 + 0.35 * (1 - (1 - p) ** 3), CX, CY)
            bt_ = tv - (win_end - slow_len) - 0.35
            if bt_ > 0:
                from .canvas import pop_scale
                blit(frame, win_banner, W / 2, 1180, scale=pop_scale(bt_, 0.25, 1.12))
        idx = attempts.index(cur) + 1
        if tv < 3.0:                                        # hook card, then a smaller rule line
            card_a = 1.0 if tv < 2.6 else max(0.0, 1 - (tv - 2.6) / 0.4)
            rounded_rect(frame, 80, 150, 1000, 300, 34, (36, 28, 28), 0.88 * card_a)
            if mascot_sprite is not None:
                blit(frame, mascot_sprite, 150, 225, alpha=card_a)
            blit(frame, hook_big, 210, 225 - hook_big.shape[0] / 2, alpha=card_a, anchor="top-left")
        else:
            blit(frame, rule_small, W / 2, 225, alpha=min(1.0, (tv - 3.0) / 0.3))
        blit(frame, text_sprite(f"ATTEMPT {idx}/{len(attempts)}", "Poppins Black", 70, stroke=9), W / 2, 365)
        val = cur.rule_value
        stat = (f"{label['label']}: {val:.0f} {label['unit']}" if rule != "boost"
                else f"{label['label']}: +{val:.1f}{label['unit']}")
        blit(frame, text_sprite(stat, "Poppins ExtraBold", 38, stroke=4), W / 2, 428, alpha=0.8)
        writer.write(frame)
    return {"total": total, "events": events, "sfx": sfx_events, "attempts": len(attempts),
            "win_at": win_end, "rule": rule, "cover_at": win_end + 0.5}


def soundtrack(info: dict, spec: dict) -> np.ndarray:
    total = info["total"]
    mix = au.render_notes(info["events"], total, spec["instrument"], transpose=spec.get("transpose", 0))
    for at, kind in info["sfx"]:
        if kind == "fail":
            au.place(mix, au.thud(), at, 0.8)
            au.place(mix, au.fail_figure(), at + 0.05, 0.5)
        elif kind == "rebuild":
            au.place(mix, au.whoosh(0.6), at, 0.5)
        elif kind == "win":
            au.place(mix, au.sweep_up(0.5), at - 0.3, 0.4)
            au.place(mix, au.success(), at, 0.8)
    mix += au.pad(total, root=45 + spec.get("transpose", 0) % 12, vol=0.05)[: len(mix)]
    return mix
