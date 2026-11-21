"""Automatic campaign submission within 30 minutes of posting (master plan Phase 7; owner 21 Nov: "the post link must
be submitted within 30 minutes of posting ... this is your part of job not mine, automation must handle this also").

Content Rewards (Whop) form, read 21 Nov on the joined Dasgasd3m campaign page: "Submit clip" opens a dialog with a
"Clip link" URL field and the checkbox "I've read the requirements and accept that non-compliant clips may be
auto-rejected", then "Submit clip". Conditions shown there: posted from one of OUR LINKED accounts, not already
submitted to a campaign, posted within the last 30 minutes. Every clip already passed the strict clip + campaign gates
before it was posted (that is what the checkbox affirms).

- submit(campaign_url, post_url): drives the logged-in HookHouse Chrome (port 9333; the cloud tick has the same
  session), returns {"ok", "message", "proof"}; a screenshot of the result is the proof.
- after_post(it, links): called by the publish queue right after a campaign clip is posted; submits the first link the
  brief allows, records the submission (campaign_safety.submissions) and tells the owner the outcome in plain words.
- A submitted post is frozen: nothing may edit, re-title, re-upload or delete it (see is_frozen)."""
from __future__ import annotations

import asyncio
import base64
import json
import time
from pathlib import Path

from .config import ROOT

PROOFS = ROOT / "data" / "campaign_proofs"
SUBMIT_HOSTS = ("contentrewards.com",)
WINDOW_S = 30 * 60
OK_WORDS = ("submitted", "under review", "pending review", "received")
FAIL_WORDS = ("can't be used", "not from a linked account", "already submitted", "older than", "invalid", "error")


def supported(campaign_url: str) -> bool:
    return any(h in (campaign_url or "") for h in SUBMIT_HOSTS)


def pick_link(links: dict[str, str], platforms: list[str] | None) -> str | None:
    """The first posted link on a platform the brief allows (YouTube first: Content Rewards tracks it best)."""
    allowed = [p.lower() for p in (platforms or [])] or ["youtube"]
    for p in ("youtube", "tiktok", "instagram", "x", "facebook"):
        if p in allowed and links.get(p):
            return links[p]
    return None


async def _submit(campaign_url: str, post_url: str, item_id: str) -> dict:
    from . import kick
    async with kick._Tab(campaign_url) as tab:
        await asyncio.sleep(12)
        if not await tab.js("document.body.innerText.includes('Submit clip')"):
            return {"ok": False, "message": "the campaign page shows no 'Submit clip' (not joined or signed out)"}
        await tab.click_text("Submit clip")
        await asyncio.sleep(4)
        filled = await tab.js("""(() => {
          const i = [...document.querySelectorAll('input[type=url]')].find(e => e.offsetParent !== null);
          if (!i) return false;
          i.focus();
          const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
          set.call(i, %s); i.dispatchEvent(new Event('input', {bubbles: true}));
          i.dispatchEvent(new Event('change', {bubbles: true}));
          return true; })()""" % json.dumps(post_url))
        if not filled:
            return {"ok": False, "message": "the submit form has no clip link field"}
        await asyncio.sleep(3)
        await tab.js("""(() => { const c = [...document.querySelectorAll('input[type=checkbox]')]
          .find(e => e.offsetParent !== null && /requirements/i.test((e.labels && e.labels[0] && e.labels[0].innerText) || ''));
          if (c && !c.checked) c.click(); return !!c; })()""")
        await asyncio.sleep(1)
        state = await tab.js("""(() => { const d = [...document.querySelectorAll('[role=dialog]')]
          .find(x => /Clip link|Submit clip/.test(x.innerText)); return d ? d.innerText.slice(0, 1200) : ''; })()""") or ""
        if any(w in state.lower() for w in ("can't be used", "not from a linked account", "already submitted")):
            msg = next(w for w in FAIL_WORDS if w in state.lower())
            return {"ok": False, "message": f"Content Rewards refused before submitting: {msg}", "form": state[:400],
                    "proof": await _proof(tab, item_id)}
        btn = await tab.js("""(() => { const d = [...document.querySelectorAll('[role=dialog]')]
          .find(x => /Clip link/.test(x.innerText)); if (!d) return null;
          const b = [...d.querySelectorAll('button')].filter(e => (e.innerText || '').trim() === 'Submit clip').pop();
          if (!b || b.disabled) return null; const r = b.getBoundingClientRect();
          return [r.x + r.width / 2, r.y + r.height / 2]; })()""")
        if not btn:
            return {"ok": False, "message": "Submit stayed disabled (the link was not accepted)", "form": state[:400],
                    "proof": await _proof(tab, item_id)}
        for k in ("mouseMoved", "mousePressed", "mouseReleased"):
            await tab.cmd("Input.dispatchMouseEvent", {"type": k, "x": btn[0], "y": btn[1], "button": "left",
                                                       "clickCount": 1})
        await asyncio.sleep(8)
        after = (await tab.js("document.body.innerText") or "")[:4000].lower()
        proof = await _proof(tab, item_id)
        if any(w in after for w in OK_WORDS) and not any(w in after for w in ("can't be used", "already submitted")):
            return {"ok": True, "message": "submitted", "proof": proof}
        bad = next((w for w in FAIL_WORDS if w in after), "no confirmation shown")
        return {"ok": False, "message": f"no confirmation after Submit ({bad})", "proof": proof}


