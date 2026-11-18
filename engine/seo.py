"""SEO fill (owner, 11 Nov: SEO and virality must raise the reach of every video, Short and Reel).

New scripts get these fields from the writer itself (story.WRITER_PROMPT). This module adds them to scripts or finished
videos that were written before (re-renders from a saved script, review samples): one short writer call per video.
Research: research_notes/Viral faceless video formats 2026/seo_virality_reach_2026-11-11.md
"""
from __future__ import annotations

import json
from pathlib import Path

SEO_PROMPT = """You write search-friendly upload text for a {language} {fmt} video on the channel "{channel}".
Title: {title}
Summary: {summary}
Narration (start): {opening}

Return ONLY JSON:
{{"search_phrase": "the 2-5 words a viewer would type to find this video (name + event/place)",
  "summary": "2 lines, no spoilers; the FIRST sentence contains the search phrase naturally",
  "instagram_caption": "first line = the search phrase inside a hook question, then 1-2 lines (no hashtags)",
  "alt_text": "one plain sentence describing the video, with the search phrase",
  "pinned_comment": "one honest question about the story that invites opinions (never 'like and subscribe')",
  "hashtags": ["3-5 specific hashtags: topic, place, person; never #viral/#fyp"]}}
Rules: facts only from the title/summary/narration; {lang_rule}"""


def fill_seo(brain, channel: dict, script: dict, fmt: str) -> dict:
    """Return the script with search_phrase / alt_text / pinned_comment (and a search-first summary + caption)."""
    if script.get("search_phrase") and script.get("pinned_comment"):
        return script
    opening = " ".join(b.get("narration", "") for b in (script.get("beats") or [])[:4])
    lang = channel.get("language", "en")
    prompt = SEO_PROMPT.format(language="Hindi (Hinglish in Latin letters for captions)" if lang == "hi" else "English",
                               fmt="long" if fmt == "long" else "Short/Reel", channel=channel["name"],
                               title=script.get("title", ""), summary=script.get("summary", ""), opening=opening[:600],
                               lang_rule="write Hinglish (Hindi in Latin letters)." if lang == "hi" else "plain English.")
    data, _ = brain.ask_json("writer", prompt, temperature=0.4)
    out = dict(script)
    for k in ("search_phrase", "summary", "instagram_caption", "alt_text", "pinned_comment", "hashtags"):
        v = (data or {}).get(k)
        if v:
            out[k] = v
    return out


def backfill_folder(brain, folder: Path) -> dict:
    """Add the SEO fields to a finished video's upload.json / reel.json (no re-render)."""
    from . import story
    from .config import channel as get_channel
    meta = json.loads((folder / "upload.json").read_text(encoding="utf-8"))
    ch = get_channel(meta["channel"])
    script = {k: meta.get(k) for k in ("title", "summary", "hook_text", "instagram_caption", "hashtags", "beats",
                                         "search_phrase", "pinned_comment", "alt_text")}
    if not script.get("summary"):
        sj = folder / "script.json"
        if sj.exists():
            script["summary"] = json.loads(sj.read_text(encoding="utf-8")).get("summary", "")
    script = fill_seo(brain, ch, script, meta.get("format", "short"))
    meta.update({k: script.get(k) for k in ("search_phrase", "alt_text", "pinned_comment", "instagram_caption",
                                            "hashtags") if script.get(k)})
    meta["tags"] = story.seo_tags(ch, script)
    desc = meta.get("description", "")
    first = desc.split("\n", 1)[0] if desc else ""
    if script.get("summary") and first != script["summary"]:     # search-first description opening
        rest = desc.split("\n", 1)[1] if "\n" in desc else ""
        meta["description"] = f"{script['summary']}\n{rest}".strip()
    (folder / "upload.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    rj = folder / "reel.json"
    if rj.exists():
        reel = json.loads(rj.read_text(encoding="utf-8"))
        tags = [t if t.startswith("#") else f"#{t}" for t in (script.get("hashtags") or [])]
        tags = [t for t in dict.fromkeys(tags) if t.lower() not in story.YT_ONLY_TAGS][:5]
        cap = (script.get("instagram_caption") or "").strip()
        if cap:
            reel.update(caption=f"{cap}\n\n{' '.join(tags)}".strip(), hashtags=tags)
        reel["alt_text"] = script.get("alt_text", "")
        rj.write_text(json.dumps(reel, indent=2, ensure_ascii=False), encoding="utf-8")
    return meta
