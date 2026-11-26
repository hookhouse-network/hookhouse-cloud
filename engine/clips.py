"""Clip engine (channel #1, Hot Take HQ):
source video -> transcript -> brain proposes moments -> virality score (0-100)
-> top moments -> face-tracked 9:16 crop -> captions + hook -> campaign rule check."""
from __future__ import annotations
from engine.core.quiet import noted

import json
import os
import math
import re
import subprocess
import time
from pathlib import Path

import numpy as np
import requests

from .config import ROOT
from .media import ffmpeg
from .media.captions import HookStyle, Word, build_ass
from .media.compose import Finisher, Grader, Look, _blend
from .media.stickers import emoji_png, load_rgba
from .media.fonts import FONTS_DIR, ensure_fonts
from .media.transcribe import transcribe
from engine.core.http import HTTP

OUT_W, OUT_H = 1080, 1920
YUNET_URL = ("https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/"
             "face_detection_yunet_2023mar.onnx")

# Virality checklist and weights (sum = 100)
WEIGHTS = {"hook": 25, "emotion": 15, "curiosity": 15, "complete": 15, "ending": 10,
           "audience_fit": 10, "brand_safe": 10}

EDITOR_SYSTEM = ("You are the best short-form video editor in the world. You find the moments in long "
                 "podcasts that become viral Shorts. You are honest when a moment is weak.")

EDITOR_PROMPT = """Below is a timestamped podcast transcript. Find the {n} best moments for vertical Shorts.

Rules:
- Each moment {min_len}-{max_len} seconds, self-contained (a stranger understands it).
- Must START on a strong line (hook in the first 2 seconds), never on filler ("so", "um", "yeah").
- The first sentence must make sense to a stranger: never open on a back-reference ("as I said", "that point"),
  on "he/she/they" for someone not named yet, on a one-word answer to a question the clip leaves out, or on a
  sentence that continues an earlier point ("But...", "And then...", "So that's why..."). Skip lead-in banter
  ("No. No? Ah!", greetings, calling someone over): start where the point starts.
- One idea per clip; end on the sentence that lands the payoff, without the first words of the next thought.
- Skip stretches where the picture is unusable: "be right back", "starting soon", technical problems, a frozen
  or lost stream, a black or placeholder screen.
- Title: who + the concrete thing they said or did, or the number from the clip ("Kevin Hart Turned Down $50M
  For One Reason"), never a vague slogan ("Respect Is Earned") or a line only fans get. Name the person when the
  transcript or source names them. Every claim must be in the clip's own words. Never "BREAKING", "JUST IN" or
  "LIVE" (this is a recording).
- Fewer strong moments beat filling the count: return fewer if the rest are weak.
- Audience: {audience}.
{campaign_rules}

What has worked before:
{memory}

Score each moment 0-10 on: hook, emotion, curiosity, complete, ending, audience_fit, brand_safe.

Return ONLY JSON:
{{"moments": [
  {{"start": seconds, "end": seconds,
    "first_words": "exact first 5 words of the clip",
    "last_words": "exact last 5 words of the clip",
    "hook_options": ["3 on-screen hooks, max 7 words each"],
    "title": "YouTube Shorts title under 60 chars",
    "caption": "Instagram/Shorts caption: hook line + 1 line",
    "scores": {{"hook": 0, "emotion": 0, "curiosity": 0, "complete": 0, "ending": 0, "audience_fit": 0, "brand_safe": 0}},
    "emphasis": ["3-6 key words said in the clip (numbers, strong words) to pop on screen"],
    "emoji": "one emoji that fits the clip's emotion",
    "why": "one sentence"}}
]}}

Transcript:
{transcript}"""


# ---------------- source ----------------
PLATFORM_LINKS = re.compile(r"(youtube\.com|youtu\.be|twitch\.tv|kick\.com|tiktok\.com|instagram\.com|facebook\.com|"
                            r"//(www\.)?x\.com|twitter\.com)", re.I)   # 17 Nov: bare x.com matched dropbox.com


FOOTAGE_DIR = Path(__file__).resolve().parents[1] / "data" / "pc" / "footage"


def local_footage(name: str) -> Path | None:
    """'src-<campaign id[:30]>-<file>' -> the PC's own download of that file (data/pc/footage/<campaign>/<file>)."""
    if not name.startswith("src-") or not FOOTAGE_DIR.is_dir():
        return None
    for f in FOOTAGE_DIR.rglob("*"):
        if f.is_file() and name == f"src-{f.parent.name[:30]}-{f.name}":
            return f
    for f in FOOTAGE_DIR.rglob("*"):                     # the folder name differs (older downloads)
        if f.is_file() and name.endswith("-" + f.name):
            return f
    return None


