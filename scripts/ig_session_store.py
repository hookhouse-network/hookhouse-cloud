"""Keep Instagram logins across browser restarts without passwords: save the Instagram session cookies of the
private windows (scripts/ig_signup accounts) to data/secrets/ig_session_<user>.json, or load one into the main profile
of the (hidden) HookHouse Chrome. Owner 19 Nov: "your browser popup opening bothers me, do it silently".
python -m scripts.ig_session_store save          (all private windows)
python -m scripts.ig_session_store load <user>   (main profile becomes that Instagram account)"""
import asyncio
import json
import sys

from engine.config import ROOT
from scripts.ig_context_login import Browser, username

SECRETS = ROOT / "data" / "secrets"
KEEP = ("name", "value", "domain", "path", "secure", "httpOnly", "sameSite", "expires")


def _clean(cookies):
    return [{k: c[k] for k in KEEP if k in c and not (k == "expires" and c[k] in (-1, None))}
            for c in cookies if c["domain"].endswith("instagram.com")]


async def save():
    async with Browser() as b:
        for ctx in (await b.cmd("Target.getBrowserContexts")).get("browserContextIds", []):
            user = await username(b, ctx)
            if not user:
                continue
            ck = _clean((await b.cmd("Storage.getCookies", {"browserContextId": ctx})).get("cookies", []))
            (SECRETS / f"ig_session_{user}.json").write_text(json.dumps(ck), encoding="utf-8")
            print(f"saved Instagram login: @{user} ({len(ck)} cookies)")


async def load(user: str):
    p = SECRETS / f"ig_session_{user}.json"
    if not p.exists():
        print(f"no saved login for @{user}")
        return
    async with Browser() as b:
        await b.cmd("Storage.setCookies", {"cookies": json.loads(p.read_text(encoding="utf-8"))})
    print(f"main profile is now logged in to Instagram as @{user}")


if __name__ == "__main__":
    asyncio.run(save() if sys.argv[1] == "save" else load(sys.argv[2]))
