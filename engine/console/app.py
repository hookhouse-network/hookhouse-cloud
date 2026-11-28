"""Control Center v1 (P2b, 27 Nov): a local, read-only window on the whole system, at http://127.0.0.1:8765.

Screens: Home (today, publish queue, the PC's live log), Pipeline (every video of the next days and its stage),
Gates (what the gates hold and why), Queue (posts that gave up). The PC holds a READ-ONLY copy of the cloud's plan,
so the console never changes it: every action button opens the cloud dashboard (the same path as the Telegram taps),
never a second code path. When the shared queue cannot be reached a 'degraded' banner says so; the rest still shows.
Bound to 127.0.0.1 only. Start: python -m engine.console.app  (or scripts/console.cmd)."""
from __future__ import annotations

import time
from datetime import datetime

from jinja2 import Environment
from starlette.applications import Starlette
from starlette.responses import HTMLResponse
from starlette.routing import Route

from ..config import ROOT

ENV = Environment(autoescape=True)
PAGE = ENV.from_string("""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport"
content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="30"><title>HookHouse · {{ title }}</title>
<style>body{font:15px/1.45 system-ui,sans-serif;margin:0;background:#0f1115;color:#e8e8ea}
nav{display:flex;gap:4px;padding:10px 14px;background:#171a21;flex-wrap:wrap}nav a{color:#cfd3dc;text-decoration:none;
padding:6px 12px;border-radius:8px}nav a.on{background:#2b3140;color:#fff}main{padding:14px;max-width:1100px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px}.card{background:#171a21;
border-radius:12px;padding:12px}.big{font-size:28px;font-weight:700}.muted{color:#8b91a0}table{width:100%;
border-collapse:collapse;margin-top:8px}td,th{padding:6px 8px;border-bottom:1px solid #232733;text-align:left;
vertical-align:top}.banner{background:#5a3b10;color:#ffd79a;padding:8px 14px}.ok{color:#7ddc8f}.bad{color:#ff8a80}
pre{background:#0a0c10;padding:10px;border-radius:8px;overflow:auto;font-size:12px;max-height:380px}
a.btn{display:inline-block;background:#3d6df2;color:#fff;padding:7px 14px;border-radius:8px;text-decoration:none}
</style></head><body><nav>{% for href, name in tabs %}<a href="{{ href }}" class="{{ 'on' if name == title else '' }}">
{{ name }}</a>{% endfor %}{% if dash %}<a class="btn" href="{{ dash }}" target="_blank">Approve / act (cloud)</a>
{% endif %}</nav>{% if degraded %}<div class="banner">Degraded: {{ degraded }} (showing the PC's last copy)</div>
{% endif %}<main>{{ body|safe }}<p class="muted">Updated {{ now }} · refreshes every 30 s · read-only</p></main>
</body></html>""")
TABS = [("/", "Home"), ("/pipeline", "Pipeline"), ("/gates", "Gates"), ("/queue", "Queue")]


def _dash() -> str:
    try:
        from ..pc_fallback import dash_link
        return dash_link() or ""
    except Exception as e:  # noqa: BLE001 - the console works without the link (said in the banner)
        from ..core.quiet import noted
        noted("console:dash_link", e)
        return ""


def _page(title: str, body: str, degraded: str = "") -> HTMLResponse:
    return HTMLResponse(PAGE.render(title=title, body=body, tabs=TABS, dash=_dash(), degraded=degraded,
                                    now=datetime.now().strftime("%d %b %H:%M:%S")))


def _items(back: int = 1, ahead: int = 3) -> list[dict]:
    from .. import autopilot
    return [it for _s, it in autopilot.items(back, ahead)]


def _log_tail(n: int = 25) -> str:
    p = ROOT / "data" / "logs" / "pc_maker.log"
    try:
        return "\n".join(p.read_text(encoding="utf-8", errors="replace").splitlines()[-n:])
    except OSError:
        return "(no PC maker log yet)"


def _queue() -> tuple[dict, str]:
    try:
        from .. import publish_queue
        return publish_queue.summary(), ""
    except Exception as e:  # noqa: BLE001 - shown as degraded, never a crash page
        return {}, f"publish queue unreadable ({type(e).__name__})"


