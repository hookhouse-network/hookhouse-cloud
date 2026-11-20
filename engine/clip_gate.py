"""Strict clip verification (owner, 20 Nov 2026: "the campaign format, rules and upload only eligible videos, create
super strict verification and validation gates, all the clips must and mandatorily pass these gates").

One fail-closed gate for every clip (anything cut from someone else's footage). It runs:
  - before a clip is offered for approval (autopilot._campaign_held),
  - before auto-approval (engine/auto_approve.py),
  - and again right before EVERY platform post (engine/publish_queue.py), because a campaign can end, run out of
    budget or change its platforms between approval and posting.

Fail closed: missing data never means "fine". A clip without its record, without a permission basis, whose campaign
can't be read, whose brief lists no platforms, or whose file can't be measured is blocked.

Layers (all must pass):
  1. Is it a clip? Decided from every signal (upload meta clip/campaign, channel type clips, item kind clip, clips.json
     present), so a clip can't slip through as "not a clip" because one field is missing.
  2. Permission: a basis on record; campaign footage -> the full campaign gate (engine/campaign_gate.py: joined,
     active, budget, safety, footage is the campaign's own, made after joining, length, caption tags/#ad/required
     text, on-screen Ad label, logo, no added music, banned words, no reuse across campaigns, brief rules read by the
     AI checker); register footage -> an open licence or written evidence.
  3. Platform: the brief must list the platform (unknown brief platforms = blocked everywhere).
  4. The FILE, measured (never trusting the notes): exists, plays, real duration matches the record (+-2 s) and the
     campaign's length window, vertical 9:16, at least 720x1280, has sound, no letterbox bars, perceptual hash equal
     to the one recorded at cut time when there is one (the approved edit is the posted edit)."""
from __future__ import annotations

import json
from pathlib import Path

DUR_TOLERANCE_S = 2.0
MIN_W, MIN_H = 720, 1280


def _meta(it: dict) -> dict:
    try:
        from .publish import item_meta
        return item_meta(it) or {}
    except Exception as e:  # noqa: BLE001 - no readable meta: the record checks below fail closed
        print(f"clip gate: metadata of {it.get('id')} unreadable ({type(e).__name__}: {e})")
        return {}


def is_clip(it: dict, meta: dict | None = None, ch: dict | None = None) -> bool:
    meta = meta if meta is not None else _meta(it)
    if meta.get("clip") or meta.get("campaign") or it.get("kind") == "clip":
        return True
    if (ch or {}).get("type") == "clips":
        return True
    out = Path(it.get("out_dir") or "")
    return bool(it.get("out_dir")) and (out / "clips.json").exists()


def file_problems(video: Path, expect_s: float | None = None, length: tuple[float, float] | None = None,
                  expect_hash: str | None = None, probe=None, letterbox=None, hasher=None) -> list[str]:
    if not video.exists() or video.stat().st_size < 1024:
        return [f"video file missing or empty ({video.name})"]
    try:
        if probe is None:
            from .reach_gate import probe
        info = probe(video)
    except Exception as e:  # noqa: BLE001 - can't measure = not verified
        return [f"video could not be measured ({type(e).__name__})"]
    p = []
    w, h, dur = int(info.get("w") or 0), int(info.get("h") or 0), float(info.get("dur") or 0)
    if dur <= 0:
        p.append("video does not play (no duration)")
    if expect_s and dur and abs(dur - float(expect_s)) > DUR_TOLERANCE_S:
        p.append(f"file is {dur:.0f}s but the record says {float(expect_s):.0f}s (not the checked edit)")
    if length and dur and not length[0] <= dur <= length[1]:
        p.append(f"file length {dur:.0f}s is outside the campaign's {length[0]:.0f}-{length[1]:.0f}s")
    if not (w and h) or not 0.5 <= w / h <= 0.6:
        p.append(f"not vertical 9:16 ({w}x{h})")
    elif w < MIN_W or h < MIN_H:
        p.append(f"resolution too low ({w}x{h}, need at least {MIN_W}x{MIN_H})")
    if not info.get("audio"):
        p.append("no sound track")
    try:
        if letterbox is None:
            from .reach_gate import letterboxed as letterbox
        if dur and letterbox(video, dur):
            p.append("black bars top and bottom (landscape pasted into 9:16)")
    except Exception as e:  # noqa: BLE001
        p.append(f"letterbox check could not run ({type(e).__name__})")
    if expect_hash:
        try:
            if hasher is None:
                from .campaign_safety import video_hash as hasher
            from .campaign_safety import hash_distance, same_edit
            got = hasher(video)
            if not same_edit(got, expect_hash):
                p.append(f"the file differs from the edit that was checked (hash mismatch, "
                         f"{min(hash_distance(got, expect_hash), 512)} bits)")
        except Exception as e:  # noqa: BLE001
            p.append(f"edit hash could not be checked ({type(e).__name__})")
    return p


