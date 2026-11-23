"""Legends told as legends (owner 23 Nov: the human-story template for story channels, after the storyteller channel
he chose; "all the things must be r&d based"). R&D 23 Nov 23:25: the strong writer (gemini-3.6) wrote the Haldighati
draft with a real dialogue scene and cast voices, but told two legends as history: Chetak's elephant-trunk mask and
his leap across the stream on three legs. The fact-check cannot see this: the sources DO mention both (as legends),
so neither claim is "contradicted".

`check()` asks the checker once. A story that is a legend or folk tale as a whole (an Akbar-Birbal tale) is framed
ONCE near the start ("एक मशहूर किस्सा है..."); a true story with legend parts gets ONE marker at the first narrator line
of each legend episode ("legend says...", "कहते हैं...") and the episode's next lines go on as the tale. 24 Nov
measurement: marking every flagged line put "कहते हैं," in front of 10 of 16 Haldighati lines and 10 of 11 Akbar-Birbal
lines (a storyteller says it once), while the English fact Shorts (D.B. Cooper, Titanic, peregrine falcon) had nothing
flagged. Code checks every edit (a legend marker in it, a narrator line, the quoted words really in the line) and uses
a plain marker prefix where the model's edit does not hold; more than 3 episodes = the story is framed once instead.
Switch: settings `legend_check` (enabled, channels)."""
from __future__ import annotations

import copy
import re

MARKERS = {
    "en": r"\blegends?\b(?! (?:of|in) the (?:game|sport))|\bit is said\b|\b(?:is|was|were|are) said to\b|\bthe story goes\b"
          r"|\bfolklore\b|\bfolk ?tales?\b|\btradition (?:says|holds|tells)\b|\baccording to (?:tradition|legend|folklore|"
          r"the ballads?|the bards?|local lore|the tale)\b|\bthe bards?\b|\bballads?\b|\bsome say\b|\bpeople say\b"
          r"|\bthey say\b|\bmyths?\b|\blore\b|\bthe tale goes\b|\bstories (?:say|tell)\b|\ba famous tale\b",
    "hi": r"कहते हैं|कहा जाता है|कही जाती|कहे जाते|मान्यता|मानते हैं|माना जाता|लोककथा|लोक कथा|किंवदंती|किवदंती|दंतकथा|"
          r"गाथा|लोकगीत|भाट|चारण|बताया जाता|बताते हैं|कहानी कहती|किस्सा है|किस्से कहते|\bkehte hain\b|\bkaha jata\b"
          r"|\bmaanyata\b",
}
PREFIX = {"en": "Legend says ", "hi": "कहते हैं, "}
MAX_EPISODES = 3
_LOWER_FIRST = {"The", "A", "An", "He", "She", "It", "They", "His", "Her", "Their", "This", "That", "There", "Then",
                "When", "In", "On", "At", "After", "Before", "One", "Every", "Some", "With"}

PROMPT = """You check a {language} video script against its sources for LEGENDS TOLD AS FACTS.
A legend here = anything the sources call a legend, tradition, folklore, folk tale, ballad, popular belief or "it is
said"; anything they say historians doubt or dispute; any miracle or physically impossible feat the sources do not
state as plain fact. Facts the sources state plainly are NOT legends, and neither is science: a real feature whose
purpose scientists only think or suggest is a hypothesis, not a legend (leave it).
Script lines (index: narration):
{lines}
Sources:
{refs}
Answer two questions.
1. Is the WHOLE story a legend or folk tale (for example a famous folk tale about a real king)? A storyteller then says
   so ONCE near the start and tells the rest normally. If lines 0-1 do not already say it, give "frame": the smallest
   edit of line 0 or 1 that says it is a legend or folk tale (Hindi e.g. "कहते हैं", "एक मशहूर किस्सा है").
2. Otherwise (a true story with legend parts): list each legend EPISODE told as fact (an episode = the run of lines that
   tells one legend). A storyteller marks each episode ONCE, at its first narrator line ("legend says...", "कहते
   हैं..."); the next lines of the episode go on without a marker. Give the edit for that first line only.
Never mark plain facts. Never put a marker inside a character's spoken words. Copy "old" exactly from the line.
Return ONLY JSON: {{"whole_story_is_legend": true or false,
"frame": {{"i": 0, "old": "exact words from line 0 or 1", "new": "the same words, now saying it is a legend"}} or null,
"episodes": [{{"lines": [3, 4], "claim": "the legend in 3-10 words", "i": 3, "old": "exact words from line i",
"new": "the words telling it as a legend"}}]}}"""


