"""One command for a new Instagram account, no owner needed (owner 19 Nov): sign-up form -> password, birthday and
Gmail code -> picture + bio (read back) -> Creator profile -> login kept in data/secrets -> handle in the config.
python -m scripts.ig_new_account <channel_id>"""
import asyncio
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(mod: str, *args, timeout=420) -> str:
    r = subprocess.run([sys.executable, "-m", mod, *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=timeout, env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"})
    return (r.stdout + r.stderr).strip()


def handle_now() -> str:
    from scripts.ig_signup import js
    return asyncio.run(js('([...document.querySelectorAll("a[href]")].map(a => a.getAttribute("href")).filter(h => '
                          '/^\\/[a-z0-9._]+\\/$/.test(h) && !/^\\/(reels|explore|direct|accounts)\\/$/.test(h))[0] || "")'
                          '.replace(/\\//g, "")')) or ""


def set_handle(cid: str, handle: str) -> None:
    p = ROOT / "config" / "links.yaml"
    s = p.read_text(encoding="utf-8")
    s2 = re.sub(rf'^({cid}:\s*\{{[^}}]*?instagram: )"[^"]*"(, )(?:instagram_live: true, )?',
                rf'\1"{handle}"\2instagram_live: true, ', s, flags=re.M)
    p.write_text(s2, encoding="utf-8")
    for f in (ROOT / "config" / "channels").glob(f"*{cid}*.yaml"):
        t = f.read_text(encoding="utf-8")
        f.write_text(re.sub(r'"instagram": "[^"]*"', f'"instagram": "{handle}"', t, count=1), encoding="utf-8")


def main(cid: str):
    out = run("scripts.ig_signup", cid)
    print(out.splitlines()[-1] if out else "sign-up: no output")
    if "ready for the owner" not in out:
        return
    fin = run("scripts.ig_signup_finish", cid)
    print("finish:", fin.splitlines()[-1][:160] if fin else "-")
    for _ in range(12):                                    # the account appears a few seconds after the code
        h = handle_now()
        if h and h != "popular":
            break
        time.sleep(5)
    else:
        print("account not confirmed yet: check the sign-up window")
        return
    print("created:", "@" + h)
    print("profile:", run("scripts.ig_profile", cid).replace("\n", " | ")[-120:])
    time.sleep(3)
    print("bio:", [ln for ln in run("scripts.ig_bio", cid).splitlines() if "matches" in ln])
    print("creator:", run("scripts.ig_creator").splitlines()[-1:])
    print("login:", run("scripts.ig_session_store", "save").splitlines()[-1:])
    set_handle(cid, h)
    print(f"config: {cid} -> @{h} (instagram_live)")


if __name__ == "__main__":
    main(sys.argv[1])
