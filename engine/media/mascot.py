"""Our own cute mascot, drawn by code (100% original — never copies any show's characters).

A round glossy blob with big sparkly eyes that blinks, squashes when it bounces and moves
its mouth with the voice (lip-sync from the audio loudness). Used by Brain Snack (#9)
and the kids channel (#10)."""
from __future__ import annotations

import math

import cv2
import numpy as np
import soundfile as sf


def _bgr(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return b, g, r


def mouth_track(wav_path, fps: int = 30, offset_s: float = 0.0) -> np.ndarray:
    """Mouth openness 0..1 per video frame, from the narration loudness."""
    audio, sr = sf.read(str(wav_path), dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    hop = int(sr / fps)
    n = len(audio) // hop
    rms = np.sqrt(np.mean(audio[: n * hop].reshape(n, hop) ** 2, axis=1))
    rms = rms / (np.percentile(rms, 95) + 1e-9)
    track = np.clip((rms - 0.08) * 1.4, 0, 1)
    track = np.convolve(track, np.ones(2) / 2, mode="same")
    pad = np.zeros(int(offset_s * fps))
    return np.concatenate([pad, track])


# ---------- lip-sync mouth shapes (research: kids_made_for_kids.md "clear mouth shapes for lip-sync") ----------
# The words are known (our own TTS lines), so each line is turned into sounds (misaki, the phonemizer Kokoro already
# uses) and each sound into one of a cartoon's classic mouth shapes. The sounds are spread over the line by its
# loudness: vowels are the loud part, so they land on the loud frames; lips close on m/b/p, round on oo/oh/w,
# stretch on ee/ay, show teeth on f/v and most other consonants. Idea from Rhubarb Lip Sync (MIT), done in-house.
VISEMES = ("rest", "closed", "fv", "round", "wide", "open", "teeth")
_SOUND = {**{c: "closed" for c in "mbp"}, **{c: "fv" for c in "fv"},
          **{c: "round" for c in "uʊwOɔYoQ"}, **{c: "wide" for c in "iɪᵻAɛe"},
          **{c: "open" for c in "aɑʌəɜæIWɐ"}}
_WEIGHT = {"closed": 1.0, "fv": 1.0, "teeth": 0.8, "round": 2.0, "wide": 2.0, "open": 2.2}
_LETTER = {**{c: "open" for c in "a"}, **{c: "wide" for c in "eiy"}, **{c: "round" for c in "ouw"},
           **{c: "closed" for c in "mbp"}, **{c: "fv" for c in "fv"}}
_G2P = None


def mouth_sounds(text: str) -> list[str]:
    """Mouth shapes for a line, in speaking order (word gaps are not shapes)."""
    global _G2P
    phones = ""
    try:
        if _G2P is None:
            from misaki import en
            _G2P = en.G2P(trf=False, british=False, fallback=None)
        phones = _G2P(text)[0] or ""
    except Exception:  # noqa: BLE001 - spelling is a fine fallback for a cartoon
        phones = ""
    out = []
    if phones:
        for ch in phones:
            if ch in "ˈˌː ,.!?;:-'\"…—":
                continue
            out.append(_SOUND.get(ch, "teeth"))
    else:
        for ch in text.lower():
            if ch.isalpha():
                out.append(_LETTER.get(ch, "teeth"))
    merged = []
    for s in out:                                        # "ee" twice in a row is one longer "ee"
        if not merged or merged[-1] != s or s == "closed":
            merged.append(s)
    return merged


def viseme_track(segments: list[tuple], audio: np.ndarray, sr: int, fps: int, threshold: float = 0.12) -> list[str]:
    """One mouth shape per video frame. segments: [(start_s, end_s, text)] of what this voice says."""
    hop = int(sr / fps)
    n = len(audio) // hop if hop else 0
    out = ["rest"] * n
    if n == 0:
        return out
    rms = np.sqrt(np.mean(audio[: n * hop].reshape(n, hop) ** 2, axis=1))
    loud = rms[rms > 1e-4]
    ref = np.percentile(loud, 95) if len(loud) else 1.0
    level = np.clip((rms / (ref + 1e-9) - 0.08) * 1.4, 0, 1)
    for start, end, text in segments:
        sounds = mouth_sounds(text)
        f0, f1 = max(0, int(start * fps)), min(n, int(np.ceil(end * fps)) + 1)
        if not sounds or f1 - f0 < 2:
            continue
        energy = rms[f0:f1] + 1e-6
        pos = np.cumsum(energy) - energy / 2
        pos = pos / pos[-1]                              # how far through the line's loudness each frame is
        w = np.array([_WEIGHT.get(s, 1.0) for s in sounds])
        edges = np.cumsum(w) / w.sum()
        for k, f in enumerate(range(f0, f1)):
            s = sounds[min(int(np.searchsorted(edges, pos[k])), len(sounds) - 1)]
            out[f] = s if (level[f] >= threshold or s == "closed") else "rest"
    return out


class Mascot:
    def __init__(self, size: int = 320, body: str = "#FF7AB8", outline: str = "#B0306A", seed: int = 0,
                 shape: str | None = None):
        """shape=None keeps the classic glossy blob (Brain Snack, story mascots).
        Toon shapes for the kids cast: "drop" (water-drop tip), "sprout" (leaf on top),
        "tall" (pill-shaped body), "ears" (two round ears); guests: "pointy" (kitten ears), "bunny" (long ears),
        "antenna" (two antennae) - soft shading and one ink outline."""
        self.size = size
        self.body, self.outline = _bgr(body), _bgr(outline)
        self.shape = shape
        self.rng = np.random.default_rng(seed)
        self.blinks = sorted(self.rng.uniform(0, 600, 220))
        self._cache: dict = {}

    def _blinking(self, t: float) -> bool:
        return any(0 <= t - b < 0.12 for b in self.blinks)

    def draw(self, t: float, mouth: float = 0.0, hop: float = 0.0, look: float = 0.0, viseme: str = "") -> np.ndarray:
        """BGRA sprite. mouth 0..1, hop 0..1 (jump/squash), look -1..1 (eyes left/right), viseme = a mouth shape
        from VISEMES (kids cast; empty = open/close by loudness only). Poses are rounded and cached."""
        key = (round(mouth * 5) / 5, round(hop * 6) / 6, round(look * 2) / 2, self._blinking(t),
               int((t * 3.0) % (2 * math.pi) / (2 * math.pi) * 10), viseme if self.shape else "")
        if key not in self._cache:
            if self.shape:
                self._cache[key] = self._draw_toon(key[4] / 10 * 2 * math.pi / 3.0, key[0], key[1], key[2], key[3],
                                                   key[5])
            else:
                self._cache[key] = self._draw(key[4] / 10 * 2 * math.pi / 3.0, key[0], key[1], key[2], key[3])
        return self._cache[key]

    def _draw_toon(self, t: float, mouth: float, hop: float, look: float, blink: bool, viseme: str = "") -> np.ndarray:
        """Flat 2D toon look: one silhouette mask (body + tip/ears/leaf), ink outline, soft top-to-bottom
        shading, gloss, big sparkly eyes and an open/closed mouth."""
        S, k = self.size, 2
        C = S * k
        img = np.zeros((C, C, 4), np.uint8)
        breathe = 0.025 * math.sin(t * 3.0)
        squash = 0.12 * math.sin(hop * math.pi) if hop else 0.0
        wf, hf = {"tall": (0.29, 0.38), "sprout": (0.33, 0.30)}.get(self.shape, (0.35, 0.32))
        rx = int(C * wf * (1 + breathe + squash))
        ry = int(C * hf * (1 - breathe - squash))
        foot = int(C * 0.90)
        cx, cy = C // 2, int(foot - ry - hop * C * 0.08)
        mask = np.zeros((C, C), np.uint8)
        cv2.ellipse(mask, (cx, cy), (rx, ry), 0, 0, 360, 255, -1, cv2.LINE_AA)
        if self.shape == "drop":                                     # water-drop tip, leaning a little
            tip = np.array([[cx - int(rx * 0.62), cy - int(ry * 0.62)], [cx + int(rx * 0.12), cy - int(ry * 1.45)],
                            [cx + int(rx * 0.62), cy - int(ry * 0.62)]], np.int32)
            cv2.fillPoly(mask, [tip], 255, cv2.LINE_AA)
        if self.shape == "ears":
            for sx in (-1, 1):
                cv2.circle(mask, (cx + sx * int(rx * 0.62), cy - int(ry * 0.80)), int(rx * 0.30), 255, -1, cv2.LINE_AA)
        if self.shape == "pointy":                                     # guest Kiki: two pointed (kitten) ears
            for sx in (-1, 1):
                ear = np.array([[cx + sx * int(rx * 0.22), cy - int(ry * 0.80)], [cx + sx * int(rx * 0.74), cy - int(ry * 1.40)],
                                [cx + sx * int(rx * 0.90), cy - int(ry * 0.42)]], np.int32)
                cv2.fillPoly(mask, [ear], 255, cv2.LINE_AA)
        if self.shape == "bunny":                                      # guest Hop: two long ears
            for sx in (-1, 1):
                cv2.ellipse(mask, (cx + sx * int(rx * 0.36), cy - int(ry * 1.12)), (int(rx * 0.16), int(ry * 0.45)),
                            sx * 10, 0, 360, 255, -1, cv2.LINE_AA)
        if self.shape in ("drop", "ears", "pointy", "bunny"):          # round off the joints (organic silhouette)
            soft = cv2.GaussianBlur(mask, (0, 0), C * 0.02).astype(np.float32)
            mask = np.clip((soft - 128) * 24 + 128, 0, 255).astype(np.uint8)
        ink = np.array((89, 58, 46), np.float32)                       # #2E3A59 in BGR
        outline = cv2.dilate(mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9 * k, 9 * k)))
        # contact shadow on the ground
        sh = np.zeros((C, C), np.uint8)
        cv2.ellipse(sh, (cx, foot + int(C * 0.02)), (int(rx * (0.95 - hop * 0.35)), int(C * 0.03)), 0, 0, 360, 70, -1,
                    cv2.LINE_AA)
        img[..., 3] = np.maximum(sh, outline)
        a = (outline.astype(np.float32) / 255)[..., None]
        img[..., :3] = (ink * a).astype(np.uint8)
        # body: soft shading from top (lighter) to bottom (darker)
        yy = np.linspace(0, 1, C, dtype=np.float32)[:, None, None]
        top_y, bot_y = (cy - ry * 1.5) / C, (cy + ry) / C
        g = np.clip((yy - top_y) / max(1e-3, bot_y - top_y), 0, 1)
        body = np.array(self.body, np.float32)
        light = np.minimum(255, body * 1.10 + 12)
        shade = body * 0.82
        col = light * (1 - g) + shade * g                              # C x 1 x 3
        m = (mask.astype(np.float32) / 255)[..., None]
        img[..., :3] = (img[..., :3] * (1 - m) + np.broadcast_to(col, (C, C, 3)) * m).astype(np.uint8)
        img[..., 3] = np.maximum(img[..., 3], mask)

        def ell(center, axes, color, alpha=255, start=0, end=360, thick=-1):
            # blend only inside the shape's bounding box (fast)
            pad = max(4, thick + 4)
            x0, y0 = max(center[0] - axes[0] - pad, 0), max(center[1] - axes[1] - pad, 0)
            x1, y1 = min(center[0] + axes[0] + pad + 1, C), min(center[1] + axes[1] + pad + 1, C)
            if x0 >= x1 or y0 >= y1:
                return
            layer = np.zeros((y1 - y0, x1 - x0), np.uint8)
            cv2.ellipse(layer, (center[0] - x0, center[1] - y0), axes, 0, start, end, alpha, thick, cv2.LINE_AA)
            la = (layer.astype(np.float32) / 255)[..., None]
            roi = img[y0:y1, x0:x1]
            roi[..., :3] = (roi[..., :3] * (1 - la) + np.array(color, np.float32) * la).astype(np.uint8)

        if self.shape == "ears":                                       # inner ears
            for sx in (-1, 1):
                ell((cx + sx * int(rx * 0.62), cy - int(ry * 0.80)), (int(rx * 0.15), int(rx * 0.15)), (175, 160, 255),
                    alpha=200)
        if self.shape == "pointy":                                     # inner ears
            for sx in (-1, 1):
                ell((cx + sx * int(rx * 0.62), cy - int(ry * 0.92)), (int(rx * 0.09), int(ry * 0.17)), (175, 160, 255),
                    alpha=200)
        if self.shape == "bunny":
            for sx in (-1, 1):
                ell((cx + sx * int(rx * 0.36), cy - int(ry * 1.12)), (int(rx * 0.07), int(ry * 0.32)), (175, 160, 255),
                    alpha=200)
        if self.shape == "antenna":                                    # guest Zip: two springy antennae
            for sx in (-1, 1):
                tip = (cx + sx * int(rx * 0.42), cy - ry - int(C * 0.10))
                cv2.line(img, (cx + sx * int(rx * 0.22), cy - ry + 6), tip, (*[int(v) for v in ink], 255), 4 * k,
                         cv2.LINE_AA)
                cv2.circle(img, tip, int(C * 0.032), (*[int(v) for v in ink], 255), -1, cv2.LINE_AA)
                cv2.circle(img, tip, int(C * 0.024), tuple(int(min(255, v * 1.15 + 30)) for v in self.body) + (255,), -1,
                           cv2.LINE_AA)
        if self.shape == "sprout":                                     # little leaf on a stem
            stem_top = (cx + int(rx * 0.05), cy - ry - int(C * 0.07))
            cv2.line(img, (cx, cy - ry + 4), stem_top, (*[int(v) for v in ink], 255), 4 * k, cv2.LINE_AA)
            for sx, ang in ((-1, -25), (1, 25)):
                lc = (stem_top[0] + sx * int(C * 0.045), stem_top[1] - int(C * 0.01))
                cv2.ellipse(img, lc, (int(C * 0.05), int(C * 0.024)), ang, 0, 360, (*[int(v) for v in ink], 255), -1,
                            cv2.LINE_AA)
                cv2.ellipse(img, lc, (int(C * 0.042), int(C * 0.017)), ang, 0, 360, (112, 215, 155, 255), -1,
                            cv2.LINE_AA)
        # gloss + cheeks
        ell((cx - int(rx * 0.38), cy - int(ry * 0.52)), (int(rx * 0.22), int(ry * 0.10)), (255, 255, 255), alpha=120)
        for sx in (-1, 1):
            ell((cx + sx * int(rx * 0.56), cy + int(ry * 0.20)), (int(rx * 0.13), int(ry * 0.08)), (175, 150, 255),
                alpha=105)
        # eyes
        eye_y = cy - int(ry * 0.14)
        for sx in (-1, 1):
            ex = cx + sx * int(rx * 0.34)
            if blink:
                cv2.ellipse(img, (ex, eye_y), (int(rx * 0.15), int(ry * 0.06)), 0, 0, 180, (*[int(v) for v in ink], 255),
                            4 * k, cv2.LINE_AA)
                continue
            ell((ex, eye_y), (int(rx * 0.19), int(ry * 0.26)), (255, 255, 255))
            ell((ex, eye_y), (int(rx * 0.19), int(ry * 0.26)), tuple(int(v) for v in ink), thick=2 * k)
            px = ex + int(look * rx * 0.06)
            ell((px, eye_y + int(ry * 0.04)), (int(rx * 0.12), int(ry * 0.17)), (60, 40, 40))
            ell((px - int(rx * 0.04), eye_y - int(ry * 0.05)), (int(rx * 0.045), int(rx * 0.045)), (255, 255, 255))
            ell((px + int(rx * 0.05), eye_y + int(ry * 0.08)), (int(rx * 0.02), int(rx * 0.02)), (255, 255, 255))
        # mouth: smile when quiet, open when talking; with a viseme, the classic cartoon mouth shapes
        my = cy + int(ry * 0.36)
        inkc = tuple(int(v) for v in ink)
        if viseme == "closed":                                       # m / b / p: lips pressed together
            cv2.ellipse(img, (cx, my - int(ry * 0.02)), (int(rx * 0.13), int(ry * 0.03)), 0, 0, 180,
                        (*inkc, 255), 4 * k, cv2.LINE_AA)
        elif mouth < 0.12 or viseme == "rest":
            cv2.ellipse(img, (cx, my - int(ry * 0.07)), (int(rx * 0.17), int(ry * 0.11)), 0, 15, 165,
                        (*inkc, 255), 4 * k, cv2.LINE_AA)
        else:
            shape = viseme or "open"
            size = {"open": (0.15 + 0.06 * mouth, 0.06 + 0.18 * mouth), "round": (0.08 + 0.03 * mouth, 0.07 + 0.13 * mouth),
                    "wide": (0.19 + 0.04 * mouth, 0.035 + 0.09 * mouth), "teeth": (0.15, 0.04 + 0.07 * mouth),
                    "fv": (0.14, 0.05 + 0.03 * mouth)}.get(shape, (0.15 + 0.06 * mouth, 0.06 + 0.18 * mouth))
            mw, mh = max(3, int(rx * size[0])), max(3, int(ry * size[1]))
            ell((cx, my), (mw + 2 * k, mh + 2 * k), inkc)
            ell((cx, my), (mw, mh), (60, 40, 140))
            if shape in ("wide", "teeth", "fv"):                      # upper teeth show
                cv2.ellipse(img, (cx, my - mh // 2), (int(mw * 0.82), max(2, mh // 2)), 0, 180, 360,
                            (255, 255, 255, 255), -1, cv2.LINE_AA)
            if shape == "fv":                                          # lower lip tucked under the teeth
                cv2.ellipse(img, (cx, my + mh // 2), (int(mw * 0.9), max(2, mh // 3)), 0, 0, 180,
                            (*inkc, 255), 3 * k, cv2.LINE_AA)
            if shape in ("open", "round"):
                ell((cx, my + mh // 2), (int(mw * 0.6), max(2, mh // 3)), (150, 130, 255))
        return cv2.resize(img, (S, S), interpolation=cv2.INTER_AREA)

    def _draw(self, t: float, mouth: float, hop: float, look: float, blink: bool) -> np.ndarray:
        S = self.size
        k = 2                                   # draw at 2x, then shrink = smooth edges
        C = S * k
        img = np.zeros((C, C, 4), np.uint8)
        breathe = 0.03 * math.sin(t * 3.0)
        squash = 0.12 * math.sin(hop * math.pi) if hop else 0.0
        rx = int(C * 0.36 * (1 + breathe + squash))
        ry = int(C * 0.34 * (1 - breathe - squash))
        cx, cy = C // 2, int(C * 0.56 - hop * C * 0.12)

        def ell(center, axes, color, thick=-1, alpha=255):
            # blend only inside the shape's bounding box (fast)
            x0, y0 = max(center[0] - axes[0] - 4, 0), max(center[1] - axes[1] - 4, 0)
            x1, y1 = min(center[0] + axes[0] + 5, C), min(center[1] + axes[1] + 5, C)
            if x0 >= x1 or y0 >= y1:
                return
            roi = img[y0:y1, x0:x1]
            layer = np.zeros_like(roi)
            cv2.ellipse(layer, (center[0] - x0, center[1] - y0), axes, 0, 0, 360, (*color, alpha), thick, cv2.LINE_AA)
            m = layer[..., 3:4].astype(np.float32) / 255
            roi[..., :3] = (layer[..., :3] * m + roi[..., :3] * (1 - m)).astype(np.uint8)
            roi[..., 3] = np.maximum(roi[..., 3], layer[..., 3])

        # shadow on the ground
        ell((C // 2, int(C * 0.93)), (int(rx * (0.9 - hop * 0.3)), int(C * 0.035)), (0, 0, 0), alpha=70)
        # body + outline + gloss
        ell((cx, cy), (rx + 7 * k, ry + 7 * k), self.outline)
        ell((cx, cy), (rx, ry), self.body)
        ell((cx - rx // 3, cy - ry // 2), (rx // 4, ry // 7), (255, 255, 255), alpha=110)
        # cheeks
        for sx in (-1, 1):
            ell((cx + sx * int(rx * 0.55), cy + int(ry * 0.18)), (int(rx * 0.14), int(ry * 0.08)), (150, 120, 255),
                alpha=150)
        # eyes
        eye_y = cy - int(ry * 0.18)
        for sx in (-1, 1):
            ex = cx + sx * int(rx * 0.36)
            if blink:
                cv2.ellipse(img, (ex, eye_y), (int(rx * 0.16), int(ry * 0.05)), 0, 0, 180, (40, 30, 30, 255),
                            4 * k, cv2.LINE_AA)
                continue
            ell((ex, eye_y), (int(rx * 0.2), int(ry * 0.26)), (255, 255, 255))
            px = ex + int(look * rx * 0.06)
            ell((px, eye_y + int(ry * 0.03)), (int(rx * 0.12), int(ry * 0.17)), (45, 30, 30))
            ell((px - int(rx * 0.04), eye_y - int(ry * 0.06)), (int(rx * 0.045), int(rx * 0.045)), (255, 255, 255))
            ell((px + int(rx * 0.05), eye_y + int(ry * 0.06)), (int(rx * 0.02), int(rx * 0.02)), (255, 255, 255))
        # mouth: smile when quiet, open "o" when talking
        my = cy + int(ry * 0.32)
        if mouth < 0.12:
            cv2.ellipse(img, (cx, my - int(ry * 0.06)), (int(rx * 0.2), int(ry * 0.12)), 0, 15, 165,
                        (40, 30, 60, 255), 5 * k, cv2.LINE_AA)
        else:
            mw, mh = int(rx * (0.17 + 0.06 * mouth)), int(ry * (0.06 + 0.2 * mouth))
            ell((cx, my), (mw, mh), (50, 30, 120))
            ell((cx, my + mh // 2), (int(mw * 0.6), max(2, mh // 3)), (140, 120, 255))
        return cv2.resize(img, (S, S), interpolation=cv2.INTER_AREA)