# What the SOURCES (English Wikipedia) say when they report a legend. 24 Nov, second measurement: another checker
# model marked documented facts ("Legend says ... he jumped" for D.B. Cooper, the Navy's 12-day limit for Ballard),
# so an episode is only marked when the sources use this vocabulary near the claim's own words.
SOURCE_LEGEND = re.compile(r"\blegends?\b|\bfolklore\b|\bfolk[- ]?tales?\b|\btradition(?:al|ally)?\b|\bit is said\b"
                           r"|\bis said to\b|\bsaid to have\b|\bballads?\b|\bbards?\b|\bmyths?\b|\bmythical\b"
                           r"|\bapocryphal\b|\bpopular belief\b|\bfolk hero\b|\bpopularly believed\b", re.I)
_STOP = set("that this with from were was have has had into their there them they then than about after before over "
            "under while when where which what would could should being been also only very much more most such "
            "enemy legend legends story".split())


def sourced(claim: str, refs: str) -> bool:
    """Do the sources call THIS claim a legend: a sentence with legend vocabulary that, with its neighbouring
    sentences, holds at least two of the claim's own words (4+ letters)?"""
    keys = {w for w in re.findall(r"[a-z]{4,}", (claim or "").lower()) if w not in _STOP}
    if len(keys) < 2 or not refs:
        return False
    sents = re.split(r"(?<=[.!?])\s+", refs.lower())
    for i, s in enumerate(sents):
        if SOURCE_LEGEND.search(s):
            near = " ".join(sents[max(0, i - 1): i + 2])
            if sum(1 for k in keys if k in near) >= 2:
                return True
    return False


def marked(text: str, language: str = "en") -> bool:
    """Does the text tell something as a legend (a legend marker in it)?"""
    rx = MARKERS["hi"] + "|" + MARKERS["en"] if language == "hi" else MARKERS["en"]
    return bool(re.search(rx, text or "", re.I))


def cfg() -> dict:
    try:
        from .config import settings
        return {"enabled": True, "channels": [], **(settings().get("legend_check") or {})}
    except Exception:  # noqa: BLE001 - no settings = off
        return {"enabled": False, "channels": []}


def applies(channel: dict) -> bool:
    """Human-story channels always (their template acts legends as scenes); others when listed in the settings."""
    c = cfg()
    if not c.get("enabled"):
        return False
    from .human_story import enabled as human
    chans = c.get("channels") or []
    return human(channel) or chans == "all" or channel.get("id") in chans


def _spoken(beat: dict) -> bool:
    """A line that cannot carry a marker: a character's spoken words (human-story beats name their speaker), or a
    question (24 Nov measurement: "कहते हैं, चेतक ने ... क्यों पहनी?" = "they say, why did ...?")."""
    return _character(beat) or str(beat.get("narration") or "").rstrip().endswith("?")


def _character(beat: dict) -> bool:
    sp = str(beat.get("speaker") or "").strip().lower()
    return bool(sp) and sp != "narrator"


def _prefixed(line: str, language: str) -> str:
    if language != "hi":
        first, _, rest = line.partition(" ")
        if first in _LOWER_FIRST:
            line = first.lower() + (" " + rest if rest else "")
        return PREFIX["en"] + line
    return PREFIX["hi"] + line


def _apply(beats: list, i: int, old: str, new: str, language: str) -> str:
    """Edit line i so it tells a legend: the model's edit when it holds, else the plain prefix. '' = not possible."""
    if not 0 <= i < len(beats) or _spoken(beats[i]):
        return ""
    line = str(beats[i].get("narration") or "")
    if marked(line, language):
        return "already"
    if old and old in line and new and new != old and marked(new, language):
        beats[i]["narration"] = _tidy(line.replace(old, new, 1))
    else:
        beats[i]["narration"] = _prefixed(line, language)
    return "marked"


def _frame(beats: list, data: dict, language: str) -> str:
    if any(marked(str(b.get("narration") or ""), language) for b in beats[:2]):
        return "already"
    fr = data.get("frame") if isinstance(data.get("frame"), dict) else {}
    try:
        i = int(fr.get("i"))
    except (TypeError, ValueError):
        i = -1
    if i in (0, 1) and _apply(beats, i, str(fr.get("old") or ""), str(fr.get("new") or ""), language) == "marked":
        return "framed"
    for j in (1, 0):                                         # the plain prefix on the first narrator line
        if j < len(beats) and _apply(beats, j, "", "", language) == "marked":
            return "framed"
    return "not framed"