def fetch_source(src: str, dest_dir: Path) -> Path:
    """Local file or a direct file link from the rights holder (campaign brief's Google Drive / Dropbox / file URL).
    Video-platform pages (YouTube, Twitch, Kick...) are never downloaded: their terms forbid it without permission
    from the platform, and fair use doesn't stop Content ID claims. Ask the creator or the campaign for the file."""
    p = Path(src)
    if p.exists():
        return p
    if src.startswith("asset:"):                         # footage the PC fetched (Frame.io) and put in cloud storage
        local = local_footage(src[6:])
        if local:                                        # the PC still has its own copy (19 Nov: store unreachable)
            return local
        from .cloud import media
        from .cloud.store import Store
        data = Store().get(media.TAG, src[6:])
        if not data:
            raise RuntimeError(f"Footage {src[6:]} is no longer in cloud storage")
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / "source.mp4"
        dest.write_bytes(data)
        return dest
    if PLATFORM_LINKS.search(src):
        raise RuntimeError("Can't download from a video platform page. Use the source files the campaign or the "
                           "creator shares (Google Drive / Dropbox / direct link), or a file you recorded yourself.")
    dest_dir.mkdir(parents=True, exist_ok=True)
    m = re.search(r"drive\.google\.com/(?:file/d/|open\?id=|uc\?(?:export=download&)?id=)([\w-]+)", src)
    if m:            # big files: the old uc?export link now returns a "can't scan for viruses" page instead
        src = f"https://drive.usercontent.google.com/download?id={m.group(1)}&export=download&confirm=t"
    if "dropbox.com" in src:
        src = re.sub(r"[?&]dl=0", "", src) + ("&" if "?" in src else "?") + "dl=1"
    dest = dest_dir / "source.mp4"
    with HTTP.get(src, stream=True, timeout=120) as r:
        r.raise_for_status()
        if "text/html" in r.headers.get("Content-Type", ""):   # a sign-in or "can't scan" page, not the video
            raise RuntimeError("The link opened a web page instead of the video file. Set the file to 'Anyone with "
                               "the link can view' (Google Drive) or send a direct download link.")
        with open(dest, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
    return dest


DRIVE_FOLDER = re.compile(r"drive\.google\.com/drive/(?:u/\d+/)?folders/([\w-]+)")
VIDEO_NAME = re.compile(r"\.(mp4|mov|mkv|webm|m4v)$", re.I)


def expand_source(link: str, limit: int = 15) -> list[str]:
    """A shared Google Drive folder (how most campaigns share footage) -> its video file links; anything else as is.
    Uses Drive's public folder view (no sign-in, no key); the folder must be 'Anyone with the link'."""
    m = DRIVE_FOLDER.search(link)
    if not m:
        return [link]
    r = HTTP.get(f"https://drive.google.com/embeddedfolderview?id={m.group(1)}", timeout=60)
    r.raise_for_status()
    found = re.findall(r'href="https://drive\.google\.com/file/d/([\w-]+)/view[^"]*"[^>]*>.*?'
                       r'class="flip-entry-title">([^<]+)<', r.text, re.S)
    files = [f"https://drive.google.com/file/d/{fid}/view" for fid, name in found if VIDEO_NAME.search(name.strip())]
    subs = re.findall(r'href="(https://drive\.google\.com/drive/folders/[\w-]+)"', r.text)
    for sub in subs[:5]:                                   # footage is often sorted into one level of sub-folders
        if len(files) >= limit:
            break
        try:
            files += [u for u in expand_source(sub, limit) if u not in files]
        except requests.RequestException:
            continue
    return list(dict.fromkeys(files))[:limit]


# ---------------- long sources (streams, long videos, gameplay) ----------------
LONG_SOURCE_S = 25 * 60          # longer than this: find the hot spots first instead of transcribing everything
MAX_CLIPS_PER_SOURCE = 15


def loudness_per_second(video: Path) -> list[float]:
    """dB loudness of every second, streamed from ffmpeg (4 kHz mono), so a 6-hour stream needs little memory."""
    import numpy as np
    sr = 4000
    proc = subprocess.Popen([ffmpeg.ffmpeg_bin(), "-v", "error", "-i", str(video), "-vn", "-ac", "1", "-ar", str(sr),
                             "-f", "s16le", "-"], stdout=subprocess.PIPE)
    out = []
    while True:
        buf = proc.stdout.read(sr * 2)
        if not buf:
            break
        a = np.frombuffer(buf, np.int16).astype(np.float32) / 32768
        out.append(float(20 * np.log10(np.sqrt(np.mean(a * a)) + 1e-6)))
    proc.wait()
    return out


def hotspots(levels: list[float], window: int = 300, top: int = 6) -> list[tuple[int, int]]:
    """The loudest, most eventful windows (reactions, shouting, big plays): score = how often the window jumps
    well above the source's normal level. Returns non-overlapping (start, end) seconds, in time order."""
    import numpy as np
    x = np.array(levels, np.float32)
    if len(x) <= window:
        return [(0, len(x))]
    base, spread = float(np.median(x)), float(np.percentile(x, 90) - np.median(x)) or 1.0
    peaks = np.clip((x - base) / spread, 0, 3)                       # 0 = normal, 1 = loud, 3 = very loud
    csum = np.concatenate([[0], np.cumsum(peaks)])
    step = max(30, window // 5)
    scored = sorted(((csum[i + window] - csum[i], i) for i in range(0, len(x) - window, step)), reverse=True)
    chosen: list[tuple[int, int]] = []
    for _, i in scored:
        if all(i + window <= a or i >= b for a, b in chosen):
            chosen.append((i, i + window))
        if len(chosen) == top:
            break
    return sorted(chosen)


def transcribe_hotspots(video: Path, language: str = "en", log=print, window: int = 300,
                        top: int = 6) -> list[Word]:
    """Transcribe only the hot windows of a long source; word times stay absolute (seconds in the full video)."""
    import tempfile
    log("Long source: finding the hot spots by loudness…")
    spans = hotspots(loudness_per_second(video), window=window, top=top)
    words: list[Word] = []
    with tempfile.TemporaryDirectory() as tmp:
        for k, (a, b) in enumerate(spans, 1):
            log(f"  hot spot {k}/{len(spans)}: {a // 60}:{a % 60:02d} to {b // 60}:{b % 60:02d}, transcribing")
            wav = Path(tmp) / f"w{k}.wav"
            ffmpeg.run(["-ss", str(a), "-t", str(b - a), "-i", video, "-vn", "-ac", "1", "-ar", "16000", wav])
            words += [Word(w.text, w.start + a, w.end + a) for w in transcribe(wav, language=language)]
    return words


# ---------------- moments ----------------
def transcript_text(words: list[Word], line_seconds: float = 8.0) -> str:
    lines, cur, start = [], [], None
    for w in words:
        if start is None:
            start = w.start
        cur.append(w.text)
        if w.end - start >= line_seconds or re.search(r"[.!?]$", w.text):
            lines.append(f"[{start:.1f}] {' '.join(cur)}")
            cur, start = [], None
    if cur:
        lines.append(f"[{start:.1f}] {' '.join(cur)}")
    return "\n".join(lines)


PART_CHARS = 110_000     # transcript sent per request (about 2 hours of talk); the old single cut lost the rest
PART_OVERLAP_S = 90      # parts overlap so a moment on a boundary is seen whole by one of them


def transcript_parts(words: list[Word], max_chars: int = PART_CHARS, overlap_s: float = PART_OVERLAP_S) -> list[list[Word]]:
    """The transcript in time windows that each fit one request, overlapping by `overlap_s`
    (idea: Anil-matcha/AI-Youtube-Shorts-Generator chunks videos over 30 minutes with overlap)."""
    if not words or len(transcript_text(words)) <= max_chars:
        return [words]
    t0, t1 = words[0].start, words[-1].end
    n = math.ceil(len(transcript_text(words)) / (max_chars * 0.9))
    while True:                                  # more parts until every part fits (a dense hour), never a gap
        span = (t1 - t0) / n
        out = []
        for k in range(n):
            a, b = t0 + k * span - (overlap_s if k else 0), t0 + (k + 1) * span + (overlap_s if k < n - 1 else 0)
            part = [w for w in words if a <= w.start < b or (k == n - 1 and w.start >= b)]
            if part:
                out.append(part)
        if all(len(transcript_text(p)) <= max_chars for p in out) or n >= 40:
            return out
        n += 1


def _norm_word(t: str) -> str:
    return re.sub(r"[^\w']", "", t.lower())


def virality(scores: dict) -> int:
    total = sum(WEIGHTS[k] * max(0, min(10, float(scores.get(k, 0)))) / 10 for k in WEIGHTS)
    return int(round(total))


def snap(words: list[Word], start: float, end: float) -> tuple[float, float]:
    """Start exactly on a word (prefer a sentence start), end right after a word."""
    filler = {"so", "um", "uh", "yeah", "like", "and", "but", "okay", "ok", "well", "right"}
    window = [(i, w) for i, w in enumerate(words) if start - 1.5 <= w.start <= start + 1.5
              and _norm_word(w.text) not in filler]
    if window:
        sentence_starts = [w for i, w in window if i == 0 or re.search(r"[.!?]$", words[i - 1].text)]
        pool = sentence_starts or [w for _, w in window]
        start = min(pool, key=lambda w: abs(w.start - start)).start
    ends = [w for w in words if end - 2.0 <= w.end <= end + 2.0]
    if ends:
        sentence_ends = [w for w in ends if re.search(r"[.!?]$", w.text)]
        end = max(sentence_ends or [min(ends, key=lambda w: abs(w.end - end))], key=lambda w: w.end).end
    return max(start - 0.1, 0), end + 0.25


# ---------------- clean openings + grounding (round 12, ideas from reviewing SupoClip) ----------------
# The first spoken seconds decide whether a viewer stays. A clip that opens on banter ("No. No? Ah!"), on a lone
# answer ("Catharsis."), mid-sentence, or on a line that continues an unseen point ("But the main reason...") is
# moved to its first self-contained sentence when that stays within limits; otherwise it ranks lower.
OPEN_FILLERS = {"um", "uh", "erm", "hmm", "mm", "like", "yeah", "okay", "ok", "well", "right", "so", "oh", "ah"}
DANGLING_FIRST = {"but", "and", "or", "nor", "because", "cause", "'cause", "plus", "also", "then", "which", "whereas"}
DANGLING_PHRASES = ("so that's why", "so the reason", "so the main reason", "that's why", "which is why",
                    "which means", "as i said", "like i said", "as i mentioned", "like i mentioned", "as we said",
                    "like we said", "as we discussed", "going back to", "back to what", "before we started")
FRAGMENT_MAX = 2            # content words in a banter line or a one-word answer
DANGLING_SKIP_MAX = 6       # a short dangling sentence is skipped; a longer one carries the point and is penalised
SKIP_MAX_WORDS = 12         # never skip more than this to reach a clean opening ...
SKIP_MAX_S = 15.0           # ... or more than 15 s
OPENING_PENALTY = 10        # virality points off (of 100) when the opening still leans on missing context
UNGROUNDED_PENALTY = 10     # ... or when the quoted first words are nowhere near the given time
# Titles (AutoClip research note #1, 9 Oct 2026, same-account pairs): titles naming a person + a concrete act or a
# number beat abstract slogans; fake urgency on a recording is on their "what not to copy" list.
FAKE_URGENCY = re.compile(r"^\W*(breaking(?: news)?|just in|live|urgent)\s*[:!|\-–—]+\s*"
                          r"|\s*[|\-–—]\s*(breaking(?: news)?|just in|live)\W*$|\s*[(\[](breaking|live)[)\]]", re.I)
_NOT_NAMES = {"I", "I'm", "I've", "I'll", "I'd", "OK", "Okay", "God", "Mr", "Mrs", "Dr"}


def proper_nouns(words: list[Word], title: str = "") -> set[str]:
    """Names the clip itself gives: words capitalised in the middle of a transcript sentence (Whisper capitalises
    names), plus capitalised words of the source title."""
    out: set[str] = set()
    prev = "."
    for w in words:
        tok = re.sub(r"^\W+|\W+$", "", w.text)
        if tok and tok[0].isupper() and prev[-1:] not in ".?!" and tok not in _NOT_NAMES and len(tok) > 1:
            out.add(tok.lower())
        prev = w.text.strip() or prev
    out |= {x.lower() for x in re.findall(r"\b[A-Z][a-z]+\b", title or "") if x not in _NOT_NAMES}
    return out


def clean_title(title: str, names: set[str] | None = None) -> tuple[str, list[str]]:
    """(title without fake urgency, flags). 'vague' = names no one the clip names and has no number (a slogan)."""
    t = FAKE_URGENCY.sub("", title or "").strip(" -|:")
    flags = ["urgency_removed"] if t != (title or "").strip() else []
    has_name = bool(names) and any(w.lower() in names for w in re.findall(r"[A-Za-z][\w'’-]*", t))
    if t and names is not None and not has_name and not re.search(r"\d|\$|₹|%", t):
        flags.append("vague")
    return t, flags


def _tok(text: str) -> str:
    return re.sub(r"[^\w']", "", text.lower().replace("’", "'"))


def _ends_sentence(text: str) -> bool:
    return bool(re.search(r"[.!?][\"')\]]*$", text.strip()))


def _content(tokens: list[str]) -> list[str]:
    return [t for t in tokens if t and t not in OPEN_FILLERS]


def _dangling(tokens: list[str]) -> bool:
    content = _content(tokens)
    if content and content[0] in DANGLING_FIRST:
        return True
    head = " ".join(t for t in tokens[:7] if t)
    return any(head.startswith(p) for p in DANGLING_PHRASES)


def review_opening(words: list[Word], start: float, end: float, min_len: float) -> dict:
    """{"start": new start or None, "issue": None | "fragment" | "dangling" | "mid-sentence",
    "penalise": bool, "skipped": the words left out}."""
    res = {"start": None, "issue": None, "penalise": False, "skipped": ""}
    idx = [i for i, w in enumerate(words) if start - 0.05 <= w.start < end]
    if not idx:
        return res
    i0 = idx[0]
    si = i0                                            # where the sentence holding the first word really starts
    while si > 0 and not _ends_sentence(words[si - 1].text):
        si -= 1
    sents, cur = [], []
    for i in range(si, idx[-1] + 1):
        cur.append(i)
        if _ends_sentence(words[i].text):
            sents.append(cur)
            cur = []
    if cur:
        sents.append(cur)
    toks = [[_tok(words[i].text) for i in s] for s in sents]
    lead = _content([_tok(w.text) for w in words[si:i0]])
    long_dangling = False
    if lead and not (len(lead) == 1 and lead[0] in DANGLING_FIRST):
        issue = "mid-sentence"                         # real words of this sentence were left out
        inside = [i for i in sents[0] if i >= i0]
        skip = 1 if len(inside) <= SKIP_MAX_WORDS else 0
        long_dangling = not skip
    else:
        short = 0                                      # banter / one-word answers before the point
        for tk in toks:
            if len(_content(tk)) > FRAGMENT_MAX:
                break
            short += 1
        if short == len(toks) or (short == 1 and len(_content(toks[0])) == 2):
            short = 0                                  # nothing better follows / "Here's why." is a hook
        skip, issue = short, ("fragment" if short else None)
    if skip < len(toks) and _dangling(toks[skip]):
        issue = issue or "dangling"
        if len(_content(toks[skip])) <= DANGLING_SKIP_MAX:
            skip += 1
        else:
            long_dangling = True
    if issue is None:
        return res
    res["issue"] = issue
    skipped = [i for s in sents[:skip] for i in s if i >= i0]
    res["skipped"] = " ".join(words[i].text for i in skipped)
    if skip == 0 or skip >= len(sents):
        res["penalise"] = True
        return res
    new_start = words[sents[skip][0]].start
    if len(skipped) > SKIP_MAX_WORDS or new_start - words[i0].start > SKIP_MAX_S or end - new_start < min_len:
        res["penalise"] = True
        return res
    res["start"], res["penalise"] = new_start, long_dangling
    return res


def _find_phrase(words: list[Word], phrase: str, lo: float, hi: float, near: float, at_end: bool = False):
    """Index of the first word (or the last, at_end) of the closest in-order match of the quoted words."""
    target = [t for t in (_tok(x) for x in str(phrase or "").split()) if t]
    target = target[-6:] if at_end else target[:6]
    if len(target) < 3:
        return None
    best = None
    for i, w in enumerate(words):
        if not lo <= w.start <= hi:
            continue
        seq = [_tok(x.text) for x in words[i:i + len(target)]]
        hits = sum(a == b for a, b in zip(seq, target))
        if hits / len(target) >= 0.75:
            j = min(i + len(target), len(words)) - 1 if at_end else i
            score = hits - 0.01 * abs((words[j].end if at_end else words[j].start) - near)
            if best is None or score > best[0]:
                best = (score, j)
    return best[1] if best else None


def ground(words: list[Word], m: dict, start: float, end: float) -> tuple[float, float, bool | None]:
    """Re-anchor the model's times on the words it quoted (models copy text better than they keep time).
    Returns (start, end, grounded): grounded is None when nothing was quoted, False when the quote isn't there."""
    fi = _find_phrase(words, m.get("first_words", ""), start - 20, start + 20, near=start)
    li = _find_phrase(words, m.get("last_words", ""), end - 25, end + 15, near=end, at_end=True)
    grounded = None
    if fi is not None:
        shift = words[fi].start - start
        start, grounded = words[fi].start, True
        if li is None and abs(shift) > 1.5:            # the end was probably off by the same amount
            end += shift
    elif len([t for t in str(m.get("first_words") or "").split() if _tok(t)]) >= 3:
        grounded = False
    if li is not None and words[li].end > start:
        end = words[li].end
    return start, end, grounded


SHORT_SOURCE_S = 180             # a Kick/Twitch highlight the streamer's viewers already cut: keep it whole


class UnusableFootage(RuntimeError):
    """This footage can never give a clip for this campaign (for example a highlight shorter than the brief's
    minimum). 20 Nov: the PC maker retried one 30 s Kick highlight every 6 minutes; the slot must skip it at once."""

# 26 Nov: plain descriptive headlines scored caption_hook 5; the title is now a curiosity gap (what he tries / expects).
# Prompt text states rules only, never dated history (a dated note in the judge rubric was read as a directive).
WHOLE_PROMPT = """This is ONE short highlight clip ({dur:.0f} s; the last {keep:.0f} s are posted) cut from a streamer's live stream (gameplay plus the
streamer's reactions; little speech). It is posted whole as a vertical Short. Write its packaging.
- Title: a curiosity gap about the concrete moment: what he TRIES, EXPECTS or RISKS, so a stranger needs to see how
  it turns out (e.g. "Dasgas Dom thought this landing would work...", "Dasgas Dom tries to outrun 5 cop cars..."),
  under 60 chars, no "BREAKING"/"LIVE", no clickbait the clip does not deliver. Name the streamer only if the
  transcript or the campaign rules do.
- Hooks: 3 on-screen hooks, max 7 words, that make a scroller stay (a question or the stakes), true to the clip.
- No spoilers of the game's story, and never give away how THIS clip ends: the title and hooks tease the stakes
  ("Can he land this plane?", "He thought this was a good idea"), never the outcome ("he crashes", "mission failed").
  The frames below tell you what really happens so the tease is true; do not describe the ending.
{campaign_rules}
Return ONLY JSON: {{"hook_options": ["..."], "title": "...", "caption": "hook line + 1 line",
 "emphasis": ["3-6 words said in the clip"], "emoji": "one emoji",
 "scores": {{"hook": 0, "emotion": 0, "curiosity": 0, "complete": 0, "ending": 0, "audience_fit": 0, "brand_safe": 0}},
 "why": "one sentence"}}

{seen}Transcript (may be empty or partial):
{transcript}"""


def remove_letterbox(video: Path, log=print) -> Path:
    """25 Nov: a campaign reference video was landscape footage pasted into a 9:16 frame; our reframe kept its black
    bars and the gate blocked the clip. Crop to the real picture first (ffmpeg cropdetect over the source)."""
    try:
        dur = ffmpeg.duration(video)
        r = subprocess.run([ffmpeg.ffmpeg_bin(), "-hide_banner", "-ss", f"{min(5.0, dur * 0.1):.1f}", "-i", str(video),
                            "-t", f"{min(60.0, dur):.1f}", "-vf", "fps=2,cropdetect=limit=24:round=2:reset=0",
                            "-f", "null", "-"], capture_output=True, text=True, timeout=600)
        crops = re.findall(r"crop=(\d+):(\d+):(\d+):(\d+)", r.stderr)
        if not crops:
            return video
        cw, ch, cx, cy = (int(x) for x in crops[-1])
        v = next(s for s in ffmpeg.probe(video)["streams"] if s.get("codec_type") == "video")
        w, h = int(v["width"]), int(v["height"])
        if ch >= h * 0.92 and cw >= w * 0.92:
            return video
        out = video.with_name(f"{video.stem}_nobars.mp4")
        subprocess.run([ffmpeg.ffmpeg_bin(), "-y", "-v", "error", "-i", str(video), "-vf", f"crop={cw}:{ch}:{cx}:{cy}",
                        "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-c:a", "copy", str(out)],
                       check=True, timeout=3600)
        log(f"  source had black bars ({w}x{h} -> picture {cw}x{ch}): cropped before reframing")
        return out
    except Exception as e:  # noqa: BLE001 - the gate still catches bars if this check fails
        log(f"  letterbox check skipped: {type(e).__name__}: {e}")
        return video


KICK_OUTRO_S = 3.0              # free Kick downloads end with a 3 s card (one flash frame, then "Clipped by <user>")


def _card_start(cap, dur: float) -> float | None:
    """Time of the card's first frame (the flash): the first frame after which every frame stays dark. Measured 20 Nov
    on four downloads: the flash frame sits at exactly dur-3.000 s (30 fps), so a "30 s" Kick clip has 30.000 s of
    stream picture. The old fixed 3.05 s cut threw 0.05 s of picture away and every 30 s highlight fell under a
    campaign's 30 s minimum."""
    import cv2
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    first = max(0, int(round((dur - KICK_OUTRO_S - 0.6) * fps)))
    cap.set(cv2.CAP_PROP_POS_FRAMES, first)
    rows = []                                       # (frame index, mean brightness, mostly dark?)
    i = first
    while True:
        ok, f = cap.read()
        if not ok:
            break
        g = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)
        rows.append((i, float(g.mean()), (g < 25).mean() >= 0.85))
        i += 1
    win = max(6, int(round(0.4 * fps)))             # measured: ~5 bright fade frames, then the dark card
    flashes = [j for j in range(1, len(rows) - win)
               if rows[j][1] >= 140 and rows[j][1] >= 1.3 * max(rows[j - 1][1], 1.0)
               and sum(r[2] for r in rows[j + 1:j + 1 + win]) >= win // 2]
    if not flashes:
        return None
    t = rows[flashes[-1]][0] / fps                  # the flash is the card's first frame
    return t if abs((dur - t) - KICK_OUTRO_S) <= 0.35 else None


def content_end(video: Path, dur: float) -> float:
    """Where the stream picture ends: a Kick download's last 3 s are Kick's own outro card (flash, then 97% black).
    Detected from the picture, so other sources keep their full length."""
    try:
        import cv2
        cap = cv2.VideoCapture(str(video))
        cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, dur - 1.5) * 1000)
        ok, f = cap.read()
        if ok and (cv2.cvtColor(f, cv2.COLOR_BGR2GRAY) < 25).mean() >= 0.95:
            start = _card_start(cap, dur)
            cap.release()
            return round(start if start is not None else max(0.0, dur - KICK_OUTRO_S), 2)
        cap.release()
    except Exception as e:  # noqa: BLE001 - a failed check keeps the whole clip
        print(f"outro check: {type(e).__name__}: {e}")
    return dur


