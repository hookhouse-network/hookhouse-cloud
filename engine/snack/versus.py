"""Format 3, "Snack Squad VS": two of our original characters bounce around an arena with an orbiting
weapon. Every landed hit escalates the attacker's own rule (more damage, faster spin, bigger body or more
speed). It ends in a KO, a winner banner and a running season table, so every episode continues a story
(recurring characters with different outcomes, which YouTube's rules allow). 35-50 s."""
from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass, field

import cv2
import numpy as np

from ..config import ROOT
from . import audio as au
from .canvas import W, H, bgr, blit, pop_scale, rounded_rect, text_sprite

LEAGUE = ROOT / "data" / "snack_league.json"
ARENA = (70, 400, 1010, 1340)                 # x0, y0, x1, y1 (940 x 940)
ROSTER = {
    "Gummo": {"color": "#FF3B5C", "item": "blade", "rule": "damage"},
    "Pretzo": {"color": "#FFB020", "item": "hammer", "rule": "size"},
    "Mochi": {"color": "#A855F7", "item": "twin", "rule": "spin"},
    "Limo": {"color": "#22C55E", "item": "blade", "rule": "speed"},
    "Berry": {"color": "#3B82F6", "item": "twin", "rule": "damage"},
    "Coco": {"color": "#8B5A2B", "item": "hammer", "rule": "spin"},
}
RULE_TEXT = {"damage": "Damage", "spin": "Spin", "size": "Size", "speed": "Speed"}


@dataclass
class Fighter:
    name: str
    color: tuple
    item: str
    rule: str
    x: float
    y: float
    vx: float
    vy: float
    r: float = 76.0
    hp: float = 100.0
    angle: float = 0.0
    spin: float = 2.4
    dmg: float = 3.0
    speed: float = 620.0
    hits: int = 0
    cooldown: float = 0.0
    squash: float = 0.0
    squash_dir: float = 0.0
    log: list = field(default_factory=list)

    def rule_value(self) -> str:
        return {"damage": f"{self.dmg:.0f}", "spin": f"{self.spin / 2.4:.1f}x",
                "size": f"+{(self.r / 76 - 1) * 100:.0f}%", "speed": f"+{(self.speed / 620 - 1) * 100:.0f}%"}[self.rule]

    def escalate(self):
        self.hits += 1
        if self.rule == "damage":
            self.dmg += 1
        elif self.rule == "spin":
            self.spin *= 1.12
        elif self.rule == "size":
            self.r = min(self.r * 1.06, 130)
        else:
            self.speed = min(self.speed * 1.05, 1100)

    def blade(self) -> list[tuple[tuple[float, float], tuple[float, float]]]:
        """Weapon segments (start, end) in world space."""
        def seg(a, r0, r1):
            return ((self.x + r0 * math.cos(a), self.y + r0 * math.sin(a)),
                    (self.x + r1 * math.cos(a), self.y + r1 * math.sin(a)))
        if self.item == "twin":
            return [seg(self.angle, self.r + 4, self.r + 58), seg(self.angle + math.pi, self.r + 4, self.r + 58)]
        if self.item == "hammer":
            return [seg(self.angle, self.r + 4, self.r + 70)]
        return [seg(self.angle, self.r + 4, self.r + 84)]


def _seg_dist(px, py, a, b) -> float:
    (ax, ay), (bx, by) = a, b
    ex, ey = bx - ax, by - ay
    ll = ex * ex + ey * ey
    u = max(0.0, min(1.0, ((px - ax) * ex + (py - ay) * ey) / ll)) if ll else 0.0
    return math.hypot(px - (ax + u * ex), py - (ay + u * ey))


