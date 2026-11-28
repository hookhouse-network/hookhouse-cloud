"""One quality scorecard for ALL channels (owner, 12 Nov 2026: "do not just focus on single channel, focus on all of
them equally and correct all of them"). Every channel's newest Short and long video are measured against the same
research targets: loudness and peaks, the first and last frame (hook and loop), colour, length, narration pace and
words, title, captions and thumbnails. Results: data/state/quality.json, the dashboard and `python cli.py quality`.
Runs every week by itself (Wednesday, with the niche learning)."""
from __future__ import annotations

import json
import re
import subprocess
import time
from pathlib import Path

import numpy as np

from .config import ROOT

STATE = ROOT / "data" / "state" / "quality.json"
SHORT_S = {"brainrot": (8, 45), "kids": (20, 62), "clips": (15, 62)}      # per genre; default (15, 62)
TARGETS = {"lufs": (-15.0, -13.0), "true_peak": -1.0, "short_s": (15, 62), "dark": 40, "black_end": 20,
           "colour_min": {"kids": 59, "brainrot": 30}, "colour_dull": 15,
           # AutoClip research note #1 (9 Oct 2026), "technical floor": no digital silence inside the video (pauses
           # keep room tone above -45 dBFS) and no faded, lifted blacks on real footage (darkest 1% <= 10/255;
           # we warn above 30, and only when the brightest 1% is also dull (< 225): a bright white set, e.g. NASA's
           # space station, has no true black but keeps true white; washed-out grading loses both. Measured 13 Nov
           # on our Hot Take HQ clip: darkest 1% 30, brightest 1% 239 = fine).
           "silence_db": -60.0, "silence_s": 0.3, "black_p1": 30, "white_p99": 225}
FAKE_URGENCY = re.compile(r"^\W*(breaking(?: news)?|just in|live|urgent)\s*[:!|\-–—]+\s*"   # same rule as clips.py
                          r"|\s*[|\-–—]\s*(breaking(?: news)?|just in|live)\W*$|\s*[(\[](breaking|live)[)\]]", re.I)


def _colourfulness(img: np.ndarray) -> float:
    r, g, b = (img[..., i].astype(float) for i in range(3))
    rg, yb = r - g, 0.5 * (r + g) - b
    return float(np.sqrt(rg.std() ** 2 + yb.std() ** 2) + 0.3 * np.sqrt(rg.mean() ** 2 + yb.mean() ** 2))


def _frames(video: Path, dur: float, n: int = 6, first_at: float = 0.0) -> list[np.ndarray]:
    from PIL import Image

    from .media import ffmpeg
    out, tmp = [], ROOT / "data" / "tmp_quality_frame.png"
    for t in [first_at] + [dur * k / (n - 1) for k in range(1, n - 1)] + [max(0.0, dur - 0.08)]:
        subprocess.run([ffmpeg.ffmpeg_bin(), "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", str(video), "-frames:v", "1",
                        "-vf", "scale=240:-2", str(tmp)], check=False, timeout=60)
        if tmp.exists():
            out.append(np.asarray(Image.open(tmp).convert("RGB")))
    tmp.unlink(missing_ok=True)
    return out