def brief_name(campaign: dict | None) -> str:
    """The name every hook idea of the brief starts with ("Dasgas Dom reacts to ...", "Dasgas Dom fails ...") or ""."""
    ideas = [str(x).strip() for x in (campaign or {}).get("hook_ideas") or [] if str(x).strip()]
    if len(ideas) < 2:
        return ""
    first = [i.split()[:2] for i in ideas]
    return " ".join(first[0]) if all(f == first[0] for f in first) and len(first[0]) == 2 else ""


def whole_clip_moment(brain, words: list[Word], dur: float, campaign: dict | None = None,
                      max_len: float = 58, seen: list[str] | None = None) -> list[dict]:
    """20 Nov: Kick highlights are mostly gameplay; the podcast editor found no 20 s talking moment in them, so the
    first GTA clips failed. A short highlight is posted whole (trimmed to the campaign's max length)."""
    rules = f"- Campaign rules: banned: {campaign.get('banned')}, other: {campaign.get('other_rules')}" if campaign else ""
    name = brief_name(campaign)
    if name:                                           # 26 Nov: 4 of 4 headlines ignored the pattern ("Motorbike ride
        rules += f"\n- The title MUST start with \"{name}\" followed by what he does or tries."   # leads to eerie ...")
    if campaign and campaign.get("hook_ideas"):        # the brief's own title pattern ("Dasgas Dom reacts to ...")
        rules += ("\n- The title is shown as the headline for the whole clip: follow the brief's pattern, filled with "
                  f"what really happens: {campaign['hook_ideas']}. Like the campaign's best clip: "
                  "\"GTA 6 gas was too expensive for Dasgas Dom... so he robbed the store\".")
    data, result = brain.ask_json("editor", WHOLE_PROMPT.format(
        dur=dur, keep=min(dur, max_len), campaign_rules=rules,
        # 26 Nov: titles came out generic ("Streamer reacts to risky landing") from the transcript alone; the frames
        # say what happens (a plane wreck, the mission-failed screen), so the headline can name it
        seen=("What the picture shows (frames, in order): " + "; ".join(seen) + "\n\n") if seen else "",
        transcript=transcript_text([w for w in words if w.start >= dur - max_len]) if words else "(no speech)"),
        system=EDITOR_SYSTEM, temperature=0.5)
    m = dict(data or {}) if isinstance(data, dict) else {}
    m["title"], tflags = clean_title(str(m.get("title") or ""), proper_nouns(words, ""))
    if name and m["title"] and name.lower() not in m["title"].lower():
        tflags = list(tflags) + ["no_brief_name"]      # said in the record; the writer was told
    if tflags:
        m["title_flags"] = tflags
    # longer than allowed: keep the END (viewers press Clip right after the moment, so the payoff is last)
    m.update(start=round(max(0.0, dur - max_len), 2), end=round(dur, 2), picked_by=getattr(result, "provider", None),
             whole_clip=True)
    m["virality"] = virality(m.get("scores") or {})
    if not m.get("hook_options"):
        m["hook_options"] = [m["title"]] if m["title"] else []
    return [m]


