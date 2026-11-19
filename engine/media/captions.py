"""All on-screen text, written as one .ass subtitle file that ffmpeg (libass) burns in.

libass shapes Hindi correctly, so every piece of text goes through here:
- captions: 1-2 words at a time, bounce-in, glow, current word highlighted,
  key words (numbers, names) bigger in the accent colour
- hook title: stacked colour strips that slide in (first seconds only)
- labels: small tags like "REAL PHOTO · 1872" on evidence shots
- big text: full-screen kinetic words for text shots (numbers count up)
"""
from __future__ import annotations

import re
import textwrap
from dataclasses import dataclass, field
from pathlib import Path

W, H = 1080, 1920


@dataclass
class Word:
    text: str
    start: float
    end: float


@dataclass
class Label:
    start: float
    end: float
    text: str
    x: int = 90
    y: int = 330
    bg: str = "#E50914"
    fg: str = "#FFFFFF"


@dataclass
class BigText:
    start: float
    end: float
    text: str
    color: str = "#FFFFFF"
    sub: str = ""                       # smaller line under it
    count_up: bool = True               # "183 RUNS" counts 0 -> 183


@dataclass
class HookStyle:
    lines_bg: list[str] = field(default_factory=lambda: ["#FFFFFF", "#FF3B3B"])
    lines_fg: list[str] = field(default_factory=lambda: ["#000000", "#FFFFFF"])
    font: str = "Bebas Neue"
    size: int = 118
    y: int = 260
    until: float | None = 2.8           # None = whole video


def ass_color(hex_color: str, alpha: int = 0) -> str:
    """#RRGGBB -> &HAABBGGRR"""
    h = hex_color.lstrip("#")
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H{alpha:02X}{b}{g}{r}".upper()


def _ts(t: float) -> str:
    t = max(t, 0)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def _esc(text: str) -> str:
    return text.replace("\\", "").replace("{", "(").replace("}", ")").replace("\n", " ")


def chunk_words(words: list[Word], max_words: int = 3, max_chars: int = 18, max_gap: float = 0.45) -> list[list[Word]]:
    chunks, cur = [], []
    for w in words:
        if cur:
            too_long = len(" ".join(x.text for x in cur + [w])) > max_chars or len(cur) >= max_words
            gap = w.start - cur[-1].end > max_gap
            ends_sentence = re.search(r"[.!?,;:।]$", cur[-1].text) is not None
            if too_long or gap or ends_sentence:
                chunks.append(cur)
                cur = []
        cur.append(w)
    if cur:
        chunks.append(cur)
    return chunks


def _hook_single_box(hook: str, hs, size: tuple[int, int], hook_end: float, sp: int) -> list[str]:
    """The hook as one white rounded box (soft shadow) with black text, at most 2 lines: the TikTok-native look.
    Text is measured with the real font so the box always fits."""
    # research (podcast spec / cover C1): hook block max 860 px wide, at most 2 lines, top edge at y >= 290
    max_w = min(int(size[0] * 0.84), 860 + 60) if size[1] > size[0] else int(size[0] * 0.84)
    pad_x, pad_y = 30, 14
    fs = int(hs.size * 0.86)
    fs0 = fs
    words = _esc(hook).split()
    while True:
        rows, cur = [], ""
        for wd in words:
            trial = f"{cur} {wd}".strip()
            if cur and _text_width(trial, hs.font, fs) > max_w - 2 * pad_x:
                rows.append(cur)
                cur = wd
            else:
                cur = trial
        rows.append(cur)
        if len(rows) <= 2 or fs <= 56:
            break
        fs -= 4
    rows = rows[:2]
    line_h = int(fs * 1.0)
    bw = int(max(_text_width(r, hs.font, fs) for r in rows)) + 2 * pad_x
    bh = line_h * len(rows) + 2 * pad_y
    x0, y0 = size[0] // 2 - bw // 2, hs.y
    # owner, 11 Nov: boxes look outdated and cover the video -> clean white text, thin outline + soft shadow
    out = []
    for i, row in enumerate(rows):
        y = y0 + pad_y + i * line_h
        fg = ass_color(hs.lines_fg[min(i, len(hs.lines_fg) - 1)]) if hs.lines_fg else "&H00FFFFFF&"
        out.append(f"Dialogue: 4,{_ts(0)},{_ts(hook_end)},HookClean,,0,0,0,,{{\\an8\\pos({size[0] // 2},{y})\\fs{fs}"
                   f"\\bord5\\shad4\\1c{fg}\\3c&H000000&\\4c&H000000&\\4a&H60&\\fad(0,250)}}{row}")
    return out