def _sched() -> tuple[dict, str]:
    try:
        from ..cloud import sched
        c = sched.SchedClient()
        if not c.available():
            return {}, "shared queue not set up on this PC"
        return c.stats() or {}, ""
    except Exception as e:  # noqa: BLE001 - offline / D1 down: degraded banner
        return {}, f"shared queue unreachable ({type(e).__name__})"


ENV_BODY = {
    "home": ENV.from_string("""<div class="cards">{% for k, v in cards %}<div class="card"><div class="muted">{{ k }}</div>
<div class="big">{{ v }}</div></div>{% endfor %}</div><h3>Publish queue</h3><p>{% for k, v in queue.items() %}
{{ k }}: <b>{{ v }}</b> · {% endfor %}</p><h3>Workers</h3><p>{% for w in online %}<span class="ok">● {{ w.id }}
({{ w.kind }})</span> {% else %}<span class="muted">no worker online in the shared queue</span>{% endfor %}</p>
<h3>PC video maker (live log)</h3><pre>{{ log }}</pre>"""),
    "pipeline": ENV.from_string("""<table><tr><th>Slot</th><th>Channel</th><th>Kind</th><th>Status</th><th>Topic</th></tr>
{% for it in items %}<tr><td>{{ it.publish_at[5:16].replace('T', ' ') }}</td><td>{{ it.channel_name or it.channel }}</td>
<td>{{ it.kind }}</td><td class="{{ 'ok' if it.status in ('posted', 'approved') else ('bad' if it.status in
('failed', 'missed') else '') }}">{{ it.status }}</td><td>{{ (it.topic or '')[:70] }}</td></tr>{% endfor %}</table>"""),
    "gates": ENV.from_string("""{% for iid, v in held %}<div class="card" style="margin-bottom:8px"><b>{{ v.channel or ''
}}</b> · {{ slot(iid) }}<div class="muted">{{ (v.problems or [''])[0][:400] }}</div></div>{% else %}<p class="ok">
Nothing is held right now.</p>{% endfor %}"""),
    "queue": ENV.from_string("""<table><tr><th>Job</th><th>State</th><th>Tries</th><th>Last error</th></tr>
{% for j in jobs %}<tr><td>{{ j.key }}</td><td class="bad">{{ j.state }}</td><td>{{ j.attempts }}</td>
<td>{{ (j.last_error or '')[:200] }}</td></tr>{% else %}<tr><td colspan="4" class="ok">No post gave up.</td></tr>
{% endfor %}</table>"""),
}


async def home(request):
    items = _items(0, 1)
    today = datetime.now().strftime("%Y-%m-%d")
    todays = [it for it in items if str(it.get("publish_at", "")).startswith(today)]
    q, qerr = _queue()
    s, serr = _sched()
    cards = [("Today's slots", len(todays)),
             ("Posted today", sum(1 for it in todays if it.get("status") == "posted")),
             ("Waiting approval", sum(1 for it in items if it.get("status") == "made")),
             ("Approved, waiting slot", sum(1 for it in items if it.get("status") == "approved"))]
    body = ENV_BODY["home"].render(cards=cards, queue=q.get("states") or {}, online=s.get("online") or [], log=_log_tail())
    return _page("Home", body, qerr or serr)


async def pipeline(request):
    items = sorted(_items(1, 3), key=lambda it: it.get("publish_at", ""))
    return _page("Pipeline", ENV_BODY["pipeline"].render(items=items))


async def gates(request):
    from .. import autopilot
    held = sorted(autopilot.gate_held().items(), key=lambda kv: -float((kv[1] or {}).get("at") or 0))
    return _page("Gates", ENV_BODY["gates"].render(held=held, slot=slot_label))


def slot_label(item_id: str) -> str:
    """'1127_0500_x_short' -> '27 Nov 05:00 Short' (P10: no internal IDs in the main view)."""
    import re
    m = re.match(r"(\d{2})(\d{2})_(\d{2})(\d{2})_.*_(short|long|clip)$", item_id or "")
    if not m:
        return "a video"
    month = datetime(2000, int(m.group(1)), 1).strftime("%b") if 1 <= int(m.group(1)) <= 12 else ""
    return f"{int(m.group(2))} {month} {m.group(3)}:{m.group(4)} {m.group(5).capitalize()}"