def pick_moments(brain, words: list[Word], n_candidates: int = 12, keep: int = 4, min_len: int = 20,
                 max_len: int = 55, campaign: dict | None = None, memory=None, audience="US viewers",
                 channel_id: str = "hot_take_hq") -> list[dict]:
    rules = ("- Gameplay or violent scenes: the first 7 seconds must not show graphic violence or gore "
             "(YouTube ad rule, Sept 2026); open on the reaction or the setup instead.\n")
    if campaign:
        rules += (f"- Campaign rules: length {campaign.get('length_seconds')}, banned: {campaign.get('banned')}, "
                 f"other: {campaign.get('other_rules')}")
    mem = memory.context_block("viral clip hook", channel_id) if memory else ""
    parts = transcript_parts(words)
    raw, providers = [], []
    for part in parts:                           # long podcasts: every hour is read, not just the first two
        data, result = brain.ask_json("editor", EDITOR_PROMPT.format(
            n=n_candidates if len(parts) == 1 else math.ceil(n_candidates / len(parts)) + 2, min_len=min_len,
            max_len=max_len, audience=audience, campaign_rules=rules, memory=mem or "(no history yet)",
            transcript=transcript_text(part)), system=EDITOR_SYSTEM, temperature=0.5)
        raw += [dict(m, picked_by=result.provider) for m in data.get("moments", []) if isinstance(m, dict)]
    moments = []
    names = proper_nouns(words, " ".join(str((campaign or {}).get(k) or "") for k in ("name", "brand")))
    for m in raw:
        try:
            s0, e0 = float(m["start"]), float(m["end"])
        except (KeyError, TypeError, ValueError):
            continue
        s0, e0, grounded = ground(words, m, s0, e0)
        s, e = snap(words, s0, e0)
        opening = review_opening(words, s, e, min_len - 3)
        if opening["start"] is not None:
            s = max(opening["start"] - 0.1, 0)
        if not (min_len - 3 <= e - s <= max_len + 8):
            continue
        penalty = (OPENING_PENALTY if opening["penalise"] else 0) + (UNGROUNDED_PENALTY if grounded is False else 0)
        m["start"], m["end"] = round(s, 2), round(e, 2)
        m["virality"] = max(0, virality(m.get("scores", {})) - penalty)
        if opening["issue"] or grounded is False:
            m["opening"] = {"issue": opening["issue"], "moved": opening["start"] is not None,
                            "skipped": opening["skipped"], "penalty": penalty, "grounded": grounded}
        m["title"], tflags = clean_title(str(m.get("title") or ""), names)
        if tflags:
            m["title_flags"] = tflags
        moments.append(m)
    moments.sort(key=lambda m: m["virality"], reverse=True)
    chosen = []
    for m in moments:  # no overlapping clips
        if all(m["end"] <= c["start"] or m["start"] >= c["end"] for c in chosen):
            chosen.append(m)
        if len(chosen) == keep:
            break
    return chosen


