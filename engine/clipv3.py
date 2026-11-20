"""Podcast clip renderer v3 (Hot Take HQ), built from the 2026 research spec:

- Active speaker found from mouth movement (YuNet face landmarks + mouth-region motion).
- Layout A: locked full-screen crop on the speaker (eyes at ~33% height), hard cut on real speaker turns
  (>= 1.2 s and 3+ words; backchannels like "yeah" ignored; >= 1.5 s per shot).
- Layout B: stacked split (two 1080x960 panes) during rapid back-and-forth (3+ turns within 8 s).
- Snap punch-ins (1.13x) on payoff words: held >= 3 s, >= 8 s apart, max 3 per 30 s; a cut resets zoom.
- Pauses over 450 ms are tightened to 200 ms (never mid-word).
- Hook headline in a white rounded box from frame 0; clean 2-3 word captions (white, thin outline, one
  accent colour on the spoken word); optional campaign disclosure pill ("Ad") from frame 0.
- Sound: 80 Hz high-pass + two-pass loudness to -14 LUFS; YouTube-recommended H.264 settings.
"""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .config import ROOT
from .media import ffmpeg
from .media.fonts import FONTS_DIR, ensure_fonts, font_file
from .media.shaping import pil_draw_text, pil_text_length
from engine.core.http import HTTP

OUT_W, OUT_H, FPS = 1080, 1920, 30
BACKCHANNEL = {"yeah", "yes", "yep", "right", "mm", "mhm", "mm-hm", "uh-huh", "okay", "ok", "wow", "sure", "true",
               "exactly", "totally", "huh", "oh", "ah", "haha", "really"}
CAPTION_FONT = "Poppins ExtraBold"


@dataclass
class Track:
    xs: list = field(default_factory=list)          # (t, cx, cy, w, h, eye_y)
    motion: dict = field(default_factory=dict)      # t -> mouth motion energy

    def median_box(self, t0: float, t1: float):
        pts = [p for p in self.xs if t0 - 0.2 <= p[0] <= t1 + 0.2] or self.xs
        arr = np.array([p[1:] for p in pts])
        return np.median(arr, axis=0) if len(arr) else None


# ---------- timing: tighten pauses ----------

def build_segments(words: list, start: float, end: float, max_gap: float = 0.45, keep: float = 0.2):
    """[(src_a, src_b)] keeping speech and shortening long pauses to `keep` seconds."""
    ws = [w for w in words if start <= w.start < end]
    if not ws:
        return [(start, end)]
    segs, a = [], max(start, ws[0].start - 0.12)
    for w0, w1 in zip(ws, ws[1:]):
        if w1.start - w0.end > max_gap:
            segs.append((a, w0.end + keep / 2))
            a = w1.start - keep / 2
    segs.append((a, min(end, ws[-1].end + 0.18)))
    return [(x, y) for x, y in segs if y - x > 0.05]


class TimeMap:
    def __init__(self, segs):
        self.segs = segs
        self.out_starts = np.cumsum([0.0] + [b - a for a, b in segs])[:-1]
        self.duration = float(sum(b - a for a, b in segs))

    def to_out(self, t: float) -> float:
        for (a, b), o in zip(self.segs, self.out_starts):
            if t < a:
                return float(o)
            if t <= b:
                return float(o + t - a)
        return self.duration

    def to_src(self, t: float) -> float:
        for (a, b), o in zip(self.segs, self.out_starts):
            if t <= o + (b - a):
                return float(a + max(0.0, t - o))
        return self.segs[-1][1]


# ---------- faces and active speaker ----------

def _detector(w: int, h: int):
    model = ROOT / "assets" / "models" / "face_detection_yunet_2023mar.onnx"
    if not model.exists():
        from .clips import YUNET_URL
        import requests
        model.parent.mkdir(parents=True, exist_ok=True)
        model.write_bytes(HTTP.get(YUNET_URL, timeout=120).content)
    return cv2.FaceDetectorYN.create(str(model), "", (w, h), 0.7, 0.3, 5000)


@dataclass
class Scene:
    """What one look through the clip found: speaker tracks, the frame size, every face per sampled frame
    (cx, cy, w, h, eye_y as 0-1 fractions) and a 64x36 grey thumbnail per sampled frame (for motion)."""
    tracks: list
    size: tuple
    faces: list = field(default_factory=list)       # [(t, [(cx, cy, w, h, eye_y), ...])]
    thumbs: list = field(default_factory=list)      # [(t, 36x64 float32)]