def wrap_hook(text: str, width: int = 16) -> list[str]:
    return textwrap.wrap(_esc(text), width=width)[:3]


def _text_width(text: str, family: str, size: int) -> float:
    """Pixel width of one line as libass draws it. Uses the real font file when we have it, else an estimate.
    libass treats the font size as the full line height (ascent + descent), so glyphs come out
    smaller than Pillow's em-based size — scale by size / (ascent + descent)."""
    try:
        from PIL import ImageFont
        from .fonts import font_file
        f = ImageFont.truetype(str(font_file(family)), size)
        asc, desc = f.getmetrics()
        return f.getlength(text) * size / max(asc + desc, 1)
    except Exception:
        return len(text) * size * 0.45


def fit_big(text: str, family: str, base: int, max_w: int) -> tuple[list[str], int]:
    """Lines + font size so big text never runs off screen: one line if it fits,
    else two balanced lines, then shrink until the widest line fits."""
    words = text.split()
    options = [[text]]
    if len(words) > 1:
        options.append(min(([" ".join(words[:k]), " ".join(words[k:])] for k in range(1, len(words))),
                           key=lambda ls: max(len(x) for x in ls)))
    best = None
    for lines in options:
        widest = max(_text_width(x, family, base) for x in lines)
        size = int(base * min(1.0, 0.97 * max_w / max(widest, 1)))     # 3% margin: widths are not exactly linear
        if best is None or size > best[1] * 1.15:      # prefer one line unless two is much bigger
            best = (lines, size)
    return best[0], max(best[1], 40)


def _is_emphasis(word: str, emphasis: set[str]) -> bool:
    core = re.sub(r"[^\w]", "", word.lower())
    return bool(core) and (core in emphasis or any(ch.isdigit() for ch in core))


def _count_steps(text: str, start: float, end: float, steps: int = 12):
    """Yield (t0, t1, text) so a number counts up during the first 0.6 s."""
    m = re.search(r"\d[\d,]*", text)
    if not m:
        yield start, end, text
        return
    target = int(m.group().replace(",", ""))
    ramp = min(0.6, (end - start) * 0.5)
    for i in range(steps):
        t0 = start + ramp * i / steps
        t1 = start + ramp * (i + 1) / steps
        val = int(target * ((i + 1) / steps) ** 0.6)
        num = f"{val:,}" if "," in m.group() else str(val)
        yield t0, t1, text[:m.start()] + num + text[m.end():]
    yield start + ramp, end, text


