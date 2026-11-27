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
}}</b> · {{ iid }}<div class="muted">{{ (v.problems or [''])[0][:400] }}</div></div>{% else %}<p class="ok">Nothing is
held right now.</p>{% endfor %}"""),
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
    return _page("Gates", ENV_BODY["gates"].render(held=held))


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


TABS.append(("/workers", "Workers"))
app = Starlette(routes=[Route("/", home), Route("/pipeline", pipeline), Route("/gates", gates),
                        Route("/queue", queue), Route("/workers", workers),
                        Route("/workers/{what:str}", set_pause, methods=["POST"])])


def main(port: int = 8765) -> None:
    import uvicorn
    from ..config import load_env
    load_env()
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
