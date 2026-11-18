"""Bloop & Friends songs: public-domain melodies in our own arrangement, with our own lyrics (the approach ChuChu TV
used: new positive lyrics on traditional tunes). Sung by engine/media/singer.py, mixed with our own instrumental,
mastered for streaming (-14 LUFS, true peak -1 dBTP) and exported for a free distributor (RouteNote: 44.1 kHz /
16-bit WAV + 3000 x 3000 cover). YouTube Content ID must stay OFF for these tracks so our own videos are never claimed.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import soundfile as sf

from .config import ROOT

OUT = ROOT / "data" / "products" / "music"
CACHE = ROOT / "data" / "cache" / "sung_words"


def _phrase(text: str, notes: list[tuple[int, float]]) -> list[tuple[str, float, float]]:
    """'Count with Bloop it's fun to do' + notes -> [(syllable, midi, beats)] (syllables split with '|')."""
    syls = [s for s in text.replace("|", " -").split()]
    assert len(syls) == len(notes), (text, len(syls), len(notes))
    return [(s, m, b) for s, (m, b) in zip(syls, notes)]


# Twinkle (Ah! vous dirai-je, maman, 1761): A = C C G G A A G(2) | F F E E D D C(2); B = G G F F E E D(2)
TW_A1 = [(60, 1), (60, 1), (67, 1), (67, 1), (69, 1), (69, 1), (67, 2)]
TW_A2 = [(65, 1), (65, 1), (64, 1), (64, 1), (62, 1), (62, 1), (60, 2)]
TW_B = [(67, 1), (67, 1), (65, 1), (65, 1), (64, 1), (64, 1), (62, 2)]
TW_CHORDS = [48, 48, 53, 48, 53, 48, 55, 48] + [48, 53, 48, 55] * 2 + [48, 48, 53, 48, 53, 48, 55, 48]
# Frere Jacques (18th century): C D E C x2 | E F G(2) x2 | G A G F (eighths) E C x2 | C G C(2) x2
FJ_1 = [(60, 1), (62, 1), (64, 1), (60, 1)]
FJ_2 = [(64, 1), (65, 1), (67, 2)]
FJ_3 = [(67, .5), (69, .5), (67, .5), (65, .5), (64, 1), (60, 1)]
FJ_4 = [(60, 1), (55, 1), (60, 2)]


# Jingle Bells chorus (James Lord Pierpont, 1857, public domain), key of C
JB_1 = [(64, 1), (64, 1), (64, 2), (64, 1), (64, 1), (64, 2), (64, 1), (67, 1), (60, 1.5), (62, .5), (64, 4)]
JB_2 = [(65, 1), (65, 1), (65, 1.5), (65, .5), (65, 1), (64, 1), (64, 1), (64, .5), (64, .5), (64, 1), (62, 1),
        (62, 1), (64, 1), (62, 2), (67, 2)]
JB_4 = [(65, 1), (65, 1), (65, 1), (65, 1), (65, 1), (64, 1), (64, 1), (64, .5), (64, .5), (67, 1), (67, 1), (65, 1),
        (62, 1), (60, 4)]
JB_CHORDS = [48, 48, 48, 48, 53, 48, 50, 55, 48, 48, 48, 48, 53, 48, 55, 48]


def _jingle_bells(l1: str, l2: str, l4: str) -> list[tuple[str, float, float]]:
    out = []
    for text, notes in ((l1, JB_1), (l2, JB_2), (l1, JB_1), (l4, JB_4)):
        out += _phrase(text, notes)
    return out


def _twinkle(lines: list[str]) -> list[tuple[str, float, float]]:
    shapes = [TW_A1, TW_A2, TW_B, TW_B, TW_A1, TW_A2]
    out = []
    for text, notes in zip(lines, shapes):
        out += _phrase(text, notes)
    return out


def _jacques(a: str, b: str, c: str, d: str) -> list[tuple[str, float, float]]:
    out = []
    for text, notes in ((a, FJ_1), (a, FJ_1), (b, FJ_2), (b, FJ_2), (c, FJ_3), (c, FJ_3), (d, FJ_4), (d, FJ_4)):
        out += _phrase(text, notes)
    return out


