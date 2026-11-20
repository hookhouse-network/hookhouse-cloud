"""Auto-approval (owner, 20 Nov 2026: "for approval, yes you can consider auto-approval", together with "each video
must be 100/100" and "nothing should bypass these gates").

A video is approved without a tap ONLY when all of these hold:
  1. It passed the content gate (engine/content_gate.py, which includes the strict clip gate) and the reach gate;
     the content gate already demands quality 100/100. The caller (autopilot.ask) runs those first.
  2. Trust: the owner's last `min_clean` decisions on this channel's videos of the same kind (short / long / clip)
     were all plain approvals: no Reject, no Change. One Reject or Change resets the count, so a format the owner
     corrects goes back to manual approval by itself.
  3. Time to veto: the slot is at least `min_hours` away. The owner gets the video with a "❌ Stop it" button;
     Stop rejects it (and removes the scheduled YouTube upload) exactly like a normal Reject.
  4. Not switched off (config/gates.yaml auto_approve.enabled) and the channel isn't excluded.
Auto-approved videos never count as owner approvals for trust (no self-reinforcement)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta

DEFAULTS = {"enabled": True, "min_clean": 10, "min_hours": 2.0, "exclude_channels": []}


def settings() -> dict:
    from .content_gate import config
    return dict(DEFAULTS, **(config().get("auto_approve") or {}))


def _kind(it: dict) -> str:
    return "long" if it.get("kind") == "long" else ("clip" if it.get("kind") == "clip" else "short")


def owner_decisions(channel: str, kind: str, plan_items: list[dict] | None = None) -> list[str]:
    """Newest first: 'approve' | 'reject' | 'change' for the owner's own decisions on this channel + kind."""
    if plan_items is None:
        from . import weekly
        plan_items = []
        for p in sorted(weekly.WEEKS_DIR.glob("*/plan.json")) if weekly.WEEKS_DIR.exists() else []:
            try:
                plan_items += json.loads(p.read_text(encoding="utf-8")).get("items") or []
            except (OSError, ValueError) as e:     # also reported to the heal queue by autopilot.items
                print(f"auto-approval: plan {p.parent.name} unreadable ({type(e).__name__}): not counted")
    rows = []
    for it in plan_items:
        if it.get("channel") != channel or _kind(it) != kind or it.get("auto_approved"):
            continue
        st = it.get("status")
        if st == "rejected":
            rows.append((it.get("decided_at") or it.get("publish_at") or "", "reject"))
        elif it.get("note") or it.get("changes"):                 # the owner asked for a change at some point
            rows.append((it.get("approved_at") or it.get("publish_at") or "", "change"))
        elif st in ("approved", "posted") and it.get("approved_at"):
            rows.append((it.get("approved_at"), "approve"))
    rows.sort(key=lambda r: str(r[0]), reverse=True)
    return [d for _, d in rows]


def eligible(it: dict, now: datetime | None = None, plan_items: list[dict] | None = None) -> tuple[bool, str]:
    s = settings()
    if not s["enabled"]:
        return False, "auto-approval is switched off"
    if it.get("channel") in (s.get("exclude_channels") or []):
        return False, "channel excluded from auto-approval"
    if it.get("status") != "made":
        return False, f"status is {it.get('status')}"
    from . import weekly
    now = now or datetime.now(weekly._zone())
    try:
        slot = datetime.fromisoformat(it["publish_at"])
    except (KeyError, ValueError, TypeError):
        return False, "no slot"
    if slot < now + timedelta(hours=float(s["min_hours"])):
        return False, f"slot is less than {s['min_hours']} h away (no time to stop it)"
    need = int(s["min_clean"])
    recent = owner_decisions(it["channel"], _kind(it), plan_items)[:need]
    if len(recent) < need:
        return False, f"only {len(recent)} of {need} owner approvals on record for this channel's {_kind(it)}s"
    if any(d != "approve" for d in recent):
        return False, f"a recent Reject/Change on this channel's {_kind(it)}s: manual approval until {need} clean ones"
    return True, f"your last {need} decisions on this channel's {_kind(it)}s were plain approvals"
