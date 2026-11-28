"""Charts built FROM the narration (P3b data story, 28 Nov): the free writer models kept putting numbers on charts the
narrator never says (6 production tries held). Here the numbers come out of the spoken words themselves, so a chart can
never show a number the viewer didn't hear; the writer only decides which beats get a chart.

auto_chart(said) -> chart dict or None, in html_scene's chart format (checked again by html_scene.check_chart):
  - timeline: 2-5 different years (1000-2100), each with the 1-4 words around it;
  - depth:    one depth said with its unit ("3,000 feet", "a kilometre down" is skipped: no digits);
  - compare:  2-4 numbers with the same unit (miles, km, mph, tons, kilotons, years, people, percent, $...), labelled by
              the 1-3 words before each number."""
from __future__ import annotations

import re

UNITS = {
    "mile": "miles", "miles": "miles", "km": "km", "kilometre": "km", "kilometres": "km", "kilometer": "km",
    "kilometers": "km", "metre": "m", "metres": "m", "meter": "m", "meters": "m", "feet": "feet", "foot": "feet",
    "mph": "mph", "kph": "kph", "ton": "tons", "tons": "tons", "tonnes": "tons", "kiloton": "kilotons",
    "kilotons": "kilotons", "megatons": "megatons", "years": "years", "year": "years", "days": "days",
    "people": "people", "percent": "%", "%": "%", "degrees": "degrees", "times": "x", "x": "x",
    "million": "million", "billion": "billion", "trillion": "trillion",
}
DEPTH_UNITS = {"feet", "m", "km", "miles"}
STOP = {"the", "a", "an", "of", "and", "to", "in", "on", "at", "was", "is", "it", "its", "that", "with", "about", "over",
        "nearly", "almost", "just", "only", "than", "more", "less", "by", "for", "from", "which", "this", "were"}
NUM = r"(\$?\d[\d,]*(?:\.\d+)?)"


def _label(words: list[str]) -> str:
    keep = [w for w in words if w.lower() not in STOP and not re.match(r"^\$?\d", w)]
    return " ".join(keep[-3:]).strip(" ,.;:'\"")[:28] or "this"


def _years(text: str) -> list[dict]:
    out, seen = [], set()
    for m in re.finditer(r"\b(1[0-9]{3}|20[0-9]{2}|2100)\b", text):
        y = m.group(1)
        if y in seen:
            continue
        seen.add(y)
        after = re.findall(r"[A-Za-z']+", text[m.end(): m.end() + 60])[:4]
        out.append({"label": y, "text": " ".join(after)[:32] or y})
    return out


def _measures(text: str) -> list[tuple[str, float, str, str]]:
    """[(unit, value, spoken text, label)] for 'number unit' pairs in the narration."""
    out = []
    for m in re.finditer(NUM + r"[\s-]*([A-Za-z%]+)", text):
        raw, unit_w = m.group(1), m.group(2).lower()
        unit = UNITS.get(unit_w)
        if not unit:
            continue
        try:
            value = float(raw.replace("$", "").replace(",", ""))
        except ValueError:
            continue
        before = re.findall(r"[A-Za-z']+|\$?\d[\d,.]*", text[max(0, m.start() - 50): m.start()])
        out.append((unit, value, f"{raw} {unit_w}", _label(before)))
    return out


def auto_chart(said: str, depth_ok: bool = False) -> dict | None:
    """A chart whose every number is in `said` (this beat + the two before), or None."""
    years = _years(said)
    if len(years) >= 2:
        return {"type": "timeline", "title": "", "items": years[:5]}
    meas = _measures(said)
    if depth_ok:
        deep = [x for x in meas if x[0] in DEPTH_UNITS]
        if len(deep) == 1:
            unit, value, spoken, label = deep[0]
            return {"type": "depth", "title": "", "items": [{"label": label, "text": spoken}]}
    by_unit: dict[str, list] = {}
    for unit, value, spoken, label in meas:
        if value > 0:
            by_unit.setdefault(unit, []).append((value, spoken, label))
    for unit, rows in sorted(by_unit.items(), key=lambda kv: -len(kv[1])):
        uniq = []
        for v, spoken, label in rows:
            if all(abs(v - u[0]) > 1e-9 for u in uniq):
                uniq.append((v, spoken, label))
        if len(uniq) >= 2:
            return {"type": "compare", "title": "",
                    "items": [{"label": lb, "value": v, "text": sp} for v, sp, lb in uniq[:4]]}
    return None
