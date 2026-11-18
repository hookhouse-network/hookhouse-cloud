"""Builds output/review.html: the newest video of every channel with its thumbnails,
title options, angle and scores — open it in any browser to review before approving."""
from __future__ import annotations

import html
import json
from pathlib import Path

from .config import ROOT, channels


def _runs(folder: Path) -> list[Path]:
    return sorted([p for p in folder.iterdir() if p.is_dir() and any(p.glob("*.mp4"))], key=lambda p: p.name)


def _fmt(run: Path) -> str:
    mp = run / "upload.json"
    return json.loads(mp.read_text(encoding="utf-8")).get("format", "short") if mp.exists() else "short"


def _latest(folder: Path) -> Path | None:
    runs = _runs(folder)
    return runs[-1] if runs else None


def build(out: Path | None = None) -> Path:
    out_root = ROOT / "output"
    out = out or out_root / "review.html"
    cards = []
    for ch in channels():
        folder = out_root / ch["id"]
        if not folder.exists():
            continue
        entries = []
        if ch.get("type") in ("story", "kids"):       # newest Short AND newest long video, each its own card
            by_fmt = {}
            for r in _runs(folder):
                by_fmt[_fmt(r)] = r
            entries = [(by_fmt[f], " — Long video" if f == "long" else " — Short") for f in ("short", "long") if f in by_fmt]
        else:
            run0 = _latest(folder)
            entries = [(run0, "")] if run0 else []
        for run, label in entries:
          cards.append(_card(ch, folder, run, label, out_root))
    page = _page(cards)
    out.write_text(page, encoding="utf-8")
    return out


def _card(ch, folder, run, label, out_root):
        meta_path = run / "upload.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
        clips_path = run / "clips.json"
        if not meta and clips_path.exists():       # clip runs: several short clips, one info line each
            clip_meta = json.loads(clips_path.read_text(encoding="utf-8"))
            meta = {"title": " | ".join(f"Clip {i}: {(c.get('hook_options') or [c.get('title', '')])[0]} "
                                        f"(virality {c.get('virality')}/100, {c.get('duration_s')}s)"
                                        for i, c in enumerate(clip_meta, 1))}
        videos = sorted(run.glob("*.mp4"))
        if ch.get("type") == "brainrot":             # Brain Snack v3: newest video of every game format
            latest = {}
            for r in _runs(folder):
                fmt = r.name.split("_", 2)[-1] if r.name.count("_") >= 2 else ""
                if fmt in ("spiral", "multiply", "versus", "ladder", "readfast"):
                    latest[fmt] = r
            if latest:
                videos = [v for r in latest.values() for v in (r / "video.mp4", r / "reel.mp4") if v.exists()]
                names = " · ".join(latest)
                meta = {"title": f"5 rotating game formats (newest of each): {names}"}
        thumbs = sorted(run.glob("thumbnail_*.jpg")) + sorted(run.glob("cover_vertical.jpg")) + sorted(run.glob("reel_cover.jpg"))
        wide = meta.get("format") == "long"
        rel = lambda p: p.relative_to(out_root).as_posix()
        vids = "".join(f"<video controls preload='metadata' src='{rel(v)}'></video>" for v in videos[:12])
        same = [r for r in _runs(folder) if _fmt(r) == _fmt(run)] if ch.get("type") in ("story", "kids") else _runs(folder)
        first = same[0] if same else run
        if first != run:                        # oldest version of the same format, for a before/after comparison
            old = sorted(first.glob("*.mp4"))[0]
            vids += (f"<div class='old'><small>BEFORE ({first.name[:8]})</small>"
                     f"<video controls preload='metadata' src='{rel(old)}'></video></div>")
        th = "".join(f"<img src='{rel(t)}'>" for t in thumbs)
        info = []
        for key, lbl in (("title", "Title"), ("angle", "Angle"), ("interest_score", "Interest score"),
                         ("duration_s", "Length (s)")):
            if meta.get(key):
                info.append(f"<b>{lbl}:</b> {html.escape(str(meta[key]))}")
        qa = meta.get("qa") or {}
        if qa:                                   # kids: counting check + calm pacing
            info.append(f"<b>Checks:</b> counting {'✅' if qa.get('counts_ok') else '❌'} · average shot "
                        f"{qa.get('avg_shot_s')} s · Made for Kids ✅")
        if meta.get("policy_flags"):
            info.append("<b>Never-topics:</b> ❌ " + html.escape(", ".join(meta["policy_flags"]))
                        + " (blocked from upload)")
        if meta.get("midroll_eligible") is False:
            info.append("<b>Length:</b> ⚠️ under 8:00, so no mid-roll ads")
        fc = meta.get("fact_check") or {}
        if fc:
            if not fc.get("ok"):
                info.append("<b>Fact-check:</b> ❌ contradicted (blocked from upload until fixed): "
                            + html.escape("; ".join(fc.get("problems", []))[:400]))
            elif fc.get("warnings"):
                info.append("<b>Fact-check:</b> ✅ no contradictions · ⚠️ please check (not in the sources): "
                            + html.escape("; ".join(fc.get("warnings", []))[:400]))
            else:
                info.append("<b>Fact-check:</b> ✅ passed")
        others = [t for t in meta.get("title_options") or [] if t != meta.get("title")]
        if others:
            info.append("<b>Other titles (for YouTube Test &amp; Compare, with the 3 thumbnails):</b> "
                        + " · ".join(html.escape(t) for t in others[:3]))
        if meta.get("search_phrase"):
            info.append(f"<b>Search phrase:</b> {html.escape(meta['search_phrase'])}"
                        + (f" · <b>Tags:</b> {html.escape(', '.join(meta.get('tags', [])[:8]))}" if meta.get("tags") else ""))
        if meta.get("format") == "short":
            info.append("<b>When posting:</b> add a Quiz or Poll sticker in the YouTube app (research: interactive stickers)")
        if meta.get("pinned_comment"):
            info.append(f"<b>Pin this comment after upload:</b> “{html.escape(meta['pinned_comment'])}”")
        if meta.get("alt_text"):
            info.append(f"<b>Instagram alt text:</b> {html.escape(meta['alt_text'])}")
        if meta.get("chapters"):
            fmt_t = lambda t: f"{int(t // 60)}:{int(t % 60):02d}"
            info.append("<b>Chapters:</b> " + " · ".join(f"{fmt_t(float(t))} {html.escape(str(c))}"
                                                        for t, c in meta["chapters"][:12]))
        reel_json = run / "reel.json"
        if reel_json.exists():
            reel = json.loads(reel_json.read_text(encoding="utf-8"))
            info.append(f"<b>Instagram Reel:</b> hook “{html.escape(reel.get('hook', ''))}” · "
                        + html.escape(" ".join(reel.get("hashtags", []))))
        texts = ""
        if meta.get("description"):
            texts += (f"<details><summary>YouTube upload text</summary><pre>{html.escape(meta['description'])}</pre>"
                      "</details>")
        if reel_json.exists() and reel.get("caption"):
            texts += (f"<details><summary>Instagram caption</summary><pre>{html.escape(reel['caption'])}</pre>"
                      "</details>")
        return (f"<div class='card{' wide' if wide else ''}'><h2>#{ch['number']} {html.escape(ch['name'])}{label}</h2>"
                     f"<div class='vids'>{vids}</div><p>{'<br>'.join(info)}</p>{texts}<div class='thumbs'>{th}</div></div>")


