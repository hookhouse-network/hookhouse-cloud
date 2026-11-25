"""What a finished campaign clip SHOWS, in words, for the potential judge (P7, 26 Nov).

The judge reads text only: for a clip it got the captions file (mostly a streamer's starred swearing) and held every
GTA clip for caption_hook 2-3 / hook 3 / self_contained 3 ("replace the weak audio-only transcript with a visual
hook"), although the clip opens on the explosion, shows the webcam over the gameplay and carries a headline band for
its whole length. This writes the clip's own facts (layout, on-screen headline, the opening payoff flash and its words,
the end line) plus a free Gemini look at four frames into the clip record (clips.json "shown"); the judge reads it
before the transcript. Without a key or quota only the facts are written; the clip is never held by this step."""
from __future__ import annotations

import base64
import datetime as dt
import json
import re
import subprocess
import tempfile
from pathlib import Path

FRAME_Q = ("These are 4 frames of a vertical 9:16 gaming clip, left to right at {times}. The streamer's webcam is at "
           "the top, the game below. For each frame say in at most 14 plain words what happens in the game and how the "
           "streamer reacts. Do not guess names. JSON only: {{\"frames\": [\"...\", \"...\", \"...\", \"...\"]}}")


def facts(moment: dict, campaign: dict | None, words: list | None = None) -> str:
    """The clip's on-screen facts we set ourselves (no model needed)."""
    out = []
    stream = bool(moment.get("stream"))
    if stream:
        out.append("Layout: the streamer's face cam on top, the gameplay below.")
    title = str(moment.get("title") or "").strip()
    if title and (campaign or {}).get("headline_box"):
        out.append(f"On-screen headline for the whole clip (white band): \"{title}\".")
    teaser = moment.get("teaser")
    if teaser and teaser[1]:
        t0 = float(moment.get("start") or 0) + float(teaser[0])
        line = " ".join(w.text for w in (words or []) if t0 <= w.start < t0 + teaser[1] - 0.1).strip()
        out.append(f"Opens with a {teaser[1]:.1f}s flash of the payoff moment" + (f" (he says: \"{line}\")" if line else "")
                   + ", then plays from the setup to that payoff.")
    out.append("Word-by-word captions are burned in.")
    if (campaign or {}).get("end_text"):
        out.append(f"Last 3 seconds show: \"{campaign['end_text']}\".")
    return " ".join(out)


def _sheet(video: Path, times: list[float], dest: Path) -> bool:
    from PIL import Image
    from .media import ffmpeg
    tiles = []
    try:
        for i, t in enumerate(times):
            f = dest.with_name(f"f{i}.jpg")
            ffmpeg.run(["-ss", f"{t:.2f}", "-i", str(video), "-frames:v", "1", "-vf", "scale=256:-1", "-q:v", "4",
                        str(f)])
            tiles.append(Image.open(f).convert("RGB"))
    except (RuntimeError, OSError, subprocess.SubprocessError) as e:
        print(f"  clip frames for the judge: {type(e).__name__}: {str(e)[:100]}", flush=True)
        return False
    sheet = Image.new("RGB", (sum(x.width for x in tiles), max(x.height for x in tiles)))
    x = 0
    for im in tiles:
        sheet.paste(im, (x, 0))
        x += im.width
    sheet.save(dest, quality=85)
    return True


def frames(video: Path, duration: float) -> list[str]:
    """A free Gemini look at four frames ([] without a key, quota or answer)."""
    import os
    key = os.environ.get("GEMINI_API_KEY")
    if not key or duration < 4:
        return []
    from . import storyboard
    times = [0.7, duration * 0.35, duration * 0.65, max(0.0, duration - 3.5)]
    with tempfile.TemporaryDirectory() as tmp:
        sheet = Path(tmp) / "sheet.jpg"
        if not _sheet(video, times, sheet):
            return []
        image = base64.b64encode(sheet.read_bytes()).decode()
    q = FRAME_Q.format(times=", ".join(f"{t:.1f}s" for t in times))
    today = dt.datetime.now(dt.timezone.utc).date().isoformat()
    for model in storyboard.EYES_MODELS:
        if storyboard._EYES_OUT.get(model) == today:
            continue
        r = storyboard._eyes_ask(model, key, image, q)
        if getattr(r, "status_code", None) != 200:
            if r is not None and r.status_code == 429 and "PerDay" in str(r.text):
                storyboard._EYES_OUT[model] = today
            continue
        try:
            said = "".join(str(p.get("text") or "") for p in r.json()["candidates"][0]["content"]["parts"])
            found = re.search(r"\{.*\}", said, re.S)
            got = json.loads(found.group(0) if found else said).get("frames") or []
            return [f"{t:.1f}s: {str(x).strip().rstrip('.')[:120]}" for t, x in zip(times, got) if str(x).strip()]
        except (ValueError, KeyError, IndexError, AttributeError) as e:
            print(f"  clip frames for the judge: odd answer ({type(e).__name__})", flush=True)
            return []
    return []


def describe(video: Path, moment: dict, campaign: dict | None, words: list | None = None,
             duration: float | None = None) -> str:
    seen = frames(video, float(duration or moment.get("duration_s") or 0))
    return facts(moment, campaign, words) + (" Frames: " + "; ".join(seen) + "." if seen else "")