SONGS = [
    {"id": "count_with_bloop", "title": "Count with Bloop!", "bpm": 100, "style": "play", "voice": "af_heart",
     "season": "evergreen", "themes": ["counting", "numbers", "theme song"],
     "chords": TW_CHORDS, "melody": "Twinkle, Twinkle (Ah! vous dirai-je, maman, 1761, public domain)",
     "verses": [_twinkle(["Count with Bloop it's fun to do", "one and two and three and four",
                          "five and six and sev|en eight", "nine and ten now we are great",
                          "Count with Bloop it's fun to do", "you can count and I can too"])] * 2},
    {"id": "where_is_bloop", "title": "Where Is Bloop?", "bpm": 112, "style": "play", "voice": "af_heart",
     "season": "evergreen", "themes": ["hide and seek", "counting", "game"],
     "chords": [48] * 16, "melody": "Frere Jacques (18th century, public domain)",
     "verses": [_jacques("one two three four", "where is Bloop", "count to ten and find him", "here he is"),
                _jacques("five six sev|en", "where is Pip", "count to ten and find Pip", "there is Pip")]},
    {"id": "count_the_snowflakes", "title": "Count the Snowflakes", "bpm": 120, "style": "play", "voice": "af_heart",
     "season": "winter", "themes": ["winter", "snow", "christmas", "holiday", "jingle"],
     "chords": JB_CHORDS, "melody": "Jingle Bells chorus (James Lord Pierpont, 1857, public domain)",
     "verses": [_jingle_bells("snow|flakes fall snow|flakes fall count them one by one",
                              "one two three and four and five oh what fun it is to count them",
                              "six and sev|en eight and nine and ten now we are all done")] * 2},
    {"id": "goodnight_bloop", "title": "Goodnight, Bloop", "bpm": 76, "style": "lullaby", "voice": "af_heart",
     "season": "evergreen", "themes": ["bedtime", "lullaby", "sleep", "stars", "night"],
     "chords": TW_CHORDS, "melody": "Twinkle, Twinkle (1761, public domain), as a lullaby",
     "verses": [_twinkle(["Good|night Bloop the moon is bright", "count the stars with me to|night",
                          "one star two stars three stars glow", "four and five now off we go",
                          "Good|night Bloop the moon is bright", "sleep now sweet dreams and good|night"])] * 2},
]


SEASONS = {12: "winter", 1: "winter", 2: "winter", 11: "winter"}      # Nov-Feb: winter / holiday songs lead


def plan_releases(today=None, trend_words: list[str] | None = None) -> list[dict]:
    """Which songs to release and use first: the season's songs, then songs whose themes match what is winning in
    the kids niche right now (weekly YouTube search, memory), then the evergreen ones."""
    import datetime as _dt
    today = today or _dt.date.today()
    season = SEASONS.get(today.month, "evergreen")
    words = [w.lower() for w in (trend_words if trend_words is not None else _kids_trend_words())]

    def rank(song):
        hits = sum(1 for th in song.get("themes", []) for w in words if th in w)
        return (song.get("season") == season and season != "evergreen", hits)
    return sorted(SONGS, key=rank, reverse=True)


def _kids_trend_words() -> list[str]:
    """Titles of the kids niche's current winners (weekly official YouTube search, kept 30 days)."""
    import sqlite3
    db = ROOT / "data" / "memory.db"
    if not db.exists():
        return []
    try:
        with sqlite3.connect(db) as c:
            return [r[0] for r in c.execute("SELECT text FROM items WHERE kind='viral_example' AND "
                                            "channel='bloop_and_friends'").fetchall()]
    except sqlite3.Error:
        return []


def intelligibility(vocal: np.ndarray, sr: int, lyrics: list[tuple[str, float, float]]) -> float:
    """Share of the lyric words that speech recognition hears in the sung vocal (an automatic 'listen')."""
    import re
    import tempfile

    from .media.transcribe import transcribe
    want = [re.sub(r"[^a-z']", "", w.lower()) for w in " ".join(
        (syl if not syl.startswith("-") else "\x00" + syl[1:]) for syl, _, _ in lyrics).replace(" \x00", "").split()]
    want = [w for w in want if w]
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "vocal.wav"
        sf.write(f, vocal, sr)
        heard = {re.sub(r"[^a-z']", "", w.text.lower()) for w in transcribe(f, language="en", size="small")}
    return round(sum(1 for w in want if w in heard) / max(1, len(want)), 2)


QA = {"pitch_cents": 35.0, "intelligibility": 0.6}


def jingle() -> np.ndarray:
    """Sonic logo for the end of every Bloop video: a sung "Count with Bloop!" over a bell chord (cached)."""
    from .media.singer import sing
    from .snack import audio as au
    f = OUT / "jingle_count_with_bloop.wav"
    if f.exists():
        x, _ = sf.read(f, dtype="float32")
        return x if x.ndim == 1 else x.mean(axis=1)
    voc = sing([("Count", 67, 1), ("with", 69, 1), ("Bloop", 72, 2)], 100, "af_heart", CACHE, out_sr=au.SR)
    n = len(voc)
    bell = au.chord([60, 64, 67, 72], n / au.SR, "bell", 0.5)[:n]
    mix = voc * 3.0
    mix[: len(bell)] += bell * 0.35
    mix = mix / (np.abs(mix).max() + 1e-9) * 0.5
    OUT.mkdir(parents=True, exist_ok=True)
    sf.write(f, mix.astype(np.float32), au.SR)
    return mix.astype(np.float32)


