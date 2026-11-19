"""Dashboard "Accounts & links" grid (owner 19 Nov: "all the things should be inter-linked ... upgrade the dashboard
and other information"): one row per channel, one column per platform; each cell links to the real account, or says
what is still to do. Built from config/links.yaml and the login files in data/secrets (names only, never contents
beyond ids)."""
from __future__ import annotations

import html
import json

from .config import ROOT, channels

SECRETS = ROOT / "data" / "secrets"
COLS = [("youtube", "▶️ YouTube"), ("instagram", "📸 Instagram"), ("facebook", "📘 Facebook"), ("threads", "🧵 Threads"),
        ("dailymotion", "🎞 Dailymotion"), ("pinterest", "📌 Pinterest")]


def _j(name: str) -> dict:
    try:
        return json.loads((SECRETS / name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def cells(cid: str, row: dict) -> dict[str, tuple[str, str, str]]:
    """platform -> (state good|warn|todo, label, url)."""
    out: dict[str, tuple[str, str, str]] = {}
    yt = str(row.get("youtube") or "")
    ytc = (SECRETS / f"youtube_{cid}.json").exists()
    out["youtube"] = ("good" if ytc else "warn", yt or "-", f"https://www.youtube.com/{yt}" if yt else "")
    meta = _j(f"meta_{cid}.json")
    ig = str(row.get("instagram") or "").lstrip("@")
    if ig and (meta.get("ig_user_id") or row.get("instagram_live")):
        out["instagram"] = ("good" if meta.get("ig_user_id") else "warn", "@" + ig + ("" if meta.get("ig_user_id")
                            else " (not linked to Meta yet)"), f"https://www.instagram.com/{ig}")
    else:
        out["instagram"] = ("todo", "to create" if ig else "-", "")
    page = meta.get("page_id")
    out["facebook"] = (("good", "Page", f"https://www.facebook.com/{page}") if page else ("todo", "Page to create", ""))
    th = _j(f"threads_{cid}.json")
    if th:
        out["threads"] = ("good", "@" + ig if ig else "connected", f"https://www.threads.com/@{ig}")
    elif row.get("threads_live") and ig:            # profile exists; automatic posting not connected yet
        out["threads"] = ("warn", "@" + ig + " (posting not connected)", f"https://www.threads.com/@{ig}")
    else:
        out["threads"] = ("todo", "to create", "")
    dm = _j("dailymotion.json")
    out["dailymotion"] = (("good", "HookHouse Media", "https://www.dailymotion.com/hookhousemedia") if dm and
                          row.get("dailymotion", True) else ("todo", "-", ""))
    pin = row.get("pinterest")
    out["pinterest"] = (("good", str(pin), f"https://www.pinterest.com/{str(pin).lstrip('@')}") if pin
                        else ("todo", "to create", ""))
    return out


def card() -> str:
    from .links import data
    links = data()
    rows, counts = [], {k: 0 for k, _ in COLS}
    for ch in channels():
        row = links.get(ch["id"]) or {}
        c = cells(ch["id"], row)
        tds = ""
        for k, _ in COLS:
            state, label, url = c[k]
            counts[k] += state == "good"
            lab = html.escape(label)
            inner = f"<a href='{html.escape(url)}' target=_blank rel=noopener>{lab}</a>" if url else lab
            tds += f"<td class='acc-{state}'>{inner}</td>"
        rows.append(f"<tr><td><b>{html.escape(ch['name'])}</b></td>{tds}</tr>")
    head = "".join(f"<th>{html.escape(t)}<br><small>{counts[k]}/{len(rows)}</small></th>" for k, t in COLS)
    return ("<div class='card wide'><h2>🔗 Accounts &amp; links</h2><div class=tw><table class='stack acc'><tr><th>Channel"
            f"</th>{head}</tr>{''.join(rows)}</table></div><p class=muted>Green = live and linked · amber = exists, not "
            "linked yet · grey = still to set up. Every bio points to the channel's other accounts; YouTube About lists "
            "the real Instagram and Facebook links.</p></div>")


def training_card() -> str:
    """Progress of our own training set (fine-tune on Kaggle once READY_AT labelled videos exist)."""
    from .training_data import status
    s = status()
    pct = min(100, round(100 * s["labelled"] / max(1, s["ready_at"])))
    return (f"<div class=card><h2>🧠 Our own AI model</h2><p>Training set: <b>{s['labelled']}</b> videos with results "
            f"(of {s['ready_at']} needed) · {s['scripts']} scripts saved</p><div style='background:var(--panel2);"
            f"border-radius:6px;height:10px'><div style='width:{pct}%;height:10px;border-radius:6px;background:var(--acc)'>"
            "</div></div><p class=muted>Every video's words are kept with its later numbers. At the target, a free model "
            "is fine-tuned on our best videos (on a GPU service that allows commercial use) so it writes in our winning style.</p></div>")


CSS = """
.acc td{white-space:nowrap}.acc-good a{color:#7ff0a8}.acc-warn{color:#ffd27a}.acc-warn a{color:#ffd27a}
.acc-todo{color:var(--mut)}
"""
