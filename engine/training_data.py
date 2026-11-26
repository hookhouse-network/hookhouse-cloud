"""Our own training set, collected from day one (owner 19 Nov: "let's go with your suggestion" = save every script with
its later results, so a model can be fine-tuned on our winners once there is enough data).

- record(item): when a video is made, its words are kept: title, hook line, opening lines, hook type, feeling, topic,
  channel, format (data/state/training/scripts.jsonl; data/state travels in the cloud memory bundle).
- build(): each day after the stats, every recorded script is joined with its newest YouTube numbers (views, stayed %,
  average % viewed, likes per 100 views) into examples.jsonl, and a 0-100 score is computed relative to the channel's
  own median (so small and big channels compare fairly).
- status(): how close we are to a useful set (READY_AT labelled videos; guides: <500 rarely beats a good prompt).
The fine-tuning itself needs a GPU home that allows COMMERCIAL use (not Kaggle: its terms are personal/non-commercial
and ban server farming; never GitHub Actions). The owner picks it when the set is ready.
"""
from __future__ import annotations
from engine.core.quiet import noted

import json
import sqlite3
import statistics
import time
from pathlib import Path

from .config import ROOT

DIR = ROOT / "data" / "state" / "training"
SCRIPTS = DIR / "scripts.jsonl"
EXAMPLES = DIR / "examples.jsonl"
READY_AT = 500
MIN_HOURS = 48                  # numbers settle after about two days


def _read_json(p: Path) -> dict:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _scripts() -> dict[str, dict]:
    out: dict[str, dict] = {}
    try:
        for ln in SCRIPTS.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(ln)
            except ValueError:
                continue
            out[r["item_id"]] = r                       # newest record wins (a remake replaces the first)
    except OSError:
        pass
    return out


def record(item: dict) -> dict | None:
    """Keep the words of a freshly made video. Never raises (making a video must not fail because of this)."""
    try:
        out = Path(item.get("out_dir") or "")
        script, up = _read_json(out / "script.json"), _read_json(out / "upload.json")
        beats = [str(b.get("narration") or "").strip() for b in (script.get("beats") or []) if b.get("narration")]
        rec = {"item_id": item["id"], "channel": item.get("channel"), "kind": item.get("kind"),
               "made_at": time.time(), "topic": item.get("topic"), "angle": item.get("angle"),
               "feeling": item.get("feeling"), "now_hook": item.get("now_hook"),
               "title": up.get("title") or script.get("title") or "", "hook_text": script.get("hook_text") or "",
               "hook_type": script.get("hook_type") or "", "opening": beats[:3], "words": sum(len(b.split()) for b in beats),
               "beats": len(beats), "search_phrase": script.get("search_phrase") or "",
               "language": up.get("language") or script.get("language") or ""}
        if not (rec["title"] or rec["opening"]):
            return None
        DIR.mkdir(parents=True, exist_ok=True)
        with SCRIPTS.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return rec
    except Exception as _swallowed:  # noqa: BLE001
        noted("training_data.py:70", _swallowed)
        return None


def _metrics(db: Path) -> dict[str, dict]:
    """item id -> newest YouTube snapshot that is at least MIN_HOURS old."""
    if not db.exists():
        return {}
    with sqlite3.connect(db) as c:
        c.row_factory = sqlite3.Row
        rows = c.execute("SELECT item_id, hours_after, views, likes, comments, engaged_views, stayed_pct, avg_pct_viewed "
                         "FROM video_metrics WHERE platform = 'youtube' AND hours_after >= ? ORDER BY hours_after",
                         (MIN_HOURS,)).fetchall()
    out: dict[str, dict] = {}
    for r in rows:
        out[r["item_id"]] = dict(r)
    return out


def build(db: Path | None = None) -> int:
    """Join scripts with their numbers -> examples.jsonl. Returns how many labelled examples exist."""
    scripts, metrics = _scripts(), _metrics(db or ROOT / "data" / "analytics.db")
    rows = []
    for iid, s in scripts.items():
        m = metrics.get(iid)
        if not m:
            continue
        views = float(m["views"] or 0)
        stayed = m["stayed_pct"]
        if stayed is None and m["engaged_views"] is not None and views:
            stayed = 100.0 * float(m["engaged_views"]) / views
        rows.append({**s, "views": views, "stayed_pct": stayed, "avg_pct_viewed": m["avg_pct_viewed"],
                     "like_rate": (100.0 * float(m["likes"] or 0) / views) if views else None,
                     "hours_after": m["hours_after"]})
    by_ch: dict[str, list[float]] = {}
    for r in rows:
        by_ch.setdefault(r["channel"], []).append(r["views"])
    for r in rows:                                      # score: channel-relative views, nudged by retention
        med = statistics.median(by_ch[r["channel"]]) or 1.0
        rel = min(2.0, r["views"] / med) / 2.0          # 0..1, the channel median = 0.5
        ret = (r["stayed_pct"] / 100.0) if r["stayed_pct"] is not None else rel
        r["score"] = round(100 * (0.6 * rel + 0.4 * ret), 1)
    DIR.mkdir(parents=True, exist_ok=True)
    EXAMPLES.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    return len(rows)


def status() -> dict:
    labelled = 0
    try:
        labelled = sum(1 for ln in EXAMPLES.read_text(encoding="utf-8").splitlines() if ln.strip())
    except OSError:
        pass
    return {"scripts": len(_scripts()), "labelled": labelled, "ready_at": READY_AT,
            "ready": labelled >= READY_AT}
