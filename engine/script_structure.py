"""S1 structure checks for a Short's script (P3, 26 Nov): owner standard S1 "SCRIPTS hook in 1 s, open loops every
8-12 s, one story turn, payoff + loop ending". The script judge scored the general rubric only, so none of these was
checked before voice and pictures. Plain-code checks (no AI call); each finding is a concrete fix the writer gets in
the judge's rewrite round. They coach the script; they never hold a finished video."""
from __future__ import annotations

import re

WARMUP = re.compile(r"^\s*(so[,\s]|today\b|in this video|have you ever|did you know|let'?s talk|hey\b|hi\b|welcome\b|"
                    r"ever wondered|imagine\b|picture this|here'?s (the|a) story|this is the story)", re.I)
LOOP = re.compile(r"\?|\b(but|until|wait|yet|nobody|no one|secret|why|how|what happened|what else|here'?s|the catch|"
                  r"turns out|except|instead|still|only|then|guess|watch|the reason|the real|no idea|about to|"
                  r"that'?s not all|even (more|worse|stranger))\b", re.I)
TURN = re.compile(r"\b(but|until|instead|suddenly|turns out|turned out|except|that'?s when|then one|the problem|"
                  r"what (nobody|no one) (knew|saw)|plot twist|not because)\b", re.I)
STOP = {"the", "and", "that", "this", "with", "from", "they", "their", "there", "what", "when", "were", "have",
        "into", "your", "just", "then", "than", "about", "would", "could", "will", "said", "says"}
LOOP_GAP_S = 12.0


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", (text or "").lower())


def findings(script: dict, wpm: float = 165.0) -> list[str]:
    """[] = the structure meets S1; else the fixes, in plain words (English narration; other languages: [])."""
    beats = [b for b in script.get("beats") or [] if isinstance(b, dict) and str(b.get("narration") or "").strip()]
    if len(beats) < 4 or str(script.get("language") or "en") not in ("en", ""):
        return []
    lines = [str(b["narration"]).strip() for b in beats]
    out = []
    if WARMUP.search(lines[0]):
        out.append(f"hook: beat 1 opens with a warm-up (\"{' '.join(lines[0].split()[:4])}...\"); start on the "
                   "payoff, the surprise or the stakes in the very first words")
    per_s = max(wpm, 60.0) / 60.0
    t, last_loop, gap_at = 0.0, len(_words(lines[0])) / per_s, None    # the hook opens the first loop
    for i, line in enumerate(lines):
        t_end = t + len(_words(line)) / per_s
        if LOOP.search(line) and i < len(lines) - 1:
            last_loop = t_end
        elif t_end - last_loop > LOOP_GAP_S and gap_at is None and i < len(lines) - 1:
            gap_at = (last_loop, t_end)
        t = t_end
    if gap_at:
        out.append(f"open loops: nothing pulls the viewer forward from {gap_at[0]:.0f}s to {gap_at[1]:.0f}s; add a "
                   "question, a 'but' or a tease of what comes next at least every 10 seconds")
    mid = lines[max(1, len(lines) * 3 // 10): max(2, len(lines) * 85 // 100)]
    if not any(TURN.search(x) for x in mid):
        out.append("story turn: no turn in the middle (the moment it goes another way: 'but', 'until', 'turns out'); "
                   "give the story one clear turn before the payoff")
    first = {w for w in _words(lines[0]) if len(w) > 3 and w not in STOP}
    last = {w for w in _words(lines[-1]) if len(w) > 3 and w not in STOP}
    if first and not (first & last):
        out.append("loop ending: the last line does not lead back into the first; finish beat 1's thought in new "
                   "words so the Short loops")
    return out