def analyse(video: Path, start: float, end: float, fps: float = 10.0) -> Scene:
    cap = cv2.VideoCapture(str(video))
    w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    scale = 640 / w
    sh = int(h * scale)
    det = _detector(640, sh)
    tracks: list[Track] = []
    seen: list = []
    thumbs: list = []
    prev_mouth: dict[int, np.ndarray] = {}
    cap.set(cv2.CAP_PROP_POS_MSEC, start * 1000)
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 30
    step = max(1, int(round(src_fps / fps)))
    fi, t = 0, start
    while t < end:
        ok, frame = cap.read()
        if not ok:
            break
        t = start + fi / src_fps
        fi += 1
        if (fi - 1) % step:
            continue
        small = cv2.resize(frame, (640, sh))
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        thumbs.append((t, cv2.resize(gray, (64, 36), interpolation=cv2.INTER_AREA).astype(np.float32)))
        _, faces = det.detect(small)
        seen.append((t, []))
        for f in (faces if faces is not None else []):
            x, y, fw, fh = f[:4]
            cx, cy = (x + fw / 2) / 640, (y + fh / 2) / sh
            eye_y = ((f[5] + f[7]) / 2) / sh
            seen[-1][1].append((float(cx), float(cy), float(fw / 640), float(fh / sh), float(eye_y)))
            # assign to the nearest existing track by x position
            best, bd = None, 0.14
            for k, tr in enumerate(tracks):
                if tr.xs and abs(tr.xs[-1][1] - cx) < bd:
                    best, bd = k, abs(tr.xs[-1][1] - cx)
            if best is None:
                tracks.append(Track())
                best = len(tracks) - 1
            tracks[best].xs.append((t, cx, cy, fw / 640, fh / sh, eye_y))
            # mouth region: between the mouth corners, extended down
            mx0, mx1 = int(min(f[10], f[12]) - fw * 0.08), int(max(f[10], f[12]) + fw * 0.08)
            my0, my1 = int(min(f[11], f[13]) - fh * 0.08), int(max(f[11], f[13]) + fh * 0.22)
            mx0, my0 = max(0, mx0), max(0, my0)
            crop = gray[my0:my1, mx0:mx1]
            if crop.size > 20:
                m = cv2.resize(crop, (32, 16)).astype(np.float32)
                m = (m - m.mean()) / (m.std() + 1e-3)
                if best in prev_mouth:
                    tracks[best].motion[round(t, 2)] = float(np.abs(m - prev_mouth[best]).mean())
                prev_mouth[best] = m
    cap.release()
    tracks = [tr for tr in tracks if len(tr.xs) >= max(4, 0.15 * fps * (end - start))]
    tracks.sort(key=lambda tr: np.median([p[1] for p in tr.xs]))     # left to right
    return Scene(tracks, (w, h), seen, thumbs)


# ---------- moving pictures and stream webcams (round 12, ideas from reviewing SupoClip) ----------
# Pause tightening is a podcast trick: on a still camera a cut is invisible. On gameplay, sport or a moving camera
# the same cut makes the picture jump, and a silent stretch is often the action itself, so pauses stay.
# Measured 13 Nov (64x36 grey, 10 samples/s, median change per sample): DVIDS interview 0.30 (its pauses 0.26-1.14);
# stock clips with camera moves 1.39 / 2.40, slow Ken Burns pan 1.49, Brain Snack game 3.30, Mandelbrot zoom 3.27.
MOVING_MEDIAN = 1.0
# Streams: the streamer's webcam on top (top third), the game cropped to the action below, captions in the band
# between them (research 13 Nov: Cut.Pro gameplay guide 2026; Twitch's own clip editor stacks camera + game).
CAM_PANE_H = 640
GAME_PANE_H = OUT_H - CAM_PANE_H
STREAM_CAPTION_Y = CAM_PANE_H + 210      # just under the seam: the hook covers the seam for its first seconds
WEBCAM_MAX_FACE_H = 0.2          # a webcam inset face is small: fixtures 0.085 / 0.11 of the height; studio 0.385
WEBCAM_SIDE = 0.35               # its centre sits in the outer 35% on the left or right
WEBCAM_MIN_SHARE = 0.5           # and is found in at least half of the sampled frames
WEBCAM_CELL = 0.04               # the busiest spot (faces within 4% of the frame) ...
WEBCAM_ROAM = 0.10               # ... and the streamer may lean around it (fixture with a camera cut: 0.08 apart)


def motion_values(thumbs: list, region: tuple | None = None) -> list[float]:
    """Mean grey change between neighbouring samples, optionally inside region (x0, y0, x1, y1) as 0-1."""
    out = []
    for (_, a), (_, b) in zip(thumbs, thumbs[1:]):
        if region:
            x0, y0, x1, y1 = region
            ys, xs = slice(int(y0 * a.shape[0]), int(y1 * a.shape[0])), slice(int(x0 * a.shape[1]), int(x1 * a.shape[1]))
            a, b = a[ys, xs], b[ys, xs]
        out.append(float(np.abs(b - a).mean()))
    return out


def moving_picture(thumbs: list, region: tuple | None = None) -> bool:
    vals = motion_values(thumbs, region)
    return bool(vals) and float(np.median(vals)) > MOVING_MEDIAN