async def queue(request):
    from ..core import ledger
    try:
        jobs = [j for j in ledger.default().jobs(state="dead")] if hasattr(ledger.default(), "jobs") else []
        err = ""
    except Exception as e:  # noqa: BLE001 - degraded banner, never a crash page
        jobs, err = [], f"ledger unreadable ({type(e).__name__})"
    return _page("Queue", ENV_BODY["queue"].render(jobs=jobs[-50:]), err)


WORKERS = ENV.from_string("""<div class="cards"><div class="card"><div class="muted">PC video maker</div>
<div class="big {{ 'bad' if paused else ('ok' if alive else 'bad') }}">{{ 'Paused' if paused else ('Running' if alive
else 'Not seen') }}</div><div class="muted">last log line {{ age }}</div></div><div class="card"><div class="muted">
Shared queue</div>{% for w in online %}<div class="ok">● {{ w.id }} ({{ w.kind }})</div>{% else %}<div class="muted">
no worker online</div>{% endfor %}</div></div><form method="post" action="/workers/{{ 'resume' if paused else
'pause' }}" style="margin-top:14px"><button class="btn" style="border:0;cursor:pointer;background:{{ '#2e9e55' if
paused else '#c0392b' }};color:#fff;padding:9px 18px;border-radius:8px">{{ 'Resume video making' if paused else
'Pause video making' }}</button></form><p class="muted">Pause stops NEW videos after the current one finishes; the cloud
keeps posting what is ready. Resume starts again within a minute.</p>""")