def simulate(a_name: str, b_name: str, seed: int, base_dmg: float, max_s: float = 60.0, sub: int = 120):
    """Runs the fight; returns (frames of state at 60 fps, events, winner name, ko time)."""
    rng = random.Random(seed)
    f = []
    for name, x in ((a_name, 300.0), (b_name, 780.0)):
        meta = ROSTER[name]
        ang = rng.uniform(0, 2 * math.pi)
        f.append(Fighter(name, bgr(meta["color"]), meta["item"], meta["rule"], x, rng.uniform(600, 1140),
                         620 * math.cos(ang), 620 * math.sin(ang), angle=rng.uniform(0, 6.28), dmg=base_dmg))
    f[1].spin = -f[1].spin
    dt = 1.0 / sub
    frames, events = [], []
    x0, y0, x1, y1 = ARENA
    steps_per_frame = sub // 60
    ko_t, winner = None, None
    for step in range(int(max_s * sub)):
        t = step * dt
        for me in f:
            me.x += me.vx * dt
            me.y += me.vy * dt
            me.angle += me.spin * dt
            me.cooldown = max(0.0, me.cooldown - dt)
            me.squash = max(0.0, me.squash - dt)
            if me.x - me.r < x0 or me.x + me.r > x1:
                me.vx = abs(me.vx) * (1 if me.x - me.r < x0 else -1)
                me.x = min(max(me.x, x0 + me.r), x1 - me.r)
                events.append((t, "wall", me.name))
            if me.y - me.r < y0 or me.y + me.r > y1:
                me.vy = abs(me.vy) * (1 if me.y - me.r < y0 else -1)
                me.y = min(max(me.y, y0 + me.r), y1 - me.r)
                events.append((t, "wall", me.name))
        a, b = f
        dx, dy = b.x - a.x, b.y - a.y
        d = math.hypot(dx, dy)
        if 0 < d < a.r + b.r:                        # bodies bump
            nx, ny = dx / d, dy / d
            over = (a.r + b.r - d) / 2
            a.x, a.y, b.x, b.y = a.x - nx * over, a.y - ny * over, b.x + nx * over, b.y + ny * over
            rel = (b.vx - a.vx) * nx + (b.vy - a.vy) * ny
            if rel < 0:
                a.vx += rel * nx
                a.vy += rel * ny
                b.vx -= rel * nx
                b.vy -= rel * ny
            events.append((t, "bump", ""))
        for me, other in ((a, b), (b, a)):           # weapon hits
            if me.cooldown > 0:
                continue
            for s0, s1 in me.blade():
                if _seg_dist(other.x, other.y, s0, s1) < other.r:
                    other.hp -= me.dmg
                    me.cooldown = 0.35
                    kx, ky = other.x - me.x, other.y - me.y
                    kn = math.hypot(kx, ky) or 1.0
                    other.vx += kx / kn * 380
                    other.vy += ky / kn * 380
                    other.squash, other.squash_dir = 0.12, math.atan2(ky, kx)
                    events.append((t, "hit", me.name, round(me.dmg), me.hits + 1, other.x, other.y))
                    me.escalate()
                    break
        for me in f:                                 # constant speed (re-normalised)
            sp = math.hypot(me.vx, me.vy) or 1.0
            me.vx, me.vy = me.vx / sp * me.speed, me.vy / sp * me.speed
        if step % steps_per_frame == 0:
            frames.append([(m.x, m.y, m.r, max(0.0, m.hp), m.angle, m.squash, m.squash_dir, m.rule_value(), m.hits)
                           for m in f])
        if min(m.hp for m in f) <= 0:
            ko_t = t
            winner = a.name if b.hp <= 0 else b.name
            frames.append([(m.x, m.y, m.r, max(0.0, m.hp), m.angle, m.squash, m.squash_dir, m.rule_value(), m.hits)
                           for m in f])
            break
    return frames, events, winner, ko_t, f


def plan_fight(a_name: str, b_name: str, seed: int):
    """A fight that ends by KO between 30 and 45 s, preferably close. Damage rises until fights finish."""
    best = None
    for base in (6.0, 7.0, 8.0, 9.0, 11.0, 13.0, 16.0):
        for k in range(12):
            res = simulate(a_name, b_name, seed * 100 + int(base) * 13 + k, base)
            _frames, _events, _winner, ko, fighters = res
            if ko is None:
                continue
            left = max(m.hp for m in fighters)
            if 30 <= ko <= 45 and left <= 40:
                return res
            score = abs(ko - 38) + left * 0.15
            if best is None or score < best[0]:
                best = (score, res)
        if best is not None and best[0] < 12:
            return best[1]
    if best is None:
        raise RuntimeError(f"No fight between {a_name} and {b_name} ended in a KO")
    return best[1]


def league() -> dict:
    if LEAGUE.exists():
        try:
            return json.loads(LEAGUE.read_text(encoding="utf-8"))
        except ValueError:
            pass
    return {"season": 1, "matches": []}


def record(winner: str, loser: str) -> tuple[int, int, int]:
    """Adds the result to the league table; returns (season, winner's wins, loser's wins) head-to-head."""
    lg = league()
    lg["matches"].append({"w": winner, "l": loser})
    season = (len(lg["matches"]) - 1) // 30 + 1          # 30 matches per season
    lg["season"] = season
    LEAGUE.parent.mkdir(parents=True, exist_ok=True)
    LEAGUE.write_text(json.dumps(lg, indent=1), encoding="utf-8")
    current = lg["matches"][(season - 1) * 30:]
    w = sum(1 for m in current if m["w"] == winner and m["l"] == loser)
    l_ = sum(1 for m in current if m["w"] == loser and m["l"] == winner)
    return season, w, l_


