"""File storage in the private GitHub repo's releases (free, no card; each file up to 2 GB, no total-size limit per
GitHub's docs). Used for the encrypted state bundle and the finished video folders."""
from __future__ import annotations

import os

import requests

API = "https://api.github.com"
UPLOADS = "https://uploads.github.com"


class StoreError(RuntimeError):
    pass


# 18 Nov (owner approved): the CODE runs in a public repo (unlimited free Actions minutes, 4-core machines) while
# the memory bundle, videos and campaign footage stay in the PRIVATE repo's releases (STORE_REPO + STORE_TOKEN).
def repo() -> str:
    """Where files are stored (the private repo)."""
    r = os.environ.get("STORE_REPO") or os.environ.get("HOOKHOUSE_REPO") or os.environ.get("GITHUB_REPOSITORY", "")
    if not r:
        raise StoreError("no repository set (STORE_REPO, HOOKHOUSE_REPO or GITHUB_REPOSITORY)")
    return r


def code_repo() -> str:
    """Where the cloud runs are started (the public code repo)."""
    r = os.environ.get("CODE_REPO") or os.environ.get("GITHUB_REPOSITORY") or os.environ.get("HOOKHOUSE_REPO", "")
    if not r:
        raise StoreError("no code repository set (CODE_REPO or GITHUB_REPOSITORY)")
    return r


_CLI_TOKEN = ""              # the GitHub CLI's token, once read (this process)


def token() -> str:
    """24 Nov: every Store asked the GitHub CLI again; under load `gh auth token` took 8 s and once timed out (20 s),
    and the PC helper stopped with "no GitHub token". The CLI's answer is kept for the process (the helper restarts
    with every code update anyway)."""
    global _CLI_TOKEN
    t = (os.environ.get("STORE_TOKEN") or os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
         or os.environ.get("HOOKHOUSE_GH_TOKEN", ""))
    if not t and _CLI_TOKEN:
        return _CLI_TOKEN
    if not t:                                    # the PC helper: the GitHub CLI login made during cloud setup
        try:
            import subprocess
            from .setup import _gh
            t = subprocess.run([_gh(), "auth", "token"], capture_output=True, text=True, timeout=20).stdout.strip()
        except Exception:  # noqa: BLE001
            t = ""
        _CLI_TOKEN = t
    if not t:
        raise StoreError("no GitHub token (GITHUB_TOKEN in Actions, GH_TOKEN on the PC)")
    return t


class Store:
    def __init__(self, session=None, repository: str | None = None, gh_token: str | None = None):
        self.s = session or requests.Session()
        self.repo = repository or repo()
        self.h = {"Authorization": f"Bearer {gh_token or token()}", "Accept": "application/vnd.github+json",
                  "X-GitHub-Api-Version": "2022-11-28"}
        self._rel: dict[str, dict] = {}

    # ----- releases -----
    def release(self, tag: str) -> dict:
        if tag in self._rel:
            return self._rel[tag]
        r = self.s.get(f"{API}/repos/{self.repo}/releases/tags/{tag}", headers=self.h, timeout=30)
        if r.status_code == 404:
            r = self.s.post(f"{API}/repos/{self.repo}/releases", headers=self.h, timeout=30,
                            json={"tag_name": tag, "name": f"HookHouse {tag}", "prerelease": True,
                                  "body": "Managed by HookHouse (state / finished videos). Do not edit by hand."})
            if r.status_code == 422 and "already_exists" in r.text:     # 18 Nov: farm machines raced to create it
                r = self.s.get(f"{API}/repos/{self.repo}/releases/tags/{tag}", headers=self.h, timeout=30)
        if r.status_code not in (200, 201):
            raise StoreError(f"release {tag}: {r.status_code} {r.text[:200]}")
        self._rel[tag] = r.json()
        return self._rel[tag]

    def assets(self, tag: str) -> dict[str, dict]:
        rel = self.release(tag)
        out, page = {}, 1
        while True:
            r = self.s.get(f"{API}/repos/{self.repo}/releases/{rel['id']}/assets", headers=self.h, timeout=30,
                           params={"per_page": 100, "page": page})
            if r.status_code != 200:
                raise StoreError(f"assets {tag}: {r.status_code}")
            batch = r.json()
            out.update({a["name"]: a for a in batch})
            if len(batch) < 100:
                return out
            page += 1

    def get(self, tag: str, name: str) -> bytes | None:
        a = self.assets(tag).get(name)
        if not a:
            return None
        r = self.s.get(f"{API}/repos/{self.repo}/releases/assets/{a['id']}", timeout=300,
                       headers=dict(self.h, Accept="application/octet-stream"))
        if r.status_code != 200:
            raise StoreError(f"download {name}: {r.status_code}")
        return r.content

    def delete(self, tag: str, name: str) -> bool:
        a = self.assets(tag).get(name)
        if not a:
            return False
        r = self.s.delete(f"{API}/repos/{self.repo}/releases/assets/{a['id']}", headers=self.h, timeout=30)
        return r.status_code == 204

    def put(self, tag: str, name: str, data: bytes, content_type: str = "application/octet-stream") -> dict:
        rel = self.release(tag)
        for attempt in range(3):
            self.delete(tag, name)                   # GitHub refuses a second asset with the same name
            r = self.s.post(f"{UPLOADS}/repos/{self.repo}/releases/{rel['id']}/assets", params={"name": name},
                            headers=dict(self.h, **{"Content-Type": content_type}), data=data, timeout=900)
            if r.status_code == 422 and "already_exists" in r.text and attempt < 2:
                continue                             # another writer slipped in between delete and upload
            break
        if r.status_code not in (200, 201):
            raise StoreError(f"upload {name}: {r.status_code} {r.text[:200]}")
        return r.json()
