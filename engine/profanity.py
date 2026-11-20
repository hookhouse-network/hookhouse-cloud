"""Mute swear words and slurs in campaign clips (20 Nov 2026).

Dom (dasgasd3m) swears in nearly every stream clip, and the campaign gate held all of them ("excessive profanity",
"racial slur"). The brief allows exactly this fix: "cut, mute or blur where appropriate ... keep his meaning intact".
So the word is silenced in the audio, shown as f*** in the captions, and the gate reads the cleaned transcript. Clips
whose content is explicit (not just the words) are still held by the gate and the slot tries the next footage.
"""
from __future__ import annotations

import re

from .media.captions import Word

# strong profanity + slurs (whole words, common spellings). Mild words (damn, hell, crap) stay.
_BAD = (r"f+u+c*k+\w*|f+k+|fuk\w*|motherf\w*|mf+|sh+i+t+\w*|bullsh\w*|b+i+t+c+h+\w*|a+s+s+h+o+l+e+s?|"
        r"d+i+c+k+s?|d+i+c+k+head\w*|c+u+n+t+s?|p+u+s+s+y+|pussies|c+o+c+k+s?|wh+o+r+e+s?|sl+u+t+s?|"
        r"n+i+g+g+\w*|n+i+g+\w*a+s?|n+i+g+e+r+s?|f+a+g+\w*|r+e+t+a+r+d+\w*|tr+a+n+n+y+")
BAD = re.compile(rf"^({_BAD})$", re.I)
PAD_S = 0.04                       # a little silence either side so no syllable leaks


def is_bad(token: str) -> bool:
    return bool(BAD.match(re.sub(r"[^\w]", "", token or "")))


def stars(token: str) -> str:
    core = re.sub(r"[^\w]", "", token)
    lead = token[: len(token) - len(token.lstrip("\"'([{"))]
    trail = token[len(token.rstrip(".,!?;:\"')]}")):]
    return f"{lead}{core[:1]}{'*' * max(2, len(core) - 1)}{trail}"


def clean(words: list[Word]) -> tuple[list[Word], list[tuple[float, float]]]:
    """(captions with f***, mute spans in source seconds). Spans that touch are merged."""
    out, spans = [], []
    for w in words:
        if is_bad(w.text):
            out.append(Word(stars(w.text), w.start, w.end))
            a, b = max(0.0, w.start - PAD_S), w.end + PAD_S
            if spans and a <= spans[-1][1]:
                spans[-1] = (spans[-1][0], max(spans[-1][1], b))
            else:
                spans.append((a, b))
        else:
            out.append(w)
    return out, spans


def mute_filter(spans: list[tuple[float, float]], offset: float = 0.0) -> str:
    """ffmpeg audio filter silencing the spans (times relative to a file that starts at `offset` source seconds)."""
    parts = [f"volume=enable='between(t,{max(0.0, a - offset):.3f},{max(0.0, b - offset):.3f})':volume=0"
             for a, b in spans if b > offset]
    return ",".join(parts) or "anull"