def verify(it: dict, platform: str | None = None, brain_fn=None, ch: dict | None = None,
           check_file: bool = True) -> list[str]:
    """[] = the clip may go (to `platform`, or anywhere it is offered when None). Non-clips return []."""
    meta = _meta(it)
    if ch is None:
        try:
            from .config import channel
            ch = channel(it["channel"])
        except Exception:  # noqa: BLE001
            ch = {}
    if not is_clip(it, meta, ch):
        return []
    p: list[str] = []
    out = Path(it.get("out_dir") or "")
    video = out / (it.get("file") or "video.mp4")
    entry = None
    try:
        from .campaign_gate import clip_entry
        entry, _rows, _cj = clip_entry(it)
    except Exception as e:  # noqa: BLE001
        p.append(f"clip record unreadable ({type(e).__name__})")
    rec = dict(meta, **(entry or {}))
    campaign_id = rec.get("campaign")
    basis = (rec.get("permission") or {}).get("basis")
    if not basis:
        p.append("no permission record for this footage")
    length = None
    if campaign_id:
        if entry is None:
            p.append("campaign clip without its clip record (clips.json): can't verify the brief")
        else:
            try:
                from .campaign_gate import gate_item
                p += gate_item(it, brain_fn=brain_fn)
            except Exception as e:  # noqa: BLE001 - a gate that cannot run blocks
                p.append(f"campaign gate could not run ({str(e)[:80]})")
        try:
            from . import db
            camp = db.get_campaign(db.connect(), campaign_id) or {}
        except Exception as e:  # noqa: BLE001
            camp = {}
            p.append(f"campaign {campaign_id} could not be read ({type(e).__name__})")
        names = [str(x).lower() for x in camp.get("platforms") or []]
        if not names:
            p.append("the campaign brief lists no platforms: posting nowhere until it does")
        elif platform:
            from .platforms import CAMPAIGN_NAMES
            if CAMPAIGN_NAMES.get(platform, platform) not in names:
                p.append(f"not allowed on {platform} by the campaign brief")
        ls = camp.get("length_seconds") or {}
        if ls.get("min") or ls.get("max"):
            from .campaign_gate import DEFAULT_LEN
            length = (float(ls.get("min") or DEFAULT_LEN[0]), float(ls.get("max") or DEFAULT_LEN[1]))
    elif basis:
        from .clip_sources import OK_BASIS
        if basis not in OK_BASIS:
            p.append(f"permission basis '{basis}' is not one we accept ({', '.join(sorted(OK_BASIS))})")
        elif not (rec.get("permission") or {}).get("evidence"):
            p.append(f"permission '{basis}' has no evidence on record")
    if check_file:
        p += file_problems(video, expect_s=rec.get("duration_s"), length=length, expect_hash=rec.get("edit_hash"))
        reel = rec.get("reel")                       # Instagram/Facebook/Threads post the Reel variant: check it too
        if reel and platform in (None, "instagram", "facebook", "threads"):
            p += [f"Reel variant: {x}" for x in file_problems(out / str(reel), length=length)]
    return list(dict.fromkeys(p))


def summary(problems: list[str]) -> str:
    return "✅ clip verified" if not problems else "🛑 clip blocked: " + "; ".join(problems)[:600]


def dump(it: dict) -> str:
    """Readable report for /why and the Studio."""
    return json.dumps({"item": it.get("id"), "problems": verify(it)}, ensure_ascii=False, indent=1)