def _alive() -> tuple[bool, str]:
    p = ROOT / "data" / "logs" / "pc_maker.log"
    try:
        age = time.time() - p.stat().st_mtime
    except OSError:
        return False, "never"
    mins = int(age // 60)
    return age < 20 * 60, (f"{mins} min ago" if mins else "just now")


async def workers(request):
    from ..cloud.runner import PAUSE_FILE
    s, serr = _sched()
    alive, age = _alive()
    return _page("Workers", WORKERS.render(paused=PAUSE_FILE.exists(), alive=alive, age=age,
                                           online=s.get("online") or []), serr)


def _same_origin(request) -> bool:
    """Only the console's own page may press its buttons (a form post from another site is refused)."""
    origin = request.headers.get("origin") or request.headers.get("referer") or ""
    return origin == "" or origin.startswith(("http://127.0.0.1:8765", "http://localhost:8765"))


async def set_pause(request):
    from starlette.responses import PlainTextResponse, RedirectResponse
    from ..cloud.runner import PAUSE_FILE
    if not _same_origin(request):
        return PlainTextResponse("refused: not from the Control Center", status_code=403)
    if request.path_params["what"] == "pause":
        PAUSE_FILE.parent.mkdir(parents=True, exist_ok=True)
        PAUSE_FILE.write_text(datetime.now().strftime("%Y-%m-%d %H:%M"), encoding="utf-8")
    else:
        PAUSE_FILE.unlink(missing_ok=True)
    return RedirectResponse("/workers", status_code=303)


BUDGETS = ENV.from_string("""<h3>AI calls today</h3><table><tr><th>Provider</th><th>Calls</th><th>Errors</th>
<th>Daily limit hit</th></tr>{% for r in ai %}<tr><td>{{ r.provider }}</td><td>{{ r.calls }}</td><td>{{ r.errors }}</td>
<td class="{{ 'bad' if r.quota_hits else 'ok' }}">{{ r.quota_hits or '—' }}</td></tr>{% else %}<tr><td colspan="4"
class="muted">no AI calls recorded today on this PC</td></tr>{% endfor %}</table><h3>Picture sources</h3><table>
<tr><th>Source</th><th>State</th></tr>{% for p in pics %}<tr><td>{{ p.source }}</td><td class="{{ 'ok' if p.open else
'bad' }}">{{ 'open' if p.open else 'used up until ' ~ p.until }}</td></tr>{% endfor %}<tr><td>PC local pictures</td>
<td class="{{ 'ok' if not local.why_not else 'bad' }}">{{ local.used }} / {{ local.cap }} today{{ ' · ' ~ local.why_not
if local.why_not else '' }}</td></tr></table><p class="muted">When a budget is used up, work waits for its reset (no
video is failed for it).</p>""")


async def budgets_page(request):
    from .. import budgets
    s = budgets.summary()
    return _page("Budgets", BUDGETS.render(ai=s["ai"], pics=s["pictures"], local=s["local"]))


MONEY = ENV.from_string("""<div class="cards"><div class="card"><div class="muted">Campaign money received</div>
<div class="big">Rs {{ '{:,.0f}'.format(inr) }}</div></div><div class="card"><div class="muted">Campaign money pending</div>
<div class="big">${{ '{:,.2f}'.format(usd) }}</div></div><div class="card"><div class="muted">Store products listed</div>
<div class="big">{{ listed }}</div></div></div><h3>Last 7 days per channel</h3><table><tr><th>Channel</th><th>Posts</th>
<th>Views</th></tr>{% for r in board %}<tr><td>{{ r.channel }}</td><td>{{ r.posts }}</td><td>{{ '{:,.0f}'.format(r.views)
}}</td></tr>{% else %}<tr><td colspan="3" class="muted">no posts in the last 7 days</td></tr>{% endfor %}</table>
<p class="muted">Store sales are paid out by Payhip once a payout method is connected there.</p>""")

CALENDAR = ENV.from_string("""{% for day, rows in days %}<h3>{{ day }}</h3><table><tr><th>Time</th><th>Channel</th>
<th>Kind</th><th>State</th></tr>{% for it in rows %}<tr><td>{{ it.publish_at[11:16] }}</td><td>{{ it.channel_name or
it.channel }}</td><td>{{ it.kind }}</td><td class="{{ 'ok' if it.status in ('posted', 'approved') else ('bad' if
it.status in ('failed', 'missed') else '') }}">{{ states.get(it.status, it.status) }}</td></tr>{% endfor %}</table>
{% else %}<p class="muted">Nothing planned in the next 7 days.</p>{% endfor %}""")
STATES = {"planned": "to make", "making": "being made", "made": "waiting approval", "approved": "approved, waits slot",
          "posted": "posted", "redo": "being remade", "failed": "failed, retrying", "missed": "missed",
          "needs_source": "needs footage"}


def _board(days: int = 7) -> list[dict]:
    """[{channel, posts, views}] for the last days, most viewed first (operator_brief's earnings board numbers)."""
    import sqlite3
    from collections import Counter
    from .. import operator_brief as ob
    since = time.time() - days * 86400
    posts: Counter = Counter()
    seen = set()
    for r in ob._log_rows(since):
        if ob._is_post(r) and (r["item_id"], r.get("channel")) not in seen:
            seen.add((r["item_id"], r.get("channel")))
            posts[r.get("channel") or "?"] += 1
    views: dict[str, float] = {}
    try:
        c = sqlite3.connect(str(ROOT / "data" / "analytics.db"))
        for ch, v in c.execute("SELECT channel, SUM(mv) FROM (SELECT channel, item_id, platform, MAX(views) AS mv FROM "
                               "video_metrics WHERE posted_at >= ? GROUP BY channel, item_id, platform) GROUP BY channel",
                               (since,)):
            views[ch] = float(v or 0)
        c.close()
    except sqlite3.Error as e:
        from ..core.quiet import noted
        noted("console:board", e)
    names = {}
    try:
        from ..config import channels
        names = {c["id"]: c.get("name") or c["id"] for c in channels()}
    except Exception as e:  # noqa: BLE001 - ids are shown instead of names
        from ..core.quiet import noted
        noted("console:names", e)
    return sorted(({"channel": names.get(c, c), "posts": posts.get(c, 0), "views": views.get(c, 0.0)}
                   for c in set(posts) | set(views)), key=lambda r: -r["views"])


async def money(request):
    from .. import operator_brief as ob
    inr, usd = ob.earnings()
    try:
        from ..store_publish import listed
        n = sum(1 for v in listed().values() if v)
        err = ""
    except Exception as e:  # noqa: BLE001 - degraded, never a crash page
        n, err = 0, f"store list unreadable ({type(e).__name__})"
    return _page("Money", MONEY.render(inr=inr, usd=usd, listed=n, board=_board()), err)


async def calendar(request):
    items = sorted(_items(0, 7), key=lambda it: it.get("publish_at", ""))
    days: dict[str, list] = {}
    for it in items:
        try:
            label = datetime.fromisoformat(str(it["publish_at"])).strftime("%a %d %b")
        except (KeyError, ValueError):
            continue
        days.setdefault(label, []).append(it)
    return _page("Calendar", CALENDAR.render(days=list(days.items()), states=STATES))


GROWTH = ENV.from_string("""<table><tr><th>Channel</th>{% for w in weeks %}<th>{{ w }}</th>{% endfor %}<th>Trend</th></tr>
{% for r in rows %}<tr><td>{{ r.name }}</td>{% for v in r.views %}<td>{{ '{:,.0f}'.format(v) }}</td>{% endfor %}
<td class="{{ 'ok' if r.trend > 0 else ('bad' if r.trend < 0 else 'muted') }}">{{ '▲' if r.trend > 0 else ('▼' if r.trend
< 0 else '–') }}</td></tr>{% else %}<tr><td colspan="6" class="muted">no measured videos yet</td></tr>{% endfor %}
</table><p class="muted">Views of the videos posted in each week (newest week on the right), all platforms.</p>""")

PRODUCTS = ENV.from_string("""<h3>Store products ({{ products|length }})</h3><table><tr><th>Product</th><th>Price</th>
<th>Store</th></tr>{% for p in products %}<tr><td>{{ p.title }}</td><td>{{ p.price }}</td><td>{% if p.url %}<a
href="{{ p.url }}" target="_blank" style="color:#8fb3ff">open</a>{% else %}<span class="muted">draft</span>{% endif %}
</td></tr>{% else %}<tr><td colspan="3" class="muted">no products listed yet</td></tr>{% endfor %}</table>
<h3>Campaigns</h3><div class="cards">{% for k, v in camps %}<div class="card"><div class="muted">{{ k }}</div>
<div class="big">{{ v }}</div></div>{% endfor %}</div><p class="muted">Joined campaigns get clips made from their
footage; ticked ones wait for your ✅ Confirm in Telegram (the system checks footage and joins).</p>""")
CAMP_LABELS = [("joined", "Joined"), ("picked", "Ticked, not joined"), ("eligible", "Found, fits us"),
               ("review", "Being checked"), ("ended", "Ended")]


def _weekly_views(weeks: int = 4) -> tuple[list[str], list[dict]]:
    import sqlite3
    now = time.time()
    labels = [datetime.fromtimestamp(now - (weeks - i) * 7 * 86400).strftime("%d %b") for i in range(weeks)]
    per: dict[str, list[float]] = {}
    try:
        c = sqlite3.connect(str(ROOT / "data" / "analytics.db"))
        rows = c.execute("SELECT channel, posted_at, MAX(views) FROM video_metrics WHERE posted_at >= ? "
                         "GROUP BY channel, item_id, platform", (now - weeks * 7 * 86400,)).fetchall()
        c.close()
    except sqlite3.Error as e:
        from ..core.quiet import noted
        noted("console:growth", e)
        rows = []
    for ch, at, v in rows:
        i = min(weeks - 1, max(0, int((float(at or now) - (now - weeks * 7 * 86400)) // (7 * 86400))))
        per.setdefault(ch, [0.0] * weeks)[i] += float(v or 0)
    names = {}
    try:
        from ..config import channels
        names = {c["id"]: c.get("name") or c["id"] for c in channels()}
    except Exception as e:  # noqa: BLE001
        from ..core.quiet import noted
        noted("console:growth_names", e)
    out = [{"name": names.get(ch, ch), "views": v, "trend": (v[-1] > v[-2]) - (v[-1] < v[-2]) if weeks > 1 else 0}
           for ch, v in per.items()]
    return labels, sorted(out, key=lambda r: -sum(r["views"]))


async def growth(request):
    weeks, rows = _weekly_views()
    return _page("Growth", GROWTH.render(weeks=weeks, rows=rows))


async def products(request):
    err = ""
    try:
        from ..store_publish import listed
        items = []
        for pid, stores in listed().items():
            p = (stores or {}).get("payhip") or next(iter((stores or {}).values()), {})
            price = p.get("price_usd")
            items.append({"title": str(p.get("title") or pid)[:80], "price": f"${price:g}" if price else "",
                          "url": p.get("public") or ""})
    except Exception as e:  # noqa: BLE001 - degraded, never a crash page
        items, err = [], f"store list unreadable ({type(e).__name__})"
    camps = []
    try:
        from collections import Counter
        from .. import db
        n = Counter(c.get("status") for c in db.list_campaigns(db.connect()))
        camps = [(label, n.get(k, 0)) for k, label in CAMP_LABELS]
    except Exception as e:  # noqa: BLE001
        err = err or f"campaigns unreadable ({type(e).__name__})"
    return _page("Products", PRODUCTS.render(products=sorted(items, key=lambda x: x["title"]), camps=camps), err)


def md_html(text: str) -> str:
    """The owner guide's small markdown (headings, bullets, bold, `code`, tables) as safe HTML (escaped first)."""
    import html
    import re

    def inline(s: str) -> str:
        s = html.escape(s)
        s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
        return re.sub(r"`(.+?)`", r"<code>\1</code>", s)
    out, in_list, table = [], False, []

    def flush_table():
        if table:
            rows = [r for r in table if not re.match(r"^\|[\s|:-]+\|$", r)]
            cells = [[c.strip() for c in r.strip("|").split("|")] for r in rows]
            head, body = cells[0], cells[1:]
            out.append("<table><tr>" + "".join(f"<th>{inline(c)}</th>" for c in head) + "</tr>" + "".join(
                "<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>" for r in body) + "</table>")
            table.clear()
    for line in (text or "").splitlines():
        if line.startswith("|"):
            table.append(line)
            continue
        flush_table()
        if line.startswith("- "):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{inline(line[2:])}</li>")
            continue
        if line.startswith("  ") and in_list and out and out[-1].endswith("</li>"):
            out[-1] = out[-1][:-5] + " " + inline(line.strip()) + "</li>"    # a wrapped bullet line
            continue
        if in_list:
            out.append("</ul>")
            in_list = False
        m = re.match(r"^(#{1,3}) (.*)", line)
        if m:
            n = len(m.group(1)) + 1
            out.append(f"<h{n}>{inline(m.group(2))}</h{n}>")
        elif line.strip():
            out.append(f"<p>{inline(line)}</p>")
    flush_table()
    if in_list:
        out.append("</ul>")
    return "\n".join(out)


async def help_page(request):
    try:
        text = (ROOT / "docs" / "OWNER_GUIDE.md").read_text(encoding="utf-8")
        err = ""
    except OSError as e:
        text, err = "", f"guide unreadable ({type(e).__name__})"
    return _page("Help", md_html(text) or "<p class='muted'>The owner guide is missing.</p>", err)


TABS.append(("/workers", "Workers"))
TABS.append(("/budgets", "Budgets"))
TABS.append(("/calendar", "Calendar"))
TABS.append(("/money", "Money"))
TABS.append(("/growth", "Growth"))
TABS.append(("/products", "Products"))
TABS.append(("/help", "Help"))
app = Starlette(routes=[Route("/", home), Route("/pipeline", pipeline), Route("/gates", gates),
                        Route("/queue", queue), Route("/workers", workers), Route("/budgets", budgets_page),
                        Route("/calendar", calendar), Route("/money", money), Route("/help", help_page),
                        Route("/growth", growth), Route("/products", products),
                        Route("/workers/{what:str}", set_pause, methods=["POST"])])


def main(port: int = 8765) -> None:
    import uvicorn
    from ..config import load_env
    load_env()
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
