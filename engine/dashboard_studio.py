"""Per-channel "Studio" for the dashboard (owner 18 Nov: "each channel menu should be like the YouTube Studio:
insights and video upload, changes, approval and similar operations").

Two cards on every channel page:
- Insights: views per day (28 days), per-video table (views, likes, stayed to watch, average % viewed, what the
  retention curve taught), totals per platform.
- Content: every planned / made / posted video of the channel with its picture, slot and status, and the buttons:
  Approve, Upload now, Change, Reject, Make now. A tap goes to the Worker (cmd), the PC stand-in or the cloud does
  it, and the answer appears under the video (res). Buttons only work on the live link (/d?k=...); the offline
  file (Telegram) shows the same page read-only.
"""
from __future__ import annotations

import html
import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import ROOT

IST = ZoneInfo("Asia/Kolkata")
PLAT = {"youtube": "▶️", "instagram": "📸", "facebook": "📘", "dailymotion": "🎞", "threads": "🧵", "telegram": "✈️"}


def _e(x) -> str:
    return html.escape(str(x if x is not None else ""))


def _num(n) -> str:
    if n is None:
        return "-"
    n = float(n)
    for div, suf in ((1e6, "M"), (1e3, "K")):
        if abs(n) >= div:
            return f"{n / div:.1f}{suf}".replace(".0", "")
    return f"{n:,.0f}"


def video_rows(cid: str, limit: int = 15) -> list[dict]:
    """Latest snapshot per (video, platform) for one channel, live counters on top, newest first."""
    db = ROOT / "data" / "analytics.db"
    rows: dict[tuple, dict] = {}
    if db.exists():
        try:
            with sqlite3.connect(db) as c:
                q = ("SELECT m.item_id, m.platform, m.video_id, m.hook, m.topic, m.format, m.posted_at, m.views, "
                     "m.likes, m.comments, m.shares, m.stayed_pct, m.avg_pct_viewed FROM video_metrics m JOIN "
                     "(SELECT item_id, platform, MAX(hours_after) h FROM video_metrics WHERE channel = ? GROUP BY "
                     "item_id, platform) l ON m.item_id = l.item_id AND m.platform = l.platform AND m.hours_after = l.h "
                     "WHERE m.channel = ?")
                for r in c.execute(q, (cid, cid)).fetchall():
                    rows[(r[0], r[1])] = {"item": r[0], "platform": r[1], "video_id": r[2], "title": r[3] or r[4] or r[0],
                                          "format": r[5], "posted": r[6], "views": r[7] or 0, "likes": r[8] or 0,
                                          "comments": r[9] or 0, "shares": r[10] or 0, "stayed": r[11], "pct": r[12]}
                lessons = dict(c.execute("SELECT item_id, lesson FROM retention WHERE channel = ?", (cid,)).fetchall())
        except sqlite3.Error:
            lessons = {}
    else:
        lessons = {}
    try:
        from .stats_fetch import live_stats
        for vid, v in (live_stats().get("videos") or {}).items():
            if v.get("channel") != cid:
                continue
            k = (str(v.get("item") or vid), "youtube")
            r = rows.setdefault(k, {"item": k[0], "platform": "youtube", "video_id": vid, "title": v.get("title") or vid,
                                    "format": v.get("format"), "posted": v.get("posted_at"), "views": 0, "likes": 0,
                                    "comments": 0, "shares": 0, "stayed": None, "pct": None})
            r["views"] = max(float(r["views"] or 0), float(v.get("views") or 0))
            r["likes"] = max(float(r["likes"] or 0), float(v.get("likes") or 0))
            r["video_id"] = r.get("video_id") or vid
    except Exception:  # noqa: BLE001 - live counters are a bonus
        pass
    out = sorted(rows.values(), key=lambda r: r.get("posted") or 0, reverse=True)[:limit]
    for r in out:
        r["lesson"] = lessons.get(r["item"]) or ""
    return out