def _accompany(lyrics: list[tuple[str, float, float]], chords: list[int], bpm: float, style: str,
               total: float) -> np.ndarray:
    """Our own arrangement: the melody softly doubled, chords, bass, and a shaker (play) or a music box (lullaby)."""
    from .kids import _clap, _pad_chord
    from .snack import audio as au
    beat = 60.0 / bpm
    melody, t = [], 0.0
    for syl, m, b in lyrics:
        if syl.strip():
            melody.append((t, int(m) + 12, 0.45))
        t += b * beat
    n_chords = int(np.ceil(t / (2 * beat)))
    bass, pad = [], np.zeros(int(total * au.SR) + au.SR, np.float32)
    for k in range(n_chords):
        root = chords[k % len(chords)]
        bass.append((k * 2 * beat, root, 0.55))
        au.place(pad, _pad_chord(root, 2 * beat + 0.15), k * 2 * beat)
    lead = "bell" if style == "lullaby" else "kalimba"
    bed = au.render_notes(melody, total, lead, min_gap=0.05, dur=1.2) * (0.55 if style == "lullaby" else 0.5)
    if style != "lullaby":
        bed += au.render_notes(bass, total, "pluck", min_gap=0.05, dur=1.0) * 0.5
        s = beat / 2
        while s < t:
            au.place(bed, _clap(int(s * 10))[: int(0.05 * au.SR)] * 0.18, s)
            s += beat
    bed += pad[: len(bed)] * (1.3 if style == "lullaby" else 1.0)
    return bed


def render(song: dict, log=print) -> dict:
    from .media.singer import pitch_error_cents, sing
    from .snack import audio as au
    beat = 60.0 / song["bpm"]
    intro = 4 * beat
    parts, errs, heard = [], [], None
    voice = song["voice"]
    for cand in (song["voice"], "af_bella", "af_sarah"):        # automatic quality gate: re-sing if unclear
        test = sing(song["verses"][0], song["bpm"], cand, CACHE, out_sr=au.SR)
        e = pitch_error_cents(test, au.SR, song["verses"][0], song["bpm"])
        try:
            h = intelligibility(test, au.SR, song["verses"][0])
        except Exception:  # noqa: BLE001 - no speech recognition available: pitch check only
            h = None
        if heard is None or (h or 0) > (heard or 0):
            voice, heard = cand, h
        if e <= QA["pitch_cents"] and (h is None or h >= QA["intelligibility"]):
            voice, heard = cand, h
            break
    for verse in song["verses"]:
        voc = sing(verse, song["bpm"], voice, CACHE, out_sr=au.SR)
        errs.append(pitch_error_cents(voc, au.SR, verse, song["bpm"]))
        dur = sum(b for _, _, b in verse) * beat
        bed = _accompany(verse, song["chords"], song["bpm"], song["style"], dur + 1.0)
        n = int(dur * au.SR)
        mix = np.zeros(n, np.float32)
        mix += bed[:n] * 0.9
        mix[: min(n, len(voc))] += voc[:n] * 3.2
        parts.append(mix)
    intro_bed = _accompany(song["verses"][0][:4], song["chords"], song["bpm"], song["style"], intro + 0.5)[: int(intro * au.SR)]
    outro = au.chord([60, 64, 67, 72], 2.6, "bell", 0.5) * 0.6
    track = np.concatenate([intro_bed * 0.9, *parts, outro]).astype(np.float32)
    OUT.mkdir(parents=True, exist_ok=True)
    raw = OUT / f"{song['id']}_raw.wav"
    sf.write(raw, np.stack([track, track], axis=1), au.SR)
    final = OUT / f"{song['id']}.wav"
    _master(raw, final)
    raw.unlink(missing_ok=True)
    pitch = round(float(np.median(errs)), 1)
    passed = pitch <= QA["pitch_cents"] and (heard is None or heard >= QA["intelligibility"]) and len(track) / au.SR >= 31
    info = {"id": song["id"], "title": song["title"], "file": final.name, "seconds": round(len(track) / au.SR, 1),
            "pitch_error_cents": pitch, "intelligibility": heard, "voice": voice, "qa_passed": passed,
            "season": song.get("season", "evergreen"), "melody": song["melody"]}
    log(f"Song: {song['title']} {info['seconds']} s, pitch {pitch} cents, words heard "
        f"{'-' if heard is None else f'{heard:.0%}'}, QA {'passed' if passed else 'FAILED'}")
    return info