def build_ass(words: list[Word], out_path: Path, *, font: str = "Poppins Black", language: str = "en",
              caption_color: str = "#FFFFFF", highlight_color: str = "#FFE600",
              emphasis_color: str | None = None, emphasis_words: set[str] | None = None,
              glow_color: str | None = None,
              hook: str | None = None, hook_style: HookStyle | None = None,
              hook_bg: str | None = None, hook_text: str | None = None, hook_until: float | None = 2.8,
              part_label: str | None = None, labels: list[Label] | None = None,
              big_texts: list[BigText] | None = None, big_font: str | None = None,
              caption_margin_v: int = 560, font_size: int = 96, uppercase: bool | None = None,
              max_words: int = 2, max_chars: int = 16, size: tuple[int, int] = (W, H),
              modern: bool = False, chips: list | None = None, skip_spans: list | None = None,
              pop_emphasis: bool = False, hook_font: str | None = None) -> Path:
    # modern=True: the 2026 look (sentence case, thin outline + soft shadow, colour-only highlight,
    # subtle 92%->100% pop, no glow layer). The old look stays available for comparison.
    uppercase = (language == "en" and not modern) if uppercase is None else uppercase
    end_time = max((w.end for w in words), default=5.0)
    # Letter spacing must be 0 for Hindi: libass shapes letter-by-letter when spacing is set,
    # which breaks Devanagari vowel signs.
    sp = 0 if language == "hi" else 1
    emphasis = {re.sub(r"[^\w]", "", e.lower()) for e in (emphasis_words or set())}
    emph_col = ass_color(emphasis_color or highlight_color)
    glow = ass_color(glow_color or highlight_color, alpha=0x60)
    hs = hook_style or HookStyle(lines_bg=[hook_bg or "#FFFFFF", highlight_color],
                                 lines_fg=[hook_text or "#000000", "#FFFFFF"], until=hook_until)
    big_font = big_font or font
    cx = size[0] // 2

    lines = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {size[0]}", f"PlayResY: {size[1]}",
        "WrapStyle: 2", "ScaledBorderAndShadow: yes", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Caption,{font},{font_size},{ass_color(caption_color)},{ass_color(caption_color)},"
        f"&H00000000,&H{'80' if modern else '64'}000000,0,0,0,0,100,100,{sp},0,1,"
        f"{6 if modern else max(6, font_size // 11)},{3 if modern else 5},2,40,40,{caption_margin_v},1",   # research: 5-8 px stroke
        f"Style: Glow,{font},{font_size},&HFF000000,&HFF000000,{glow},&HFF000000,0,0,0,0,100,100,{sp},0,1,"
        f"{max(14, font_size // 5)},0,2,40,40,{caption_margin_v},1",
        f"Style: Hook,{hs.font},{hs.size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,{sp},0,3,"
        f"18,0,8,60,60,{hs.y},1",
        f"Style: HookClean,{hook_font or hs.font},{hs.size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H60000000,0,0,0,0,100,100,{sp},0,1,"
        f"3,4,8,60,60,{hs.y},1",
        f"Style: Label,Poppins Black,{max(40, int(font_size * 0.46))},&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,{sp},0,3,"
        f"12,0,7,0,0,0,1",
        f"Style: Big,{big_font},{int(font_size * 2.4)},&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,0,0,0,0,"
        f"100,100,{sp},0,1,{max(8, font_size // 8)},8,5,60,60,0,1",
        "Style: Chip,Poppins ExtraBold,30,&H4DFFFFFF,&H4DFFFFFF,&H80000000,&H00000000,0,0,0,0,100,100,0,0,1,2,0,7,"
        "0,0,0,1",
        f"Style: Part,Poppins Black,48,&H00FFFFFF,&H00FFFFFF,&H00000000,&HB4000000,0,0,0,0,100,100,{sp},0,3,"
        f"12,0,9,40,50,130,1",
        "", "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    # Hook: stacked colour strips, each line slides in from the side, slightly after the previous one
    if hook and modern:                             # ONE rounded white box behind all lines (owner: no 'staircase')
        hook_end = hs.until if hs.until is not None else end_time + 0.5
        lines += _hook_single_box(hook, hs, size, hook_end, sp)
    elif hook:
        hook_end = hs.until if hs.until is not None else end_time + 0.5
        line_h = int(hs.size * 1.18)
        for i, text in enumerate(wrap_hook(hook.upper() if uppercase else hook)):
            bg = hs.lines_bg[i % len(hs.lines_bg)]
            fg = hs.lines_fg[i % len(hs.lines_fg)]
            y = hs.y + i * line_h
            if modern:                              # straight, visible from frame 0, no slide-in
                tags = f"\\an8\\pos({cx},{y})\\1c{ass_color(fg)}\\3c{ass_color(bg)}\\fad(0,200)"
            else:
                delay = i * 90
                x_from = cx - 260 if i % 2 == 0 else cx + 260
                tags = (f"\\an8\\move({x_from},{y},{cx},{y},{delay},{delay + 220})\\1c{ass_color(fg)}"
                        f"\\3c{ass_color(bg)}\\frz{-2 if i % 2 == 0 else 2}\\alpha&HFF&"
                        f"\\t({delay},{delay + 120},\\alpha&H00&)\\fad(0,180)")
            lines.append(f"Dialogue: 3,{_ts(0)},{_ts(hook_end)},Hook,,0,0,0,,{{{tags}}}{text}")

    for c0, c1, ctext in chips or []:              # small "AI-generated" chip, top-left, 70% opacity (research)
        lines.append(f"Dialogue: 5,{_ts(c0)},{_ts(c1)},Chip,,0,0,0,,{{\\pos(70,{236 if size[1] > size[0] else 40})}}"
                     f"{_esc(ctext)}")

    if part_label:
        lines.append(f"Dialogue: 3,{_ts(0)},{_ts(end_time + 0.5)},Part,,0,0,0,,{_esc(part_label)}")

    for lb in labels or []:
        tags = (f"\\pos({lb.x},{lb.y})\\1c{ass_color(lb.fg)}\\3c{ass_color(lb.bg)}\\fscx40\\fscy40"
                f"\\t(0,120,\\fscx105\\fscy105)\\t(120,180,\\fscx100\\fscy100)\\fad(0,150)")
        lines.append(f"Dialogue: 4,{_ts(lb.start)},{_ts(lb.end)},Label,,0,0,0,,{{{tags}}}{_esc(lb.text)}")

    big_base = int(font_size * 2.4)
    for bt in big_texts or []:
        raw = bt.text.upper() if uppercase else bt.text
        # 12% headroom for the pop-in overshoot (112%)
        rows, fs = fit_big(raw, big_font, big_base, int(size[0] * 0.86 / 1.12))
        text = "\\N".join(_esc(r) for r in rows)
        y = int(size[1] * 0.42)                     # Big is centre-aligned (an5): y is the block centre
        steps = _count_steps(text, bt.start, bt.end) if bt.count_up else [(bt.start, bt.end, text)]
        for k, (t0, t1, shown) in enumerate(steps):
            pop = "\\fscx50\\fscy50\\t(0,90,\\fscx112\\fscy112)\\t(90,160,\\fscx100\\fscy100)" if k == 0 else ""
            lines.append(f"Dialogue: 2,{_ts(t0)},{_ts(t1)},Big,,0,0,0,,"
                         f"{{\\pos({cx},{y})\\fs{fs}\\1c{ass_color(bt.color)}{pop}}}{shown}")
        if bt.sub:
            sub = bt.sub.upper() if uppercase else bt.sub
            sub_rows, sub_fs = fit_big(sub, font, font_size, int(size[0] * 0.9))
            sub_y = y + int(len(rows) * fs * 0.55) + int(font_size * 0.15)
            lines.append(f"Dialogue: 2,{_ts(bt.start + 0.15)},{_ts(bt.end)},Caption,,0,0,0,,"
                         f"{{\\an8\\pos({cx},{sub_y})\\fs{sub_fs}\\fad(120,0)}}"
                         + "\\N".join(_esc(r) for r in sub_rows))

    big_spans = [(b.start, b.end) for b in big_texts or []]
    hl = ass_color(highlight_color)
    chunks = chunk_words(words, max_words=max_words, max_chars=max_chars)
    for ci, chunk in enumerate(chunks):
        if any(s <= chunk[0].start < e for s, e in big_spans):
            continue                        # big text already says it
        if any(s <= chunk[0].start < e for s, e in skip_spans or []):
            continue                        # money: no captions while a number card is on screen
        texts = [_esc(w.text.upper() if uppercase else w.text) for w in chunk]
        next_start = chunks[ci + 1][0].start if ci + 1 < len(chunks) else chunk[-1].end + 0.4
        chunk_end = min(chunk[-1].end + 0.3, next_start)
        # stop before a big-text screen starts, so the two never overlap
        chunk_end = min([chunk_end] + [s for s, _ in big_spans if chunk[0].start < s])
        for wi, w in enumerate(chunk):
            start = chunk[0].start if wi == 0 else w.start
            end = min(chunk[wi + 1].start if wi + 1 < len(chunk) else chunk_end, chunk_end)
            if start >= chunk_end:
                break
            if end <= start:
                end = start + 0.05
            parts = []
            for j, t in enumerate(texts):
                if modern:                          # colour only, no size jumps
                    if j == wi and pop_emphasis and _is_emphasis(chunk[j].text, emphasis):
                        # movie spec: keyword pop 1.0 -> 1.15 -> 1.0 over 120 ms
                        parts.append(f"{{\\c{hl}\\t(0,60,\\fscx115\\fscy115)\\t(60,120,\\fscx100\\fscy100)}}{t}{{\\r}}")
                    elif j == wi:
                        parts.append(f"{{\\c{hl}}}{t}{{\\r}}")
                    elif _is_emphasis(chunk[j].text, emphasis):
                        parts.append(f"{{\\c{emph_col}}}{t}{{\\r}}")
                    else:
                        parts.append(t)
                elif _is_emphasis(chunk[j].text, emphasis):
                    parts.append(f"{{\\c{emph_col}\\fscx122\\fscy122}}{t}{{\\r}}")
                elif j == wi:
                    parts.append(f"{{\\c{hl}\\fscx110\\fscy110}}{t}{{\\r}}")
                else:
                    parts.append(t)
            if modern:
                pop = "{\\fscx92\\fscy92\\t(0,100,\\fscx100\\fscy100)\\fad(60,0)}" if wi == 0 else ""
            else:
                pop = ("{\\fscx55\\fscy55\\t(0,70,\\fscx114\\fscy114)\\t(70,140,\\fscx100\\fscy100)}"
                       if wi == 0 else "")
            body = " ".join(parts)
            if not modern:
                glow_body = re.sub(r"\\c&H[0-9A-F]+&?", "", body)    # same sizes, no fill colour
                lines.append(f"Dialogue: 0,{_ts(start)},{_ts(end)},Glow,,0,0,0,,{pop}{glow_body}")
            lines.append(f"Dialogue: 1,{_ts(start)},{_ts(end)},Caption,,0,0,0,,{pop}{body}")

    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out_path