def find_webcam(scene: Scene) -> dict | None:
    """A streamer's webcam inset: one small face that stays at the same spot on the left or right in most sampled
    frames while the middle of the picture keeps moving (the game). Faces inside the game move around and are
    ignored. Returns {"face": (cx, cy, w, h, eye_y), "share": 0-1} or None."""
    n = len(scene.faces)
    if n < 8:
        return None
    cands = [(i, f) for i, (_, fs) in enumerate(scene.faces) for f in fs
             if f[3] <= WEBCAM_MAX_FACE_H and (f[0] <= WEBCAM_SIDE or f[0] >= 1 - WEBCAM_SIDE)]
    best = None
    for _, f0 in cands[::max(1, len(cands) // 150)]:                  # try each spot (sampled when there are many)
        members = [(i, f) for i, f in cands if abs(f[0] - f0[0]) <= WEBCAM_CELL and abs(f[1] - f0[1]) <= WEBCAM_CELL]
        frames = len({i for i, _ in members})
        if best is None or frames > best[0]:
            best = (frames, members)
    if not best:
        return None
    spot = np.median(np.array([f for _, f in best[1]]), axis=0)
    members = [(i, f) for i, f in cands if abs(f[0] - spot[0]) <= WEBCAM_ROAM and abs(f[1] - spot[1]) <= WEBCAM_ROAM]
    share = len({i for i, _ in members}) / n
    if share < WEBCAM_MIN_SHARE:
        return None
    face = tuple(float(v) for v in np.median(np.array([f for _, f in members]), axis=0))
    if not moving_picture(scene.thumbs, (0.3, 0.15, 0.7, 0.85)):     # a still middle = a studio, not a game
        return None
    return {"face": face, "share": round(share, 2)}


STEP_W = 8                       # analysis pixels compared on each side of a candidate border
STEP_MIN = 5.0                   # grey levels of extra change on the game side ...
STEP_RATIO = 1.6                 # ... and at least 1.6x the change inside the webcam


def _border(change: np.ndarray, edges: np.ndarray, lo: int, hi: int, game_before: bool, need_edge: bool = False):
    """Where 'keeps changing' (the game) turns into 'mostly still' (the webcam) inside [lo, hi), or None.
    change: time-variation profile; edges: persistent-edge profile used to land on the exact line.
    game_before: the game lies at lower indices than the webcam. need_edge: also demand a persistent line there
    (outer borders: moving hands at the bottom of a webcam change a lot too, but leave no fixed line)."""
    lo, hi = max(STEP_W, int(lo)), min(len(change) - STEP_W, int(hi))
    best = None
    for i in range(lo, hi):
        g, c = (change[i - STEP_W:i], change[i:i + STEP_W]) if game_before else (change[i:i + STEP_W], change[i - STEP_W:i])
        g, c = float(g.mean()), float(c.mean())
        if g - c >= STEP_MIN and g >= STEP_RATIO * c and (best is None or g - c > best[0]):
            best = (g - c, i)
    if best is None:
        return None
    i = best[1]
    near = edges[max(0, i - 4):i + 5]
    j = max(0, i - 4) + int(np.argmax(near)) if len(near) else i
    if need_edge and edges[j] < 2.0 * float(np.median(edges)):
        return None
    return j


def webcam_rect(video: Path, start: float, end: float, face: tuple, size: tuple, samples: int = 15):
    """The webcam inset (x0, y0, x1, y1) in source pixels and whether its border was found.
    The game behind the inset keeps changing while the webcam picture (a person in a room) barely does, so the
    border is where the change over time drops; the strongest persistent edge there gives the exact line.
    Without a clear border the box is estimated from the face (typical framing: face ~1/3 of a 16:9 inset)."""
    w, h = size
    sh = int(round(h * 640 / w))
    cap = cv2.VideoCapture(str(video))
    frames = []
    for t in np.linspace(start, end, samples, endpoint=False):
        cap.set(cv2.CAP_PROP_POS_MSEC, float(t) * 1000)
        ok, f = cap.read()
        if ok:
            frames.append(cv2.cvtColor(cv2.resize(f, (640, sh), interpolation=cv2.INTER_AREA),
                                       cv2.COLOR_BGR2GRAY).astype(np.float32))
    cap.release()
    cx, cy, fw, fh = face[0] * 640, face[1] * sh, face[2] * 640, face[3] * sh
    right, top = face[0] > 0.5, face[1] < 0.5
    eh = min(sh * 0.6, fh * 3.2)
    ew = min(640 * 0.45, eh * 16 / 9)
    box = [cx - ew / 2, cy - 0.45 * eh, cx + ew / 2, cy + 0.55 * eh]
    found = False
    if len(frames) >= 5:
        st = np.stack(frames)
        change = st.std(0)
        ex = np.mean([np.abs(cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3)) for g in frames], axis=0)
        ey = np.mean([np.abs(cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3)) for g in frames], axis=0)
        rows = slice(max(0, int(cy - (1.0 if top else 1.6) * fh)), max(1, min(sh, int(cy + (1.6 if top else 1.0) * fh))))
        cprof, eprof = change[rows].mean(0), ex[rows].mean(0)
        margin = int(0.08 * 640)                         # an inset may sit a little away from the frame edge
        if right:
            inner = _border(cprof, eprof, max(320, cx - 6 * fw), cx - 0.55 * fw, game_before=True)
            outer = _border(cprof, eprof, 640 - margin, 640, game_before=False, need_edge=True)
        else:
            inner = _border(cprof, eprof, cx + 0.55 * fw, min(320, cx + 6 * fw), game_before=False)
            outer = _border(cprof, eprof, 0, margin, game_before=True, need_edge=True)
        if inner is not None:
            found = True
            box[0], box[2] = (inner, outer if outer is not None else 640) if right else (outer or 0, inner)
        cols = slice(max(0, int(min(box[0], box[2]))), max(1, min(640, int(max(box[0], box[2])))))
        rprof, eprof = change[:, cols].mean(1), ey[:, cols].mean(1)
        hmargin = int(0.08 * sh)
        if top:
            hin = _border(rprof, eprof, cy + 0.55 * fh, min(sh, cy + 6 * fh), game_before=False)
            hout = _border(rprof, eprof, 0, hmargin, game_before=True, need_edge=True)
        else:
            hin = _border(rprof, eprof, max(0, cy - 6 * fh), cy - 0.55 * fh, game_before=True)
            hout = _border(rprof, eprof, sh - hmargin, sh, game_before=False, need_edge=True)
        if hin is not None:
            found = True
            box[1], box[3] = (hout or 0, hin) if top else (hin, hout if hout is not None else sh)
    if not found:
        return webcam_rect_estimate(face, size), False
    x0, x1 = sorted((max(0.0, box[0]), min(640.0, box[2])))
    y0, y1 = sorted((max(0.0, box[1]), min(float(sh), box[3])))
    area = (x1 - x0) * (y1 - y0) / (640 * sh)
    if not (x0 <= cx <= x1 and y0 <= cy <= y1 and 0.015 <= area <= 0.3):
        return webcam_rect_estimate(face, size), False
    s = w / 640
    return (int(x0 * s), int(y0 * s), int(x1 * s), int(y1 * s)), True