def check(brain, script: dict, refs: str, language: str = "en", log=print) -> tuple[dict, list[dict]]:
    """(script with legends told as legends, report [{i, claim, action: framed|marked|already|not framed|skipped}])."""
    beats = script.get("beats") or []
    if not beats or not refs or brain is None:
        return script, []
    lines = "\n".join(f"{i}: {b.get('narration', '')}" + (" [spoken by a character]" if _character(b) else "")
                      for i, b in enumerate(beats))
    data, _ = brain.ask_json("checker", PROMPT.format(language="Hindi" if language == "hi" else "English",
                                                      lines=lines, refs=refs[:30000]), temperature=0.0)
    data = data if isinstance(data, dict) else {}
    episodes = [e for e in data.get("episodes") or [] if isinstance(e, dict)]
    unsourced = [e for e in episodes if not sourced(str(e.get("claim") or ""), refs)]
    if unsourced:                                            # the sources do not call these legends: left as written
        log("Legends: not marked (the sources do not call them legends): "
            + "; ".join(str(e.get("claim") or "")[:60] for e in unsourced))
        episodes = [e for e in episodes if e not in unsourced]
    whole = bool(data.get("whole_story_is_legend")) and bool(SOURCE_LEGEND.search(refs))
    if not whole and not episodes:
        return script, []
    out = copy.deepcopy(script)
    report: list[dict] = []
    if whole or len(episodes) > MAX_EPISODES:               # one frame near the start covers the whole tale
        report.append({"i": 0, "claim": "the whole story is a legend" if whole else
                       f"{len(episodes)} legend episodes: the story is framed once", "action": _frame(out["beats"], data,
                                                                                                    language)})
    else:
        for e in episodes:
            claim = str(e.get("claim") or e.get("old") or "")[:80]
            try:
                i = int(e.get("i"))
            except (TypeError, ValueError):
                report.append({"i": -1, "claim": claim, "action": "skipped"})
                continue
            span = [int(x) for x in e.get("lines") or [] if str(x).lstrip("-").isdigit()] or [i]
            if any(marked(str(out["beats"][j].get("narration") or ""), language)
                   for j in range(max(0, min(span) - 1), min(len(out["beats"]), max(span) + 1)) if j != i):
                report.append({"i": i, "claim": claim, "action": "already"})   # the episode is told as a tale already
                continue
            action = _apply(out["beats"], i, str(e.get("old") or ""), str(e.get("new") or ""), language)
            if not action:                                  # a spoken line: the episode's first narrator line instead
                for j in sorted(span):
                    if j != i and _apply(out["beats"], j, "", "", language) == "marked":
                        i, action = j, "marked"
                        break
            report.append({"i": i, "claim": claim, "action": action or "skipped"})
    if any(r["action"] in ("framed", "marked") for r in report):
        out["_fact_check"] = {}                              # wording changed: the fact-check runs on the new text
        log("Legends: " + "; ".join(f"{r['action']} '{r['claim']}' (line {r['i']})" for r in report))
    out["_legends"] = report
    return out, report


def _tidy(text: str) -> str:
    s = re.sub(r"\s{2,}", " ", text)
    s = re.sub(r"\s+([,.;:!?।])", r"\1", s)
    s = re.sub(r"^[\s,.;:]+", "", s).strip()
    return s[:1].upper() + s[1:] if s[:1].islower() else s


def from_sources(brain, script: dict, channel: dict, log=print) -> dict:
    """The pipeline step: the script's own Wikipedia sources (the fact-check's), then check(). Never raises."""
    if not applies(channel) or not script.get("sources"):
        return script
    try:
        from .story import wikipedia_summaries
        refs = wikipedia_summaries(script.get("sources", []), focus=" ".join(script.get("claims", [])), chars=9000)
        if not refs:
            log("Legends: no sources could be read; not checked")
            return script
        new, _report = check(brain, script, refs, channel.get("language", "en"), log=log)
        return new
    except Exception as e:  # noqa: BLE001 - the script still goes on; the fact gate still runs
        log(f"Legends: check skipped ({type(e).__name__}: {str(e)[:100]})")
        return script
