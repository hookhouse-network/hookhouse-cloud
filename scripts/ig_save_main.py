"""Save the Instagram logins kept in the main HookHouse Chrome profile's account switcher into
data/secrets/ig_session_<user>.json (switch to each, copy its cookies), so every account can be handled the same way
(scripts/ig_bio_all, hidden windows). python -m scripts.ig_save_main <username> [...]"""
import asyncio
import json
import sys

from engine.config import ROOT
from scripts.ig_context_login import Browser
from scripts.meta_link_ig import ig_switch

KEEP = ("name", "value", "domain", "path", "secure", "httpOnly", "sameSite", "expires")


async def main(users):
    for u in users:
        sw = await ig_switch(u)
        if sw not in ("already", "switched"):
            print(f"@{u}: {sw}")
            continue
        async with Browser() as b:
            ck = [c for c in (await b.cmd("Storage.getCookies")).get("cookies", []) if c["domain"].endswith("instagram.com")]
        ck = [{k: c[k] for k in KEEP if k in c and not (k == "expires" and c[k] in (-1, None))} for c in ck]
        (ROOT / "data" / "secrets" / f"ig_session_{u}.json").write_text(json.dumps(ck), encoding="utf-8")
        print(f"@{u}: login saved ({len(ck)} cookies)")

if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