def webcam_rect_estimate(face: tuple, size: tuple) -> tuple:
    w, h = size
    eh = min(h * 0.6, face[3] * h * 3.2)
    ew = min(w * 0.45, eh * 16 / 9)
    cx, cy = face[0] * w, face[1] * h
    x0, y0 = min(max(cx - ew / 2, 0), w - ew), min(max(cy - 0.45 * eh, 0), h - eh)
    return int(x0), int(y0), int(x0 + ew), int(y0 + eh)


def stream_crops(rect: tuple, face: tuple, size: tuple) -> tuple[tuple, tuple]:
    """(webcam crop, game crop) as (x0, y0, cw, ch) source boxes for the 1080x640 and 1080x1280 panes."""
    w, h = size
    x0, y0, x1, y1 = rect
    rw, rh = max(2, x1 - x0), max(2, y1 - y0)
    asp = OUT_W / CAM_PANE_H
    if rw / rh > asp:                                   # wide inset: trim the sides, keep the face centred
        cw, ch = rh * asp, rh
    else:                                               # tall inset: trim top/bottom, eyes at 40% of the pane
        cw, ch = rw, rw / asp
    fx, ey = face[0] * w, face[4] * h
    cx0 = min(max(fx - cw / 2, x0), x1 - cw)
    cy0 = min(max(ey - 0.40 * ch, y0), y1 - ch)
    cam = (int(cx0), int(cy0), int(cw), int(ch))
    gasp = OUT_W / GAME_PANE_H
    gh = h
    gw = gh * gasp
    if gw > w:
        gw, gh = w, w / gasp
    gx = (w - gw) / 2                                   # the action (crosshair) sits in the middle of the screen
    shift = 0.12 * w                                    # step aside from the webcam, at most 12% of the width
    if face[0] > 0.5 and gx + gw > x0:
        gx = max(gx - shift, x0 - gw)
    elif face[0] <= 0.5 and gx < x1:
        gx = min(gx + shift, x1)
    gx = min(max(gx, 0), w - gw)
    return cam, (int(gx), int((h - gh) / 2), int(gw), int(gh))


def _sharpen(img: np.ndarray) -> np.ndarray:
    """Gentle unsharp mask for a small webcam blown up to the top pane."""
    return cv2.addWeighted(img, 1.4, cv2.GaussianBlur(img, (0, 0), 1.1), -0.4, 0)


def speakers_per_word(words: list, tracks: list[Track]) -> list[int]:
    if len(tracks) <= 1:
        return [0] * len(words)
    out, prev = [], 0
    for wd in words:
        scores = []
        for tr in tracks:
            vals = [v for t, v in tr.motion.items() if wd.start - 0.15 <= t <= wd.end + 0.15]
            scores.append(np.mean(vals) if vals else 0.0)
        best = int(np.argmax(scores))
        srt = sorted(scores, reverse=True)
        if srt[0] > 0 and (len(srt) < 2 or srt[0] > srt[1] * 1.15):
            prev = best
        out.append(prev)
    return out


def make_shots(words: list, spk: list[int], n_tracks: int, total: float) -> list[dict]:
    """Shots in OUTPUT time: {'t0','t1','layout': 'A'|'B','speaker'}. Applies the turn rules."""
    if not words:
        return [{"t0": 0.0, "t1": total, "layout": "A", "speaker": 0}]
    turns = []
    for wd, s in zip(words, spk):
        if turns and turns[-1]["speaker"] == s:
            turns[-1]["t1"], turns[-1]["n"] = wd.end, turns[-1]["n"] + 1
            turns[-1]["words"].append(wd.text)
        else:
            turns.append({"speaker": s, "t0": wd.start, "t1": wd.end, "n": 1, "words": [wd.text]})
    merged = []
    for tn in turns:                                   # backchannels / tiny turns stay on the previous shot
        tiny = tn["t1"] - tn["t0"] < 1.2 or tn["n"] < 3
        backch = all(re.sub(r"[^\w-]", "", x.lower()) in BACKCHANNEL for x in tn["words"])
        if merged and (tiny or backch):
            merged[-1]["t1"] = tn["t1"]
        else:
            merged.append(dict(tn))
    coalesced = []                                     # same speaker twice in a row = one turn
    for tn in merged:
        if coalesced and coalesced[-1]["speaker"] == tn["speaker"]:
            coalesced[-1]["t1"] = tn["t1"]
        else:
            coalesced.append(tn)
    merged = coalesced
    shots = []
    for k, tn in enumerate(merged):
        t0 = 0.0 if k == 0 else tn["t0"]
        t1 = merged[k + 1]["t0"] if k + 1 < len(merged) else total
        shots.append({"t0": t0, "t1": t1, "layout": "A", "speaker": tn["speaker"]})
    # rapid exchange -> stacked split until a turn longer than 5 s
    if n_tracks >= 2:
        for k in range(len(shots)):
            window = [s for s in shots if shots[k]["t0"] <= s["t0"] < shots[k]["t0"] + 8.0]
            if len(window) >= 3:
                for s in window:
                    if s["t1"] - s["t0"] <= 5.0:
                        s["layout"] = "B"
    # minimum shot length 1.5 s; merge equal neighbours
    out = []
    for s in shots:
        if out and (s["t1"] - s["t0"] < 1.5 or (s["layout"] == "B" and out[-1]["layout"] == "B")
                    or (s["layout"] == out[-1]["layout"] == "A" and s["speaker"] == out[-1]["speaker"])):
            out[-1]["t1"] = s["t1"]
        else:
            out.append(s)
    return out


