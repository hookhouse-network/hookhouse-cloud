"""A human kids character as a puppet (plan P3r characters workstream, S2 + S10).

The face is a DiceBear Toon Head (engine/media/characters.py: fixed seed + options, CC BY 4.0, credited) with lip sync
(the kids renderer's visemes -> closed / small round / open mouth), blinks at varied seeded times and moods (happy,
asking, joy, sad). The body is drawn by our own code in the character's colours: torso (or a dress), legs, shoes and
two-part arms that wave, clap, point and cheer. Poses change 12 times a second ("on twos", like hand-drawn cartoons).

Same call as media.mascot.Mascot.draw, so engine/kids.py swaps one for the other:
    sprite = puppet.draw(t, mouth=0..1, hop=0..1, look=-1..1, viseme="open", action="wave")
The sprite is BGRA, square (0.8 x size), the feet on its bottom edge, centred like the Mascot's."""
from __future__ import annotations

import math
import random
from collections import OrderedDict

import cv2
import numpy as np

from . import characters

MOUTHS = ("smile", "agape", "laugh")
EYES = ("happy", "humble", "bow")
BROWS = ("happy", "raised", "sad")
VISEME_MOUTH = {"rest": "smile", "closed": "smile", "fv": "smile", "round": "agape", "wide": "laugh",
                "open": "laugh", "teeth": "laugh"}
JOY = {"praise", "answer", "clap", "together", "cheer"}
INK = (89, 58, 46)                                  # BGR of #2E3A59, the kids show's outline colour
FPS_POSE = 12


def _bgr(hex6: str) -> tuple[int, int, int]:
    h = str(hex6).lstrip("#")
    return int(h[4:6], 16), int(h[2:4], 16), int(h[0:2], 16)


def _first(v, default: str) -> str:
    return str(v[0] if isinstance(v, list) and v else (v or default))


