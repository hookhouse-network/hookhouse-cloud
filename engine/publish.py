"""Uploader for approved videos: YouTube (Shorts + long), Instagram Reels, Facebook Page Reels.

Safety rules (owner is the signing authority):
- Only items the owner APPROVED on the week page are ever uploaded (weekly.approved_items()).
- YouTube uploads are scheduled (private until publishAt, then public) or public at once. Since 2 Nov 2026 Google
  no longer locks uploads from unaudited API projects to private.
- Instagram: checks the 24-hour publishing limit first; optional Trial Reel (shown to non-followers only).
- DRY RUN is the default: without credentials (or with dry_run=True) it only prints the exact actions.
Credentials live in .env / data/secrets (git-ignored). Uses plain HTTPS calls (requests), no extra libraries.

Official endpoints:
- YouTube Data API v3 resumable upload, playlistItems.insert; OAuth 2.0 for installed apps (loopback).
- Instagram Graph API: POST /{ig-user}/media (media_type=REELS, upload_type=resumable) ->
  upload to rupload.facebook.com -> poll status_code -> POST /{ig-user}/media_publish;
  GET /{ig-user}/content_publishing_limit.
- Facebook Pages: POST /{page}/video_reels (start -> upload -> finish).
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import requests

from .config import ROOT
from engine.core.http import HTTP

SECRETS = ROOT / "data" / "secrets"
LOG = ROOT / "data" / "publish_log.jsonl"
YT_UPLOAD = "https://www.googleapis.com/upload/youtube/v3/videos"
YT_API = "https://www.googleapis.com/youtube/v3"
META_VERSION = os.environ.get("META_API_VERSION", "v24.0")  # v21.0 is retired around 21 Jan 2027
GRAPH = f"https://graph.facebook.com/{META_VERSION}"
IG_GRAPH = f"https://graph.instagram.com/{META_VERSION}"     # "Instagram API with Instagram Login" (no Page needed)
RUPLOAD = "https://rupload.facebook.com"
QUOTA_STOP = 0.8                       # stop at 80% of the day's YouTube quota
UPLOAD_UNITS = int(os.environ.get("YOUTUBE_UPLOAD_UNITS", "100"))   # ~1,600 before Dec 2025, ~100 after (reported);
                                                                    # a real quotaExceeded reply is handled anyway


@dataclass
class Action:
    platform: str
    channel: str
    item_id: str
    what: str
    when: str = ""
    details: dict = field(default_factory=dict)
    done: bool = False
    result: dict = field(default_factory=dict)


def _log(action: Action) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"at": time.time(), **action.__dict__}, ensure_ascii=False) + "\n")


# ---------- YouTube ----------

def yt_token_path(channel_id: str) -> Path:
    return SECRETS / f"youtube_{channel_id}.json"


def yt_access_token(channel_id: str, session=HTTP) -> str | None:
    """Refreshes the stored OAuth token. None if the channel is not connected yet."""
    return google_access_token(yt_token_path(channel_id), session)


def google_access_token(p: Path, session=HTTP) -> str | None:
    """Fresh access token from a stored Google refresh token (data/secrets/*.json); None if not connected."""
    cid, secret = os.environ.get("YOUTUBE_CLIENT_ID"), os.environ.get("YOUTUBE_CLIENT_SECRET")
    if not p.exists() or not cid or not secret:
        return None
    tok = json.loads(p.read_text(encoding="utf-8"))
    if tok.get("access_token") and tok.get("expires_at", 0) > time.time() + 60:
        return tok["access_token"]
    r = session.post("https://oauth2.googleapis.com/token", data={
        "client_id": cid, "client_secret": secret, "refresh_token": tok["refresh_token"],
        "grant_type": "refresh_token"}, timeout=30)
    r.raise_for_status()
    data = r.json()
    tok.update(access_token=data["access_token"], expires_at=time.time() + data.get("expires_in", 3600))
    p.write_text(json.dumps(tok), encoding="utf-8")
    return tok["access_token"]


def ch_lang(channel_id: str) -> str:
    try:
        from .config import channel as get_channel
        return get_channel(channel_id).get("language", "en")
    except Exception:  # noqa: BLE001 - captions language is a nice-to-have
        return "en"


def youtube_metadata(meta: dict, publish_at: str | None, made_for_kids: bool = False) -> dict:
    clean = lambda t: str(t or "").replace("<", "").replace(">", "").strip()   # YouTube refuses < and >
    title = clean(meta.get("title"))[:100] or "New video"   # no "#shorts" in titles: vertical <=3 min is a Short
    meta = dict(meta, description=clean(meta.get("description")),
                tags=[clean(t) for t in meta.get("tags") or [] if clean(t)],
                hashtags=[clean(t) for t in meta.get("hashtags") or [] if clean(t)])
    status = {"privacyStatus": "private" if publish_at else "public",
              "selfDeclaredMadeForKids": bool(made_for_kids), "containsSyntheticMedia": bool(meta.get("yt_synthetic", meta.get("ai_label")))}
    # YouTube asks for the "altered or synthetic" label only for REALISTIC AI visuals (cartoons/animation and an AI
    # narrator over real footage are exempt); Meta's "AI info" (ai_label) also covers realistic AI voices (17 Nov)
    if publish_at:                                           # scheduled (needs private status), sent in UTC
        status["publishAt"] = datetime.fromisoformat(publish_at).astimezone(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%S.000Z")
    tags, total = [], 0
    for t in dict.fromkeys((meta.get("tags") or []) + [t.lstrip("#") for t in meta.get("hashtags", [])]):
        cost = len(t) + (2 if " " in t else 0) + 1           # YouTube: 500 characters for all tags together
        if len(tags) < 15 and total + cost <= 480:
            tags.append(t)
            total += cost
    return {"snippet": {"title": title, "description": (meta.get("description") or "")[:4900],
                        "tags": tags,
                        "categoryId": "27" if made_for_kids else "24"},      # 27 Education (kids learning)
            "status": status}


def youtube_upload(channel_id: str, video: Path, meta: dict, publish_at: str | None, session=HTTP,
                   dry_run: bool = True) -> Action:
    from .links import footer as _footer
    foot = _footer(channel_id, ch_lang(channel_id), kids=bool(meta.get("made_for_kids"))) if not meta.get("clip") else ""
    if foot and foot not in str(meta.get("description") or ""):        # cross-links to sibling channels + Instagram
        meta = dict(meta, description=(str(meta.get("description") or "").rstrip() + "\n\n" + foot))
    body = youtube_metadata(meta, publish_at, meta.get("made_for_kids", False))
    if meta.get("campaign"):                                 # a brand pays for campaign clips: disclose it
        body["paidProductPlacementDetails"] = {"hasPaidProductPlacement": True}
    lang = meta.get("language") or ch_lang(channel_id)
    body["snippet"]["defaultLanguage"] = body["snippet"]["defaultAudioLanguage"] = "hi" if lang == "hi" else "en"
    act = Action("youtube", channel_id, meta.get("_item", ""), f"upload {video.name}" + (" (scheduled)" if publish_at else ""),
                 publish_at or "", {"title": body["snippet"]["title"], "made_for_kids": meta.get("made_for_kids", False),
                                    "synthetic_label": body["status"]["containsSyntheticMedia"],
                                    "format": meta.get("format", "short")})
    token = None if dry_run else yt_access_token(channel_id, session)
    if not token:
        act.details["dry_run"] = True
        _log(act)
        return act
    if not quota_ok(UPLOAD_UNITS, "insert"):
        act.result = {"error": "YouTube quota guard: 80% of today's upload quota used"}
        _log(act)
        return act
    if channel_id in (_quota_state().get("blocked") or []):
        act.result = {"error": "this channel reached YouTube's upload limit today; it tries again tomorrow"}
        _log(act)
        return act
    h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8",
         "X-Upload-Content-Type": "video/mp4", "X-Upload-Content-Length": str(video.stat().st_size)}
    try:
        parts = "snippet,status" + (",paidProductPlacementDetails" if "paidProductPlacementDetails" in body else "")
        r = session.post(f"{YT_UPLOAD}?uploadType=resumable&part={parts}", headers=h, data=json.dumps(body),
                         timeout=60)
        r.raise_for_status()
        loc = r.headers["Location"]
        with open(video, "rb") as fh:
            r2 = session.put(loc, headers={"Authorization": f"Bearer {token}", "Content-Type": "video/mp4"}, data=fh,
                             timeout=3600)
        r2.raise_for_status()
    except requests.RequestException as e:
        reason = _yt_reason(getattr(e, "response", None))
        if reason in ("quotaExceeded", "dailyLimitExceeded"):
            add_quota(10 ** 6, "insert")                         # the project's upload quota: stop today
        elif reason == "uploadLimitExceeded":                    # only THIS channel's daily limit
            s = _quota_state()
            s.setdefault("blocked", []).append(channel_id)
            QUOTA_FILE.parent.mkdir(parents=True, exist_ok=True)
            QUOTA_FILE.write_text(json.dumps(s), encoding="utf-8")
        act.result = {"error": f"YouTube said: {YT_REASONS.get(reason, reason or str(e)[:150])}", "reason": reason}
        _log(act)
        return act
    add_quota(UPLOAD_UNITS, "insert")
    act.done, act.result = True, {"video_id": r2.json().get("id")}
    _log(act)
    return act


YT_REASONS = {
    "quotaExceeded": "today's API quota is used up; uploads continue after the daily reset",
    "dailyLimitExceeded": "today's API quota is used up; uploads continue after the daily reset",
    "uploadLimitExceeded": "this channel hit its daily upload limit, or it needs verification for videos over "
                           "15 minutes (youtube.com/verify)",
    "invalidTitle": "the title was refused (too long or a banned character)",
    "invalidDescription": "the description was refused",
    "invalidPublishAt": "the scheduled time was refused (too soon or in the past)",
    "forbidden": "this Google login can't upload to that channel (reconnect it with the channel's account)",
    "authError": "the YouTube login stopped working (python cli.py connect youtube --channel <id>)",
}


def _yt_reason(resp) -> str:
    try:
        return resp.json()["error"]["errors"][0]["reason"]
    except Exception:  # noqa: BLE001
        return ""


def youtube_delete(channel_id: str, video_id: str, session=HTTP) -> bool:
    """Removes a scheduled upload (used when the owner changes or rejects a video after approving it)."""
    try:
        token = yt_access_token(channel_id, session)
        if not token:
            return False
        r = session.delete(f"{YT_API}/videos", params={"id": video_id},
                           headers={"Authorization": f"Bearer {token}"}, timeout=30)
    except Exception:  # noqa: BLE001 - the caller tells the owner to delete it by hand
        return False
    add_quota(50)
    ok = r.status_code in (200, 204, 404)                    # 404: already gone
    _log(Action("youtube", channel_id, "", f"delete scheduled upload {video_id}",
                details={"status": r.status_code, "deleted_video_id": video_id if ok else None}, done=ok))
    return ok


def youtube_reschedule(channel_id: str, video_id: str, publish_at: str, session=HTTP) -> bool:
    """Moves a scheduled (private) upload to a new publish time. videos.update replaces the whole status part, so
    the current status is read first and only publishAt changes (made-for-kids, AI label etc. stay as they are)."""
    try:
        token = yt_access_token(channel_id, session)
        if not token:
            return False
        h = {"Authorization": f"Bearer {token}"}
        r = session.get(f"{YT_API}/videos", params={"part": "status", "id": video_id}, headers=h, timeout=30)
        add_quota(1)
        r.raise_for_status()
        items = r.json().get("items") or []
        if not items or items[0]["status"].get("privacyStatus") != "private":
            return False                                   # already public (or gone): nothing to move
        status = {k: v for k, v in items[0]["status"].items()
                  if k in ("privacyStatus", "embeddable", "license", "publicStatsViewable", "selfDeclaredMadeForKids",
                           "containsSyntheticMedia")}
        status["publishAt"] = datetime.fromisoformat(publish_at).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        u = session.put(f"{YT_API}/videos", params={"part": "status"}, headers=h, timeout=30,
                        json={"id": video_id, "status": status})
        add_quota(50)
        ok = u.status_code == 200
    except Exception:  # noqa: BLE001
        return False
    _log(Action("youtube", channel_id, "", f"reschedule {video_id}", when=publish_at,
                details={"status": u.status_code}, done=ok))
    return ok


def youtube_thumbnail(channel_id: str, video_id: str, image: Path, session=HTTP, dry_run: bool = True) -> Action:
    """Custom thumbnail (thumbnails.set, ~50 units; needs a verified channel; max 50 MB). Shorts too since 3 Nov 2026,
    but only after YouTube finished processing the Short (see process_pending_thumbnails)."""
    act = Action("youtube", channel_id, "", f"thumbnail {image.name} -> {video_id}")
    token = None if dry_run else yt_access_token(channel_id, session)
    if not token or not image.exists() or image.stat().st_size > 50 * 1024 * 1024:
        act.details["dry_run"] = True
        _log(act)
        return act
    r = session.post("https://www.googleapis.com/upload/youtube/v3/thumbnails/set", params={"videoId": video_id},
                     headers={"Authorization": f"Bearer {token}", "Content-Type": "image/jpeg"},
                     data=image.read_bytes(), timeout=120)
    r.raise_for_status()
    add_quota(50)
    act.done = True
    _log(act)
    return act


PENDING_THUMBS = ROOT / "data" / "state" / "pending_thumbnails.json"


def queue_short_thumbnail(channel_id: str, video_id: str, image: Path) -> None:
    rows = json.loads(PENDING_THUMBS.read_text(encoding="utf-8")) if PENDING_THUMBS.exists() else []
    rows.append({"channel": channel_id, "video_id": video_id, "image": str(image), "at": time.time()})
    PENDING_THUMBS.parent.mkdir(parents=True, exist_ok=True)
    PENDING_THUMBS.write_text(json.dumps(rows), encoding="utf-8")


def process_pending_thumbnails(session=HTTP) -> int:
    """Set queued Shorts thumbnails once YouTube says processing succeeded (videos.list, 1 unit each)."""
    if not PENDING_THUMBS.exists():
        return 0
    rows, keep, done = json.loads(PENDING_THUMBS.read_text(encoding="utf-8")), [], 0
    for r in rows:
        if time.time() - r["at"] > 48 * 3600 or not Path(r["image"]).exists():
            continue                                              # give up after 2 days
        try:
            tok = yt_access_token(r["channel"], session)
            if not tok:
                continue
            q = session.get(f"{YT_API}/videos", params={"part": "processingDetails", "id": r["video_id"]},
                            headers={"Authorization": f"Bearer {tok}"}, timeout=30)
            add_quota(1)
            items = (q.json() or {}).get("items") or []
            if not items:
                continue                                          # deleted
            st = (items[0].get("processingDetails") or {}).get("processingStatus")
            if st == "succeeded":
                if youtube_thumbnail(r["channel"], r["video_id"], Path(r["image"]), session=session,
                                     dry_run=False).done:
                    done += 1
                continue
            if st in ("failed", "terminated"):
                continue
        except Exception:  # noqa: BLE001 - try again next time
            pass
        keep.append(r)
    PENDING_THUMBS.write_text(json.dumps(keep), encoding="utf-8")
    return done


def already_posted(it: dict, ignore_youtube_id: str | None = None) -> list[str]:
    """Platforms where THIS version of the item is already live or scheduled (no double posting). Uploads of an
    older version, YouTube uploads that were deleted, and dry runs don't count."""
    if not LOG.exists():
        return []
    since = float(it.get("made_at") or 0)
    deleted, rows, hits = set(), [], []
    for ln in LOG.read_text(encoding="utf-8").splitlines():
        try:
            a = json.loads(ln)
        except json.JSONDecodeError:
            continue
        det = a.get("details") or {}
        if det.get("deleted_video_id"):
            deleted.add(det["deleted_video_id"])
        elif (a.get("item_id") == it.get("id") and a.get("done") and not det.get("dry_run")
              and (a.get("at") or 0) >= since):
            rows.append(a)
    for a in rows:
        vid = (a.get("result") or {}).get("video_id")
        if a.get("platform") == "youtube" and (vid in deleted or (ignore_youtube_id and vid == ignore_youtube_id)):
            continue
        if a.get("platform") not in hits:
            hits.append(a.get("platform"))
    return hits


def logged_result(it: dict, platform: str, field: str):
    """A field of this item version's successful post on a platform (e.g. the Instagram media id that Threads can
    fall back to when Threads is posted in a later queue run)."""
    if not LOG.exists():
        return None
    since, found = float(it.get("made_at") or 0), None
    for ln in LOG.read_text(encoding="utf-8").splitlines():
        try:
            a = json.loads(ln)
        except json.JSONDecodeError:
            continue
        if (a.get("item_id") == it.get("id") and a.get("platform") == platform and a.get("done")
                and not (a.get("details") or {}).get("dry_run") and (a.get("at") or 0) >= since
                and "Story" not in str(a.get("what") or "")):
            found = (a.get("result") or {}).get(field) or found
    return found


CAPTION_UNITS = 400


def youtube_captions(channel_id: str, video_id: str, srt: Path, language: str, session=HTTP,
                     dry_run: bool = True) -> Action:
    """Our own captions file (exact words, correct Hindi): search reads it and sound-off viewers get real subtitles."""
    act = Action("youtube", channel_id, "", f"captions {srt.name} -> {video_id} ({language})")
    token = None if dry_run else yt_access_token(channel_id, session)
    if not token or not srt.exists():
        act.details["dry_run"] = True
        _log(act)
        return act
    if not quota_ok(CAPTION_UNITS):
        act.result = {"error": "YouTube quota guard: captions skipped today"}
        _log(act)
        return act
    boundary = "clipfactorycaptions"
    meta = json.dumps({"snippet": {"videoId": video_id, "language": language, "name": "", "isDraft": False}})
    body = (f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n{meta}\r\n"
            f"--{boundary}\r\nContent-Type: application/octet-stream\r\n\r\n").encode("utf-8") \
        + srt.read_bytes() + f"\r\n--{boundary}--\r\n".encode("utf-8")
    r = session.post("https://www.googleapis.com/upload/youtube/v3/captions?uploadType=multipart&part=snippet",
                     headers={"Authorization": f"Bearer {token}",
                              "Content-Type": f"multipart/related; boundary={boundary}"}, data=body, timeout=120)
    r.raise_for_status()
    add_quota(CAPTION_UNITS)
    act.done, act.result = True, {"caption_id": r.json().get("id")}
    _log(act)
    return act


def youtube_add_to_playlist(channel_id: str, video_id: str, playlist_id: str, session=HTTP,
                            dry_run: bool = True) -> Action:
    act = Action("youtube", channel_id, "", f"add {video_id} to playlist {playlist_id}")
    token = None if dry_run else yt_access_token(channel_id, session)
    if not token:
        act.details["dry_run"] = True
        _log(act)
        return act
    for attempt in range(3):              # 409 = the fresh upload is still processing on YouTube's side (17 Nov log)
        r = session.post(f"{YT_API}/playlistItems?part=snippet", headers={"Authorization": f"Bearer {token}"},
                         json={"snippet": {"playlistId": playlist_id,
                                           "resourceId": {"kind": "youtube#video", "videoId": video_id}}}, timeout=30)
        if getattr(r, "status_code", 200) != 409:
            break
        if "alreadyinplaylist" in str(getattr(r, "text", "")).lower().replace(" ", ""):
            act.done, act.result = True, {"playlist_item": "already there"}
            _log(act)
            return act
        time.sleep(20 * (attempt + 1))
    r.raise_for_status()
    add_quota(50)
    act.done, act.result = True, {"playlist_item": r.json().get("id")}
    _log(act)
    return act


PLAYLISTS = SECRETS / "playlists.json"


def playlist_title(channel_id: str, fmt: str) -> str:
    """One playlist per channel and format: long videos binge in "full episodes", Shorts in "Shorts"."""
    try:
        from .config import channel as get_channel
        ch = get_channel(channel_id)
        name = ch.get("name", channel_id)
        custom = (ch.get("playlists") or {}).get(fmt)
    except Exception:  # noqa: BLE001
        name, custom = channel_id, None
    return custom or (f"{name}: full episodes" if fmt == "long" else f"{name}: Shorts")


def ensure_playlist(channel_id: str, title: str, session=HTTP, kids: bool = False) -> str | None:
    """The playlist's id, creating it once (playlists.insert, ~50 units)."""
    cache = json.loads(PLAYLISTS.read_text(encoding="utf-8")) if PLAYLISTS.exists() else {}
    pid = (cache.get(channel_id) or {}).get(title)
    if pid:
        return pid
    token = yt_access_token(channel_id, session)
    if not token or not quota_ok(50):
        return None
    r = session.post(f"{YT_API}/playlists?part=snippet,status", headers={"Authorization": f"Bearer {token}"},
                     json={"snippet": {"title": title[:150]}, "status": {"privacyStatus": "public"}}, timeout=30)
    r.raise_for_status()
    add_quota(50)
    pid = r.json().get("id")
    if pid:
        cache.setdefault(channel_id, {})[title] = pid
        PLAYLISTS.parent.mkdir(parents=True, exist_ok=True)
        PLAYLISTS.write_text(json.dumps(cache, indent=1), encoding="utf-8")
    return pid


def ensure_podcast(channel_id: str, playlist_id: str, session=HTTP) -> bool:
    """Mark the channel's full-episodes playlist as a podcast show (YouTube Music podcasts): a square playlist image
    (playlistImages.insert, 50 units) then status.podcastStatus=enabled. Done once; remembered in playlists.json."""
    cache = json.loads(PLAYLISTS.read_text(encoding="utf-8")) if PLAYLISTS.exists() else {}
    flags = cache.setdefault("_podcast", {})
    if flags.get(playlist_id):
        return True
    token = yt_access_token(channel_id, session)
    if not token or not quota_ok(100):
        return False
    art = ROOT / "output" / "brand" / channel_id / "avatar.png"
    if art.exists():
        from PIL import Image
        import io
        buf = io.BytesIO()
        Image.open(art).convert("RGB").resize((1400, 1400)).save(buf, "JPEG", quality=92)
        boundary = "hookhouseplaylistimage"
        meta = json.dumps({"snippet": {"playlistId": playlist_id, "type": "hero"}})
        body = (f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n{meta}\r\n"
                f"--{boundary}\r\nContent-Type: image/jpeg\r\n\r\n").encode() + buf.getvalue() + \
            f"\r\n--{boundary}--\r\n".encode()
        r = session.post("https://www.googleapis.com/upload/youtube/v3/playlistImages?uploadType=multipart&part=snippet",
                         headers={"Authorization": f"Bearer {token}",
                                  "Content-Type": f"multipart/related; boundary={boundary}"}, data=body, timeout=120)
        add_quota(50)
        if getattr(r, "status_code", 500) >= 400:
            _log(Action("youtube", channel_id, "", f"podcast image refused (HTTP {r.status_code})"))
            return False
    r = session.put(f"{YT_API}/playlists?part=status", headers={"Authorization": f"Bearer {token}"},
                    json={"id": playlist_id, "status": {"privacyStatus": "public", "podcastStatus": "enabled"}}, timeout=30)
    add_quota(50)
    ok = getattr(r, "status_code", 500) < 400
    _log(Action("youtube", channel_id, "", f"podcast show {'enabled' if ok else 'refused'} for {playlist_id}", done=ok))
    if ok:
        flags[playlist_id] = True
        PLAYLISTS.parent.mkdir(parents=True, exist_ok=True)
        PLAYLISTS.write_text(json.dumps(cache, indent=1), encoding="utf-8")
    return ok


TG_BOT_MAX = 48 * 1024 * 1024          # Telegram bots may send files up to 50 MB


def telegram_copy(video: Path) -> Path:
    """Same picture size, lower bitrate, so the file fits a Telegram bot upload (~44 MB). Made once, kept beside it."""
    import subprocess
    from .media import ffmpeg
    out = video.with_name(f"{video.stem}_tg.mp4")
    if out.exists() and out.stat().st_size <= TG_BOT_MAX:
        return out
    dur = max(1.0, ffmpeg.duration(video))
    kbps = max(300, int(TG_BOT_MAX * 0.9 * 8 / 1024 / dur) - 128)
    subprocess.run([ffmpeg.ffmpeg_bin(), "-y", "-v", "error", "-i", str(video), "-c:v", "libx264", "-preset", "medium",
                    "-b:v", f"{kbps}k", "-maxrate", f"{int(kbps * 1.2)}k", "-bufsize", f"{kbps * 2}k",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(out)],
                   check=True, timeout=3600)
    return out


def telegram_channel_post(channel_id: str, video: Path, meta: dict, youtube_id: str | None = None,
                          item_id: str = "", dry_run: bool = True) -> Action:
    """Post to the channel's own Telegram channel (bot as admin; @name in config/links.yaml). Shorts go as the video;
    long videos (over the bot's 50 MB limit) as the thumbnail + the YouTube link."""
    act = Action("telegram", channel_id, item_id, f"post {video.name} to the Telegram channel")
    from .links import data as _links
    chat = ((_links().get(channel_id) or {}).get("telegram") or "").strip()
    if dry_run or not chat or not os.environ.get("TELEGRAM_BOT_TOKEN"):
        act.details["dry_run"] = True
        _log(act)
        return act
    from . import telegram_bot as tb
    yt = f"https://youtu.be/{youtube_id}" if youtube_id else ""
    cap = (str(meta.get("title") or "") + (f"\n\n▶ {yt}" if yt else ""))[:1024]
    try:
        if video.stat().st_size > TG_BOT_MAX:            # 25 Nov: a 52 MB Short was blocked; send a smaller copy
            video = telegram_copy(video)
        if video.stat().st_size <= TG_BOT_MAX:
            with video.open("rb") as fh:
                res = tb.api("sendVideo", files={"video": (video.name, fh, "video/mp4")}, chat_id=chat, caption=cap,
                             supports_streaming=True, http_timeout=600)
        else:
            thumbs = sorted(video.parent.glob("thumbnail_v2*.jpg")) or sorted(video.parent.glob("*.jpg"))
            if thumbs:
                with thumbs[0].open("rb") as fh:
                    res = tb.api("sendPhoto", files={"photo": (thumbs[0].name, fh, "image/jpeg")}, chat_id=chat,
                                 caption=cap, http_timeout=120)
            else:
                res = tb.api("sendMessage", chat_id=chat, text=cap)
    except Exception as e:  # noqa: BLE001
        act.result = {"error": f"Telegram channel: {str(e)[:150]}"}
        _log(act)
        return act
    act.done, act.result = True, {"message_id": (res or {}).get("message_id")}
    _log(act)
    return act


QUOTA_FILE = ROOT / "data" / "state" / "youtube_quota.json"


def _quota_state() -> dict:
    from zoneinfo import ZoneInfo
    today = datetime.now(ZoneInfo("America/Los_Angeles")).strftime("%Y-%m-%d")   # Google resets at midnight Pacific
    if QUOTA_FILE.exists():
        s = json.loads(QUOTA_FILE.read_text(encoding="utf-8"))
        if s.get("day") == today:
            return s
    lim = int(os.environ.get("YOUTUBE_DAILY_QUOTA", "10000"))
    return {"day": today, "used": 0, "limit": lim, "insert_used": 0,
            "insert_limit": int(os.environ.get("YOUTUBE_UPLOAD_QUOTA", str(lim)))}


def quota_ok(units: int, bucket: str = "general") -> bool:
    """Since 1 June 2026 videos.insert and search.list each have their own quota bucket ("insert", "search");
    everything else shares the general one."""
    s = _quota_state()
    if bucket == "general":
        return s["used"] + units <= s["limit"] * QUOTA_STOP
    lim = s.get(f"{bucket}_limit") or int(os.environ.get(f"YOUTUBE_{bucket.upper()}_QUOTA", str(s["limit"])))
    return s.get(f"{bucket}_used", 0) + units <= lim * QUOTA_STOP


def add_quota(units: int, bucket: str = "general") -> None:
    s = _quota_state()
    if bucket == "general":
        s["used"] += units
    else:
        s[f"{bucket}_used"] = s.get(f"{bucket}_used", 0) + units
    QUOTA_FILE.parent.mkdir(parents=True, exist_ok=True)
    QUOTA_FILE.write_text(json.dumps(s), encoding="utf-8")


# ---------- Instagram / Facebook ----------

def meta_creds(channel_id: str) -> dict | None:
    p = SECRETS / f"meta_{channel_id}.json"                    # {"ig_user_id", "page_id", "access_token"}
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


IG_MAX_TAGS = 5                                        # Mosseri, 18 Dec 2025: 30 -> 5 per post/Reel
SHARE_TAG = "share"                                    # temporary public-link copies (deleted after Instagram fetched)
WORKER_URL = os.environ.get("WORKER_URL", "https://hookhouse-bot.clipping-system.workers.dev")


def _live(session) -> bool:
    """True for the real network (plain `requests` or the shared retrying HTTP); False for a test's fake session.
    19 Nov: the old `session is requests` check went False once HTTP became the default, so Threads never got our
    signed link and failed on Instagram's CDN link ("could not process the video: UNKNOWN")."""
    return session is requests or session is HTTP


def share_link(video: Path, hours: float = 2.0):
    """A signed, short-lived public link to one video (owner, 17 Nov: Instagram stopped posting). Instagram API with
    Instagram/unified login takes only a public video_url; direct upload (rupload) answers ProcessingFailedError.
    The file goes to the private "share" release; the Worker streams it for `hours`. Returns (url, cleanup) or None."""
    import hashlib
    import hmac
    import uuid
    key = os.environ.get("TG_WEBHOOK_SECRET")
    if not key or os.environ.get("IG_VIDEO_URL", "on") == "off":
        return None
    try:
        from .cloud.store import Store
        st = Store()
        name = f"{uuid.uuid4().hex}.mp4"
        asset = st.put(SHARE_TAG, name, Path(video).read_bytes(), "video/mp4")
    except Exception:  # noqa: BLE001 - no cloud store here: the old upload is tried
        return None
    exp = int(time.time() + hours * 3600)
    sig = hmac.new(("media:" + key).encode(), f"{asset['id']}.{exp}".encode(), hashlib.sha256).hexdigest()

    def cleanup():
        try:
            st.delete(SHARE_TAG, name)
        except Exception:  # noqa: BLE001 - a leftover copy is harmless (the link expires)
            pass
    return f"{WORKER_URL}/v/{asset['id']}/{exp}/{sig}", cleanup


def _ig_container(host: str, ig: str, tok: str, video: Path, params: dict, session=HTTP):
    """Create the media container: public link first (works for every login type), direct upload as the fallback.
    Returns (container id or None, error text, cleanup)."""
    link = share_link(video) if _live(session) else None
    if link:
        url, cleanup = link
        c = session.post(f"{host}/{ig}/media", data=dict(params, video_url=url), timeout=60).json()
        if c.get("id"):
            return c["id"], "", cleanup
        cleanup()
        return None, _meta_err(c), lambda: None
    c = session.post(f"{host}/{ig}/media", data=dict(params, upload_type="resumable"), timeout=60).json()
    if not c.get("id"):
        return None, _meta_err(c), lambda: None
    data = Path(video).read_bytes()
    up = session.post(c.get("uri") or f"{RUPLOAD}/ig-api-upload/{META_VERSION}/{c['id']}",
                      headers={"Authorization": f"OAuth {tok}", "offset": "0", "file_size": str(len(data))},
                      data=data, timeout=600)
    if (getattr(up, "status_code", 200) or 200) >= 400:
        return None, f"upload failed (HTTP {up.status_code}): {str(getattr(up, 'text', ''))[:200]}", lambda: None
    return c["id"], "", lambda: None


def instagram_reel(channel_id: str, video: Path, caption: str, trial: bool = False, session=HTTP,
                   dry_run: bool = True, poll_s: float = 5.0, item_id: str = "", ai: bool = False,
                   paid: bool = False) -> Action:
    act = Action("instagram", channel_id, item_id, f"publish Reel {video.name}" + (" as Trial Reel" if trial else ""),
                 details={"caption_hashtags": caption.count("#")})
    creds = None if dry_run else meta_creds(channel_id)
    if not creds:
        act.details["dry_run"] = True
        _log(act)
        return act
    ig, tok = creds["ig_user_id"], creds["access_token"]
    host = IG_GRAPH if creds.get("login") == "instagram" else GRAPH
    lim = session.get(f"{host}/{ig}/content_publishing_limit", params={"fields": "quota_usage,config",
                                                                         "access_token": tok}, timeout=30).json()
    usage = ((lim.get("data") or [{}])[0]).get("quota_usage", 0)
    if usage >= 50:                                            # stay far below the 100/day cap
        act.result = {"error": f"publishing limit guard: {usage} posts in the last 24 h"}
        _log(act)
        return act
    from .reach_gate import cap_hashtags
    caption = cap_hashtags(caption, IG_MAX_TAGS)                 # Instagram: max 5 hashtags since 18 Dec 2025
    params = {"media_type": "REELS", "caption": caption[:2200], "access_token": tok}
    if ai:
        params["is_ai_generated"] = "true"                        # "AI info" label (Meta, 22 June 2026)
    if paid:
        params["is_paid_partnership"] = "true"                    # "Paid partnership" label (Meta, 22 April 2026)
    if trial:
        params["trial_params"] = json.dumps({"graduation_strategy": "MANUAL"})
    cid, err, cleanup = _ig_container(host, ig, tok, video, params, session)
    if not cid:
        act.result = {"error": "Instagram refused the Reel: " + err}
        _log(act)
        return act
    finished = False
    for _ in range(120):
        st = session.get(f"{host}/{cid}", params={"fields": "status_code", "access_token": tok}, timeout=30).json()
        if st.get("status_code") == "FINISHED":
            finished = True
            break
        if st.get("status_code") == "ERROR":
            cleanup()
            act.result = {"error": "Instagram could not process the video"}
            _log(act)
            return act
        time.sleep(poll_s)
    if not finished:
        cleanup()
        act.result = {"error": "Instagram was still processing the video after 10 minutes"}
        _log(act)
        return act
    pub = session.post(f"{host}/{ig}/media_publish", data={"creation_id": cid, "access_token": tok}, timeout=60).json()
    cleanup()
    if not pub.get("id"):
        act.result = {"error": "Instagram didn't publish: " + _meta_err(pub)}
        _log(act)
        return act
    act.done, act.result = True, {"media_id": pub.get("id")}
    _log(act)
    return act


def story_clip(video: Path, out: Path, seconds: float = 15.0, banner: str = "NEW VIDEO  |  TAP OUR PROFILE") -> Path:
    """A Story teaser from a finished Reel (owner, 14 Nov: "stories for all the channel posts"): the first 15 s,
    9:16, with a banner. The Stories API can't add link stickers, so the banner sends people to the profile."""
    from .media import ffmpeg
    font = (ROOT / "assets" / "fonts" / "Anton-Regular.ttf").as_posix().replace(":", "\\:")
    txt = banner.replace(":", "\\:").replace("'", "")
    vf = ("scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black,"
          "drawbox=x=0:y=150:w=iw:h=150:color=black@0.65:t=fill,"
          f"drawtext=fontfile='{font}':text='{txt}':fontcolor=white:fontsize=64:x=(w-text_w)/2:y=190")
    ffmpeg.run(["-i", str(video), "-t", f"{seconds:.1f}", "-vf", vf, "-c:v", "libx264", "-preset", "veryfast",
                "-crf", "21", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(out)])
    return out


def instagram_story(channel_id: str, video: Path, session=HTTP, dry_run: bool = True, poll_s: float = 5.0,
                    item_id: str = "") -> Action:
    """Publish a video Story (Content Publishing API, media_type=STORIES; professional accounts)."""
    act = Action("instagram", channel_id, item_id, f"publish Story {video.name}")
    creds = None if dry_run else meta_creds(channel_id)
    if not creds:
        act.details["dry_run"] = True
        _log(act)
        return act
    ig, tok = creds["ig_user_id"], creds["access_token"]
    host = IG_GRAPH if creds.get("login") == "instagram" else GRAPH
    cid, err, cleanup = _ig_container(host, ig, tok, video, {"media_type": "STORIES", "access_token": tok}, session)
    if not cid:
        act.result = {"error": "Instagram refused the Story: " + err}
        _log(act)
        return act
    for _ in range(60):
        st = session.get(f"{host}/{cid}", params={"fields": "status_code", "access_token": tok}, timeout=30).json()
        if st.get("status_code") == "FINISHED":
            break
        if st.get("status_code") == "ERROR":
            cleanup()
            act.result = {"error": "Instagram could not process the Story"}
            _log(act)
            return act
        time.sleep(poll_s)
    pub = session.post(f"{host}/{ig}/media_publish", data={"creation_id": cid, "access_token": tok}, timeout=60).json()
    cleanup()
    act.done = bool(pub.get("id"))
    act.result = {"media_id": pub.get("id")} if act.done else {"error": "Story not published: " + _meta_err(pub)}
    _log(act)
    return act


def facebook_reel(channel_id: str, video: Path, description: str, session=HTTP, dry_run: bool = True,
                  item_id: str = "") -> Action:
    act = Action("facebook", channel_id, item_id, f"cross-post Reel {video.name} to the Facebook Page")
    creds = None if dry_run else meta_creds(channel_id)
    if not creds or not creds.get("page_id") or (creds.get("login") == "instagram" and not creds.get("page_token")):
        act.details["dry_run"] = True                          # no Facebook Page connected: Instagram only
        _log(act)
        return act
    page, tok = creds["page_id"], creds.get("page_token") or creds["access_token"]
    start = session.post(f"{GRAPH}/{page}/video_reels", data={"upload_phase": "start", "access_token": tok}, timeout=60).json()
    if not start.get("video_id"):
        act.result = {"error": "Facebook refused the Reel: " + _meta_err(start)}
        _log(act)
        return act
    vid = start["video_id"]
    with open(video, "rb") as fh:
        data = fh.read()
    session.post(f"{RUPLOAD}/video-upload/{META_VERSION}/{vid}", headers={"Authorization": f"OAuth {tok}", "offset": "0",
                                                                  "file_size": str(len(data))}, data=data, timeout=600)
    fin = session.post(f"{GRAPH}/{page}/video_reels", data={"upload_phase": "finish", "video_id": vid,
                                                            "video_state": "PUBLISHED", "description": description,
                                                            "access_token": tok}, timeout=60).json()
    if not fin.get("success"):
        act.result = {"error": "Facebook didn't publish: " + _meta_err(fin), "video_id": vid}
        _log(act)
        return act
    act.done, act.result = True, {"video_id": vid, "success": True}
    _log(act)
    return act


def _meta_err(resp: dict) -> str:
    e = (resp or {}).get("error") or {}
    return str(e.get("error_user_msg") or e.get("message") or resp)[:200]


# ---------- Dailymotion (API v2, private API key from Dailymotion Studio) ----------
DM_API = "https://api.dailymotion.com/v2"
DM_TOKEN = "https://oauth2.dailymotion.com/v2/token"
_DM_TOKENS: dict = {}


def dm_creds(channel_id: str) -> dict | None:
    """data/secrets/dailymotion_<channel>.json, or one shared data/secrets/dailymotion.json with "profiles":
    {channel: profile_id}. Fields: client_id, client_secret, profile_id."""
    p = SECRETS / f"dailymotion_{channel_id}.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    shared = SECRETS / "dailymotion.json"
    if shared.exists():
        rec = json.loads(shared.read_text(encoding="utf-8"))
        prof = (rec.get("profiles") or {}).get(channel_id)
        if prof:
            return {**rec, "profile_id": prof}
    return None


def _dm_token(creds: dict, session=HTTP) -> str:
    key = creds["client_id"]
    tok = _DM_TOKENS.get(key)
    if tok and tok[1] > time.time() + 60:
        return tok[0]
    r = session.post(DM_TOKEN, data={"grant_type": "client_credentials", "client_id": creds["client_id"],
                                     "client_secret": creds["client_secret"],
                                     "scope": "video.read video.upload video.write"}, timeout=30)
    r.raise_for_status()
    d = r.json()
    _DM_TOKENS[key] = (d["access_token"], time.time() + float(d.get("expires_in") or 3600))
    return d["access_token"]


def dm_hashtags(tags: list) -> list[str]:
    """Dailymotion hashtags as its API documents them: each with a leading '#' (example "#hello, #world"), letters,
    digits and underscores only, at most 10. 20-21 Nov: tags sent without '#' ("ThePlay", "LakePeigneur") were refused
    with INVALID_HASHTAGS on every story channel; Brain Snack, which sends none, uploaded fine."""
    out = []
    for t in tags:
        core = re.sub(r"[^0-9A-Za-z_]", "", str(t).lstrip("#"))
        if core and f"#{core}" not in out:
            out.append(f"#{core}")
    return out[:10]


def dailymotion_upload(channel_id: str, video: Path, meta: dict, item_id: str = "", session=HTTP,
                       dry_run: bool = True) -> Action:
    """Our own video on Dailymotion: upload session -> file -> create the public video with the right labels."""
    act = Action("dailymotion", channel_id, item_id, f"upload {video.name}")
    creds = None if dry_run else dm_creds(channel_id)
    if not creds:
        act.details["dry_run"] = True
        _log(act)
        return act
    h = {"Authorization": f"Bearer {_dm_token(creds, session)}"}
    us = session.post(f"{DM_API}/files/upload_sessions", headers=h, timeout=60)
    up_url = (us.json() or {}).get("upload_url") if us.ok else None
    if not up_url:
        act.result = {"error": f"Dailymotion refused the upload session (HTTP {us.status_code})"}
        _log(act)
        return act
    with open(video, "rb") as fh:
        up = session.post(up_url, files={"file": (video.name, fh, "video/mp4")}, timeout=3600)
    file_url = (up.json() or {}).get("url") if up.ok else None
    if not file_url:
        act.result = {"error": f"Dailymotion file upload failed (HTTP {up.status_code})"}
        _log(act)
        return act
    title = str(meta.get("title") or "").replace("<", "").replace(">", "")[:255] or "New video"
    body = {"title": title, "description": str(meta.get("description") or "")[:3000], "visibility": "public",
            "is_for_kids": bool(meta.get("made_for_kids")), "is_ai_altered": bool(meta.get("ai_label")),
            "has_paid_partnership": bool(meta.get("campaign")),
            "hashtags": dm_hashtags(meta.get("hashtags") or []), "source": {"file_url": file_url}}
    r = session.post(f"{DM_API}/profiles/{creds['profile_id']}/videos", headers={**h, "Content-Type": "application/json"},
                     data=json.dumps(body), timeout=60)
    d = r.json() if r.content else {}
    vid = d.get("id") or d.get("xid") or d.get("video_id")     # 18 Nov: the profile API answers with video_id
    if r.status_code >= 400 or not vid:
        act.result = {"error": f"Dailymotion didn't create the video: {str(d)[:500]}"}   # the reason was cut at 200
        _log(act)
        return act
    act.done, act.result = True, {"video_id": vid}
    _log(act)
    return act


# ---------- the approved week ----------

def item_meta(it: dict) -> dict:
    """Upload metadata for a plan item. Clips have no upload.json: their title, caption (credit + campaign tags)
    and permission live in clips.json."""
    out = Path(it["out_dir"])
    if (out / "upload.json").exists():
        meta = json.loads((out / "upload.json").read_text(encoding="utf-8"))
        if it.get("product") and not meta.get("made_for_kids"):    # 20 Nov: value-first promo Short of our product
            try:
                from .product_promo import description_line
                line = description_line(it)
                if line and line.strip() not in str(meta.get("description") or ""):
                    meta["description"] = str(meta.get("description") or "").rstrip() + line
            except Exception as e:  # noqa: BLE001 - the video posts without the shop line
                print(f"promo line skipped for {it.get('id')}: {type(e).__name__}: {e}")
        return meta
    cj = out / "clips.json"
    if cj.exists():
        for c in json.loads(cj.read_text(encoding="utf-8")):
            if c.get("file") == it.get("file"):
                hooks = [h for h in (c.get("hook_options") or []) if h]
                return {"title": c.get("title") or (hooks[0] if hooks else it.get("channel_name")),
                        "title_options": hooks, "description": c.get("caption", ""), "format": "short",
                        "hashtags": [t for t in c.get("caption", "").split() if t.startswith("#")][:8],
                        "made_for_kids": False, "ai_label": False, "permission": c.get("permission"),
                        "campaign": c.get("campaign"), "rule_check": c.get("rule_check"), "clip": True}
    return {"title": it.get("topic") or it["channel_name"], "format": "short"}


def _duration(video: Path) -> float:
    try:
        from .media import ffmpeg
        return ffmpeg.duration(video)
    except Exception:  # noqa: BLE001
        return 0.0


def fb_posts_last_24h(channel_id: str) -> int:
    if not LOG.exists():
        return 0
    cutoff, n = time.time() - 86400, 0
    for ln in LOG.read_text(encoding="utf-8").splitlines():
        try:
            a = json.loads(ln)
        except json.JSONDecodeError:
            continue
        if a.get("platform") == "facebook" and a.get("channel") == channel_id and a.get("done") and a.get("at", 0) > cutoff:
            n += 1
    return n


def _safe(fn, platform: str, channel_id: str, item_id: str, what: str) -> Action:
    """Run one platform post; any error becomes a logged, readable result (never a crash)."""
    try:
        return fn()
    except Exception as e:  # noqa: BLE001
        act = Action(platform, channel_id, item_id, what)
        act.result = {"error": f"{type(e).__name__}: {str(e)[:200]}"}
        _log(act)
        return act


def upload_item(it: dict, dry_run: bool = True, session=HTTP, platforms=("youtube", "instagram", "facebook"),
                publish_at: str | None = "item") -> list[Action]:
    """Uploads ONE owner-approved plan item to the chosen platforms (safety checks first). publish_at="item" keeps
    the item's own time (YouTube schedules it); None posts now."""
    out = Path(it["out_dir"])
    meta = item_meta(it)
    meta["_item"] = it["id"]
    when = it["publish_at"] if publish_at == "item" else publish_at
    actions = []
    fc = meta.get("fact_check") or {}
    if fc.get("checked") and not fc.get("ok"):         # safety net: never upload a failed fact-check
        act = Action("youtube", it["channel"], it["id"], "SKIPPED: fact-check failed — fix the script first", when or "",
                     {"problems": fc.get("problems", [])[:3]})
        act.result = {"error": "fact-check failed"}
        _log(act)
        return [act]
    if meta.get("clip") and not (meta.get("permission") or {}).get("basis"):
        act = Action("youtube", it["channel"], it["id"], "SKIPPED: clip has no permission record", when or "", {})
        act.result = {"error": "no permission record"}
        _log(act)
        return [act]
    if meta.get("policy_flags"):                       # owner's never-topics list
        act = Action("youtube", it["channel"], it["id"], "SKIPPED: touches a never-topic: "
                     + ", ".join(meta["policy_flags"]), when or "", {})
        act.result = {"error": "never-topic"}
        _log(act)
        return [act]
    video = out / (it.get("file") or "video.mp4")
    if not dry_run:
        # 20 Nov (owner: "nothing should bypass these gates"): every real upload passes the content gate, per
        # platform, right here (the queue, the approval-time YouTube schedule and every repost path call this).
        from . import content_gate
        try:
            base = content_gate.base_problems(it)
        except Exception as e:  # noqa: BLE001 - a gate that cannot run blocks
            base = [f"content gate could not run ({type(e).__name__}: {str(e)[:80]})"]
        keep = []
        for p in platforms:
            try:
                probs = content_gate.verify(it, p, _base=base)
            except Exception as e:  # noqa: BLE001
                probs = [f"content gate could not run ({type(e).__name__}: {str(e)[:80]})"]
            if probs:
                act = Action(p, it["channel"], it["id"], "BLOCKED by the content gate", when or "",
                             {"problems": probs[:6]})
                act.result = {"error": content_gate.summary(probs)}
                _log(act)
                actions.append(act)
            else:
                keep.append(p)
        platforms = tuple(keep)
        if not platforms:
            return actions
    if it.get("role") == "spoke" and it.get("hub"):           # topic cluster: the Short points to its full story
        link = _hub_link(it)
        meta["description"] = (str(meta.get("description") or "").rstrip() + "\n\n▶ The full story on this channel: "
                               + str(it["hub"])[:90] + (f" {link}" if link else ""))
    from .platforms import allowed as _allowed, campaign_allows as _campaign_ok
    try:
        from .config import channel as _get_channel
        _ch = _get_channel(it["channel"])
    except Exception:  # noqa: BLE001
        _ch = {"id": it["channel"], "type": "story"}
    for p in [p for p in platforms if p != "youtube" and not _allowed(_ch, p, meta)]:
        act = Action(p, it["channel"], it["id"], f"SKIPPED: not for {p} (kids rule, campaign platforms or channel list)")
        act.details["dry_run"] = True                     # informational, not an error
        actions.append(act)
    platforms = tuple(p for p in platforms if p == "youtube" or _allowed(_ch, p, meta))
    if "youtube" in platforms and not _campaign_ok("youtube", meta):     # the brief doesn't license YouTube
        act = Action("youtube", it["channel"], it["id"], "SKIPPED: not for youtube (campaign brief)")
        act.details["dry_run"] = True
        actions.append(act)
        platforms = tuple(p for p in platforms if p != "youtube")
    if "youtube" in platforms:
        up = _safe(lambda: youtube_upload(it["channel"], video, meta, when, session=session, dry_run=dry_run),
                   "youtube", it["channel"], it["id"], f"upload {video.name}")
        actions.append(up)
        vid = (up.result or {}).get("video_id") if up.done else None
        if vid and meta.get("captions_file"):
            lang = "hi" if (meta.get("language") or ch_lang(it["channel"])) == "hi" else "en"
            cfile = Path(meta["captions_file"])
            cfile = cfile if cfile.is_absolute() else out / cfile        # kids write "captions.srt" (relative)
            actions.append(_safe(lambda: youtube_captions(it["channel"], vid, cfile, lang,
                                                          session=session, dry_run=dry_run),
                                 "youtube", it["channel"], "", "captions"))
        thumbs = [Path(t) for t in meta.get("thumbnails") or []] or sorted(out.glob("thumbnail_v2*.jpg"))
        if vid and meta.get("format") == "long" and thumbs:
            actions.append(_safe(lambda: youtube_thumbnail(it["channel"], vid, thumbs[0], session=session,
                                                           dry_run=dry_run), "youtube", it["channel"], "", "thumbnail"))
        cover = next((out / n for n in ("cover_vertical.jpg", "cover.jpg") if (out / n).exists()), None)
        if vid and not dry_run and meta.get("format") != "long" and cover and not meta.get("clip"):
            queue_short_thumbnail(it["channel"], vid, cover)      # set after YouTube finishes processing
        if vid and not dry_run and not meta.get("clip"):            # binge: every video joins its channel playlist
            def _to_playlist():
                pid = ensure_playlist(it["channel"], playlist_title(it["channel"], meta.get("format") or "short"),
                                      session=session)
                if not pid:
                    a = Action("youtube", it["channel"], "", "playlist skipped (quota or login)")
                    a.details["dry_run"] = True
                    return a
                res = youtube_add_to_playlist(it["channel"], vid, pid, session=session, dry_run=False)
                if meta.get("format") == "long" and _allowed(_ch, "youtube_podcasts", meta):
                    try:
                        ensure_podcast(it["channel"], pid, session=session)
                    except Exception:  # noqa: BLE001 - the video is in the playlist either way
                        pass
                return res
            actions.append(_safe(_to_playlist, "youtube", it["channel"], "", "playlist"))
    reel = out / "reel.mp4"
    clip_reel = out / (it.get("file") or "").replace(".mp4", "_reel.mp4")
    reel_file = reel if reel.exists() else clip_reel if clip_reel.exists() else None
    if reel_file is None and meta.get("format", "short") != "long" and it.get("kind") != "long" and video.exists():
        reel_file = video                                   # Shorts are 9:16 already
    if reel_file and not meta.get("made_for_kids"):       # Made for Kids never goes to Instagram/Facebook (13+)
        rj = reel_file.with_suffix(".json") if reel_file.name != "reel.mp4" else out / "reel.json"
        if rj.exists() and rj.name != "upload.json":
            cap = json.loads(rj.read_text(encoding="utf-8")).get("caption", "")
        else:
            cap = meta.get("description") or meta.get("title", "")
        dur = _duration(reel_file)
        if "instagram" in platforms:
            if dur > 900:
                act = Action("instagram", it["channel"], it["id"], "SKIPPED: Reel longer than 15 minutes")
                act.result = {"error": "Instagram API limit is 15 minutes"}
                actions.append(act)
            else:
                actions.append(_safe(lambda: instagram_reel(it["channel"], reel_file, cap, trial=False, session=session,
                                                            dry_run=dry_run, item_id=it["id"],
                                                            ai=bool(meta.get("ai_label")),
                                                            paid=bool(meta.get("campaign"))),
                                     "instagram", it["channel"], it["id"], f"publish Reel {reel_file.name}"))
                ig_ok = next((a for a in actions if a.platform == "instagram" and a.done), None)
                if ig_ok or dry_run:                     # every posted Reel also gets a Story teaser (more reach)
                    def _story():
                        teaser = reel_file.with_name("story_teaser.mp4")
                        if not dry_run:                  # a dry run only plans it
                            story_clip(reel_file, teaser)
                        return instagram_story(it["channel"], teaser, session=session, dry_run=dry_run,
                                               item_id=it["id"])
                    actions.append(_safe(_story, "instagram", it["channel"], it["id"], "publish Story teaser"))
        if "threads" in platforms:                       # Threads takes the Reel's own Instagram video link
            ig = next((a for a in actions if a.platform == "instagram" and a.done), None)
            media_id = (ig.result or {}).get("media_id") if ig else logged_result(it, "instagram", "media_id")
            if dry_run:     # 20 Nov: Threads is its own queue job; our signed link needs no Instagram post
                act = Action("threads", it["channel"], it["id"], "Threads follows the Instagram Reel (not posted there)")
                act.details["dry_run"] = True
                actions.append(act)
            else:
                yt_id = it.get("youtube_id") or next(((a.result or {}).get("video_id") for a in actions
                                                      if a.platform == "youtube" and a.done
                                                      and (a.result or {}).get("video_id")), None)

                def _threads():
                    # 18 Nov: Threads answered "could not process the video: UNKNOWN" for Instagram's CDN link.
                    # Our own signed link (the one that fixed Instagram) first; the CDN link only as the fallback.
                    from .threads import creds, ig_video_url, post_video, text_for
                    text = text_for(meta, yt_id)
                    if not creds(it["channel"]):
                        # 24 Nov: a channel with no Threads account only plans the post (like Instagram does);
                        # it used to fall through to "Instagram gave no video link" and queue a high heal item
                        return post_video(it["channel"], "", text, session=session, dry_run=True, item_id=it["id"])
                    link = share_link(reel_file) if _live(session) else None
                    if link:
                        url, cleanup = link
                        try:
                            a = post_video(it["channel"], url, text, session=session, dry_run=False, item_id=it["id"])
                        finally:
                            cleanup()
                        if a.done:
                            return a
                    url = ig_video_url(it["channel"], media_id, session=session) if media_id else None
                    if not url:
                        a = Action("threads", it["channel"], it["id"], "publish Threads video")
                        a.result = {"error": "Instagram gave no video link to pass on to Threads"}
                        _log(a)
                        return a
                    return post_video(it["channel"], url, text, session=session, dry_run=False, item_id=it["id"])
                actions.append(_safe(_threads, "threads", it["channel"], it["id"], "publish Threads video"))
        if "facebook" in platforms:
            if dur and not 3 <= dur <= 90:                       # Facebook Reels API: 3-90 s, 9:16
                act = Action("facebook", it["channel"], it["id"], "SKIPPED: Facebook Reels must be 3-90 seconds")
                act.result = {"error": f"Reel is {dur:.0f} s"}
                actions.append(act)
            elif not dry_run and fb_posts_last_24h(it["channel"]) >= 25:   # API cap is 30 per Page per 24 h
                act = Action("facebook", it["channel"], it["id"], "SKIPPED: Facebook daily Reels limit guard")
                act.result = {"error": "25 Reels already posted on this Page in 24 h"}
                actions.append(act)
            else:
                actions.append(_safe(lambda: facebook_reel(it["channel"], reel_file, cap, session=session,
                                                           dry_run=dry_run, item_id=it["id"]),
                                     "facebook", it["channel"], it["id"], f"Reel {reel_file.name}"))
    if "telegram" in platforms and video.exists():
        actions.append(_safe(lambda: telegram_channel_post(it["channel"], video, meta, it.get("youtube_id"),
                                                           item_id=it["id"], dry_run=dry_run),
                             "telegram", it["channel"], it["id"], f"post {video.name}"))
    if "dailymotion" in platforms and video.exists():
        actions.append(_safe(lambda: dailymotion_upload(it["channel"], video, meta, item_id=it["id"], session=session,
                                                        dry_run=dry_run),
                             "dailymotion", it["channel"], it["id"], f"upload {video.name}"))
    return actions


def _hub_link(it: dict) -> str:
    """The long video (hub) of this Short's topic cluster, if it is already on YouTube."""
    try:
        from .autopilot import items
        for _, x in items(14, 14):
            if x.get("channel") == it.get("channel") and x.get("role") == "hub" and x.get("topic") == it.get("hub") \
                    and x.get("youtube_id"):
                return f"https://youtu.be/{x['youtube_id']}"
    except Exception:  # noqa: BLE001
        pass
    return ""


def plan_uploads(week: str | None = None, dry_run: bool = True, session=HTTP) -> list[Action]:
    """Turns the owner's APPROVED items of a week into upload actions (dry run unless dry_run=False)."""
    from . import weekly
    week = week or weekly.latest_week()
    if not week:
        return []
    actions = []
    for it in weekly.approved_items(week):
        actions += upload_item(it, dry_run=dry_run, session=session)
    return actions