def plan_punches(words: list, emphasis: set[str], shots: list[dict], total: float) -> list[tuple[float, float]]:
    """[(t_start, t_end)] snap punch-ins on payoff words; reset at cuts; spacing rules from the spec."""
    cuts = [s["t0"] for s in shots[1:]]
    out = []
    for wd in words:
        key = re.sub(r"[^\w]", "", wd.text.lower())
        if key not in emphasis:
            continue
        t0 = wd.start
        if out and t0 - out[-1][0] < 8.0:
            continue
        if sum(1 for a, _ in out if t0 - a < 30) >= 3:
            continue
        shot = next((s for s in shots if s["t0"] <= t0 < s["t1"]), None)
        if not shot or shot["layout"] != "A":
            continue
        # held until the next cut (owner 15 Nov: a punch that let go mid-shot read as zoom in, zoom out)
        t1 = min(total, min([c for c in cuts if c > t0], default=total))
        if t1 - t0 >= 2.0:
            out.append((t0, t1))
    return out


# ---------- overlays ----------

def _font(size: int, family: str = CAPTION_FONT):
    return ImageFont.truetype(str(font_file(family)), size)


def hook_box(text: str, max_w: int = 860, min_w: int = 0, min_h: int = 0) -> np.ndarray:
    """White rounded box with black text (TikTok-native look), BGRA. min_w/min_h: never smaller than a box
    it has to cover (Reel versions swap the hook wording)."""
    size = 68
    while True:
        font = _font(size)
        words, lines, cur = text.split(), [], ""
        for wd in words:
            trial = f"{cur} {wd}".strip()
            if cur and pil_text_length(None, trial, font) > max_w - 56:
                lines.append(cur)
                cur = wd
            else:
                cur = trial
        lines.append(cur)
        if len(lines) <= 2 or size <= 46:
            break
        size -= 4
    asc, desc = font.getmetrics()
    lh = int((asc + desc) * 1.02)
    bw = max(int(max(pil_text_length(None, ln, font) for ln in lines)) + 56, min_w - 16)
    bh = max(lh * len(lines) + 30, min_h - 16)
    top = (bh - (lh * len(lines) + 30)) // 2
    img = Image.new("RGBA", (bw + 16, bh + 16), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((8, 10, bw + 8, bh + 10), radius=24, fill=(0, 0, 0, 70))        # soft drop shadow
    d.rounded_rectangle((8, 6, bw + 8, bh + 6), radius=22, fill=(255, 255, 255, 255))
    for i, ln in enumerate(lines):
        x = 8 + (bw - pil_text_length(None, ln, font)) / 2
        pil_draw_text(img, (x, 6 + 14 + top + i * lh), ln, font, (10, 10, 10, 255))
    arr = np.array(img)
    return np.ascontiguousarray(arr[..., [2, 1, 0, 3]])


HOOK_SECONDS = 2.6
END_SECONDS = 3.0      # campaign end line ("Watch live: kick.com/...") shows this long at the end


def _splits(n: int, k: int) -> list[list[tuple[int, int]]]:
    """All ways to cut n words into k non-empty consecutive rows."""
    if k == 1:
        return [[(0, n)]]
    out = []
    for i in range(1, n - k + 2):
        for rest in _splits(n - i, k - 1):
            out.append([(0, i)] + [(a + i, b + i) for a, b in rest])
    return out


def hook_text(text: str, size: int = 72, max_w: int = 860) -> np.ndarray:   # podcast spec: 64-72 px, 860 px wide
    """Clean white hook text (thin dark outline + soft shadow), no box, at most 2 lines. BGRA."""
    from .snack.canvas import text_sprite
    from PIL import ImageFont
    from .media.fonts import font_file
    words = text.split()
    while True:                             # balanced rows that fit max_w; 3 rows before shrinking (cap ~0.71 x size)
        f = ImageFont.truetype(str(font_file(CAPTION_FONT)), size)
        fits = lambda r: f.getlength(r) <= max_w
        rows = None
        for n in (1, 2):                    # research: at most 2 lines
            if len(words) < n:
                break
            best = None
            for cuts in _splits(len(words), n):
                parts = [" ".join(words[a:b]) for a, b in cuts]
                if all(fits(x) for x in parts):
                    score = max(f.getlength(x) for x in parts)
                    if best is None or score < best[0]:
                        best = (score, parts)
            if best:
                rows = best[1]
                break
        if rows or size <= 56:
            rows = rows or [text]
            break
        size -= 6
    return text_sprite("\n".join(rows), CAPTION_FONT, size, fill="#FFFFFF", stroke=5, stroke_fill="#000000",
                       shadow=6)            # research variant B: no box, white text, 5 px black outline


def pill(text: str, size: int = 42) -> np.ndarray:
    font = _font(size)
    w = int(font.getlength(text)) + 40
    asc, desc = font.getmetrics()
    h = asc + desc + 18
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, w - 1, h - 1), radius=h // 2, fill=(0, 0, 0, 153))
    d.text((20, 9), text, font=font, fill=(255, 255, 255, 255))
    arr = np.array(img)
    return np.ascontiguousarray(arr[..., [2, 1, 0, 3]])


def brand_logo(path, max_w: int = 230, max_h: int = 150) -> np.ndarray | None:
    """The campaign's logo as a BGRA sprite (top right, below the platforms' top bar, clear of the hook)."""
    if not path or not Path(path).exists():
        return None
    im = Image.open(path).convert("RGBA")
    im.thumbnail((max_w, max_h), Image.LANCZOS)
    arr = np.array(im)
    return arr[..., [2, 1, 0, 3]].copy()


def _blit(frame, spr, x, y):
    h, w = spr.shape[:2]
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(frame.shape[1], x + w), min(frame.shape[0], y + h)
    if x1 <= x0 or y1 <= y0:
        return
    s = spr[y0 - y:y1 - y, x0 - x:x1 - x]
    a = s[..., 3:4].astype(np.float32) / 255
    roi = frame[y0:y1, x0:x1]
    roi[:] = (roi * (1 - a) + s[..., :3] * a).astype(np.uint8)