def pick_pair(seed: int) -> tuple[str, str]:
    rng = random.Random(seed)
    return tuple(rng.sample(list(ROSTER), 2))


def _face(frame, x, y, r, look, color, squash, sq_dir):
    sx = 1 + 0.12 * (squash / 0.12) if squash > 0 else 1.0
    axes = (int(r * sx), int(r / sx))
    ang = math.degrees(sq_dir) if squash > 0 else 0
    cv2.ellipse(frame, (int(x), int(y)), (axes[0] + 7, axes[1] + 7), ang, 0, 360, (20, 20, 20), -1, cv2.LINE_AA)
    cv2.ellipse(frame, (int(x), int(y)), axes, ang, 0, 360, color, -1, cv2.LINE_AA)
    hi = tuple(min(255, int(c + (255 - c) * 0.45)) for c in color)          # soft highlight = rounder look
    cv2.ellipse(frame, (int(x - r * 0.3), int(y - r * 0.38)), (int(r * 0.32), int(r * 0.18)), -30, 0, 360, hi, -1,
                cv2.LINE_AA)
    lx, ly = math.cos(look), math.sin(look)
    for ex in (-0.34, 0.34):
        cx_, cy_ = int(x + ex * r), int(y - 0.18 * r)
        cv2.circle(frame, (cx_, cy_), int(r * 0.21), (255, 255, 255), -1, cv2.LINE_AA)
        cv2.circle(frame, (cx_, cy_), int(r * 0.21), (20, 20, 20), 3, cv2.LINE_AA)
        cv2.circle(frame, (int(cx_ + lx * r * 0.09), int(cy_ + ly * r * 0.09)), int(r * 0.1), (20, 20, 20), -1, cv2.LINE_AA)


def _weapon(frame, fx, fy, r, angle, item, color):
    dark = tuple(int(c * 0.55) for c in color)
    angles = [angle, angle + math.pi] if item == "twin" else [angle]
    for a in angles:
        r0, r1 = r + 4, r + (58 if item == "twin" else 70 if item == "hammer" else 84)
        ca, sa = math.cos(a), math.sin(a)
        wv = 15
        pts = np.array([[fx + r0 * ca - wv * sa, fy + r0 * sa + wv * ca], [fx + r1 * ca - wv * sa, fy + r1 * sa + wv * ca],
                        [fx + (r1 + (26 if item == "blade" else 0)) * ca, fy + (r1 + (26 if item == "blade" else 0)) * sa],
                        [fx + r1 * ca + wv * sa, fy + r1 * sa - wv * ca], [fx + r0 * ca + wv * sa, fy + r0 * sa - wv * ca]])
        cv2.fillPoly(frame, [pts.astype(np.int32)], dark, cv2.LINE_AA)
        cv2.polylines(frame, [pts.astype(np.int32)], True, (20, 20, 20), 6, cv2.LINE_AA)
        if item == "hammer":
            hx, hy = fx + r1 * ca, fy + r1 * sa
            cv2.circle(frame, (int(hx), int(hy)), 32, dark, -1, cv2.LINE_AA)
            cv2.circle(frame, (int(hx), int(hy)), 32, (20, 20, 20), 6, cv2.LINE_AA)