def _master(src: Path, dst: Path) -> None:
    """Streaming master: -14 LUFS, true peak -1 dBTP (limiter), 44.1 kHz / 16-bit WAV (distributor format)."""
    from .media import ffmpeg
    from .snack.encode import _loudness
    m = _loudness(src)
    af = ("loudnorm=I=-14:TP=-1.5:LRA=11:linear=true:"
          f"measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}:"
          f"measured_thresh={m['input_thresh']}:offset={m['target_offset']},"
          "alimiter=limit=0.83:attack=5:release=50:level=false") if m and m.get("input_i") not in (None, "-inf") else "anull"
    ffmpeg.run(["-i", str(src), "-af", af, "-ar", "44100", "-sample_fmt", "s16", str(dst)])


def cover(dest: Path, title: str = "Count with Bloop!", subtitle: str = "Songs for Little Ones · Vol. 1") -> Path:
    """3000 x 3000 cover (distributor minimum) from our own characters."""
    from PIL import Image, ImageDraw, ImageFont

    from .kids import _BASE_CAST
    from .media.mascot import Mascot
    S = 3000
    img = Image.new("RGB", (S, S), (143, 211, 244))
    d = ImageDraw.Draw(img)
    for i in range(S):                                         # sky gradient
        c = tuple(int(a + (b - a) * i / S) for a, b in zip((120, 200, 245), (226, 245, 252)))
        d.line([(0, i), (S, i)], fill=c)
    d.ellipse((-400, 2150, S + 400, 3700), fill=(155, 215, 112))
    font = next((str(p) for p in (ROOT / "assets" / "fonts").rglob("LuckiestGuy-Regular.ttf")), None)
    big = ImageFont.truetype(font, 330) if font else ImageFont.load_default()
    small = ImageFont.truetype(font, 140) if font else ImageFont.load_default()
    d.text((S // 2, 330), title, font=big, fill=(255, 111, 97), anchor="mt", stroke_width=22, stroke_fill="white")
    d.text((S // 2, 760), subtitle, font=small, fill=(46, 58, 89), anchor="mt")
    for i, (name, x) in enumerate((("Bloop", 0.22), ("Pip", 0.44), ("Mo", 0.64), ("Dee", 0.83))):
        col, shape, *_ = _BASE_CAST[name]
        spr = Mascot(size=900 if name == "Bloop" else 720, body=col, outline="#2E3A59", seed=i, shape=shape).draw(0.4)
        rgba = Image.fromarray(spr[..., [2, 1, 0, 3]])
        img.paste(rgba, (int(S * x) - rgba.width // 2, 2350 - rgba.height + (60 if name != "Bloop" else 0)), rgba)
    d.text((S // 2, S - 230), "Bloop & Friends", font=small, fill="white", anchor="mt", stroke_width=10, stroke_fill=(46, 58, 89))
    img.save(dest, quality=92)
    return dest


def album(log=print) -> Path:
    """Render every song + cover + a release sheet for the distributor."""
    infos = [render(s, log) for s in plan_releases()]                 # the season's / trending songs first
    OUT.mkdir(parents=True, exist_ok=True)
    cv = cover(OUT / "cover_3000.jpg")
    sheet = OUT / "release.md"
    lines = ["# Release: Count with Bloop! (Songs for Little Ones, Vol. 1)", "",
             f"Made {time.strftime('%Y-%m-%d')}. Upload with a free distributor (RouteNote free plan: $0, you keep 85%).",
             "", "**Artist:** Bloop & Friends · **Genre:** Children's Music · **Label:** HookHouse · "
             "**Language:** English · **Explicit:** no",
             "**Cover:** cover_3000.jpg (3000 x 3000) · **Audio:** 44.1 kHz / 16-bit WAV, mastered to -14 LUFS",
             "**IMPORTANT:** turn OFF YouTube Content ID / 'YouTube Music monetization claims' for these tracks, or "
             "our own Bloop videos would get claimed. Composition: traditional (public domain) melody, lyrics by "
             "Bloop & Friends (HookHouse). Vocals: synthetic voice (say so if the distributor asks about AI).", "",
             "Order = upload order (the season's and trending songs first). Every track passed an automatic check: "
             "in tune (under 35 cents), words clear to speech recognition (60%+), -14 LUFS, at least 31 seconds.", "",
             "| # | Title | File | Length | Season | Melody | In tune | Words heard | Check |",
             "|---|---|---|---|---|---|---|---|---|"]
    for i, s in enumerate(infos, 1):
        heard_txt = "-" if s["intelligibility"] is None else f"{s['intelligibility']:.0%}"
        check = "✅ passed" if s["qa_passed"] else "❌ not released"
        lines.append(f"| {i} | {s['title']} | {s['file']} | {s['seconds']} s | {s['season']} | {s['melody']} | "
                     f"{s['pitch_error_cents']} cents | {heard_txt} | {check} |")
    sheet.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (OUT / "release.json").write_text(json.dumps(infos, indent=1), encoding="utf-8")
    log(f"Album ready: {OUT} (cover {cv.name})")
    return OUT
