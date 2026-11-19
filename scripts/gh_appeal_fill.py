"""Fill GitHub's reinstatement form (visible HookHouse Chrome). Leaves the policy checkbox and Continue to the owner.
python -m scripts.gh_appeal_fill"""
import asyncio
import json
import sys
import urllib.request

import websockets

SUBJECT = "Appeal: hookhouse-network suspended, heavy Actions jobs removed"
BODY = """Hello GitHub Support,

My account hookhouse-network was suspended on 18 November 2026. I believe the cause is a set of heavy GitHub Actions jobs I started that day, and I would like to explain and fix it.

What the account is for: it holds the code of my small media project (HookHouse), Python code that writes, renders and schedules videos for my own YouTube channels, plus a Cloudflare Worker for a Telegram control bot. Two repositories: hookhouse-network/hookhouse (private: code plus my project's encrypted data and finished video files) and hookhouse-network/hookhouse-cloud (public copy of the same code, created on 18 Nov).

What went wrong: on 18 Nov I added a workflow (pictures.yml) to the public repository that ran an open-source image model on many runners in parallel for several hours, up to 23 concurrent jobs, to draw illustrations for my books and channel artwork. I now understand this is outside acceptable use of Actions: it is not building, testing or deploying the software, and it put unreasonable load on shared runners. That was my mistake. There was no crypto mining, no abuse of other users and no attempt to hide activity.

What I have done: the image workflow has been deleted from the code (the change will be pushed as soon as I have access), the remaining scheduled rendering is reduced to one short run a day, and image generation will move to a service intended for model inference. Remaining workflows will be light and bounded (tests on push, a few short scheduled jobs). I will keep within the Terms of Service and the Actions acceptable-use rules, and I am happy to delete or make private the public repository if you prefer.

My request: please reinstate the account, or at least restore access so I can download my private repository's data (code, encrypted project data and release files) and remove anything you consider out of policy.

Thank you for your time.
hookhouse-network"""

JS = r'''((subject, body) => {
  const set = (el, v) => { const p = el.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(p, "value").set.call(el, v); el.dispatchEvent(new Event("input", {bubbles: true}));
    el.dispatchEvent(new Event("change", {bubbles: true})); };
  const q = n => document.querySelector(`[name="${n}"]`);
  set(q("contact_next[subject]"), subject);
  set(q("contact_next[description]"), body);
  set(q("contact_next[impacted-username]"), "hookhouse-network (repositories: hookhouse-network/hookhouse, hookhouse-network/hookhouse-cloud)");
  const pick = (name, text) => { const r = [...document.querySelectorAll(`input[name="${name}"]`)].find(i =>
      ((i.closest("label") || i.parentElement).innerText || "").trim().startsWith(text)); if (r) { r.click(); return r.checked; } return false; };
  return JSON.stringify({platform: pick("contact_next[platform]", "GitHub"),
    reason: pick("contact_next[reinstatement-reason]", "My account was disabled"),
    contacted: pick("contact_next[previously-contacted]", "No"),
    subject: q("contact_next[subject]").value.length, body: q("contact_next[description]").value.length});
})(%s, %s)'''


async def main():
    tab = next(t for t in json.loads(urllib.request.urlopen("http://127.0.0.1:9333/json/list").read())
               if t["type"] == "page" and "help.github" in t["url"])
    async with websockets.connect(tab["webSocketDebuggerUrl"], max_size=2 ** 24) as ws:
        await ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate",
                                  "params": {"expression": JS % (json.dumps(SUBJECT), json.dumps(BODY)),
                                             "returnByValue": True}}))
        while True:
            r = json.loads(await ws.recv())
            if r.get("id") == 1:
                sys.stdout.write(str(r["result"]["result"].get("value")) + "\n")
                break
        await ws.send(json.dumps({"id": 2, "method": "Page.bringToFront"}))


if __name__ == "__main__":
    asyncio.run(main())