async def _proof(tab, item_id: str) -> str:
    try:
        shot = await tab.cmd("Page.captureScreenshot", {"format": "png"})
        PROOFS.mkdir(parents=True, exist_ok=True)
        path = PROOFS / f"{item_id or 'clip'}_{int(time.time())}.png"
        path.write_bytes(base64.b64decode(shot.get("data") or b""))
        return str(path)
    except Exception as e:  # noqa: BLE001 - the submission result matters more than its picture
        print(f"campaign submit: screenshot failed ({type(e).__name__})")
        return ""


def submit(campaign_url: str, post_url: str, item_id: str = "", runner=None) -> dict:
    if not supported(campaign_url):
        return {"ok": False, "message": "no submit adapter for this marketplace yet"}
    from .kick import _run_hard
    run = runner or (lambda: _submit(campaign_url, post_url, item_id))
    try:
        return _run_hard(run, 120)
    except Exception as e:  # noqa: BLE001 - reported to the owner by after_post
        return {"ok": False, "message": f"{type(e).__name__}: {str(e)[:160]}"}


def after_post(it: dict, links: dict[str, str], campaign: dict, posted_at: float | None = None, submitter=None,
               notify=None, log=print) -> dict:
    """Right after a campaign clip is posted: submit it, record it, tell the owner."""
    posted_at = posted_at or time.time()
    url = pick_link(links, campaign.get("platforms"))
    if not url:
        res = {"ok": False, "message": "posted on no platform this campaign allows"}
    elif time.time() - posted_at > WINDOW_S:
        res = {"ok": False, "message": "more than 30 minutes since posting: the campaign no longer accepts it"}
    else:
        res = (submitter or submit)(campaign.get("url") or "", url, it.get("id", ""))
    res["post_url"] = url
    try:
        from . import campaign_safety as cs, db
        conn = cs.connect(db.connect())
        conn.execute("INSERT INTO submissions(campaign_id, account, post_url, posted_at, submitted_at, status, notes) "
                     "VALUES (?,?,?,?,?,?,?)", (campaign.get("id"), it.get("channel"), url, posted_at,
                                               time.time() if res.get("ok") else None,
                                               "submitted" if res.get("ok") else "not_submitted",
                                               json.dumps({"auto": True, **{k: res.get(k) for k in ("message", "proof")}})))
        conn.commit()
    except Exception as e:  # noqa: BLE001 - the owner message below still goes out
        log(f"campaign submit: not recorded ({type(e).__name__}: {e})")
    text = (f"💰 Submitted to {campaign.get('name') or 'the campaign'} automatically: {url}" if res.get("ok") else
            f"⚠️ Campaign clip NOT submitted ({res.get('message')}). Link: {url or '-'}")
    try:
        (notify or _notify)(text)
    except Exception as e:  # noqa: BLE001
        log(f"campaign submit notify: {e}")
    log(text)
    return res


def _notify(text: str) -> None:
    from .telegram_bot import send
    send(text)


def is_frozen(it: dict) -> bool:
    """A campaign post that was submitted must never be edited, re-titled, re-uploaded or deleted (Content Rewards
    rejects edited or deleted posts)."""
    return bool(it.get("campaign_submitted_at"))