def _hp_bar(frame, x0, y0, w, h, frac, color, right=False):
    rounded_rect(frame, x0, y0, x0 + w, y0 + h, h // 2, (40, 40, 40), 1.0)
    fw = int((w - 8) * max(0.0, min(1.0, frac)))
    if fw > 4:
        if right:
            rounded_rect(frame, x0 + w - 4 - fw, y0 + 4, x0 + w - 4, y0 + h - 4, (h - 8) // 2, color, 1.0)
        else:
            rounded_rect(frame, x0 + 4, y0 + 4, x0 + 4 + fw, y0 + h - 4, (h - 8) // 2, color, 1.0)


def render(spec: dict, writer, fps: int, log=print) -> dict:
    a_name, b_name = spec["pair"].split("|")
    frames, events, winner, ko_t, fighters = plan_fight(a_name, b_name, spec["seed"])
    loser = b_name if winner == a_name else a_name
    season, w, l_ = record(winner, loser)
    log(f"VS: {a_name} vs {b_name}, KO at {ko_t:.1f}s, {winner} wins (season {season}: {w}-{l_})")
    pre, tail = 1.5, 2.2
    total = pre + ko_t + tail
    x0, y0, x1, y1 = ARENA
    base = np.full((H, W, 3), bgr("#FFF5E6"), np.uint8)
    cv2.rectangle(base, (x0, y0), (x1, y1), (255, 255, 255), -1)
    for gx in range(x0, x1, 47):                      # light grid: makes motion readable
        cv2.line(base, (gx, y0), (gx, y1), (236, 232, 228), 2)
    for gy in range(y0, y1, 47):
        cv2.line(base, (x0, gy), (x1, gy), (236, 232, 228), 2)
    cv2.rectangle(base, (x0, y0), (x1, y1), (20, 20, 20), 7, cv2.LINE_AA)
    ca, cb = ROSTER[a_name]["color"], ROSTER[b_name]["color"]
    head_a = text_sprite(a_name.upper(), "Poppins Black", 74, fill=ca, stroke=6)
    head_vs = text_sprite("VS", "Poppins Black", 58, fill="#1A1A1A", stroke=0, shadow=0)
    head_b = text_sprite(b_name.upper(), "Poppins Black", 74, fill=cb, stroke=6)
    who = text_sprite("WHO WINS?", "Poppins Black", 110, fill="#1A1A1A", stroke=0, shadow=4)
    who2 = text_sprite(f"{a_name} or {b_name}? Comment now", "Poppins ExtraBold", 50, fill="#1A1A1A", stroke=0, shadow=0)
    banner = text_sprite(f"{winner.upper()} WINS!", "Poppins Black", 110, fill=ROSTER[winner]["color"], stroke=8)
    stand = text_sprite(f"Season {season}: {winner} {w} - {l_} {loser}", "Poppins ExtraBold", 46, fill="#1A1A1A",
                        stroke=0, shadow=0)
    hits = [e for e in events if e[1] == "hit"]
    floaters, flashes = [], []
    trail_a, trail_b = [], []
    confetti = None
    rng = np.random.default_rng(spec["seed"])
    hit_i = 0
    shake_until = -1.0
    for fi in range(int(total * fps)):
        t = fi / fps
        ft = max(0.0, t - pre)
        frame = base.copy()
        k = len(frames) - 1 if t >= pre + ko_t else min(int(ft * 60), len(frames) - 1)
        (ax, ay, ar, ahp, aang, asq, asd, aval, _), (bx, by, br, bhp, bang, bsq, bsd, bval, _) = frames[k]
        while hit_i < len(hits) and hits[hit_i][0] <= ft and t < pre + ko_t + 0.01:
            e = hits[hit_i]
            floaters.append([t, e[5], e[6] - 100, f"-{e[3]}", ROSTER[e[2]]["color"]])
            flashes.append([t, e[5], e[6]])
            shake_until = t + 0.12
            hit_i += 1
        if t >= pre and t < pre + ko_t:
            trail_a = (trail_a + [(ax, ay, ar)])[-7:]
            trail_b = (trail_b + [(bx, by, br)])[-7:]
        for trail, col in ((trail_a, bgr(ca)), (trail_b, bgr(cb))):
            for j, (tx, ty, tr) in enumerate(trail[:-1]):
                f_ = (j + 1) / len(trail)
                tint = tuple(int(c * 0.35 * f_ + 255 * (1 - 0.35 * f_)) for c in col)
                cv2.circle(frame, (int(tx), int(ty)), int(tr * (0.55 + 0.4 * f_)), tint, -1, cv2.LINE_AA)
        _weapon(frame, ax, ay, ar, aang, ROSTER[a_name]["item"], bgr(ca))
        _weapon(frame, bx, by, br, bang, ROSTER[b_name]["item"], bgr(cb))
        _face(frame, ax, ay, ar, math.atan2(by - ay, bx - ax), bgr(ca), asq, asd)
        _face(frame, bx, by, br, math.atan2(ay - by, ax - bx), bgr(cb), bsq, bsd)
        blit(frame, text_sprite(f"{ahp:.0f}", "Poppins Black", 50, stroke=5), ax, ay + ar * 0.42)
        blit(frame, text_sprite(f"{bhp:.0f}", "Poppins Black", 50, stroke=5), bx, by + br * 0.42)
        for fl in flashes:                               # impact star
            age = t - fl[0]
            if age < 0.1:
                rr = int(40 + 300 * age)
                pts = [(fl[1] + (rr if q % 2 == 0 else rr * 0.45) * math.cos(q * math.pi / 5),
                        fl[2] + (rr if q % 2 == 0 else rr * 0.45) * math.sin(q * math.pi / 5)) for q in range(10)]
                cv2.fillPoly(frame, [np.array(pts, np.int32)], (80, 240, 255), cv2.LINE_AA)
        for fl in floaters:                              # damage numbers float up and fade
            age = t - fl[0]
            if age < 0.8:
                blit(frame, text_sprite(fl[3], "Poppins Black", 62, fill=fl[4], stroke=6), fl[1], fl[2] - age * 90,
                     alpha=1 - age / 0.8, scale=pop_scale(age, 0.15, 1.25))
        wa, wvs, wb = head_a.shape[1], head_vs.shape[1], head_b.shape[1]
        sx0 = W / 2 - (wa + wvs + wb + 30) / 2
        blit(frame, head_a, sx0 + wa / 2, 175)
        blit(frame, head_vs, sx0 + wa + 15 + wvs / 2, 177)
        blit(frame, head_b, sx0 + wa + wvs + 30 + wb / 2, 175)
        _hp_bar(frame, 70, 240, 450, 44, ahp / 100, bgr(ca))
        _hp_bar(frame, 560, 240, 450, 44, bhp / 100, bgr(cb), right=True)
        blit(frame, text_sprite(f"{RULE_TEXT[ROSTER[a_name]['rule']]}: {aval}", "Poppins Black", 50, fill=ca, stroke=5),
             295, 340)
        blit(frame, text_sprite(f"{RULE_TEXT[ROSTER[b_name]['rule']]}: {bval}", "Poppins Black", 50, fill=cb, stroke=5),
             785, 340)
        if t < pre:
            rounded_rect(frame, 120, 700, 960, 1040, 40, (255, 255, 255), 0.94, border=6, border_color=(20, 20, 20))
            blit(frame, who, W / 2, 820, scale=pop_scale(t, 0.25, 1.1))
            blit(frame, who2, W / 2, 950)
        if t >= pre + ko_t:
            kt = t - pre - ko_t
            if confetti is None:
                lx, ly = (bx, by) if winner == a_name else (ax, ay)
                n = 70
                confetti = {"p": np.stack([np.full(n, lx), np.full(n, ly)], 1),
                            "v": np.stack([rng.uniform(-550, 550, n), rng.uniform(-1000, -250, n)], 1),
                            "c": [bgr(ROSTER[loser]["color"]), (255, 255, 255), (80, 220, 255)]}
            if kt > 0.25:
                confetti["v"][:, 1] += 1500 / fps
                confetti["p"] += confetti["v"] / fps
                for j, (cx_, cy_) in enumerate(confetti["p"].astype(int)):
                    cv2.rectangle(frame, (cx_ - 9, cy_ - 5), (cx_ + 9, cy_ + 5), confetti["c"][j % 3], -1)
            if kt > 0.35:
                blit(frame, banner, W / 2, 1180, scale=pop_scale(kt - 0.35, 0.25, 1.12))
            if kt > 0.8:
                blit(frame, stand, W / 2, 1290, alpha=min(1.0, (kt - 0.8) / 0.2))
        if t < shake_until:                              # small screen shake on every hit
            dx, dy = rng.uniform(-8, 8, 2)
            frame = cv2.warpAffine(frame, np.float32([[1, 0, dx], [0, 1, dy]]), (W, H), borderMode=cv2.BORDER_REPLICATE)
        writer.write(frame)
    ev = [(pre + e[0], e[1], e[4] if e[1] == "hit" else 0) for e in events]
    return {"total": total, "events": ev, "ko_at": pre + ko_t, "winner": winner, "loser": loser, "season": season,
            "cover_at": pre + ko_t + 1.2}


def soundtrack(info: dict, spec: dict) -> np.ndarray:
    total = info["total"]
    mix = au.drum_loop(total, 128, vol=0.12)
    mix = np.concatenate([mix, np.zeros(max(0, int(total * au.SR) - len(mix)), np.float32)])
    last_wall = -1.0
    for t, kind, level in info["events"]:
        if kind == "hit":
            au.place(mix, au.clack(2 ** (min(level, 12) / 12), seed=int(t * 100)), t, 0.9)
        elif kind == "wall" and t - last_wall > 0.12:
            au.place(mix, au.tick(), t, 0.25)
            last_wall = t
    ko = info["ko_at"]
    au.place(mix, au.gong(), ko, 0.7)
    fan = np.zeros(int(1.6 * au.SR), np.float32)    # an original rising fanfare: C E G C'
    for i, n in enumerate([72, 76, 79, 84]):
        au.place(fan, au.tone(au.midi_hz(n), 0.8 if i < 3 else 1.2, "bell", 0.9), i * 0.13)
    au.place(mix, fan, ko + 0.35, 0.6)
    return mix