class Puppet:
    def __init__(self, cid: str, size: int = 430, seed: int = 0, files=None):
        self.ch = characters.character(cid)
        self.cid, self.size = cid, size
        self.H = int(0.8 * size)                            # the Mascot's height: feet on the same ground line
        self.W = int(1.1 * size)                            # wider: a pointing or waving arm stays inside
        self.A = int(self.H / 1.86)                         # the face box (DiceBear's square avatar)
        opts = self.ch.get("options") or {}
        self.skin = _bgr(_first(opts.get("skinColor"), "c68e7a"))
        self.cloth = _bgr(_first(opts.get("clothesColor"), "2563eb"))
        self.clothes = _first(opts.get("clothes"), "tShirt")
        legs = str(self.ch.get("legs") or "545454")
        self.legs = self.skin if legs == "skin" else _bgr(legs)
        self.shoes = _bgr(self.ch.get("shoes") or "2E3A59")
        states = [(m, e, b) for m in MOUTHS for e in EYES for b in BROWS]
        paths = (files or characters.face_files)(cid, states, self.A)
        self.faces = {s: cv2.imread(str(p), cv2.IMREAD_UNCHANGED) for s, p in paths.items()}
        for s, img in self.faces.items():
            if img is None or img.ndim != 3 or img.shape[2] != 4:
                raise characters.CharacterError(f"face {s} of {cid} is not a transparent PNG")
        rng = random.Random(f"{cid}-{seed}")
        self.blinks, t = [], rng.uniform(0.8, 2.0)
        while t < 900:                                      # blinks every 2.2-4.8 s, varied (never metronomic)
            self.blinks.append(t)
            t += rng.uniform(2.2, 4.8)
        self.phase = rng.uniform(0, 2 * math.pi)
        self._cache: OrderedDict = OrderedDict()

    # --- states --------------------------------------------------------------------------------------------------
    def _blinking(self, t: float) -> bool:
        i = int(np.searchsorted(self.blinks, t, side="right")) - 1
        return i >= 0 and t - self.blinks[i] < 0.13

    @staticmethod
    def _mouth(mouth: float, viseme: str) -> str:
        if viseme in VISEME_MOUTH:
            return VISEME_MOUTH[viseme]
        return "laugh" if mouth > 0.35 else ("agape" if mouth > 0.12 else "smile")

    def face_state(self, t: float, mouth: float = 0.0, viseme: str = "", action: str | None = None,
                   mood: str | None = None) -> tuple[str, str, str]:
        mood = mood or ("joy" if action in JOY else "ask" if action == "question" else "happy")
        eyes = "humble" if self._blinking(t) else ("bow" if mood == "joy" else "happy")
        brows = {"ask": "raised", "sad": "sad"}.get(mood, "happy")
        return self._mouth(mouth, viseme), eyes, brows

    # --- drawing -------------------------------------------------------------------------------------------------
    def _arm_angles(self, t: float, action: str | None, look: float) -> tuple[tuple, tuple]:
        """(upper, fore) degrees per arm, (left, right); 0 = down, 90 = straight out, 180 = up."""
        sw = 4 * math.sin(2 * math.pi * 0.6 * t + self.phase)
        rest_l, rest_r = (12 + sw, 8), (12 - sw, 8)
        if action == "wave":
            return rest_l, (150, 20 + 28 * math.sin(2 * math.pi * 2.2 * t))
        if action in ("cheer", "praise", "answer"):
            k = 8 * math.sin(2 * math.pi * 3.0 * t)
            return (152 + k, 12), (152 - k, 12)
        if action == "point" or action == "count":
            side = 1 if look >= 0 else -1
            point = (92, 4)
            return (rest_l, point) if side > 0 else (point, rest_r)
        return rest_l, rest_r

    def _limb(self, img, a, b, thick, colour):
        o = max(2, int(self.A * 0.014))
        cv2.line(img, a, b, INK, thick + 2 * o, cv2.LINE_AA)
        cv2.line(img, a, b, colour, thick, cv2.LINE_AA)

    def _draw_arm(self, img, side: int, upper: float, fore: float, clap: float | None = None):
        A, W = self.A, self.W
        sh = (int(W / 2 + side * 0.33 * A), int(0.86 * A))
        thick, r = int(0.14 * A), int(0.075 * A)
        if clap is not None:                                # hands meet in front of the chest
            hand = (int(W / 2 + side * (0.05 * A + 0.26 * A * (1 - clap))), int(1.08 * A))
            elbow = (int((sh[0] + hand[0]) / 2 + side * 0.10 * A), int((sh[1] + hand[1]) / 2 + 0.05 * A))
        else:
            a1, a2 = math.radians(upper), math.radians(upper + fore)
            elbow = (int(sh[0] + side * 0.34 * A * math.sin(a1)), int(sh[1] + 0.34 * A * math.cos(a1)))
            hand = (int(elbow[0] + side * 0.29 * A * math.sin(a2)), int(elbow[1] + 0.29 * A * math.cos(a2)))
        short = self.clothes in ("tShirt", "dress")
        self._limb(img, sh, elbow, thick, self.cloth)
        self._limb(img, elbow, hand, int(thick * 0.88), self.skin if short else self.cloth)
        o = max(2, int(A * 0.014))
        cv2.circle(img, hand, r + o, INK, -1, cv2.LINE_AA)
        cv2.circle(img, hand, r, self.skin, -1, cv2.LINE_AA)

    def _body(self, t: float, action: str | None, look: float) -> np.ndarray:
        A, W, H = self.A, self.W, self.H
        img = np.zeros((H, W, 3), np.uint8)
        o = max(2, int(A * 0.014))
        cx, hip = W // 2, int(A * 1.32)
        # legs + shoes (a little step when waving or counting)
        step = 0.02 * A * math.sin(2 * math.pi * 1.2 * t) if action in ("wave", "count") else 0.0
        for side in (-1, 1):
            x = int(cx + side * 0.12 * A)
            foot = int(A * 1.74 - (step if side > 0 else -step))
            self._limb(img, (x, hip), (x, foot), int(0.17 * A), self.legs)
            cv2.ellipse(img, (x + side * int(0.04 * A), foot + int(0.03 * A)), (int(0.15 * A) + o, int(0.06 * A) + o),
                        0, 0, 360, INK, -1, cv2.LINE_AA)
            cv2.ellipse(img, (x + side * int(0.04 * A), foot + int(0.03 * A)), (int(0.15 * A), int(0.06 * A)),
                        0, 0, 360, self.shoes, -1, cv2.LINE_AA)
        # torso or dress (under the face box's shoulders)
        top = int(A * 0.86)
        if self.clothes == "dress":
            poly = np.array([(cx - 0.30 * A, top), (cx + 0.30 * A, top), (cx + 0.46 * A, hip + 0.10 * A),
                             (cx - 0.46 * A, hip + 0.10 * A)], np.int32)
        else:
            poly = np.array([(cx - 0.38 * A, top), (cx + 0.38 * A, top), (cx + 0.31 * A, hip + 0.04 * A),
                             (cx - 0.31 * A, hip + 0.04 * A)], np.int32)
        cv2.fillPoly(img, [poly], self.cloth, cv2.LINE_AA)
        cv2.polylines(img, [poly], True, INK, o, cv2.LINE_AA)
        # arms (the face box's shoulders cover their tops)
        if action == "clap":
            k = (math.sin(2 * math.pi * 1.6 * t) + 1) / 2
            self._draw_arm(img, -1, 0, 0, clap=k)
            self._draw_arm(img, 1, 0, 0, clap=k)
        else:
            (lu, lf), (ru, rf) = self._arm_angles(t, action, look)
            self._draw_arm(img, -1, lu, lf)
            self._draw_arm(img, 1, ru, rf)
        return img

    def draw(self, t: float, mouth: float = 0.0, hop: float = 0.0, look: float = 0.0, viseme: str = "",
             action: str | None = None, mood: str | None = None) -> np.ndarray:
        tq = math.floor(t * FPS_POSE) / FPS_POSE            # on twos: 12 poses a second
        face = self.face_state(t, mouth, viseme, action, mood)
        k = (face, round(hop * 6) / 6, action, int(tq * FPS_POSE) % 240, 1 if look > 0.3 else (-1 if look < -0.3 else 0))
        if k in self._cache:
            self._cache.move_to_end(k)
            return self._cache[k]
        A, W, H = self.A, self.W, self.H
        body = self._body(tq, action, look)
        alpha = (body.max(axis=2) > 0).astype(np.uint8) * 255
        spr = np.dstack([body, alpha])
        # the face: a slight tilt toward who they look at + breathing bob
        f = self.faces[face]
        tilt = 4.0 * k[4]
        if tilt:
            m = cv2.getRotationMatrix2D((A / 2, A * 0.8), -tilt, 1.0)
            f = cv2.warpAffine(f, m, (A, A), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT,
                               borderValue=(0, 0, 0, 0))
        y0 = int(0.012 * A * math.sin(2 * math.pi * 0.4 * tq + self.phase))
        x0 = (W - A) // 2
        _over(spr, f, x0, max(0, y0))
        if hop > 0:                                          # stretch in the air, feet stay on the sprite's bottom
            h2 = int(H * (1 + 0.05 * hop))
            st = cv2.resize(spr, (W, h2), interpolation=cv2.INTER_LINEAR)
            spr = st[h2 - H:, :]
        self._cache[k] = spr
        if len(self._cache) > 500:
            self._cache.popitem(last=False)
        return spr


def _over(dst: np.ndarray, src: np.ndarray, x: int, y: int) -> None:
    """Alpha-composite BGRA src onto BGRA dst at (x, y), in place."""
    h, w = src.shape[:2]
    H, W = dst.shape[:2]
    x1, y1, x2, y2 = max(0, x), max(0, y), min(W, x + w), min(H, y + h)
    if x2 <= x1 or y2 <= y1:
        return
    s = src[y1 - y:y2 - y, x1 - x:x2 - x].astype(np.float32)
    d = dst[y1:y2, x1:x2].astype(np.float32)
    a = s[..., 3:4] / 255.0
    d[..., :3] = s[..., :3] * a + d[..., :3] * (1 - a)
    d[..., 3:4] = np.maximum(d[..., 3:4], s[..., 3:4])
    dst[y1:y2, x1:x2] = d.astype(np.uint8)