# ---------------- face-tracked reframe ----------------
def _detector(w: int, h: int):
    import cv2
    model = ROOT / "assets" / "models" / "face_detection_yunet_2023mar.onnx"
    if not model.exists():
        model.parent.mkdir(parents=True, exist_ok=True)
        model.write_bytes(HTTP.get(YUNET_URL, timeout=120).content)
    return cv2.FaceDetectorYN.create(str(model), "", (w, h), 0.7, 0.3, 5000)


def face_track(video: Path, start: float, end: float, sample_fps: float = 4.0) -> tuple[list[float], str]:
    """Returns smoothed face-centre x (0-1) per output frame and a layout: 'crop' or 'fit'."""
    import cv2
    cap = cv2.VideoCapture(str(video))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    scale = 640 / w
    det = _detector(640, int(h * scale))
    xs, spreads = [], []
    t = start
    while t < end:
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, frame = cap.read()
        if not ok:
            break
        small = cv2.resize(frame, (640, int(h * scale)))
        _, faces = det.detect(small)
        if faces is not None and len(faces):
            faces = sorted(faces, key=lambda f: f[2] * f[3], reverse=True)[:2]
            centres = [(f[0] + f[2] / 2) / 640 for f in faces]
            xs.append(centres[0])
            spreads.append(abs(centres[0] - centres[1]) if len(centres) > 1 else 0)
        else:
            xs.append(np.nan)
        t += 1 / sample_fps
    cap.release()
    arr = np.array(xs, dtype=float)
    if np.all(np.isnan(arr)):
        arr = np.full(max(len(arr), 1), 0.5)
    idx = np.arange(len(arr))
    good = ~np.isnan(arr)
    arr = np.interp(idx, idx[good], arr[good])
    # smooth: slow camera, no jitter
    k = max(int(sample_fps * 1.5), 1)
    arr = np.convolve(np.pad(arr, (k, k), mode="edge"), np.ones(2 * k + 1) / (2 * k + 1), mode="same")[k:-k]
    crop_frac = (h * 9 / 16) / w
    layout = "fit" if spreads and np.median(spreads) > crop_frac * 0.9 else "crop"
    n_out = int((end - start) * 30)
    out = np.interp(np.linspace(0, len(arr) - 1, n_out), idx, arr) if len(arr) > 1 else np.full(n_out, arr[0])
    return out.tolist(), layout


