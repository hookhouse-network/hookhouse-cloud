"""The owner's to-do list, grouped by platform, with checkboxes (config/owner_todo.yaml).
Tasks with `auto` are ticked by the system itself when it can see them done (a key in .env, connected accounts, the
Windows task, free disk space, a saved choice); the rest are ticked by the owner in Telegram (/todo) and saved here."""
from __future__ import annotations

import os
import shutil
import subprocess
from collections import OrderedDict

import yaml

from .config import ROOT

FILE = ROOT / "config" / "owner_todo.yaml"
ORDER = ["Start here", "Google & Gmail", "Telegram", "Cloud (no PC needed)", "This PC", "YouTube", "Instagram & Facebook", "Dailymotion",
         "Threads, Pinterest & Snapchat", "Campaign boards", "Books & music", "Creator outreach", "AI & free keys", "Extra income"]
ICON = {"Start here": "🚀", "Google & Gmail": "📧", "Telegram": "💬", "Cloud (no PC needed)": "☁️", "This PC": "🖥", "YouTube": "▶️", "Instagram & Facebook": "📸",
        "Dailymotion": "🎞", "Threads, Pinterest & Snapchat": "🧵", "Campaign boards": "💰", "Books & music": "📚",
        "Creator outreach": "📨", "AI & free keys": "🔑", "Extra income": "➕"}


def load() -> list[dict]:
    return yaml.safe_load(FILE.read_text(encoding="utf-8")) or [] if FILE.exists() else []


def _schtask(name: str) -> bool:
    try:
        return subprocess.run(["schtasks", "/Query", "/TN", name], capture_output=True, timeout=20).returncode == 0
    except Exception:  # noqa: BLE001
        return False


def auto_status(rule: str) -> tuple[bool, str]:
    """(done, detail) for an auto rule."""
    kind, _, arg = rule.partition(":")
    if kind == "env":
        names = [a for a in arg.split(",") if a]
        have = [n for n in names if os.environ.get(n, "").strip()]
        return len(have) == len(names), f"{len(have)}/{len(names)} saved"
    if kind == "secrets":
        prefix, _, need = arg.partition(":")
        sec = ROOT / "data" / "secrets"
        n = len(list(sec.glob(f"{prefix}_*.json"))) if sec.exists() else 0
        need_n = int(need or 1)
        return n >= need_n, f"{n}/{need_n} connected"
    if kind == "dailymotion":
        from .config import channels
        from .publish import dm_creds
        n = sum(1 for c in channels() if dm_creds(c["id"]))
        return n > 0, f"{n} channel(s) connected"
    if kind == "schtask":
        ok = _schtask(arg)
        return ok, "task found" if ok else "no task yet"
    if kind == "disk":
        free = shutil.disk_usage(ROOT).free / 1e9
        return free >= float(arg), f"{free:.0f} GB free"
    if kind == "links":                                   # e.g. links:telegram:11 = 11 channels have one
        key, _, need = arg.partition(":")
        from .links import data as _links
        n = sum(1 for k, v in _links().items() if isinstance(v, dict) and str(v.get(key) or "").strip())
        return n >= int(need or 1), f"{n}/{need or 1} set"
    if kind == "choice":
        f = ROOT / "config" / "owner_choices.yaml"
        data = (yaml.safe_load(f.read_text(encoding="utf-8")) or {}) if f.exists() else {}
        return bool(data.get(arg)), str(data.get(arg) or "not chosen")
    return False, ""


def items() -> list[dict]:
    """Every task with: done (auto or manual), detail (what the system sees), manual (owner ticks it)."""
    out = []
    for t in load():
        row = dict(t)
        if t.get("auto"):
            done, detail = auto_status(t["auto"])
            row.update(done=done or bool(t.get("done")), detail=detail, manual=False)
        else:
            row.update(done=bool(t.get("done")), detail="", manual=True)
        out.append(row)
    return out


def grouped() -> "OrderedDict[str, list[dict]]":
    g: OrderedDict[str, list[dict]] = OrderedDict((p, []) for p in ORDER)
    for t in items():
        g.setdefault(t.get("platform") or "Other", []).append(t)
    return OrderedDict((k, v) for k, v in g.items() if v)


def tick(task_id: str, value: bool | None = None) -> dict | None:
    """Set (or toggle) a manual task's checkbox in owner_todo.yaml, keeping the file's layout."""
    tasks = load()
    t = next((x for x in tasks if x.get("id") == task_id), None)
    if not t:
        return None
    new = (not t.get("done")) if value is None else bool(value)
    lines = FILE.read_text(encoding="utf-8").splitlines()
    for i, ln in enumerate(lines):
        if ln.lstrip().startswith("- {id: " + task_id + ","):
            lines[i] = ln.replace("done: true}", "done: false}").replace("done: false}", f"done: {'true' if new else 'false'}}}")
    FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    t["done"] = new
    return t


def progress() -> tuple[int, int]:
    rows = items()
    return sum(1 for r in rows if r["done"]), len(rows)


def telegram_text() -> tuple[str, dict]:
    """The list for the phone (☑ / ☐ per platform) + buttons to tick the open manual tasks."""
    done, total = progress()
    lines = [f"✅ Your to-do: {done}/{total} done (☑ = done; auto = I tick it myself)"]
    buttons = []
    for plat, rows in grouped().items():
        lines.append(f"\n{ICON.get(plat, '•')} {plat}")
        for r in rows:
            short = r["task"].split(" (")[0][:70]
            lines.append(f"{'☑' if r['done'] else '☐'} {short}" + (f" · {r['detail']}" if r.get("detail") else "")
                         + (" (auto)" if not r["manual"] else ""))
            if r["manual"] and not r["done"]:
                buttons.append([{"text": f"☐ {short[:40]}", "callback_data": f"td:{r['id']}"[:64]}])
    return "\n".join(lines)[:4000], {"inline_keyboard": buttons[:20]}
