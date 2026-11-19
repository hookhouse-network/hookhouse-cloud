"""One-time move to the cloud: `python cli.py cloud setup` (after the owner's two logins: GitHub CLI and a Cloudflare
API token). Everything is free and needs no card.

1. A private GitHub repo with the code (data/, output/, .env and caches are never uploaded).
2. A STATE_KEY for the encrypted memory bundle; all keys stored as encrypted GitHub Actions secrets.
3. A Cloudflare KV namespace + the Telegram front door Worker (deployed with wrangler); the Worker gets the bot
   token, the owner's chat id, a GitHub token to start runs, and a random webhook secret.
4. Telegram's webhook pointed at the Worker (the PC bot stops polling; the PC becomes the helper).
5. The current memory (plans, databases, logins) uploaded as the first state bundle.
Each step is safe to run again."""
from __future__ import annotations

import os
import re
import secrets as pysecrets
import shutil
import subprocess
from pathlib import Path

import requests

from ..config import ROOT
from engine.core.http import HTTP

REPO_NAME = "hookhouse"
LOCAL_ONLY = {"HOOKHOUSE_CLOUD", "HOOKHOUSE_REPO", "CODE_REPO", "GH_TOKEN", "USE_CLAUDE_CLI"}     # PC settings, not sent to the cloud
CF = "https://api.cloudflare.com/client/v4"


def _run(cmd: list[str], check: bool = True, input_text: str | None = None, env: dict | None = None,
         cwd: Path = ROOT) -> str:
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", input=input_text,
                       env=dict(os.environ, **(env or {})), cwd=str(cwd))
    if check and r.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd[:3])}: {(r.stderr or r.stdout).strip()[:300]}")
    return r.stdout.strip()


def _gh() -> str:
    exe = shutil.which("gh") or next((str(p) for p in (Path(os.environ.get("ProgramFiles", "C:/Program Files")) /
                                                        "GitHub CLI" / "gh.exe",) if p.exists()), "")
    if not exe:
        raise RuntimeError("GitHub CLI not installed: winget install --id GitHub.cli")
    return exe


def _git(args: list[str], cwd: Path | None = None, check: bool = True) -> str:
    gh = _gh().replace("\\", "/")
    return _run(["git", "-c", "credential.helper=", "-c", f"credential.helper=!'{gh}' auth git-credential", *args],
                check=check, env={"GCM_INTERACTIVE": "never", "GIT_TERMINAL_PROMPT": "0"}, cwd=cwd or ROOT)


def _git_push(*args: str, check: bool = True) -> str:
    """git push with the GitHub CLI's login for this one command (no login window, no global git settings).
    A plain push (no args) also publishes the code to the public code repo (publish_code)."""
    out = _git(["push", *args], check=check)
    if not args:
        publish_code()
    return out


# 18 Nov (owner approved "code public"): the cloud runs from a PUBLIC repo (unlimited free minutes) that holds only a
# cleaned copy of the code: fresh history under a generic author, no owner notes, no PC paths. Memory, videos and
# footage stay in the private repo (cloud.store). The private repo stays the one we commit to.
PUBLIC_DIR = ROOT / "data" / "pc" / "public_repo"
PUBLIC_SKIP = ("docs/", "research_notes/", "config/owner_todo.yaml", "CLAUDE.md", "README.md")
PUBLIC_AUTHOR = ("HookHouse", "hookhouse-network@users.noreply.github.com")
_USER_PATH = re.compile(r"C:[\\/]+Users[\\/]+[^\\/\s'\"`]+", re.I)


def public_files(root: Path = ROOT) -> list[str]:
    """The tracked files that go public (everything committed except PUBLIC_SKIP)."""
    names = _run(["git", "ls-files"], cwd=root).splitlines()
    return [n for n in names if n and not n.startswith(PUBLIC_SKIP)]


def publish_code(log=print) -> bool:
    """Copy the committed code (HEAD) into the public repo clone, scrub PC paths, commit as HookHouse, push."""
    import shutil
    import tarfile
    import tempfile
    full = read_env().get("CODE_REPO") or os.environ.get("CODE_REPO")
    if not full:
        return False
    if not (PUBLIC_DIR / ".git").exists():
        PUBLIC_DIR.parent.mkdir(parents=True, exist_ok=True)
        _git(["clone", f"https://github.com/{full}.git", str(PUBLIC_DIR)])
    keep = set(public_files())
    with tempfile.TemporaryDirectory() as tmp:
        tar = Path(tmp) / "head.tar"
        _run(["git", "archive", "--format=tar", "-o", str(tar), "HEAD"], cwd=ROOT)
        with tarfile.open(tar) as t:
            t.extractall(Path(tmp) / "src", members=[m for m in t.getmembers() if m.name in keep])
        for p in PUBLIC_DIR.iterdir():                      # mirror: what left the private tree leaves here too
            if p.name != ".git":
                shutil.rmtree(p) if p.is_dir() else p.unlink()
        for name in keep:
            src, dst = Path(tmp) / "src" / name, PUBLIC_DIR / name
            if not src.exists():
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            data = src.read_bytes()
            try:
                txt = data.decode("utf-8")
                if _USER_PATH.search(txt):
                    data = _USER_PATH.sub("C:/Users/<user>", txt).encode("utf-8")    # maps to itself
            except UnicodeDecodeError:
                pass
            dst.write_bytes(data)
    (PUBLIC_DIR / "README.md").write_text(
        "# HookHouse cloud\n\nThe code of an automated video + books studio. It runs on GitHub Actions and a "
        "Cloudflare Worker; its memory, keys and videos are private.\n", encoding="utf-8")
    _run(["git", "add", "-A"], cwd=PUBLIC_DIR)
    if not _run(["git", "status", "--porcelain"], cwd=PUBLIC_DIR).strip():
        return False
    subject = _run(["git", "log", "-1", "--format=%s"], cwd=ROOT).strip() or "Update"
    name, mail = PUBLIC_AUTHOR
    _run(["git", "-c", f"user.name={name}", "-c", f"user.email={mail}", "commit", "-q", "-m", subject], cwd=PUBLIC_DIR)
    _git(["push", "origin", "HEAD:main"], cwd=PUBLIC_DIR)
    log(f"code published to {full}")
    return True