def _page(cards: list[str]) -> str:
    return f"""<!doctype html><html><head><meta charset='utf-8'><title>Clip Factory — Review</title>
<style>body{{background:#0e0e10;color:#eee;font-family:Segoe UI,sans-serif;margin:24px}}
.card{{background:#1b1b1f;border-radius:12px;padding:16px;margin-bottom:22px}}
.vids{{display:flex;gap:12px;flex-wrap:wrap}} video{{height:620px;border-radius:8px;background:#000}}
.wide video{{height:auto;width:760px}} .old video{{height:300px;opacity:.85}} .old small{{display:block;color:#999}} .thumbs img{{width:380px;margin:6px 8px 0 0;border-radius:8px}} details{{margin:6px 0}} summary{{cursor:pointer;color:#9cf}} pre{{white-space:pre-wrap;background:#111;padding:10px;border-radius:8px;font-size:13px;max-width:980px}}
h2{{margin:0 0 10px;font-size:18px}} p{{font-size:14px;line-height:1.6;max-width:1100px}}</style></head><body>
<h1>Clip Factory — v3 samples for approval</h1><p>Nothing is posted. Each card shows the YouTube version and, next to it, the Instagram Reel version (other hook,
shorter ending) with thumbnails and covers. Reply "approve" per format or tell me what to change.
Small "BEFORE" videos show the old look.</p>
<details open><summary>What to check on each card (about 1 minute per format)</summary><ol style='font-size:14px;line-height:1.7'>
<li><b>First 2 seconds:</b> would you stop scrolling? Does the hook match the title and thumbnail?</li>
<li><b>Pictures:</b> on topic, not repeated, nothing odd or off-brand.</li>
<li><b>Captions and on-screen text:</b> easy to read, correct spelling (Hindi too), nothing covered by the app's buttons.</li>
<li><b>Voice and music:</b> clear, natural pace, music not too loud.</li>
<li><b>Ending:</b> lands well (Shorts loop back to the start).</li>
<li><b>Thumbnail / cover:</b> readable on a phone, true to the video.</li>
<li><b>Upload text:</b> open "YouTube upload text" and "Instagram caption": facts, tone, hashtags.</li>
<li><b>Fact-check line:</b> ⚠️ lists details the sources didn't mention; tell me any you know are wrong.</li>
</ol><p>Reply like: <i>"approve 2, 3, 5"</i> or <i>"change 7: pictures too dark"</i>.</p></details>
{''.join(cards) or '<p>No videos yet.</p>'}</body></html>"""