def render_clip(video: Path, moment: dict, words: list[Word], out_path: Path, style: dict,
                hook: str | None = None) -> Path:
    import cv2
    start, end = moment["start"], moment["end"]
    xs, layout = face_track(video, start, end)
    cap = cv2.VideoCapture(str(video))
    w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 30
    cap.set(cv2.CAP_PROP_POS_MSEC, start * 1000)

    work = out_path.parent / f"{out_path.stem}_work"
    work.mkdir(parents=True, exist_ok=True)
    clip_words = [Word(x.text, x.start - start, x.end - start) for x in words if start <= x.start < end]
    ensure_fonts()
    accent = style.get("highlight_color", "#FFE600")
    emphasis = {re.sub(r"[^\w]", "", e.lower()) for e in moment.get("emphasis", []) if e}
    build_ass(clip_words, work / "captions.ass", font="Poppins Black", language="en",
              caption_color=style.get("caption_color", "#FFFFFF"), highlight_color=accent,
              emphasis_color="#3DFF6E" if accent.upper() != "#3DFF6E" else "#FFE600",
              emphasis_words=emphasis, hook=hook,
              hook_style=HookStyle(lines_bg=["#FFFFFF", accent], lines_fg=["#000000", "#000000"], font="Anton",
                                   size=128, y=210, until=3.5),
              caption_margin_v=560 if layout == "crop" else 430, font_size=112, max_words=2)
    # punch-in zoom on key words, a light grade and a progress bar (same look as the story channels)
    punches = [w.start for w in clip_words if re.sub(r"[^\w]", "", w.text.lower()) in emphasis]
    look = Look(size=(OUT_W, OUT_H), accent=accent, contrast=1.06, saturation=1.12, teal_orange=0.1,
                vignette=0.18, grain=0.0)
    grade, finish = Grader(look), Finisher(look, end - start)
    sticker = None
    if moment.get("emoji"):
        png = emoji_png(moment["emoji"])
        if png:
            sticker = (load_rgba(png, 230), max((punches or [1.0])[0], 0.5))
    fonts_rel = os.path.relpath(FONTS_DIR, work).replace("\\", "/")

    cmd = [ffmpeg.ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-y",
           "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{OUT_W}x{OUT_H}", "-r", "30", "-i", "-",
           "-ss", f"{start:.3f}", "-t", f"{end - start:.3f}", "-i", str(video.resolve()),
           "-vf", f"subtitles=captions.ass:fontsdir={fonts_rel}", "-map", "0:v", "-map", "1:a",
           *ffmpeg.H264, *ffmpeg.AAC, "-af", "loudnorm=I=-14:TP=-1.5", "-shortest",
           "-movflags", "+faststart", str(out_path.resolve())]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE, cwd=work)
    crop_w = int(h * 9 / 16)
    frame, cur_idx = None, -1
    for i in range(len(xs)):
        need = int(i * src_fps / 30)  # source frame that matches output frame i
        while cur_idx < need:
            ok, f = cap.read()
            if not ok:
                break
            frame, cur_idx = f, cur_idx + 1
        if frame is None:
            break
        t = i / 30
        z = 1.0
        for pt in punches:
            d = t - pt
            if 0 <= d < 0.6:
                z *= 1 + 0.08 * min(d / 0.06, 1.0) * np.exp(-max(d - 0.06, 0) * 6)
        if layout == "crop":
            cw, ch = int(crop_w / z), int(h / z)
            cx = int(xs[i] * w)
            x0 = min(max(cx - cw // 2, 0), w - cw)
            y0 = int((h - ch) * 0.35)
            out = cv2.resize(frame[y0:y0 + ch, x0:x0 + cw], (OUT_W, OUT_H), interpolation=cv2.INTER_LANCZOS4)
        else:  # two people far apart: show full width over a blurred background
            bg = cv2.GaussianBlur(cv2.resize(frame[:, (w - crop_w) // 2:(w + crop_w) // 2], (OUT_W, OUT_H)), (0, 0), 30)
            fg_h = int(h * OUT_W / w)
            fg = cv2.resize(frame, (OUT_W, fg_h), interpolation=cv2.INTER_AREA)
            y0 = (OUT_H - fg_h) // 2
            bg[y0:y0 + fg_h] = fg
            out = bg
        out = grade(out)
        if sticker is not None and 0 <= t - sticker[1] < 1.3:
            d = t - sticker[1]
            sc = max(0.05, min(1.15, d / 0.1) - max(0.0, min(0.15, d - 0.1)))
            sz = max(4, int(sticker[0].shape[0] * sc))
            _blend(out, cv2.resize(sticker[0], (sz, sz)), OUT_W - sz - 50, int(OUT_H * 0.56) - sz // 2)
        out = finish(out, t, i)
        proc.stdin.write(out.tobytes())
    proc.stdin.close()
    err = proc.stderr.read().decode("utf-8", "replace")
    if proc.wait() != 0:
        raise RuntimeError(f"ffmpeg failed: {err[-1500:]}")
    cap.release()
    moment["layout"] = layout
    return out_path


def write_clip_srt(words: list[Word], start: float, end: float, dest: Path, per_line: int = 6,
                   offset: float = 0.0, teaser: list | None = None) -> Path | None:
    """The clip's own captions file (the cleaned words: swear words starred), times relative to the clip. 20 Nov: the
    quality scorecard held a Stream Clips clip for "no captions file"; search and sound-off viewers need it, and
    the upload can send it to YouTube as captions."""
    ws = [w for w in words if start <= w.start < end and str(w.text).strip()]
    if not ws:
        return None

    def ts(s: float) -> str:
        ms = int(round(max(0.0, s) * 1000))
        return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"
    rows = []
    for k in range(0, len(ws), per_line):
        part = ws[k:k + per_line]
        a, b = part[0].start - start + offset, min(part[-1].end, end) - start + offset
        rows.append(f"{len(rows) + 1}\n{ts(a)} --> {ts(max(b, a + 0.5))}\n{' '.join(w.text.strip() for w in part)}\n")
    if teaser and teaser[1]:                    # the payoff flash's words come first (the gate reads the first one)
        t0 = start + float(teaser[0])
        flash = [w for w in words if t0 <= w.start < t0 + teaser[1] - 0.1 and str(w.text).strip()]
        if flash:
            a, b = flash[0].start - t0, min(flash[-1].end, t0 + teaser[1]) - t0
            rows = [f"0\n{ts(a)} --> {ts(max(b, a + 0.4))}\n{' '.join(w.text.strip() for w in flash)}\n"] + rows
            rows = [f"{i}\n" + r.split("\n", 1)[1] for i, r in enumerate(rows, 1)]
    dest.write_text("\n".join(rows), encoding="utf-8")
    return dest


def make_clips(brain, source: str, channel: dict, campaign: dict | None = None, memory=None, keep: int = 4,
               words: list[Word] | None = None, moments: list[dict] | None = None, log=print) -> tuple[Path, list[dict]]:
    if campaign:                                   # safety gate before any work for a campaign
        from . import campaign_safety as cs
        verdict = cs.check_campaign(campaign)
        if verdict["verdict"] == "BLOCK":
            raise RuntimeError("Campaign blocked by the safety check: " + "; ".join(verdict["block"]))
        if verdict.get("payer_id"):
            from . import db
            ok, why = cs.can_submit(cs.connect(db.connect()), verdict["payer_id"])
            if not ok:
                raise RuntimeError(f"Not making clips for this payer right now: {why}")
    from .clip_sources import permission_for           # no clip without proof of permission (raises otherwise)
    permission = permission_for(source, campaign)
    log(f"Permission: {permission.get('basis')} ({permission.get('owner')}): {permission.get('evidence')}")
    stamp = time.strftime("%Y%m%d_%H%M%S")
    out_dir = ROOT / "output" / channel["id"] / f"{stamp}_clips"
    out_dir.mkdir(parents=True, exist_ok=True)
    video = remove_letterbox(fetch_source(source, out_dir / "source"), log=log)
    if words is None:
        src_dur = ffmpeg.duration(video)
        if src_dur > LONG_SOURCE_S:                           # streams / long videos / gameplay sessions
            keep = max(keep, min(MAX_CLIPS_PER_SOURCE, int(src_dur // 1100)))     # ~1 clip per 18 min, up to 15
            log(f"Long source ({src_dur / 3600:.1f} h): aiming for {keep} clips")
            words = transcribe_hotspots(video, language="en", log=log, top=min(MAX_CLIPS_PER_SOURCE + 3, keep + 3))
        else:
            log("Transcribing (Whisper)…")
            words = transcribe(video, language="en")
    mutes = []
    if campaign:                                    # 20 Nov: swear words and slurs muted, f*** in captions (brief allows)
        from . import profanity
        words, mutes = profanity.clean(words)
        if mutes:
            log(f"  {len(mutes)} swear word(s)/slur(s) muted")
    ls = (campaign or {}).get("length_seconds") or {}
    if moments is None and ffmpeg.duration(video) <= SHORT_SOURCE_S:
        full = ffmpeg.duration(video)
        dur = content_end(video, full)
        if dur < full:
            log(f"  Kick's {full - dur:.1f} s outro card cut (the stream ends at {dur:.1f} s)")
        if dur < (ls.get("min") or 0):
            raise UnusableFootage(f"Highlight is {dur:.2f} s, under the campaign's {ls['min']} s minimum")
        log("Short highlight (a streamer's own clip): keeping it whole, writing its hook and title…")
        seen = []
        if campaign:
            try:
                from .clip_shown import frames
                seen = frames(video, dur)
            except Exception as e:  # noqa: BLE001 - the title is still written from the transcript (said)
                log(f"  frames for the title: {type(e).__name__}: {e}")
        moments = whole_clip_moment(brain, words, dur, campaign=campaign, max_len=min(ls.get("max") or 58, 60),
                                    seen=seen)
    if moments is None:
        log("Finding the best moments…")
        moments = pick_moments(brain, words, keep=keep, n_candidates=max(12, keep * 2), campaign=campaign, memory=memory,
                               channel_id=channel.get("id", "hot_take_hq"), min_len=max(ls.get("min") or 20, 15), max_len=min(ls.get("max") or 55, 58))
    results = []
    if campaign:                                    # the gate's reading of the brief decides the Ad label too
        from . import campaign_gate
        if campaign_gate.rules(campaign)["ad"] and not campaign.get("disclosure_text"):
            campaign = dict(campaign, disclosure_text="Ad")
    if campaign and campaign.get("needs_logo") and not campaign.get("logo_path"):
        from .campaign_rules import logo_file
        lp = logo_file(campaign, out_dir)
        if lp:
            campaign = dict(campaign, logo_path=str(lp))
        else:
            log("  campaign wants its logo on screen but no logo file could be read: clips are flagged for review")
    for i, m in enumerate(moments, 1):
        m["mute"] = [(a, b) for a, b in mutes if b > m["start"] and a < m["end"]]
        hook = (m.get("hook_options") or [None])[0]
        path = out_dir / f"clip_{i:02d}.mp4"
        log(f"Clip {i}: {m['start']:.0f}-{m['end']:.0f}s, virality {m.get('virality')}/100 — {hook}")
        if channel.get("style", {}).get("renderer") == "v2":
            render_clip(video, m, words, path, channel.get("style", {}), hook)
        else:                                     # v3: speaker cuts, split for exchanges, clean captions
            from .clipv3 import render_clip_v3
            render_clip_v3(video, m, words, path, channel.get("style", {}), hook, campaign=campaign, log=log)
        write_clip_srt(words, m["start"], m["end"], path.with_suffix(".srt"),
                       offset=(m.get("teaser") or [0, 0])[1],      # the payoff teaser runs first
                       teaser=m.get("teaser"))
        credit = permission.get("credit") or ""
        if campaign:                                # only the brief's real tags (never its sentences), #ad first
            caption = campaign_gate.fix_caption(f"{m.get('caption', '')}\n\n{credit}".strip(), campaign)
        else:
            caption = f"{m.get('caption', '')}\n\n{credit}\n{' '.join(channel.get('hashtags', []))}".strip()
        meta = {"file": path.name, "title": m.get("title"), "title_flags": m.get("title_flags", []), "caption": caption, "hook_options": m.get("hook_options"),
                "virality": m.get("virality"), "scores": m.get("scores"), "why": m.get("why"),
                "start": m["start"], "end": m["end"], "layout": m.get("layout"),
                "emphasis": m.get("emphasis", []), "emoji": m.get("emoji", ""),
                "duration_s": round(ffmpeg.duration(path), 2), "source": source,
                "campaign": (campaign or {}).get("id"), "disclosure": bool((campaign or {}).get("disclosure_text")),
                "permission": permission}
        if campaign:                                # ONE gate: every campaign condition (owner, 17 Nov)
            from . import db
            spoken = " ".join(w.text for w in words if m["start"] <= w.start < m["end"])
            meta.update(made_at=time.time(), logo_shown=bool(campaign.get("logo_path")), has_added_music=False,
                        transcript=spoken[:3000], gate_cache={})
            try:                                    # 26 Nov: the potential judge reads text only (clip_shown.py)
                from .clip_shown import describe
                meta["shown"] = describe(path, m, campaign, words, duration=meta["duration_s"])
                meta["teaser"] = m.get("teaser")
            except Exception as e:  # noqa: BLE001 - the description only helps the judge (said, never silent)
                log(f"  clip description for the judge failed: {type(e).__name__}: {e}")
            try:
                from . import campaign_safety as cs
                meta["edit_hash"] = cs.video_hash(path)
            except Exception as _swallowed:  # noqa: BLE001
                noted("clips.py:928", _swallowed)
                pass
            campaign_gate.stamp(meta, campaign_gate.check(meta, campaign, conn=db.connect(), brain=brain,
                                                          transcript=spoken, cache=meta["gate_cache"]))
            log("  gate: " + campaign_gate.summary(meta["gate"]["problems"]))
        try:
            from .reels import clip_reel
            meta["reel"] = clip_reel(out_dir, meta, channel, min_s=ls.get("min") or 0)["file"]
        except Exception as e:  # noqa: BLE001
            log(f"Reel variant failed: {e}")
        results.append(meta)
    (out_dir / "clips.json").write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    return out_dir, results