def _loudness(video: Path) -> tuple[float | None, float | None]:
    from .media import ffmpeg
    r = subprocess.run([ffmpeg.ffmpeg_bin(), "-hide_banner", "-nostats", "-i", str(video), "-af", "ebur128=peak=true",
                        "-f", "null", "-"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900)
    summary = r.stderr[r.stderr.rfind("Summary"):]
    i = re.search(r"I:\s+(-?[\d.]+) LUFS", summary)
    p = re.search(r"Peak:\s+(-?[\d.]+) dBFS", summary)
    return (float(i.group(1)) if i else None), (float(p.group(1)) if p else None)


def newest(ch: dict, fmt: str) -> tuple[Path | None, dict]:
    """Newest finished video of a format (clips: the newest clip)."""
    folder = ROOT / "output" / ch["id"]
    if not folder.exists():
        return None, {}
    for d in sorted((x for x in folder.iterdir() if x.is_dir()), reverse=True):
        up = d / "upload.json"
        if up.exists():
            try:
                meta = json.loads(up.read_text(encoding="utf-8"))
            except ValueError:
                continue
            if meta.get("format", "short") == fmt and (d / "video.mp4").exists():
                return d / "video.mp4", meta
        elif fmt == "short" and (d / "clips.json").exists():
            clips = sorted(d.glob("clip_0[1-9].mp4"))
            if clips:
                return clips[0], {"format": "short", "clip": True}
    return None, {}


# Hindi channels speak in Devanagari while search phrases are typed in Latin letters ("karna kavach kundal" =
# "कर्ण ... कवच कुंडल"). Both are reduced to a consonant skeleton (k-r-n, k-v-c, k-n-d-l) before comparing.
_DEVA = {c: lat for lat, group in (("k", "कखक़ख़"), ("g", "गघग़"), ("n", "ङञणनंँ"), ("c", "चछ"), ("j", "जझज़"),
                                    ("t", "टठतथ"), ("d", "डढदधड़ढ़"), ("p", "प"), ("f", "फफ़"), ("b", "बभ"),
                                    ("m", "म"), ("r", "र"), ("l", "ल"), ("v", "व"), ("s", "शषस"), ("h", "ह"))
         for c in group}
_DIGRAPHS = (("chh", "c"), ("ch", "c"), ("ph", "f"), ("bh", "b"), ("kh", "k"), ("gh", "g"), ("jh", "j"),
             ("th", "t"), ("dh", "d"), ("sh", "s"), ("ck", "k"), ("w", "v"), ("z", "j"), ("q", "k"))


def skeleton(word: str) -> str:
    w = word.lower().replace("\u093c", "")                         # drop the nukta dot
    if any("\u0900" <= c <= "\u097f" for c in w):
        out = "".join(_DEVA.get(c, "") for c in w)
    else:
        for a, b in _DIGRAPHS:
            w = w.replace(a, b)
        out = re.sub(r"[^a-z]|[aeiouy]", "", w)
    return re.sub(r"(.)\1+", r"\1", out)                         # "dd" -> "d" on both sides


def _silences(video: Path, dur: float) -> list[tuple[float, float]]:
    """Stretches of true digital silence (below -60 dBFS for 0.3 s+) away from the first and last half second."""
    from .media import ffmpeg
    r = subprocess.run([ffmpeg.ffmpeg_bin(), "-hide_banner", "-nostats", "-i", str(video), "-vn", "-af",
                        f"silencedetect=noise={TARGETS['silence_db']}dB:d={TARGETS['silence_s']}", "-f", "null", "-"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900)
    starts = [float(x) for x in re.findall(r"silence_start: (-?[\d.]+)", r.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end: (-?[\d.]+)", r.stderr)]
    out = []
    for i, a in enumerate(starts):
        b = ends[i] if i < len(ends) else dur
        if a > 0.5 and b < dur - 0.5:
            out.append((round(a, 2), round(b, 2)))
    return out


def levels(frames: list[np.ndarray]) -> tuple[float, float] | None:
    """Median over the middle frames of the darkest and brightest 1% luma (0-255)."""
    lum = [f[..., :3].astype(float) @ [0.299, 0.587, 0.114] for f in frames[1:-1]]
    if not lum:
        return None
    return float(np.median([np.percentile(x, 1) for x in lum])), float(np.median([np.percentile(x, 99) for x in lum]))


def black_p1(frames: list[np.ndarray]) -> float | None:
    """Median over frames of the darkest 1% luma: high = grey blacks."""
    lv = levels(frames)
    return lv[0] if lv else None


def washed_out(frames: list[np.ndarray]) -> tuple[float, float] | None:
    """(darkest, brightest) when the picture has neither true black nor true white (faded grading), else None."""
    lv = levels(frames)
    return lv if lv and lv[0] > TARGETS["black_p1"] and lv[1] < TARGETS["white_p99"] else None


def title_issues(ch: dict, meta: dict) -> list[tuple[str, str]]:
    """Fake urgency on a recording (all channels); clip titles that name no one and carry no number."""
    title = str(meta.get("title") or "")
    out = []
    if FAKE_URGENCY.search(title) or re.search(r"\b(BREAKING|JUST IN)\b", title):
        out.append(("warn", "title uses fake urgency (BREAKING / JUST IN / LIVE) on a recording"))
    if "vague" in (meta.get("title_flags") or []):
        out.append(("warn", "clip title names no one and has no number (specific titles beat slogans)"))
    return out


def said(keywords: list[str], text: str) -> bool:
    """True if any keyword appears in the text: same letters, or the same consonant skeleton (Hindi/Hinglish)."""
    low = text.lower()
    if any(k in low for k in keywords):
        return True
    words = {skeleton(w) for w in re.findall(r"[\w\u0900-\u097f]+", text)}
    return any(len(sk) >= 3 and sk in words for sk in (skeleton(k) for k in keywords))


def seo_issues(ch: dict, sc: dict, meta: dict, fmt: str) -> list[tuple[str, str]]:
    """SEO inside the video (claude-seo, adapted): the search phrase is spoken in the first two lines and opens the
    description; long videos end on the channel's catchphrase (brand recall)."""
    out = []
    beats = sc.get("beats") or []
    phrase = str(sc.get("search_phrase") or "").lower()
    key = [w for w in re.findall(r"\w+", phrase) if len(w) > 3][:3]
    early = " ".join(str(b.get("narration", "")) for b in beats[:2])
    if key and not said(key, early):
        out.append(("warn", f"search phrase \"{phrase}\" not spoken in the first lines"))
    desc0 = str(meta.get("description") or "").split("\n")[0]
    if key and desc0 and not said(key, desc0):
        out.append(("warn", "description's first line misses the search phrase"))
    cp = str(ch.get("catchphrase") or "").lower().strip(" .!?\"")
    if fmt == "long" and cp and beats and cp[:18] not in str(beats[-1].get("narration", "")).lower():
        out.append(("warn", "long video doesn't end with the channel's catchphrase"))
    return out


SHOT_MAX_S = 7.0           # Herk Edit Kit house rule (MIT, S9): a Short changes picture every 2-4 s; > 7 s = static


def cut_times(video: Path, threshold: float = 0.3) -> list[float]:
    """Times (s) where the picture cuts to a new shot (ffmpeg scene detection)."""
    from .media import ffmpeg
    try:
        r = subprocess.run([ffmpeg.ffmpeg_bin(), "-hide_banner", "-nostats", "-i", str(video), "-an", "-vf",
                            f"select='gt(scene,{threshold})',showinfo", "-f", "null", "-"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
    except subprocess.TimeoutExpired:
        return []
    return [float(x) for x in re.findall(r"pts_time:([\d.]+)", r.stderr)]


GAP_RECHECK = 0.1          # weaker cuts that count only inside an over-long gap (see longest_shot)


def longest_shot(video: Path, dur: float) -> float:
    # 0.2: our story Shorts cross-fade between beats; at 0.3 a real 64 s Short (13 beats) showed a false 13.5 s
    # "static" opening, at 0.2 its longest gap was 5.6 s (calibrated 21 Nov on the D. B. Cooper Short)
    cuts = [0.0] + [t for t in cut_times(video, threshold=0.2) if 0 < t < dur] + [dur]
    gaps = [(a, b) for a, b in zip(cuts, cuts[1:]) if b - a > SHOT_MAX_S]
    if gaps:
        # 23 Nov: Deep Blue Files' 17 different pictures (beats 1-5 s) read as two 7.6 s shots: the cross-fade between
        # two dark deep-sea pictures scores under 0.2 (at 0.1: cuts at 23.3 s and 30.7 s, both beat boundaries).
        # Inside an over-long gap only, a weaker cut counts too; one picture with a slow zoom stays far below it.
        weak = [t for t in cut_times(video, threshold=GAP_RECHECK) if any(a + 0.5 < t < b - 0.5 for a, b in gaps)]
        cuts = sorted(set(cuts) | set(weak))
    return round(max((b - a for a, b in zip(cuts, cuts[1:])), default=dur), 1)


def rhythm_issues(video: Path, dur: float, fmt: str) -> list[tuple[str, str]]:
    """Shot rhythm for Shorts (S9 Herk rules): one shot held too long reads as a slideshow and loses the swipe."""
    if fmt != "short" or dur <= SHOT_MAX_S:
        return []
    longest = longest_shot(video, dur)
    if longest > SHOT_MAX_S:
        return [("warn", f"one shot lasts {longest:.0f} s: change the picture every 2-4 s (house rule)")]
    return []


# 28 Nov (owner's repo review): measurable "AI slop" motion tells, our own code; the thresholds follow motionmaxxing
# (Tejashmakwana/motionmaxxing, Apache-2.0, its look.py gates G2/G3): more than 3 flat (empty) frames in a row, an
# unchanged end hold over 1.4 s, a final shot over 25 % of the film. MEASURED ONLY (rep["motion"]): they never change
# the score until their numbers on our own videos say where they fire.
FLAT_STD, FLAT_RANGE = 1.5, 8          # a frame is one flat field below these (luma, 96x54 analysis frame)
FLAT_RUN_MAX = 3                       # frames
END_HOLD_MAX_S = 1.4
HOLD_EPS = 0.35                        # mean abs frame difference (0-255) under which the picture counts as held
FINAL_SHOT_MAX = 0.25


def motion_tells(video: Path, dur: float, cuts: list[float] | None = None, frames=None, fps: float | None = None) -> dict:
    """{flat_run, flat_at, end_hold_s, final_shot_share, tells: [...]} from tiny grey frames (or `frames` in tests)."""
    if frames is None:
        from .media import ffmpeg
        fps = min(30.0, float(fps or 30.0))
        try:
            r = subprocess.run([ffmpeg.ffmpeg_bin(), "-hide_banner", "-nostats", "-i", str(video), "-an", "-vf",
                                f"fps={fps},scale=96:54,format=gray", "-f", "rawvideo", "-"],
                               capture_output=True, timeout=600)
            raw = np.frombuffer(r.stdout, dtype=np.uint8)
            frames = raw[: raw.size // (96 * 54) * 96 * 54].reshape(-1, 54, 96).astype(np.float32)
        except (subprocess.TimeoutExpired, ValueError, OSError):
            return {"tells": [], "error": "frames unreadable"}
    fps = float(fps or 30.0)
    n = len(frames)
    if n < 2:
        return {"tells": [], "error": "too few frames"}
    flat = [(float(f.std()) < FLAT_STD and float(f.max() - f.min()) < FLAT_RANGE) for f in frames]
    best, run, at = 0, 0, None
    for i, fl in enumerate(flat):
        run = run + 1 if fl else 0
        if run > best:
            best, at = run, (i - run + 1) / fps
    diffs = [float(np.abs(frames[i] - frames[i - 1]).mean()) for i in range(1, n)]
    hold = 0
    for d in reversed(diffs):
        if d >= HOLD_EPS:
            break
        hold += 1
    end_hold = round(hold / fps, 2)
    cuts = [t for t in (cuts if cuts is not None else cut_times(video)) if 0 < t < dur]
    final = round((dur - max(cuts)) / dur, 2) if cuts and dur else 0.0   # no cut: one continuous animated scene
    # (kids episodes), where a 'last shot share' means nothing; their still end is caught by the end hold instead
    tells = []
    if best > FLAT_RUN_MAX:
        tells.append(f"{best} empty frames in a row at {at:.1f}s")
    if end_hold > END_HOLD_MAX_S:
        tells.append(f"the end holds still for {end_hold:.1f}s (max {END_HOLD_MAX_S}s)")
    if final > FINAL_SHOT_MAX:
        tells.append(f"the last shot is {final:.0%} of the video (max {FINAL_SHOT_MAX:.0%})")
    return {"flat_run": best, "flat_at": at, "end_hold_s": end_hold, "final_shot_share": final, "tells": tells}


CARD_MAX = 0.2                 # share of word cards above which a video is blocked ("show the moment instead")


def card_count(shots: list[dict]) -> int:
    """Word cards in a shot list (shots.json rows): text shots and graphics. The renderer's picture-limit stop
    (story._picture_stop) uses this same count, so it stops exactly the videos this gate would block."""
    return sum(1 for s in shots if isinstance(s, dict) and (s.get("kind") == "text"
                                                            or s.get("source") in ("graphic", "text")))


def story_issues(d: Path) -> list[tuple[str, str]]:
    """Owner 15 Nov 2026: a video must SHOW what is said, not words on cards. Reads shots.json (per beat)."""
    try:
        shots = json.loads((d / "shots.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not shots:
        return []
    cards = card_count(shots)
    weak = sum(1 for s in shots if s.get("kind") in ("image", "video") and s.get("source") not in ("graphic", "chart")
               and 0 < float(s.get("match") or 1) < 0.7)
    out = []
    if cards / len(shots) > CARD_MAX:
        out.append(("bad", f"{cards}/{len(shots)} shots are word cards: show the moment instead"))
    if weak / len(shots) > 0.2:
        out.append(("warn", f"{weak}/{len(shots)} pictures barely match what is said"))
    if not any(s.get("see") for s in shots):
        out.append(("warn", "made without a storyboard (old picture search)"))
    return out


def pace_issues(ch: dict, d: Path, dur: float, fmt: str) -> list[tuple[str, str]]:
    """Owner, 15 Nov: pace must suit each channel's audience. The channel file holds the research pace
    (spec.short_wpm / long_wpm, e.g. mystery 180 wpm); more than 10% off is flagged before the owner sees it."""
    spec = ch.get("spec") or {}
    target = spec.get("long_wpm" if fmt == "long" else "short_wpm")
    if not target or dur < 5:
        return []
    try:
        script = json.loads((d / "script.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    words = sum(len(str(b.get("narration", "")).split()) for b in script.get("beats", []))
    if not words:
        return []
    span = dur - 0.65
    srt = next(iter(sorted(d.glob("*.srt"))), None)          # speech span from the captions (outro card excluded)
    if srt:
        ts = re.findall(r"(\d+):(\d+):(\d+)[,.](\d+)", srt.read_text(encoding="utf-8", errors="ignore"))
        secs = [int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000 for h, m, s, ms in ts]
        if len(secs) >= 2 and secs[-1] - secs[0] > 5:
            span = secs[-1] - secs[0]
    wpm = words / max(1.0, span) * 60
    if abs(wpm - target) / target > 0.10:
        slow = wpm < target
        return [("warn", f"narration {wpm:.0f} words/min, this audience's target {target} "
                         f"({'too slow: viewers swipe' if slow else 'too fast: hard to follow'})")]
    return []


def check_video(ch: dict, video: Path, meta: dict, fmt: str) -> dict:
    from .media import ffmpeg
    issues: list[tuple[str, str]] = []
    dur = ffmpeg.duration(video)
    lufs, peak = _loudness(video)
    frames = _frames(video, dur, first_at=1.0 if fmt == "long" else 0.0)   # long: YouTube shows a thumbnail first
    first = float(frames[0].mean()) if frames else 0.0
    first_sd = float(frames[0].std()) if frames else 0.0
    last = float(frames[-1].mean()) if frames else 0.0
    colour = float(np.mean([_colourfulness(f) for f in frames])) if frames else 0.0
    if lufs is not None and not TARGETS["lufs"][0] <= lufs <= TARGETS["lufs"][1]:
        issues.append(("warn", f"loudness {lufs:.1f} LUFS (target -14)"))
    if peak is not None and peak > TARGETS["true_peak"]:
        issues.append(("bad", f"peaks {peak:+.1f} dB: distorts after upload (made before the limiter fix?)"))
    if fmt == "short":
        lo, hi = SHORT_S.get(ch.get("type"), TARGETS["short_s"])
        if not lo <= dur <= hi:
            issues.append(("warn", f"Short is {dur:.0f} s (best {lo}-{hi} s)"))
        if last < TARGETS["black_end"]:
            issues.append(("warn", "ends on black: breaks the loop"))
    if first < TARGETS["dark"] and first_sd < 30:
        issues.append(("warn", "first frame dark and flat: weak hook in the feed"))
    need = TARGETS["colour_min"].get(ch.get("type"))
    if need and colour < need:
        issues.append(("warn", f"colourfulness {colour:.0f} (this genre's target {need}+)"))
    elif colour < TARGETS["colour_dull"]:
        issues.append(("warn", f"very dull colours ({colour:.0f})"))
    gaps = _silences(video, dur)
    if gaps:
        issues.append(("warn", f"dead silence at {gaps[0][0]:.1f}s ({len(gaps)} gap(s)): sounds broken, keep room tone"))
    p1 = black_p1(frames) if ch.get("type") == "clips" else None
    faded = washed_out(frames) if ch.get("type") == "clips" else None
    if faded:
        issues.append(("warn", f"washed-out picture (darkest 1% = {faded[0]:.0f}/255, brightest {faded[1]:.0f}): "
                               f"no true black or white"))
    issues += title_issues(ch, meta)
    issues += pace_issues(ch, video.parent, dur, fmt)
    d = video.parent
    if ch.get("type") in ("story", "kids") and not any(d.glob("*.srt")):
        issues.append(("warn", "no captions file (search and sound-off viewers)"))
    if fmt == "long" and ch.get("type") == "story" and len(list(d.glob("thumbnail_*.jpg"))) < 3:
        issues.append(("warn", "fewer than 3 thumbnails (YouTube's A/B test needs 3)"))
    if ch.get("type") == "story" and (d / "script.json").exists():               # SEO inside the video
        try:
            issues += seo_issues(ch, json.loads((d / "script.json").read_text(encoding="utf-8")), meta, fmt)
        except ValueError:
            pass
    issues += story_issues(d)
    if ch.get("type") == "story":                          # S9 Herk house rule (Brain Snack games are one-shot)
        issues += rhythm_issues(video, dur, fmt)
    if (d / "upload.json").exists() and ch.get("type") == "story":
        from .dashboard import video_checks
        v = video_checks(ch, d, meta, fmt)
        if v.get("words") and not v["pace_ok"]:
            issues.append(("warn", f"pace {v['wpm']:.0f} words/min (target {v['target_wpm']})"))
        if v.get("words") and not v["words_ok"]:
            issues.append(("warn", f"{v['words']} words (research range {v['words_range']})"))
        if not v["title_ok"]:
            issues.append(("warn", f"title {len(v['title'])} characters (best 20-40)"))
        if v.get("fact_ok") is False:
            issues.append(("bad", "fact-check failed"))
    score = max(0, 100 - sum(15 if lv == "bad" else 7 for lv, _ in issues))
    try:                                             # measured only: never in the score (see motion_tells)
        motion = motion_tells(video, dur) if fmt == "short" else {}
    except Exception as e:  # noqa: BLE001 - a measurement must never change a verdict
        motion = {"tells": [], "error": type(e).__name__}
    try:
        shown = str(video.relative_to(ROOT))
    except ValueError:
        shown = str(video)
    return {"file": shown, "format": fmt, "seconds": round(dur, 1), "lufs": lufs, "peak": peak,
            "silences": gaps[:5], "black_p1": None if p1 is None else round(p1, 1),
            "first_brightness": round(first, 1), "last_brightness": round(last, 1), "colour": round(colour, 1),
            "score": score, "issues": issues, "motion": motion,
            "made": time.strftime("%d %b", time.localtime(video.stat().st_mtime))}


def fix_peaks(video: Path, log=print) -> bool:
    """Re-master only the audio of a finished video (picture untouched) with the same chain as new renders:
    two-pass loudness with a true-peak ceiling + limiter, then measure; lower the ceiling until peaks are <= -1 dBTP."""
    from .media import ffmpeg
    from .snack.encode import _loudness
    wav = video.with_name(video.stem + "_peakfix.wav")
    tmp = video.with_name(video.stem + "_peakfix.mp4")
    subprocess.run([ffmpeg.ffmpeg_bin(), "-v", "error", "-y", "-i", str(video), "-vn", "-ac", "2", "-ar", "48000",
                    str(wav)], timeout=1800)
    if not wav.exists():
        return False
    m = _loudness(wav)
    ok = False
    for tp, lim in ((-2.0, 0.79), (-3.0, 0.70), (-4.0, 0.63)):
        af = (f"lowpass=f=17000,loudnorm=I=-14:TP={tp}:LRA=11:linear=true:measured_I={m['input_i']}:"
              f"measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:"
              f"offset={m['target_offset']},alimiter=limit={lim}:attack=5:release=50:level=false") \
            if m and m.get("input_i") not in (None, "-inf") else f"alimiter=limit={lim}:level=false"
        r = subprocess.run([ffmpeg.ffmpeg_bin(), "-v", "error", "-y", "-i", str(video), "-i", str(wav), "-map", "0:v",
                            "-map", "1:a", "-c:v", "copy", "-af", af, "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
                            "-movflags", "+faststart", str(tmp)], timeout=1800)
        if r.returncode != 0 or not tmp.exists():
            break
        _lufs, peak = _loudness_of(tmp)
        log(f"  {video.parent.name}: ceiling {tp} dB -> true peak {peak}")
        if peak is not None and peak <= -1.0:
            ok = True
            break
    wav.unlink(missing_ok=True)
    if ok:
        tmp.replace(video)
    else:
        tmp.unlink(missing_ok=True)
    return ok


def _loudness_of(video: Path) -> tuple[float | None, float | None]:
    return _loudness(video)


def run(log=print) -> dict:
    from .config import channels
    report = {"at": time.time(), "channels": {}}
    for ch in channels():
        rows = []
        for fmt in ("short", "long"):
            video, meta = newest(ch, fmt)
            if video:
                try:
                    rows.append(check_video(ch, video, meta, fmt))
                except Exception as e:  # noqa: BLE001
                    rows.append({"format": fmt, "score": 0, "issues": [("warn", f"could not check: {e}")]})
        score = round(sum(r["score"] for r in rows) / len(rows)) if rows else None
        report["channels"][ch["id"]] = {"name": ch["name"], "score": score, "videos": rows}
        log(f"{ch['name']:<24} {score if score is not None else '-':>4}  " +
            "; ".join(t for r in rows for _, t in r["issues"])[:160])
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(report, indent=1), encoding="utf-8")
    return report


def load() -> dict:
    return json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