def _bars(series: list[float]) -> str:
    """28-day views chart (SVG bars, date under every 7th)."""
    if not series:
        return "<p class=muted>No views yet.</p>"
    top = max(series) or 1
    w, h, n = 560, 120, len(series)
    bw = w / n
    today = datetime.now(IST).date()
    bars, labels = [], []
    for i, v in enumerate(series):
        bh = max(1.0, (v / top) * (h - 22))
        x = i * bw
        bars.append(f"<rect x='{x + 1:.1f}' y='{h - 18 - bh:.1f}' width='{bw - 2:.1f}' height='{bh:.1f}' rx='2'>"
                    f"<title>{today - timedelta(days=n - 1 - i):%d %b}: {_num(v)} views</title></rect>")
        if (n - 1 - i) % 7 == 0:
            labels.append(f"<text x='{x + bw / 2:.1f}' y='{h - 4}' text-anchor='middle'>"
                          f"{today - timedelta(days=n - 1 - i):%d %b}</text>")
    return (f"<svg class=sbars viewBox='0 0 {w} {h}' preserveAspectRatio='none'>{''.join(bars)}{''.join(labels)}</svg>"
            f"<div class=muted>Last 28 days: <b>{_num(sum(series))}</b> views · best day {_num(top)}</div>")


def lessons_html(cid: str, ctx: dict) -> str:
    """What the numbers taught us and what changes in the next videos (owner 19 Nov: "no improvements from the
    analytics"): the end-of-day review's keep / change rules per platform, and the content changes made from them."""
    blocks = []
    for f in sorted((ROOT / "data" / "reviews").glob(f"*/{cid}/insights.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        plat = f.parent.parent.name
        keep = "".join(f"<li class=good><span class=dot></span><span>{_e(x)}</span></li>" for x in d.get("keep", [])[:3])
        chg = "".join(f"<li class=warn><span class=dot></span><span>{_e(x)}</span></li>" for x in d.get("change", [])[:3])
        blocks.append(f"<h3>{PLAT.get(plat, '')} {_e(plat.title())} · review {_e(d.get('day', ''))}</h3>"
                      f"<p class=muted>{_e(d.get('verdict', ''))}</p><ul class=imp>{keep}{chg}</ul>")
    try:
        from .content_tuning import channel_notes
        notes = channel_notes(cid)
    except Exception:  # noqa: BLE001
        notes = []
    if notes:
        blocks.append("<h3>Changed in the next videos</h3><ul class=imp>" + "".join(
            f"<li class=good><span class=dot></span><span>{_e(n)}</span></li>" for n in notes) + "</ul>")
    if not blocks:
        posted = [it for it in ctx["items"] if it.get("channel") == cid and it.get("status") == "posted"]
        nxt = sorted((it.get("publish_at") or "") for it in ctx["items"] if it.get("channel") == cid
                     and it.get("status") in ("made", "approved", "scheduled"))
        why = ("No video has gone public on this channel yet, so there are no numbers to learn from."
               if not posted else "Too few views yet for a review (it needs a day of numbers).")
        blocks.append(f"<p class=muted>{why}" + (f" Next video ready for the slot {_e(nxt[0][:16].replace('T', ' '))}."
                                                 if nxt else "") + "</p>")
    return "<h3>🧠 What the numbers taught us</h3>" + "".join(blocks)


def insights_card(ch: dict, ctx: dict) -> str:
    cid = ch["id"]
    vids = video_rows(cid)
    per: dict[str, list[float]] = {}
    for r in vids:
        p = per.setdefault(r["platform"], [0, 0, 0])
        p[0] += 1
        p[1] += float(r["views"] or 0)
        p[2] += float(r["likes"] or 0)
    plat = "".join(f"<div class=kpi><small>{PLAT.get(k, '')} {_e(k.title())}</small><b>{_num(v[1])}</b>"
                   f"<div class=ksub>{v[0]} videos · {_num(v[2])} likes</div></div>" for k, v in per.items())
    rows = ""
    for r in vids:
        title = (f"<a href='https://youtu.be/{_e(r['video_id'])}' target=_blank>{_e(str(r['title'])[:80])}</a>"
                 if r["platform"] == "youtube" and r.get("video_id") else _e(str(r["title"])[:80]))
        when = f"{datetime.fromtimestamp(r['posted'], IST):%d %b}" if r.get("posted") else "-"
        stayed = f"{r['stayed']:.0f}%" if r.get("stayed") is not None else "-"
        pct = f"{r['pct']:.0f}%" if r.get("pct") is not None else "-"
        lesson = f"<div class=muted>{_e(r['lesson'][:140])}</div>" if r.get("lesson") else ""
        rows += (f"<tr><td>{PLAT.get(r['platform'], '')}</td><td class=topic>{title}{lesson}</td><td>{when}</td>"
                 + (f"<td data-live='vv:{_e(r['video_id'])}'>{_num(r['views'])}</td>"
                    f"<td data-live='vl:{_e(r['video_id'])}'>{_num(r['likes'])}</td>"
                    if r["platform"] == "youtube" and r.get("video_id") else
                    f"<td>{_num(r['views'])}</td><td>{_num(r['likes'])}</td>")
                 + f"<td>{stayed}</td><td>{pct}</td></tr>")
    table = (f"<div class=tw><table class=stack><tr><th></th><th>Video</th><th>Posted</th><th>Views</th><th>Likes</th>"
             f"<th>Stayed</th><th>Avg viewed</th></tr>{rows}</table></div>" if rows
             else "<p class=muted>No posted videos with numbers yet.</p>")
    return (f"<div class='card wide'><h2>📊 Insights</h2>"
            f"<h3>Latest on YouTube <span class='pill info'>live</span></h3><div class=livelist data-live-list='{cid}'>"
            "<p class=muted>Live numbers load when the page opens on your private link.</p></div>"
            f"<h3>Views per day</h3>{_bars(ctx['daily'].get(cid, []))}"
            f"{lessons_html(cid, ctx)}"
            f"<div class=kpis3>{plat}</div>{table}<p class=muted>Live counters from YouTube, Instagram, Facebook and "
            "Dailymotion, refreshed every 30 minutes. 'Stayed' = viewers still watching after the first seconds.</p>"
            "</div>")


BUTTONS = {          # owner 19 Nov: ready videos get the same buttons as the Telegram approval message
    "made": [("approve", "✅ Approve & post"), ("change", "✏️ Change"), ("reject", "❌ Reject"),
             ("upload", "🚀 Upload now")],
    "missed": [("approve", "✅ Approve (new slot)"), ("change", "✏️ Change"), ("reject", "❌ Reject")],
    "approved": [("upload", "🚀 Upload now"), ("reject", "❌ Cancel")],
    "scheduled": [("upload", "🚀 Upload now"), ("reject", "❌ Cancel")],
    "planned": [("make", "🎬 Make now")],
    "failed": [("make", "🎬 Try again")],
    "needs_source": [],
}
STATUS = {"planned": ("to be made", ""), "making": ("making now", "info"), "made": ("waiting for you", "warn"),
          "approved": ("approved", "good"), "scheduled": ("scheduled", "good"), "posted": ("posted", "good"),
          "rejected": ("rejected", "bad"), "redo": ("remaking", "warn"), "missed": ("missed", "bad"),
          "failed": ("failed", "bad"), "needs_source": ("needs footage", "warn")}
REVIEWABLE = ("made", "missed", "approved", "scheduled")


def _items_window(ctx: dict, cid: str, now: datetime, back: int = 3, ahead: int = 10) -> list[tuple[datetime, dict]]:
    mine = []
    for it in ctx["items"]:
        if it.get("channel") != cid:
            continue
        try:
            w = datetime.fromisoformat(it["publish_at"])
            w = w if w.tzinfo else w.replace(tzinfo=IST)
        except (KeyError, ValueError, TypeError):
            continue
        if now - timedelta(days=back) <= w <= now + timedelta(days=ahead):
            mine.append((w.astimezone(IST), it))
    mine.sort(key=lambda x: x[0])
    return mine


def _details(it: dict) -> str:
    """The same text the Telegram approval message carries (title options, hook, checks)."""
    try:
        from .autopilot import approval_text
        return approval_text(it).split("\n", 1)[1].rsplit("\n\n", 1)[0]
    except Exception:  # noqa: BLE001
        return ""


def _card(w: datetime, it: dict, poster, pv: dict) -> dict:
    from .pc_fallback import has_file
    st = it.get("status", "planned")
    label, cls = STATUS.get(st, (st, ""))
    local = has_file(it)
    btns = [(op, txt) for op, txt in BUTTONS.get(st, []) if local or op in ("make", "reject", "change")]
    note = ""
    if st in ("made", "missed", "approved") and not local:
        note = "File is in the cloud store (GitHub is down): make a PC version, or wait for GitHub."
        btns = ([("make", "🎬 Make a PC version")] if st == "made" else []) + [b for b in btns if b[0] == "reject"]
    if st == "failed" and it.get("error"):
        note = "Last try: " + str(it["error"]).split("\n")[0][:160]
    title = (it.get("meta") or {}).get("title") or it.get("title") or it.get("topic") or "topic picked when made"
    if local:
        try:
            up = json.loads((Path(it["out_dir"]) / "upload.json").read_text(encoding="utf-8"))
            title = up.get("title") or title
        except (OSError, ValueError, KeyError):
            pass
    pic = poster(Path(it["out_dir"]), it.get("file")) if (poster and local) else ""
    iid = _e(it["id"])
    shape = "ver" if it.get("kind") != "long" else "hor"
    if local and it["id"] in pv:
        player = f"<video class='spv {shape}' controls playsinline preload=none data-pv='{iid}' poster='{pic}'></video>"
    elif pic:
        wait = "Player ready after the next refresh (30 min)" if st in REVIEWABLE else ""
        player = f"<div class='spv {shape} still'><img src='{pic}' alt=''><span>{wait}</span></div>"
    else:
        player = f"<div class='spv {shape} still empty'><span>{_e(label)}</span></div>"
    yt = f" <a href='https://youtu.be/{_e(it['youtube_id'])}' target=_blank>▶ YouTube</a>" if it.get("youtube_id") else ""
    bhtml = "".join(f"<button class='sbtn op-{op}' onclick=\"hhAct('{op}','{iid}')\">{txt}</button>" for op, txt in btns)
    det = _details(it) if local and st in ("made", "missed") else ""
    det_html = (f"<details class=sdet><summary>Details (same as Telegram)</summary><pre>{_e(det)}</pre></details>"
                if det else "")
    head = (f"<div class=muted>{w:%a %d %b, %H:%M} IST · {_e(it.get('kind'))} · "
            f"<span class='pill {cls}'>{_e(label)}</span>{yt}</div>")
    note_html = f"<div class=muted>{_e(note)}</div>" if note else ""
    tail = f"<div class=sbtns>{bhtml}</div><div class=sres data-res='{iid}'></div>"
    card = (f"<div class='scard st-{_e(st)}' id='sc-{iid}'>{player}<div class=sbody><b>{_e(str(title)[:110])}</b>"
            f"{head}{note_html}{det_html}{tail}</div></div>")
    thumb = f"<img class=sthumb src='{pic}' alt=''>" if pic else ""
    row = f"<div class=srow>{thumb}<div class=sbody><b>{_e(str(title)[:100])}</b>{head}{note_html}{tail}</div></div>"
    chip = (f"<button class='cchip st-{_e(st)}' onclick=\"hhOpen('{iid}')\" title='{_e(str(title)[:80])}'>"
            f"{w:%H:%M} {_e(it.get('kind'))}</button>")
    return {"card": card, "row": row, "chip": chip, "day": w.date(), "status": st}


def content_card(ch: dict, ctx: dict, poster=None) -> str:
    """Content (owner 19 Nov): Cards (player + Telegram buttons), Calendar (two weeks) and List views."""
    cid = ch["id"]
    now = datetime.now(IST)
    try:
        from .pc_fallback import previews
        pv = previews()
    except Exception:  # noqa: BLE001
        pv = {}
    cards = [_card(w, it, poster, pv) for w, it in _items_window(ctx, cid, now)]
    order = {"made": 0, "missed": 1, "redo": 2, "making": 3, "approved": 4, "scheduled": 4, "failed": 5, "planned": 6}
    waiting = sum(1 for c in cards if c["status"] in ("made", "missed"))
    empty = "<p class=muted>Nothing planned in the next 10 days.</p>"
    grid = "".join(c["card"] for c in sorted(cards, key=lambda c: order.get(c["status"], 7))) or empty
    rows = "".join(c["row"] for c in cards) or empty
    first = (now - timedelta(days=now.weekday())).date()            # Monday of this week, two weeks shown
    cells = ""
    for i in range(14):
        d = first + timedelta(days=i)
        chips = "".join(c["chip"] for c in cards if c["day"] == d)
        cls = (" today" if d == now.date() else "") + (" past" if d < now.date() else "")
        cells += f"<div class='cday{cls}'><div class=cdh>{d:%a %d %b}</div>{chips}</div>"
    heads = "".join(f"<div class=cwh>{x}</div>" for x in ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"))
    cal = (f"<div class=cal>{heads}{cells}</div><p class=muted>Tap a video to watch it and approve, change or reject. "
           "<span class='pill warn'>waiting for you</span> <span class='pill good'>approved / posted</span> "
           "<span class='pill bad'>failed / missed</span> <span class=pill>to be made</span></p>")
    badge = f" <span class='pill warn'>{waiting} waiting for you</span>" if waiting else ""
    return (f"<div class='card wide sstudio' data-cid='{cid}'><h2>🎬 Content{badge}<button class='sbtn' "
            "style='float:right' onclick=\"hhAct('refresh','')\">🔄 Refresh numbers</button></h2>"
            "<div class=svtabs><button data-v=cards class=on>🗂 Cards</button><button data-v=cal>📅 Calendar</button>"
            "<button data-v=list>☰ List</button></div>"
            f"<div class=sview data-v=cards><div class=sgrid>{grid}</div></div>"
            f"<div class=sview data-v=cal hidden>{cal}</div>"
            f"<div class=sview data-v=list hidden>{rows}</div>"
            "<div class=sres data-res=''></div>"
            "<p class=muted hh-off>Buttons and the player work on your private live link (Telegram: Dashboard link). "
            "This copy is read-only.</p></div>")


CSS = """
.sbars{width:100%;height:120px;display:block}.sbars rect{fill:var(--acc)}.sbars text{fill:var(--mut);font-size:9px}
.srow{display:flex;gap:12px;padding:10px 0;border-top:1px solid var(--line)}.sbody{flex:1;min-width:0}
.sthumb{width:64px;height:110px;object-fit:cover;border-radius:8px;flex:none;background:#0c0f15}
.sbtns{display:flex;flex-wrap:wrap;gap:6px;margin-top:6px}
.sbtn{background:var(--panel2);color:var(--text);border:1px solid var(--line);border-radius:8px;padding:7px 11px;
font-size:13px;cursor:pointer}.sbtn:hover{border-color:var(--acc)}.sbtn.op-upload{border-color:#2f7d4f}
.sbtn.op-reject{border-color:#7d2f33}.sres{font-size:13px;margin-top:6px;white-space:pre-wrap;word-break:break-word}
body.hh-live [hh-off]{display:none}
.livebadge{position:fixed;right:12px;bottom:12px;z-index:9;background:var(--panel2);border:1px solid var(--line);
border-radius:999px;padding:6px 12px;font-size:12px;color:var(--mut)}.livebadge b{color:#7ff0a8}
.livebadge.off b{color:#ffd27a}.lrow{display:flex;gap:10px;align-items:center;padding:6px 0;border-top:1px solid var(--line)}
.lrow img{width:96px;height:54px;object-fit:cover;border-radius:6px;flex:none}.lrow .t{flex:1;min-width:0}
.lrow .n{font-size:12px;color:var(--mut)}
.svtabs{display:flex;gap:6px;margin:4px 0 10px}.svtabs button{background:var(--panel2);color:var(--mut);
border:1px solid var(--line);border-radius:999px;padding:6px 12px;font-size:13px;cursor:pointer}
.svtabs button.on{color:var(--text);border-color:var(--acc)}
.sgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:12px}
.scard{background:var(--panel2);border:1px solid var(--line);border-radius:12px;overflow:hidden;display:flex;
flex-direction:column}.scard .sbody{padding:10px}.scard.st-made,.scard.st-missed{border-color:#a8842f}
.spv{display:block;width:100%;background:#07090d;object-fit:contain}.spv.ver{aspect-ratio:9/16;max-height:420px}
.spv.hor{aspect-ratio:16/9}.spv.still{position:relative;display:flex;align-items:center;justify-content:center}
.spv.still img{width:100%;height:100%;object-fit:cover;opacity:.75}.spv.still span{position:absolute;bottom:8px;
left:8px;right:8px;font-size:12px;color:#fff;text-shadow:0 1px 3px #000}.spv.still.empty{aspect-ratio:16/9;max-height:120px}
.spv.still.empty span{position:static;color:var(--mut)}
.sdet{margin-top:6px;font-size:12px}.sdet pre{white-space:pre-wrap;font:12px/1.45 inherit;color:var(--mut);margin:6px 0}
.cal{display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:4px}.cwh{font-size:11px;color:var(--mut);
text-align:center}.cday{min-height:86px;background:var(--panel2);border:1px solid var(--line);border-radius:8px;
padding:4px}.cday.today{border-color:var(--acc)}.cday.past{opacity:.6}.cdh{font-size:11px;color:var(--mut);margin-bottom:3px}
.cchip{display:block;width:100%;text-align:left;font-size:11px;margin:2px 0;padding:3px 5px;border-radius:6px;
border:1px solid var(--line);background:#1b2130;color:var(--text);cursor:pointer;white-space:nowrap;overflow:hidden;
text-overflow:ellipsis}.cchip.st-made,.cchip.st-missed{background:#3a2f12;border-color:#a8842f}
.cchip.st-approved,.cchip.st-scheduled,.cchip.st-posted{background:#123a24;border-color:#2f7d4f}
.cchip.st-failed,.cchip.st-rejected{background:#3a1416;border-color:#7d2f33}.cchip.st-making{background:#12283a}
.hhmodal{position:fixed;inset:0;background:rgba(0,0,0,.72);z-index:20;display:flex;align-items:center;
justify-content:center;padding:14px}.hhmodal .scard{max-width:420px;width:100%;max-height:94vh;overflow:auto}
.hhmodal .x{position:fixed;top:10px;right:14px;font-size:26px;color:#fff;background:none;border:0;cursor:pointer}
@media(max-width:640px){.cal{grid-template-columns:1fr}.cwh{display:none}.cday{min-height:0}.cday.past{display:none}}
.flash{animation:fl 1.2s}@keyframes fl{from{color:#7ff0a8}to{}}
"""

JS = r"""
(function(){var K=new URLSearchParams(location.search).get('k');if(K)document.body.classList.add('hh-live');
function fmt(n){n=Number(n||0);return n>=1e6?(n/1e6).toFixed(1).replace('.0','')+'M':n>=1e3?(n/1e3).toFixed(1).replace('.0','')+'K':n.toLocaleString()}
function esc(t){var d=document.createElement('div');d.textContent=t||'';return d.innerHTML}
var badge=document.createElement('div');badge.className='livebadge'+(K?'':' off');
badge.innerHTML=K?'<b>●</b> loading live numbers…':'<b>●</b> offline copy (open your private link for live numbers)';
document.body.appendChild(badge);
function setLive(key,val){document.querySelectorAll('[data-live="'+key+'"]').forEach(function(e){var t=fmt(val);
if(e.textContent!==t){e.textContent=t;e.classList.remove('flash');void e.offsetWidth;e.classList.add('flash')}})}
function loadLive(){if(!K)return;fetch('live?k='+encodeURIComponent(K)).then(function(r){return r.json()}).then(function(d){
Object.keys(d.channels||{}).forEach(function(c){var ch=d.channels[c];setLive('subs:'+c,ch.subs);setLive('ytviews:'+c,ch.views);
var box=document.querySelector('[data-live-list="'+c+'"]');if(box){var h=(ch.latest||[]).map(function(v){var x=d.videos[v]||{};
return '<div class=lrow>'+(x.thumb?'<img src="'+esc(x.thumb)+'" alt="">':'')+'<div class=t><a href="https://youtu.be/'+v+'" target=_blank>'+esc(x.title)+
'</a><div class=n>'+(x.at?new Date(x.at).toLocaleString([], {day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit'}):'')+
' · <b>'+fmt(x.views)+'</b> views · '+fmt(x.likes)+' likes · '+fmt(x.comments)+' comments</div></div></div>'}).join('');
box.innerHTML=h||'<p class=muted>No public uploads yet.</p>'}});
Object.keys(d.meta||{}).forEach(function(c){var m=d.meta[c]||{};if(m.instagram!=null)setLive('ig:'+c,m.instagram)});
Object.keys(d.videos||{}).forEach(function(v){setLive('vv:'+v,d.videos[v].views);setLive('vl:'+v,d.videos[v].likes)});
var t=new Date(d.at*1000).toLocaleTimeString();badge.className='livebadge'+(d.error?' off':'');
badge.innerHTML=d.error?'<b>●</b> live YouTube numbers failed ('+esc(d.error)+'), showing '+t:'<b>●</b> Live · YouTube '+t+
(d.built?' · Instagram/Facebook '+Math.round((Date.now()/1000-d.built)/60)+' min ago':'')}).catch(function(e){badge.className='livebadge off';badge.innerHTML='<b>●</b> offline: '+esc(String(e))})}

function pvSrc(root){if(!K)return;(root||document).querySelectorAll('video[data-pv]').forEach(function(v){
if(!v.getAttribute('src'))v.setAttribute('src','pv?k='+encodeURIComponent(K)+'&id='+encodeURIComponent(v.dataset.pv))})}
pvSrc();
document.querySelectorAll('.sstudio').forEach(function(card){var tabs=card.querySelectorAll('.svtabs button');
function show(v){tabs.forEach(function(b){b.classList.toggle('on',b.dataset.v===v)});
card.querySelectorAll('.sview').forEach(function(x){x.hidden=x.dataset.v!==v});try{localStorage.hhView=v}catch(e){}}
tabs.forEach(function(b){b.onclick=function(){show(b.dataset.v)}});var keep='';try{keep=localStorage.hhView}catch(e){}
if(keep)show(keep)});
window.hhOpen=function(item){var src=document.getElementById('sc-'+item);if(!src)return;
var m=document.createElement('div');m.className='hhmodal';var c=src.cloneNode(true);c.removeAttribute('id');
var x=document.createElement('button');x.className='x';x.textContent='✕';m.appendChild(x);m.appendChild(c);
function close(){m.querySelectorAll('video').forEach(function(v){v.pause()});m.remove()}
x.onclick=close;m.onclick=function(e){if(e.target===m)close()};document.body.appendChild(m);pvSrc(m)};
loadLive();setInterval(function(){if(!document.hidden)loadLive()},120000);
window.hhAct=function(op,item){if(!K){alert('Open your private dashboard link to use the buttons.');return}
var note='',force=false;if(op==='change'){note=prompt('What should change? (e.g. "make the hook scarier", or "title: new words")');if(!note)return}
if(op==='reject'&&!confirm('Reject / cancel this video?'))return;
if(op==='upload'&&!confirm('Post this video on all platforms now?'))return;
var bx=document.querySelectorAll('[data-res="'+item+'"]'),box={set textContent(t){bx.forEach(function(e){e.textContent=t})}};box.textContent='⏳ Sent…';
fetch('cmd?k='+encodeURIComponent(K),{method:'POST',headers:{'content-type':'application/json'},
body:JSON.stringify({op:op,item:item,note:note,force:force})}).then(function(r){return r.json()}).then(function(j){
if(!j.id){box.textContent='⚠️ '+(j.error||'not accepted');return}
box.textContent=j.pc?'⏳ Queued, the PC picks it up within a minute…':'⏳ Queued (the PC is off: it runs when the PC is back on).';
var n=0,t=setInterval(function(){n++;fetch('res?k='+encodeURIComponent(K)+'&id='+j.id).then(function(r){return r.json()}).then(function(s){
if(s.text)box.textContent=s.text;if(s.state==='done'||s.state==='error'||n>400){clearInterval(t);
if(s.text&&s.text.indexOf('Tap again and confirm')>=0&&confirm(s.text+'\n\nPost anyway?')){
fetch('cmd?k='+encodeURIComponent(K),{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({op:op,item:item,note:note,force:true})});box.textContent='⏳ Sent again (forced)…'}}})},5000)})
.catch(function(e){box.textContent='⚠️ '+e})}})();
"""
