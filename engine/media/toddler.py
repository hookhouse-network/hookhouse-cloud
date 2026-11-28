"""Original toddler characters for the kids channel, drawn by our own code (owner 28 Nov: "totally change the
animations ... like CoComelon"; the DiceBear dolls looked stiff and creepy).

The LOOK of the genre, never its characters: big round heads, large glossy eyes with two highlights, rosy cheeks,
soft 3D-looking shading (radial gradients), short rounded bodies, and motion on every frame (breathing squash and
stretch, blinking, eyes that follow the speaker, arms that wave / clap / cheer / point). The cast (config/toddlers.yaml
style data in TODDLERS below) is ours; no franchise character, name or design is copied.

Same interface as media/puppet.Puppet: draw(t, mouth, hop, look, viseme, action, mood) -> BGRA sprite whose bottom
edge is the feet line, so engine/kids.py places it like any cast member."""
from __future__ import annotations

import math
from collections import OrderedDict

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

SS = 2                                   # supersampling: drawn at 2x, scaled down (smooth edges)
FPS_POSE = 15                            # pose updates a second (smooth, still cacheable)
OUTLINE = (46, 58, 89)                   # the house outline colour (RGB), as on Bloop

# Our own cast. skin/hair/top/bottom/shoes are RGB hex; hair: tuft | pigtails | puffs | bob | spiky
TODDLERS = {
    "lulu": {"name": "Lulu", "skin": "F6C9A8", "hair": "7A4A2A", "style": "pigtails", "top": "FF7BAC",
             "bottom": "FF7BAC", "dress": True, "shoes": "FFFFFF", "voice": "af_nicole"},
    "benji": {"name": "Benji", "skin": "FAD7B5", "hair": "E3A548", "style": "swoop", "top": "FFFFFF",
              "bottom": "3D8BFD", "dress": False, "shoes": "FF5A5A", "voice": "am_puck"},
    "amara": {"name": "Amara", "skin": "A86E4C", "hair": "2B1B12", "style": "puffs", "top": "FFD23F",
              "bottom": "7C5CFF", "dress": False, "shoes": "FF8A3D", "voice": "af_sky"},
    "kai": {"name": "Kai", "skin": "EDC09A", "hair": "1E1E24", "style": "spiky", "top": "35C26B",
            "bottom": "2E5AAC", "dress": False, "shoes": "FFFFFF", "voice": "am_eric"},
}


def _rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _shade(c, k: float):
    """k > 0 lighter, k < 0 darker."""
    if k >= 0:
        return tuple(int(v + (255 - v) * k) for v in c)
    return tuple(int(v * (1 + k)) for v in c)


def _ball(size: tuple[int, int], box, colour, light=(0.35, 0.3)) -> Image.Image:
    """A glossy 3D-looking ellipse: radial gradient from a soft highlight to a darker rim, as an RGBA layer."""
    w, h = size
    x0, y0, x1, y1 = box
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    cx, cy, rx, ry = (x0 + x1) / 2, (y0 + y1) / 2, max(1.0, (x1 - x0) / 2), max(1.0, (y1 - y0) / 2)
    d = ((xx - cx) / rx) ** 2 + ((yy - cy) / ry) ** 2
    lx, ly = x0 + (x1 - x0) * light[0], y0 + (y1 - y0) * light[1]
    g = np.sqrt(((xx - lx) / (rx * 1.6)) ** 2 + ((yy - ly) / (ry * 1.6)) ** 2)
    g = np.clip(g, 0, 1)
    hi, lo = np.array(_shade(colour, 0.35), np.float32), np.array(_shade(colour, -0.22), np.float32)
    rgb = hi * (1 - g[..., None]) + lo * g[..., None]
    alpha = np.clip((1.0 - d) * max(rx, ry) * 0.9, 0, 1) * 255     # anti-aliased edge
    return Image.fromarray(np.dstack([rgb, alpha]).astype(np.uint8), "RGBA")


