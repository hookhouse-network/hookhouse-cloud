"""One-time (18 Nov): give the public code repo the cloud's secrets + settings. Values are read from the PC's .env and
the GitHub CLI login and sent straight to GitHub's encrypted secrets; nothing is printed.
python -m scripts.setup_public_repo"""
import re
import subprocess

from engine.cloud.setup import ROOT, _gh, _run, cloud_env_text, gh_secret, read_env, set_env

CODE = "hookhouse-network/hookhouse-cloud"
STORE = "hookhouse-network/hookhouse"

env = read_env()
kv_id = re.search(r'id = "([^"]+)"', (ROOT / "cloud" / "worker" / "wrangler.toml").read_text(encoding="utf-8")).group(1)
token = subprocess.run([_gh(), "auth", "token"], capture_output=True, text=True, timeout=30).stdout.strip()
secrets = {"STATE_KEY": env["STATE_KEY"], "CLOUDFLARE_ACCOUNT_ID": env["CLOUDFLARE_ACCOUNT_ID"],
           "CLOUDFLARE_API_TOKEN": env["CLOUDFLARE_API_TOKEN"], "CF_KV_NAMESPACE_ID": kv_id,
           "HOOKHOUSE_ENV": cloud_env_text(env), "STORE_TOKEN": token}
for name, value in secrets.items():
    gh_secret(CODE, name, value)
    print("secret set:", name)
_run([_gh(), "variable", "set", "STORE_REPO", "--repo", CODE, "--body", STORE])
print("variable set: STORE_REPO")
set_env("CODE_REPO", CODE)
print("PC .env: CODE_REPO set")