def read_env(path: Path = ROOT / ".env") -> dict[str, str]:
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines() if path.exists() else []:
        m = re.match(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$", line)
        if m and not line.lstrip().startswith("#"):
            out[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    return out


def set_env(key: str, value: str, path: Path = ROOT / ".env") -> None:
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    lines = [ln for ln in lines if not re.match(rf"\s*{re.escape(key)}\s*=", ln)] + [f"{key}={value}"]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.environ[key] = value


def cloud_env_text(env: dict[str, str]) -> str:
    """The .env the cloud jobs get (one secret, HOOKHOUSE_ENV): every key except PC-only settings."""
    return "\n".join(f"{k}={v}" for k, v in sorted(env.items()) if k not in LOCAL_ONLY and v) + "\n"


ENV_SENT = ROOT / "data" / "state" / "env_secret.sha"


def sync_env_secret(log=print, force: bool = False) -> bool:
    """Self-heal (18 Nov: the cloud said 'nvidia: no key, openrouter: no key' while the PC had both, so every video
    failed once Gemini and Groq hit their daily limits). Re-sends the cloud's .env (HOOKHOUSE_ENV secret) whenever
    the PC's .env changed. Only a fingerprint is kept; values are never printed."""
    import hashlib
    env = read_env()
    full = env.get("CODE_REPO") or env.get("HOOKHOUSE_REPO")     # the runs live in the public code repo (18 Nov)
    if not full:
        return False
    text = cloud_env_text(env)
    sha = hashlib.sha256(text.encode()).hexdigest()
    if not force and ENV_SENT.exists() and ENV_SENT.read_text(encoding="utf-8").strip() == sha:
        return False
    gh_secret(full, "HOOKHOUSE_ENV", text)
    ENV_SENT.parent.mkdir(parents=True, exist_ok=True)
    ENV_SENT.write_text(sha, encoding="utf-8")
    log(f"cloud keys refreshed ({len(text.splitlines())} settings)")
    return True


def ensure_gitignore() -> None:
    p = ROOT / ".gitignore"
    have = p.read_text(encoding="utf-8") if p.exists() else ""
    need = ["data/", "output/", "backups/", "research_archive/", ".env", "*.mp4", "*.wav", "*.mp3", "__pycache__/",
            ".pytest_cache/", "*.zip", "cloud/worker/.wrangler/", "node_modules/"]
    add = [x for x in need if x not in have.splitlines()]
    if add:
        p.write_text(have.rstrip() + "\n# cloud setup\n" + "\n".join(add) + "\n", encoding="utf-8")


def repo_and_push(log=print) -> str:
    gh = _gh()
    user = _run([gh, "api", "user", "-q", ".login"])
    full = f"{user}/{REPO_NAME}"
    ensure_gitignore()
    if not (ROOT / ".git").exists():
        _run(["git", "init", "-b", "main"])
    _run(["git", "add", "-A"])
    _run(["git", "-c", "user.name=HookHouse", "-c", "user.email=hookhouse@users.noreply.github.com", "commit", "-q",
          "-m", "HookHouse code"], check=False)
    exists = subprocess.run([gh, "repo", "view", full], capture_output=True).returncode == 0
    if not exists:
        _run([gh, "repo", "create", full, "--private", "--source", str(ROOT), "--remote", "origin", "--push"])
        log(f"private repo created: {full}")
    else:
        if "origin" not in _run(["git", "remote"], check=False).split():
            _run(["git", "remote", "add", "origin", f"https://github.com/{full}.git"])
        _git_push("-q", "-u", "origin", "main")
        log(f"code pushed to {full}")
    return full


def gh_secret(full: str, name: str, value: str) -> None:
    _run([_gh(), "secret", "set", name, "--repo", full], input_text=value)


def cf_kv_namespace(acct: str, token: str, title: str = "hookhouse") -> str:
    h = {"Authorization": f"Bearer {token}"}
    r = HTTP.get(f"{CF}/accounts/{acct}/storage/kv/namespaces", headers=h, params={"per_page": 100}, timeout=30)
    r.raise_for_status()
    for ns in r.json().get("result", []):
        if ns.get("title") == title:
            return ns["id"]
    r = requests.post(f"{CF}/accounts/{acct}/storage/kv/namespaces", headers=h, json={"title": title}, timeout=30)
    r.raise_for_status()
    return r.json()["result"]["id"]


def cf_subdomain(acct: str, token: str) -> str:
    r = HTTP.get(f"{CF}/accounts/{acct}/workers/subdomain", headers={"Authorization": f"Bearer {token}"}, timeout=30)
    r.raise_for_status()
    return r.json()["result"]["subdomain"]


def deploy_worker(full: str, env: dict[str, str], kv_id: str, log=print) -> str:
    wdir = ROOT / "cloud" / "worker"
    toml = wdir / "wrangler.toml"
    t = toml.read_text(encoding="utf-8")
    t = re.sub(r'id = "[^"]*"', f'id = "{kv_id}"', t)
    toml.write_text(t, encoding="utf-8")
    cfenv = {"CLOUDFLARE_API_TOKEN": env["CLOUDFLARE_API_TOKEN"], "CLOUDFLARE_ACCOUNT_ID": env["CLOUDFLARE_ACCOUNT_ID"]}
    npx = shutil.which("npx") or "npx"
    _run([npx, "--yes", "wrangler", "deploy", "--config", str(toml), "--var", f"GH_REPO:{full}"], env=cfenv, cwd=wdir)
    tg_secret = env.get("TG_WEBHOOK_SECRET") or pysecrets.token_urlsafe(24)
    set_env("TG_WEBHOOK_SECRET", tg_secret)
    gh_token = _run([_gh(), "auth", "token"])
    for name, value in (("TG_TOKEN", env["TELEGRAM_BOT_TOKEN"]), ("OWNER_CHAT", env["TELEGRAM_CHAT_ID"]),
                        ("TG_SECRET", tg_secret), ("GH_TOKEN", gh_token)):
        _run([npx, "--yes", "wrangler", "secret", "put", name, "--config", str(toml)], input_text=value, env=cfenv, cwd=wdir)
    url = f"https://hookhouse-bot.{cf_subdomain(env['CLOUDFLARE_ACCOUNT_ID'], env['CLOUDFLARE_API_TOKEN'])}.workers.dev/tg"
    log(f"Telegram front door deployed: {url.rsplit('/', 1)[0]}")
    return url


def set_webhook(bot_token: str, url: str, secret: str) -> None:
    r = requests.post(f"https://api.telegram.org/bot{bot_token}/setWebhook", timeout=30,
                      json={"url": url, "secret_token": secret, "allowed_updates": ["message", "callback_query"]})
    if not r.json().get("ok"):
        raise RuntimeError(f"Telegram refused the webhook: {r.text[:200]}")


def missing(env: dict[str, str]) -> list[str]:
    need = ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_API_TOKEN"]
    return [k for k in need if not env.get(k)]


def run(log=print) -> str:
    env = read_env()
    gaps = missing(env)
    if gaps:
        raise RuntimeError("first add to .env: " + ", ".join(gaps))
    if not env.get("STATE_KEY"):
        from .state import new_key
        set_env("STATE_KEY", new_key())
        env = read_env()
    full = repo_and_push(log)
    set_env("HOOKHOUSE_REPO", full)
    kv_id = cf_kv_namespace(env["CLOUDFLARE_ACCOUNT_ID"], env["CLOUDFLARE_API_TOKEN"])
    env = read_env()
    for name, value in (("STATE_KEY", env["STATE_KEY"]), ("CLOUDFLARE_ACCOUNT_ID", env["CLOUDFLARE_ACCOUNT_ID"]),
                        ("CLOUDFLARE_API_TOKEN", env["CLOUDFLARE_API_TOKEN"]), ("CF_KV_NAMESPACE_ID", kv_id),
                        ("HOOKHOUSE_ENV", cloud_env_text(env))):
        gh_secret(full, name, value)
    log("keys stored as encrypted GitHub secrets")
    url = deploy_worker(full, env, kv_id, log)
    env = read_env()
    set_webhook(env["TELEGRAM_BOT_TOKEN"], url, env["TG_WEBHOOK_SECRET"])
    log("Telegram now talks to the cloud")
    from . import state
    from .store import Store
    os.environ["STATE_KEY"] = env["STATE_KEY"]
    size = state.push(Store(repository=full, gh_token=_run([_gh(), "auth", "token"])))
    log(f"memory uploaded ({size // 1024} KB)")
    set_env("HOOKHOUSE_CLOUD", "1")
    _run(["git", "add", "-A"])
    _run(["git", "-c", "user.name=HookHouse", "-c", "user.email=hookhouse@users.noreply.github.com", "commit", "-q",
          "-m", "Cloud: Worker KV id"], check=False)
    _git_push("-q", check=False)
    return full