class Toddler:
    def __init__(self, cid: str, size: int = 520, seed: int = 0):
        self.spec = TODDLERS[cid]
        self.cid, self.size = cid, size
        self.H = int(0.8 * size)
        self.W = int(1.1 * size)
        self.phase = (seed * 0.37 + len(cid)) % (2 * math.pi)
        self._cache: OrderedDict = OrderedDict()
        self.blink_at = [(1.7 + 3.1 * k + (seed % 7) * 0.13) for k in range(400)]

    # ---------------------------------------------------------------- state
    def _blink(self, t: float) -> float:
        """0 open .. 1 closed; a 0.16 s blink every ~3 s."""
        for b in self.blink_at:
            if b - 0.08 <= t <= b + 0.08:
                return 1 - abs(t - b) / 0.08
            if b > t + 0.1:
                break
        return 0.0

    def draw(self, t: float, mouth: float = 0.0, hop: float = 0.0, look: float = 0.0, viseme: str = "",
             action: str | None = None, mood: str | None = None) -> np.ndarray:
        tq = math.floor(t * FPS_POSE) / FPS_POSE
        blink = round(self._blink(t) * 3) / 3
        mo = round(min(1.0, max(0.0, mouth)) * 4) / 4
        lk = 1 if look > 0.3 else (-1 if look < -0.3 else 0)
        k = (int(tq * FPS_POSE) % 300, blink, mo, lk, action, round(hop * 5) / 5, mood)
        if k in self._cache:
            self._cache.move_to_end(k)
            return self._cache[k]
        spr = self._render(tq, blink, mo, lk, action, hop, mood)
        self._cache[k] = spr
        if len(self._cache) > 900:
            self._cache.popitem(last=False)
        return spr

    # ---------------------------------------------------------------- drawing
    def _render(self, t, blink, mouth, look, action, hop, mood) -> np.ndarray:
        s = self.spec
        W, H = self.W * SS, self.H * SS
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        skin, hair, top, bottom, shoes = (_rgb(s[k]) for k in ("skin", "hair", "top", "bottom", "shoes"))
        breathe = math.sin(2 * math.pi * 0.45 * t + self.phase)
        squash = 1 + 0.025 * breathe - 0.06 * hop                      # squash and stretch
        unit = H / 100.0
        cx = W / 2 + 1.2 * unit * math.sin(2 * math.pi * 0.23 * t + self.phase)   # a gentle sway
        feet = H - 2 * unit
        # body proportions (toddler: head about 55 % of the height)
        leg_h, body_h = 14 * unit, 24 * unit * squash
        head_r = 25 * unit * (2 - squash) ** 0.5
        hip_y = feet - leg_h
        neck_y = hip_y - body_h
        head_cy = neck_y - head_r * 0.82
        d = ImageDraw.Draw(img)
        lw = max(2, int(1.1 * unit))
        # legs + shoes
        for side in (-1, 1):
            lx = cx + side * 6.5 * unit
            d.rounded_rectangle([lx - 4.2 * unit, hip_y - 2 * unit, lx + 4.2 * unit, feet - 3 * unit],
                                radius=int(3 * unit), fill=skin if s["dress"] else bottom, outline=OUTLINE, width=lw)
            img.alpha_composite(_ball((W, H), (lx - 6.5 * unit, feet - 7 * unit, lx + 7.5 * unit, feet + 0.5 * unit),
                                      shoes))
        d = ImageDraw.Draw(img)
        # arms (behind the body when down, in front when raised)
        self._arms(img, cx, neck_y, body_h, unit, skin, top, action, t, front=False)
        # body: a glossy rounded torso (dress = a wider bell shape)
        bw = (17 if s["dress"] else 14.5) * unit
        img.alpha_composite(_ball((W, H), (cx - bw, neck_y - 2 * unit, cx + bw, hip_y + 4 * unit), top))
        if not s["dress"]:                                              # overalls / shorts band
            band = _ball((W, H), (cx - bw * 0.92, hip_y - 7 * unit, cx + bw * 0.92, hip_y + 4 * unit), bottom)
            img.alpha_composite(band)
        d = ImageDraw.Draw(img)
        d.ellipse([cx - bw, neck_y - 2 * unit, cx + bw, hip_y + 4 * unit], outline=OUTLINE, width=lw)
        # head
        hx0, hy0, hx1, hy1 = cx - head_r * 1.04, head_cy - head_r, cx + head_r * 1.04, head_cy + head_r * 0.98
        self._hair_back(img, s["style"], hair, cx, head_cy, head_r, unit)
        for side in (-1, 1):                                            # ears
            ex = cx + side * head_r * 1.0
            img.alpha_composite(_ball((W, H), (ex - 4.5 * unit, head_cy - 3 * unit, ex + 4.5 * unit, head_cy + 6 * unit),
                                      skin))
        img.alpha_composite(_ball((W, H), (hx0, hy0, hx1, hy1), skin, light=(0.38, 0.28)))
        d = ImageDraw.Draw(img)
        d.ellipse([hx0, hy0, hx1, hy1], outline=OUTLINE, width=lw)
        self._hair_front(img, s["style"], hair, cx, head_cy, head_r, unit)
        self._face(img, cx + look * 2.2 * unit, head_cy + 3 * unit, head_r, unit, blink, mouth, look, mood, skin)
        self._arms(img, cx, neck_y, body_h, unit, skin, top, action, t, front=True)   # raised arms over the head edge
        out = img.resize((self.W, self.H), Image.LANCZOS)
        a = np.array(out)
        return np.dstack([a[..., 2], a[..., 1], a[..., 0], a[..., 3]])  # RGBA -> BGRA

    def _arms(self, img, cx, neck_y, body_h, unit, skin, sleeve, action, t, front: bool):
        """Short arms with round hands. Angles (0 = down, 90 = sideways, 160 = up) per action, always a little alive."""
        base = 18 + 6 * math.sin(2 * math.pi * 0.5 * t + self.phase)
        angles = {-1: base, 1: base}
        if action == "wave":                       # raised arms swing OUT beside the big head, never behind it
            angles[1] = 122 + 16 * math.sin(2 * math.pi * 2.2 * t)
        elif action == "clap":
            c = abs(math.sin(2 * math.pi * 1.8 * t))
            angles = {-1: 70 - 25 * c, 1: 70 - 25 * c}
        elif action == "cheer":
            angles = {-1: 128 + 8 * math.sin(6 * t), 1: 128 + 8 * math.sin(6 * t + 1)}
        elif action == "count":
            angles[1] = 98
        elif action == "question":
            angles[1] = 115
        d = ImageDraw.Draw(img)
        lw = max(2, int(1.1 * unit))
        for side in (-1, 1):
            raised = angles[side] > 60
            if raised != front:
                continue
            sx, sy = cx + side * 12.5 * unit, neck_y + 4 * unit
            a = math.radians(angles[side])
            ln = (18 if raised else 15) * unit
            if action == "clap" and front:                             # hands meet in front of the chest
                ex, ey = cx + side * (2 + 7 * (1 - abs(math.sin(2 * math.pi * 1.8 * t)))) * unit, neck_y + 9 * unit
            else:
                ex, ey = sx + side * ln * math.sin(a), sy + ln * math.cos(a)
            d.line([sx, sy, ex, ey], fill=OUTLINE, width=int(7.4 * unit))
            d.line([sx, sy, ex, ey], fill=sleeve, width=int(5.6 * unit))
            img.alpha_composite(_ball(img.size, (ex - 3.6 * unit, ey - 3.6 * unit, ex + 3.6 * unit, ey + 3.6 * unit), skin))
            d = ImageDraw.Draw(img)
            d.ellipse([ex - 3.6 * unit, ey - 3.6 * unit, ex + 3.6 * unit, ey + 3.6 * unit], outline=OUTLINE, width=lw)

    def _hair_back(self, img, style, hair, cx, cy, r, unit):
        if style == "pigtails":
            for side in (-1, 1):
                x = cx + side * r * 1.12
                img.alpha_composite(_ball(img.size, (x - 8 * unit, cy - 6 * unit, x + 8 * unit, cy + 12 * unit), hair))
        elif style == "puffs":
            for side in (-1, 1):
                x = cx + side * r * 0.78
                img.alpha_composite(_ball(img.size, (x - 10 * unit, cy - r - 9 * unit, x + 10 * unit, cy - r + 9 * unit),
                                          hair))

    def _hair_front(self, img, style, hair, cx, cy, r, unit):
        """A cap of hair over the top of the head, plus the style's signature shape."""
        cap = Image.new("RGBA", img.size, (0, 0, 0, 0))
        top = _ball(img.size, (cx - r * 1.06, cy - r * 1.06, cx + r * 1.06, cy + r * 0.2), hair, light=(0.35, 0.2))
        mask = Image.new("L", img.size, 0)
        md = ImageDraw.Draw(mask)
        md.ellipse([cx - r * 1.06, cy - r * 1.06, cx + r * 1.06, cy + r * 1.06], fill=255)
        md.rectangle([0, cy - r * 0.38, img.size[0], img.size[1]], fill=0)     # fringe line
        if style in ("bob", "pigtails"):
            md.ellipse([cx - r * 0.95, cy - r * 0.62, cx + r * 0.95, cy - r * 0.15], fill=255)
        cap.paste(top, (0, 0), Image.composite(top, Image.new("RGBA", img.size), mask).split()[3])
        img.alpha_composite(cap)
        d = ImageDraw.Draw(img)
        if style == "swoop":                                           # a side-swept fringe (never a single top curl:
            img.alpha_composite(_ball(img.size, (cx - r * 0.95, cy - r * 0.62, cx + r * 0.25, cy - r * 0.12), hair,
                                      light=(0.3, 0.2)))                # that is a famous show's baby signature)
        elif style == "spiky":
            for k in (-2, -1, 0, 1, 2):
                x = cx + k * 6.5 * unit
                d.polygon([(x - 4 * unit, cy - r * 0.86), (x + 4 * unit, cy - r * 0.86),
                           (x + k * 1.5 * unit, cy - r - 6 * unit)], fill=hair)

    def _face(self, img, cx, cy, r, unit, blink, mouth, look, mood, skin):
        d = ImageDraw.Draw(img)
        lw = max(2, int(1.0 * unit))
        ey, ex_off = cy - 2 * unit, 10.5 * unit
        ew, eh = 6.4 * unit, 8.6 * unit
        for side in (-1, 1):
            ex = cx + side * ex_off
            if blink >= 0.66:                                          # closed: a happy curve
                d.arc([ex - ew, ey - eh * 0.4, ex + ew, ey + eh * 0.9], 200, 340, fill=OUTLINE, width=int(1.6 * unit))
                continue
            h = eh * (1 - 0.6 * blink)
            d.ellipse([ex - ew, ey - h, ex + ew, ey + h], fill=(255, 255, 255), outline=OUTLINE, width=lw)
            ix = ex + look * 1.6 * unit
            ir = ew * 0.82
            d.ellipse([ix - ir, ey - min(h, ir * 1.15), ix + ir, ey + min(h, ir * 1.15)], fill=(70, 44, 30))
            pr = ir * 0.55
            d.ellipse([ix - pr, ey - min(h, pr * 1.1), ix + pr, ey + min(h, pr * 1.1)], fill=(20, 14, 12))
            d.ellipse([ix - ir * 0.62, ey - h * 0.62, ix - ir * 0.62 + ir * 0.62, ey - h * 0.62 + ir * 0.62],
                      fill=(255, 255, 255))                             # two catch-lights: the glossy look
            d.ellipse([ix + ir * 0.2, ey + h * 0.12, ix + ir * 0.2 + ir * 0.3, ey + h * 0.12 + ir * 0.3],
                      fill=(255, 255, 255))
            bw = ew * 0.9                                               # brows: up on a question / surprise
            by = ey - eh - (2.6 if mood in ("question", "wow") else 1.4) * unit
            d.arc([ex - bw, by - 1.5 * unit, ex + bw, by + 3 * unit], 200, 340, fill=_shade(OUTLINE, 0.1),
                  width=int(1.3 * unit))
        cheek = Image.new("RGBA", img.size, (0, 0, 0, 0))               # rosy cheeks, soft
        cd = ImageDraw.Draw(cheek)
        for side in (-1, 1):
            x = cx + side * 15 * unit
            cd.ellipse([x - 5 * unit, cy + 4 * unit, x + 5 * unit, cy + 8.5 * unit], fill=(255, 120, 130, 110))
        img.alpha_composite(cheek.filter(ImageFilter.GaussianBlur(1.6 * unit)))
        d = ImageDraw.Draw(img)
        my = cy + 8 * unit
        if mouth < 0.2:                                                # a smile
            d.arc([cx - 6 * unit, my - 5 * unit, cx + 6 * unit, my + 3 * unit], 20, 160, fill=OUTLINE,
                  width=int(1.5 * unit))
        else:                                                          # talking / singing: an open smile
            mh = (2.5 + 5.5 * mouth) * unit
            d.chord([cx - 5.5 * unit, my - mh * 0.3, cx + 5.5 * unit, my + mh], 0, 180, fill=(140, 40, 50),
                    outline=OUTLINE, width=lw)
            d.chord([cx - 3.4 * unit, my + mh * 0.35, cx + 3.4 * unit, my + mh * 0.95], 180, 360,
                    fill=(255, 130, 140))                               # tongue