# ---------- captions (ASS) ----------

def _ass_color(hex_color: str, alpha: int = 0) -> str:
    h = hex_color.lstrip("#")
    return f"&H{alpha:02X}{h[4:6]}{h[2:4]}{h[0:2]}".upper()


def build_captions(words: list, shots: list[dict], path: Path, accent: str = "#FF6A3D", size: int = 150) -> Path:
    """2-3 word chunks (<= 18 chars), white with 4 px outline, active word in the accent colour,
    92% -> 100% scale-in over 100 ms. Position follows the layout (below the chin / split seam)."""
    merged = []                               # the transcript splits "meet-and-greet" into meet / -and / -greet
    for wd in words:
        if merged and wd.text.startswith("-"):
            p = merged[-1]
            merged[-1] = type(p)(p.text + wd.text, p.start, wd.end)
        else:
            merged.append(wd)
    words = merged
    chunks, cur = [], []
    for wd in words:
        text = " ".join(x.text for x in cur + [wd])
        if cur and (len(cur) >= 3 or len(text) > 14 or re.search(r"[.!?,;:]$", cur[-1].text)):
            chunks.append(cur)
            cur = []
        cur.append(wd)
    if cur:
        chunks.append(cur)
    lines = ["[Script Info]", "ScriptType: v4.00+", f"PlayResX: {OUT_W}", f"PlayResY: {OUT_H}", "WrapStyle: 2", "",
             "[V4+ Styles]",
             "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, "
             "Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
             "MarginL, MarginR, MarginV, Encoding",
             f"Style: Cap,{CAPTION_FONT},{size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,4,2,"
             "5,40,40,0,1", "", "[Events]",
             "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]

    def ts(t):
        t = max(0.0, t)
        return f"{int(t // 3600)}:{int(t % 3600 // 60):02d}:{t % 60:05.2f}"

    acc = _ass_color(accent)
    for ci, ch in enumerate(chunks):
        c0 = ch[0].start - 0.05
        c1 = chunks[ci + 1][0].start - 0.05 if ci + 1 < len(chunks) else ch[-1].end + 0.3
        if c1 - ch[-1].end > 0.4:                       # long gap: let the caption go away
            c1 = ch[-1].end + 0.25
        c1 = max(c1, c0 + 0.3)
        shot = next((s for s in shots if s["t0"] <= ch[0].start < s["t1"]), shots[-1])
        y = {"B": 960, "S": STREAM_CAPTION_Y}.get(shot["layout"], 1150)  # research: ~60% height, below the chin
        for wi, wd in enumerate(ch):
            s0 = c0 if wi == 0 else wd.start
            s1 = ch[wi + 1].start if wi + 1 < len(ch) else c1
            if s1 <= s0:
                continue
            parts = []
            for k, x in enumerate(ch):
                txt = x.text.replace("{", "(").replace("}", ")")
                parts.append(f"{{\\1c{acc}}}{txt}{{\\1c&H00FFFFFF&}}" if k == wi else txt)
            anim = r"\fscx92\fscy92\t(0,100,\fscx100\fscy100)\fad(60,0)" if wi == 0 else ""
            lines.append(f"Dialogue: 0,{ts(s0)},{ts(s1)},Cap,,0,0,0,,{{\\an5\\pos({OUT_W // 2},{y}){anim}}}"
                         + " ".join(parts))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


# ---------- render ----------

def lower_third_top(video: Path, start: float, end: float, step: float = 1.0) -> float:
    """Top of the source's own burned-in name tag / lower third (0-1 of the height), or 1.0 when there is none.
    A name tag = dense white text in the bottom band that is absent higher up. Our vertical crop would cut it in half
    (owner saw a cropped 'IGUEZ' tag), so the crop stops above it."""
    cap = cv2.VideoCapture(str(video))
    top = 1.0
    try:
        for t in np.arange(start, end, step):
            cap.set(cv2.CAP_PROP_POS_MSEC, float(t) * 1000)
            ok, f = cap.read()
            if not ok:
                break
            hsv = cv2.cvtColor(f, cv2.COLOR_BGR2HSV)
            gx = np.abs(cv2.Sobel(cv2.cvtColor(f, cv2.COLOR_BGR2GRAY), cv2.CV_32F, 1, 0, ksize=3))
            white = (hsv[..., 2] > 215) & (hsv[..., 1] < 50) & (gx > 80)
            H = f.shape[0]
            rows = white.mean(1)
            band, mid = rows[int(H * 0.66):int(H * 0.96)], rows[int(H * 0.30):int(H * 0.60)]
            if band.mean() > 0.004 and band.mean() > 4 * mid.mean():
                hits = np.nonzero(rows[int(H * 0.60):] > 0.01)[0]
                if len(hits):
                    top = min(top, (int(H * 0.60) + hits[0]) / H - 0.03)
    finally:
        cap.release()
    return max(0.6, top) if top < 1.0 else 1.0


def _crop_for(box, w, h, zoom: float = 1.0, pane_aspect: float = 9 / 16, eye_frac: float = 0.39,
              face_frac: float | None = None, bottom: float = 1.0):
    """Source crop (x0, y0, cw, ch) keeping the face centred and eyes at eye_frac of the output height.
    bottom: the crop never goes below this fraction of the height (keeps burned-in name tags out)."""
    cx, cy, fw, fh, eye_y = box
    if face_frac:                                       # pane crops size from the face height
        ch = min(h, max(fh * h / face_frac, 0.4 * h)) / zoom
    else:
        ch = h / zoom
    ch = min(ch, bottom * h)
    cw = ch * pane_aspect
    if cw > w:
        cw, ch = w, w / pane_aspect
    x0 = min(max(cx * w - cw / 2, 0), w - cw)
    y0 = min(max(eye_y * h - eye_frac * ch, 0), bottom * h - ch)
    return int(x0), int(y0), int(cw), int(ch)


def render_clip_v3(video: Path, moment: dict, words: list, out_path: Path, style: dict, hook: str | None = None,
                   campaign: dict | None = None, log=print) -> Path:
    ensure_fonts()
    start, end = moment["start"], moment["end"]
    clip_words = [w for w in words if start <= w.start < end]
    scene = analyse(video, start, end)
    tracks, (w, h) = scene.tracks, scene.size
    webcam = find_webcam(scene)
    stream = None
    if webcam:                                   # stream: webcam on top, the game below, for the whole clip
        rect, found = webcam_rect(video, start, end, webcam["face"], (w, h))
        cam_box, game_box = stream_crops(rect, webcam["face"], (w, h))
        stream = {"rect": rect, "border_found": found, "cam": cam_box, "game": game_box}
        log(f"  v3: stream webcam at {rect} ({'border found' if found else 'estimated'}): webcam on top, game below")
    # a streamer's own highlight is never tightened: the brief wants the reaction to breathe (20 Nov: a 26 s Kick clip
    # became 20.8 s, too short for the campaign)
    moving = bool(webcam) or bool(moment.get("whole_clip")) or moving_picture(scene.thumbs)
    segs = [(start, end)] if moving else build_segments(clip_words, start, end)
    tm = TimeMap(segs)
    total = tm.duration
    spk = speakers_per_word(clip_words, tracks)
    from .clips import Word
    out_words = [Word(x.text, tm.to_out(x.start), tm.to_out(x.end)) for x in clip_words]
    shots = ([{"t0": 0.0, "t1": total, "layout": "S", "speaker": 0}] if stream
             else make_shots(out_words, spk, len(tracks), total))
    emphasis = {re.sub(r"[^\w]", "", e.lower()) for e in moment.get("emphasis", []) if e}
    punches = plan_punches(out_words, emphasis, shots, total)
    log(f"  v3: {len(tracks)} face track(s), {len(shots)} shot(s) {[s['layout'] for s in shots]}, "
        f"{len(punches)} punch-in(s), {end - start:.1f}s -> {total:.1f}s "
        + ("(pauses kept: the picture moves)" if moving else "after tightening pauses"))
    work = out_path.parent / f"{out_path.stem}_work"
    work.mkdir(parents=True, exist_ok=True)
    accent = style.get("accent_color") or "#FF6A3D"
    build_captions(out_words, shots, work / "captions.ass", accent=accent)
    disclosure = (campaign or {}).get("disclosure_text") or ""
    pill_img = pill(disclosure) if disclosure else None
    logo_img = brand_logo((campaign or {}).get("logo_path"))
    hook_img = hook_text(hook) if hook else None          # boxless, first seconds only
    handle = (campaign or {}).get("onscreen_tag") or ""
    handle_img = None
    if handle:
        from .snack.canvas import text_sprite
        handle_img = text_sprite(handle, CAPTION_FONT, 40, stroke=2, shadow=0)
    end_line = (campaign or {}).get("end_text") or ""      # brief: "End: send viewers to his stream" (last seconds)
    end_img = None
    if end_line:
        from .snack.canvas import text_sprite
        end_img = text_sprite(end_line, CAPTION_FONT, 52, stroke=3, shadow=0)
    hook_y = 290        # research (podcast spec): hook top edge y >= 290, below Meta's 14% top UI line; eyes sit lower
    if stream and hook_img is not None:          # streams: the hook sits on the seam, clear of the streamer's face
        hook_y = max(290, CAM_PANE_H - hook_img.shape[0] // 2)
    bottom = 1.0 if stream else lower_third_top(video, start, end)
    if bottom < 1.0:
        log(f"  v3: source has a burned-in name tag from {bottom:.0%} of the height: cropping above it")

    # audio: cut the same segments, high-pass, then two-pass loudness
    raw = work / "audio_src.wav"
    ffmpeg.run(["-ss", f"{start:.3f}", "-t", f"{end - start + 0.5:.3f}", "-i", str(video.resolve()), "-vn",
                "-ac", "2", "-ar", "48000", str(raw)])
    filt = []
    for k, (a, b) in enumerate(segs):
        ln = b - a
        filt.append(f"[0:a]atrim=start={a - start:.3f}:end={b - start:.3f},asetpts=PTS-STARTPTS,"
                    f"afade=t=in:d=0.01,afade=t=out:st={max(0.0, ln - 0.012):.3f}:d=0.012[s{k}]")
    filt.append("".join(f"[s{k}]" for k in range(len(segs))) + f"concat=n={len(segs)}:v=0:a=1,highpass=f=80[out]")
    cut = work / "audio_cut.wav"
    ffmpeg.run(["-i", str(raw), "-filter_complex", ";".join(filt), "-map", "[out]", str(cut)])
    from .snack.encode import _loudness
    m = _loudness(cut)
    af = (f"loudnorm=I=-14:TP=-1.5:LRA=11:linear=true:measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
          f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:offset={m['target_offset']}"
          ",alimiter=limit=0.83:attack=5:release=50:level=false"     # true peak stays <= -1 dBTP after AAC
          if m and m.get("input_i") not in (None, "-inf") else "anull")

    fonts = Path(FONTS_DIR).resolve().as_posix().replace(":", r"\:")
    cmd = [ffmpeg.ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-y",
           "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{OUT_W}x{OUT_H}", "-r", str(FPS), "-i", "-",
           "-i", str(cut.resolve()), "-map", "0:v", "-map", "1:a",
           "-vf", f"subtitles=captions.ass:fontsdir='{fonts}'", "-af", af,
           "-c:v", "libx264", "-profile:v", "high", "-preset", "medium", "-crf", "18", "-maxrate", "10M",
           "-bufsize", "20M", "-bf", "2", "-g", str(FPS // 2), "-flags", "+cgop", "-pix_fmt", "yuv420p",
           "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-r", str(FPS),
           "-c:a", "aac", "-b:a", "320k", "-ar", "48000", "-shortest", "-movflags", "+faststart",
           str(out_path.resolve())]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE, cwd=work)
    cap = cv2.VideoCapture(str(video))
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 30
    cap.set(cv2.CAP_PROP_POS_MSEC, start * 1000)
    cur_t, frame = start - 1.0, None
    n_out = int(total * FPS)
    boxes_cache: dict = {}
    for i in range(n_out):
        t_out = i / FPS
        t_src = tm.to_src(t_out)
        if t_src < cur_t - 0.5 or t_src > cur_t + 2.0:  # big jump: seek
            cap.set(cv2.CAP_PROP_POS_MSEC, t_src * 1000)
            ok, frame = cap.read()
            cur_t = t_src
        while cur_t + 1 / src_fps <= t_src + 1e-6:
            ok, f = cap.read()
            if not ok:
                break
            frame, cur_t = f, cur_t + 1 / src_fps
        if frame is None:
            ok, frame = cap.read()
            if not ok:
                break
        shot = next((s for s in shots if s["t0"] <= t_out < s["t1"]), shots[-1])
        zoom = 1.13 if any(a <= t_out < b for a, b in punches) else 1.0
        key = (shots.index(shot), zoom)
        if shot["layout"] == "S":
            cx0, cy0, cw, ch = stream["cam"]
            gx0, gy0, gw, gh = stream["game"]
            top = cv2.resize(frame[cy0:cy0 + ch, cx0:cx0 + cw], (OUT_W, CAM_PANE_H), interpolation=cv2.INTER_LANCZOS4)
            if OUT_W / max(cw, 1) >= 1.5:                 # a small webcam blown up: gentle sharpening
                top = _sharpen(top)
            game = cv2.resize(frame[gy0:gy0 + gh, gx0:gx0 + gw], (OUT_W, GAME_PANE_H), interpolation=cv2.INTER_LANCZOS4)
            out = np.vstack([top, game])
            cv2.line(out, (0, CAM_PANE_H - 1), (OUT_W, CAM_PANE_H - 1), (20, 20, 20), 4)
        elif shot["layout"] == "A" or len(tracks) < 2:
            if key not in boxes_cache:
                tr = tracks[min(shot["speaker"], len(tracks) - 1)] if tracks else None
                box = tr.median_box(tm.to_src(shot["t0"]), tm.to_src(shot["t1"])) if tr else None
                if box is None:
                    box = np.array([0.5, 0.4, 0.2, 0.3, 0.35])
                boxes_cache[key] = _crop_for(box, w, h, zoom, bottom=bottom)
            x0, y0, cw, ch = boxes_cache[key]
            out = cv2.resize(frame[y0:y0 + ch, x0:x0 + cw], (OUT_W, OUT_H), interpolation=cv2.INTER_LANCZOS4)
        else:
            if key not in boxes_cache:
                crops = []
                for tr in tracks[:2]:
                    box = tr.median_box(tm.to_src(shot["t0"]), tm.to_src(shot["t1"]))
                    crops.append(_crop_for(box, w, h, 1.0, pane_aspect=OUT_W / 960, eye_frac=0.35, face_frac=0.36, bottom=bottom))
                boxes_cache[key] = crops
            panes = []
            for (x0, y0, cw, ch) in boxes_cache[key]:
                panes.append(cv2.resize(frame[y0:y0 + ch, x0:x0 + cw], (OUT_W, 960), interpolation=cv2.INTER_LANCZOS4))
            out = np.vstack(panes)
            cv2.line(out, (0, 959), (OUT_W, 959), (20, 20, 20), 4)
        if pill_img is not None and t_out < max(3.0, total):
            _blit(out, pill_img, 110, 340)
        if logo_img is not None:                             # campaign rule: brand logo on screen, whole clip
            _blit(out, logo_img, OUT_W - logo_img.shape[1] - 60, 330)
        showing_hook = hook_img is not None and t_out < HOOK_SECONDS
        if showing_hook:
            _blit(out, hook_img, (OUT_W - hook_img.shape[1]) // 2, hook_y)
        if handle_img is not None:                           # campaign tag: small, top, whole clip (under the hook)
            hy = hook_y + hook_img.shape[0] + 6 if showing_hook else hook_y
            _blit(out, handle_img, (OUT_W - handle_img.shape[1]) // 2, hy)
        if end_img is not None and t_out >= total - END_SECONDS and not showing_hook:
            _blit(out, end_img, max(0, (OUT_W - end_img.shape[1]) // 2), hook_y + 60)
        proc.stdin.write(out.tobytes())
    proc.stdin.close()
    err = proc.stderr.read().decode("utf-8", "replace")
    cap.release()
    if proc.wait() != 0:
        raise RuntimeError(f"ffmpeg failed: {err[-1500:]}")
    moment["layout"] = "v3:" + "".join(s["layout"] for s in shots)
    moment["shots"] = shots
    if stream:
        moment["stream"] = stream
    moment["tightened_s"] = round((end - start) - total, 2)
    (work / "plan.json").write_text(json.dumps({"segments": segs, "shots": shots, "punches": punches}, indent=1),
                                    encoding="utf-8")
    return out_path
