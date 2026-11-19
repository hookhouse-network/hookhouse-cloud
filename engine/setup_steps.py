"""Setup assistant: the steps, the key checks and the savers (no browser here, so everything is testable).

Owner, 12 Nov 2026: "prepare a playwright script for all the account setups and required key setups".
What the assistant does by itself: opens every page in the right order, shows each text with a Copy button, picks
up keys from the page the moment they appear (developer pages only), checks every key with the service's own API,
saves it (.env / data/secrets), connects the channels, writes the YouTube channel pages, fills config/links.yaml and
ticks the to-do list. What only the owner may do (the sites' rules, and passwords are never shared with Claude):
sign in, type passwords and codes, phone/ID checks, captchas, accept terms, press "Create". New accounts are paced at
3 per platform per day so the platforms don't flag them.
"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import date

import requests

from .config import ROOT, channels

ENV = ROOT / ".env"
PROGRESS = ROOT / "data" / "state" / "setup_progress.json"
SECRETS = ROOT / "data" / "secrets"
PACE_PER_DAY = 3
YT_ORDER = [1, 2, 5, 6, 3, 11, 12, 13, 4, 7, 8, 9, 14, 10]       # docs/owner_setup_guide.md, phase 2


# ----------------------------------------------------------------------------------------------- saving
def save_env(name: str, value: str) -> None:
    """Write NAME=value into .env (replacing an old line) and into this process. Values are never printed."""
    value = str(value).strip().replace("\n", " ")
    lines = ENV.read_text(encoding="utf-8").splitlines() if ENV.exists() else []
    out, done = [], False
    for ln in lines:
        if ln.split("=", 1)[0].strip() == name:
            if not done:
                out.append(f"{name}={value}")
            done = True
        else:
            out.append(ln)
    if not done:
        out.append(f"{name}={value}")
    ENV.write_text("\n".join(out) + "\n", encoding="utf-8")
    os.environ[name] = value


def env_file_value(name: str) -> str:
    """Read straight from .env (another process, e.g. the bot, may have written it)."""
    for ln in ENV.read_text(encoding="utf-8").splitlines() if ENV.exists() else []:
        k, _, v = ln.partition("=")
        if k.strip() == name:
            return v.strip()
    return ""


def progress() -> dict:
    try:
        return json.loads(PROGRESS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_progress(p: dict) -> None:
    PROGRESS.parent.mkdir(parents=True, exist_ok=True)
    PROGRESS.write_text(json.dumps(p, indent=1), encoding="utf-8")


def mark(step_id: str, what: str = "done") -> None:
    p = progress()
    if what == "created" and step_id in p.get("created", {}):
        return                                     # keep the first date: pacing counts real creation days
    p.setdefault(what, {})[step_id] = time.time()
    _save_progress(p)


def created_today(family: str) -> int:
    """New accounts of one platform family marked today (the assistant keeps it at 3 a day)."""
    today = date.today().isoformat()
    ids = {s["id"] for s in steps() if s["family"] == family}
    return sum(1 for sid, ts in progress().get("created", {}).items()
               if sid in ids and date.fromtimestamp(ts).isoformat() == today)


def set_project(project_id: str) -> None:
    if re.fullmatch(r"[a-z][a-z0-9-]{4,29}", project_id or ""):
        p = progress()
        p["gcloud_project"] = project_id
        _save_progress(p)


# ----------------------------------------------------------------------------------------------- key checks
def _ok(r) -> bool:
    return getattr(r, "status_code", 0) == 200


def _get(s, url, **kw):
    try:
        return s.get(url, timeout=20, **kw)
    except requests.RequestException:
        return None


def check_telegram(v, s=requests):
    r = _get(s, f"https://api.telegram.org/bot{v}/getMe")
    d = r.json() if r is not None and _ok(r) else {}
    if d.get("ok"):
        return True, f"bot @{d['result'].get('username')} found"
    return False, "Telegram doesn't know this token"


def check_gemini(v, s=requests):
    r = _get(s, "https://generativelanguage.googleapis.com/v1beta/models", params={"key": v, "pageSize": 1})
    return (True, "Gemini answered") if r is not None and _ok(r) else (False, "Gemini refused this key")


def _bearer(url, name):
    def check(v, s=requests):
        r = _get(s, url, headers={"Authorization": f"Bearer {v}"})
        return (True, f"{name} answered") if r is not None and _ok(r) else (False, f"{name} refused this key")
    return check


check_groq = _bearer("https://api.groq.com/openai/v1/models", "Groq")
check_openrouter = _bearer("https://openrouter.ai/api/v1/key", "OpenRouter")
check_nvidia = _bearer("https://integrate.api.nvidia.com/v1/models", "NVIDIA")
check_cerebras = _bearer("https://api.cerebras.ai/v1/models", "Cerebras")
check_pollinations = _bearer("https://gen.pollinations.ai/v1/models", "Pollinations")


def check_hf(v, s=requests):
    r = _get(s, "https://huggingface.co/api/whoami-v2", headers={"Authorization": f"Bearer {v}"})
    if r is not None and _ok(r):
        return True, f"Hugging Face account {r.json().get('name', '')}"
    return False, "Hugging Face refused this token"


def check_pexels(v, s=requests):
    r = _get(s, "https://api.pexels.com/v1/search", params={"query": "ocean", "per_page": 1}, headers={"Authorization": v})
    return (True, "Pexels answered") if r is not None and _ok(r) else (False, "Pexels refused this key")


def check_cloudflare_token(v, s=requests):
    r = _get(s, "https://api.cloudflare.com/client/v4/user/tokens/verify", headers={"Authorization": f"Bearer {v}"})
    if r is not None and _ok(r) and r.json().get("success"):
        return True, "Cloudflare token is active"
    acc = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")
    if acc:                                                    # account-owned tokens are checked per account
        r = _get(s, f"https://api.cloudflare.com/client/v4/accounts/{acc}/tokens/verify",
                 headers={"Authorization": f"Bearer {v}"})
        if r is not None and _ok(r) and r.json().get("success"):
            return True, "Cloudflare token is active"
    return False, "Cloudflare refused this token"


def check_cloudflare_account(v, s=requests):
    return (True, "account id looks right") if re.fullmatch(r"[0-9a-f]{32}", v) else (False, "an account id is 32 letters/numbers (0-9, a-f)")


def check_youtube_key(v, s=requests):
    r = _get(s, "https://www.googleapis.com/youtube/v3/videos",
             params={"part": "id", "chart": "mostPopular", "maxResults": 1, "key": v})
    if r is not None and _ok(r):
        return True, "YouTube Data API answered"
    return False, "YouTube refused this key (is the YouTube Data API enabled in the project?)"


def check_client_id(v, s=requests):
    ok = bool(re.fullmatch(r"\d{6,}-[a-z0-9]{10,}\.apps\.googleusercontent\.com", v))
    return (True, "looks right (Google checks it when the first channel connects)") if ok else (False, "a Client ID ends in .apps.googleusercontent.com")


def check_client_secret(v, s=requests):
    return (True, "looks right") if re.fullmatch(r"GOCSPX-[A-Za-z0-9_\-]{20,}", v) else (False, "a client secret starts with GOCSPX-")


def check_meta_secret(v, s=requests):
    app = os.environ.get("META_APP_ID", "")
    if not re.fullmatch(r"[0-9a-f]{32}", v):
        return False, "the App Secret is 32 letters/numbers (0-9, a-f)"
    if not app:
        return True, "saved (it's checked together with the App ID)"
    r = _get(s, "https://graph.facebook.com/oauth/access_token",
             params={"client_id": app, "client_secret": v, "grant_type": "client_credentials"})
    return (True, "Meta accepted the App ID + Secret") if r is not None and _ok(r) else (False, "Meta refused this App ID + Secret pair")


def check_meta_app_id(v, s=requests):
    return (True, "looks right") if re.fullmatch(r"\d{10,20}", v) else (False, "the App ID is a long number")


def check_hf_token(v, s=requests):
    """Who is this token, and has that account accepted the Indic Parler-TTS terms? (free, no card)"""
    if not re.fullmatch(r"hf_[A-Za-z0-9]{30,}", v):
        return False, "a Hugging Face token starts with hf_"
    r = _get(s, "https://huggingface.co/api/whoami-v2", headers={"Authorization": f"Bearer {v}"})
    if r is None:
        return False, "couldn't reach Hugging Face (internet?)"
    if not _ok(r):
        return False, "Hugging Face refused this token"
    m = _get(s, "https://huggingface.co/ai4bharat/indic-parler-tts/resolve/main/config.json",
             headers={"Authorization": f"Bearer {v}"})
    if m is None or not _ok(m):
        return False, "token works, but press 'Agree and access repository' on the Indic Parler-TTS page first"
    return True, "works: the natural Hindi voice is ready"


def check_google_tts_key(v, s=requests):
    """Lists Google's Hindi voices with the key: proves the key works and the Text-to-Speech API is on, spends nothing."""
    if not re.fullmatch(r"AIza[0-9A-Za-z_\-]{35}", v):
        return False, "a Google API key starts with AIza and is 39 characters"
    r = _get(s, "https://texttospeech.googleapis.com/v1/voices", params={"languageCode": "hi-IN", "key": v})
    if r is None:
        return False, "couldn't reach Google (internet?)"
    if not _ok(r):
        return False, "Google refused it: switch on 'Cloud Text-to-Speech API' (and billing) in the project"
    names = [x.get("name", "") for x in (r.json().get("voices") or [])]
    hd = [n for n in names if "Chirp3-HD" in n]
    return (True, f"works: {len(hd)} natural Hindi voices ready") if hd else (True, "works (no Chirp 3 HD voices listed yet)")


def check_threads_app_id(v, s=requests):
    return (True, "looks right") if re.fullmatch(r"\d{10,20}", v) else (False, "the Threads app ID is a long number")


def check_threads_secret(v, s=requests):
    app = os.environ.get("THREADS_APP_ID", "")
    if not re.fullmatch(r"[0-9a-f]{32}", v):
        return False, "the Threads app secret is 32 letters/numbers (0-9, a-f)"
    if not app:
        return True, "saved (it's checked together with the Threads app ID)"
    r = _get(s, "https://graph.threads.net/oauth/access_token",
             params={"client_id": app, "client_secret": v, "grant_type": "client_credentials"})
    return (True, "Threads accepted the app ID + secret") if r is not None and _ok(r) else (False, "Threads refused this app ID + secret pair")


def check_threads_redirect(v, s=requests):
    host = v.split("//", 1)[-1].split("/", 1)[0].lower()
    if not v.startswith("https://") or "@" in host or host.split(":")[0] in ("localhost", "127.0.0.1"):
        return False, "Threads needs an https link that isn't localhost (e.g. your HookHouse site + /threads)"
    return True, "saved: put exactly this link in the Threads settings too"


def _amazon(suffix):
    def check(v, s=requests):
        ok = bool(re.fullmatch(r"[a-z0-9][a-z0-9-]{1,60}" + suffix, v))
        return (True, "looks right") if ok else (False, f"Amazon tags end in {suffix}")
    return check


def check_contact_url(v, s=requests):
    host = v.split("//", 1)[-1].split("/", 1)[0]
    if not v.startswith("https://") or "@" in host or v.lower().startswith("mailto"):
        return False, "use a web page link (https://...), never an email address"
    return True, "saved"


def check_postal(v, s=requests):
    ok = len(v) >= 12 and any(c.isdigit() for c in v)
    return (True, "saved: it goes at the bottom of outreach emails") if ok else (False, "a full postal address with PIN code, e.g. PO Box 12, Andheri, Mumbai 400053, India")


# name -> label, check, capture pattern, pages the assistant may read it from (developer pages only, never social apps)
KEYS = {
    "TELEGRAM_BOT_TOKEN": ("Telegram bot token", check_telegram, r"\b\d{8,10}:[A-Za-z0-9_-]{35}\b", ["web.telegram.org"]),
    "GEMINI_API_KEY": ("Gemini API key", check_gemini, r"\bAIza[0-9A-Za-z_\-]{35}\b", ["aistudio.google.com"]),
    "GROQ_API_KEY": ("Groq API key", check_groq, r"\bgsk_[A-Za-z0-9]{40,60}\b", ["console.groq.com"]),
    "OPENROUTER_API_KEY": ("OpenRouter key", check_openrouter, r"\bsk-or-v1-[0-9a-f]{64}\b", ["openrouter.ai"]),
    "NVIDIA_API_KEY": ("NVIDIA key", check_nvidia, r"\bnvapi-[A-Za-z0-9_\-]{60,70}\b", ["build.nvidia.com", "org.ngc.nvidia.com"]),
    "CEREBRAS_API_KEY": ("Cerebras key", check_cerebras, r"\bcsk-[A-Za-z0-9]{40,60}\b", ["cloud.cerebras.ai"]),
    "POLLINATIONS_KEY": ("Pollinations key", check_pollinations, r"\bsk_[A-Za-z0-9]{20,80}\b", ["enter.pollinations.ai"]),
    "PEXELS_API_KEY": ("Pexels API key", check_pexels, r"\b[A-Za-z0-9]{56}\b", ["www.pexels.com"]),
    "CLOUDFLARE_ACCOUNT_ID": ("Cloudflare account id", check_cloudflare_account, r"dash\.cloudflare\.com/([0-9a-f]{32})", ["dash.cloudflare.com"]),
    "CLOUDFLARE_API_TOKEN": ("Cloudflare API token", check_cloudflare_token, r"\b[A-Za-z0-9_\-]{40,60}\b", ["dash.cloudflare.com"]),
    "YOUTUBE_API_KEY": ("YouTube API key", check_youtube_key, r"\bAIza[0-9A-Za-z_\-]{35}\b", ["console.cloud.google.com"]),
    "GOOGLE_TTS_API_KEY": ("Google voice key", check_google_tts_key, "", []),
    "HF_TOKEN": ("Hugging Face token", check_hf_token, r"\bhf_[A-Za-z0-9]{30,}\b", ["huggingface.co"]),
    "YOUTUBE_CLIENT_ID": ("Client ID", check_client_id, r"\b\d{6,}-[a-z0-9]{10,}\.apps\.googleusercontent\.com\b", ["console.cloud.google.com"]),
    "YOUTUBE_CLIENT_SECRET": ("Client secret", check_client_secret, r"\bGOCSPX-[A-Za-z0-9_\-]{20,}\b", ["console.cloud.google.com"]),
    "META_APP_ID": ("Meta App ID", check_meta_app_id, r"developers\.facebook\.com/apps/(\d{10,20})", ["developers.facebook.com"]),
    "META_APP_SECRET": ("Meta App Secret", check_meta_secret, r"\b[0-9a-f]{32}\b", ["developers.facebook.com"]),
    "THREADS_APP_ID": ("Threads app ID", check_threads_app_id, "", []),
    "THREADS_APP_SECRET": ("Threads app secret", check_threads_secret, "", []),
    "THREADS_REDIRECT_URI": ("Threads return link (only if Meta refused the default)", check_threads_redirect, "", []),
    "AMAZON_COM_TAG": ("amazon.com tag", _amazon("-20"), "", []),
    "AMAZON_IN_TAG": ("amazon.in tag", _amazon("-21"), "", []),
    "CONTACT_URL": ("Contact page link", check_contact_url, "", []),
    "POSTAL_ADDRESS": ("Postal address for outreach emails", check_postal, "", []),
}


def check_key(name: str, value: str, s=requests) -> tuple[bool, str]:
    spec = KEYS.get(name)
    value = str(value or "").strip()
    if not spec:
        return False, "unknown key"
    if not value:
        return False, "empty"
    try:
        return spec[1](value, s)
    except Exception as e:  # noqa: BLE001 - a check must never crash the assistant
        return False, f"couldn't check it ({type(e).__name__})"


def submit_key(name: str, value: str, s=requests) -> tuple[bool, str]:
    """Check, then save into .env."""
    ok, msg = check_key(name, value, s)
    if ok:
        save_env(name, str(value).strip())
    return ok, msg


def candidates(name: str, text: str, url: str = "") -> list[str]:
    """Possible keys of this kind on a page (its text + field values, or its address)."""
    spec = KEYS.get(name)
    if not spec or not spec[2]:
        return []
    src = url if spec[2].startswith(("dash\\.", "developers\\.")) else text
    found = re.findall(spec[2], src or "")
    used = {os.environ.get(k, "") for k in KEYS if k != name}
    seen, out = set(), []
    for f in found:
        if f not in seen and f not in used:
            seen.add(f)
            out.append(f)
    return out[:6]


def google_client_from_json(raw: str) -> tuple[str, str] | None:
    """The 'Download JSON' file of a Google OAuth client -> (client id, secret)."""
    try:
        d = json.loads(raw)
    except ValueError:
        return None
    for k in ("installed", "web"):
        if isinstance(d.get(k), dict) and d[k].get("client_id") and d[k].get("client_secret"):
            return d[k]["client_id"], d[k]["client_secret"]
    return None


# ----------------------------------------------------------------------------------------------- connections
def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def meta_connect(user_token: str, s=requests) -> list[str]:
    """One token from Graph API Explorer connects every channel: Pages + their Instagram accounts are matched to
    our channels by name / username and saved (60-day user token, Page tokens that don't expire)."""
    from .connect import meta_long_lived, save_meta
    from .publish import GRAPH
    tok, exp = meta_long_lived(user_token.strip(), s)
    r = s.get(f"{GRAPH}/me/accounts", params={"fields": "id,name,access_token,instagram_business_account{id,username}",
                                              "limit": 100, "access_token": tok}, timeout=30)
    r.raise_for_status()
    pages = r.json().get("data") or []
    out = []
    for ch in channels():
        if ch.get("type") == "kids":
            continue
        names = {_norm(ch["name"])}
        igs = {_norm(h) for k, h in (ch.get("handles") or {}).items() if k.startswith("instagram")}
        page = next((p for p in pages if _norm(p.get("name")) in names or
                     _norm((p.get("instagram_business_account") or {}).get("username")) in igs), None)
        if not page:
            continue
        ig = (page.get("instagram_business_account") or {}).get("id", "")
        user_tok, user_exp = tok, exp
        old_f = SECRETS / f"meta_{ch['id']}.json"
        if not ig and old_f.exists():               # 18 Nov: a reconnect wiped working Instagram links (the IG account
            old = json.loads(old_f.read_text(encoding="utf-8"))     # isn't linked to the Page, so Meta didn't list it)
            if old.get("ig_user_id"):
                ig, user_tok, user_exp = old["ig_user_id"], old.get("access_token") or tok, old.get("expires_at") or exp
        save_meta(ch["id"], ig, page["id"], user_tok, page.get("access_token", ""), s, exchange=False,
                  expires_at=user_exp)
        uname = (page.get("instagram_business_account") or {}).get("username")
        if uname:
            from . import links
            links.set_link(ch["id"], instagram=uname)
        out.append(f"{ch['name']}: Facebook Page" + (f" + Instagram @{uname}" if uname else " (no Instagram linked yet)"))
    if not out:
        out.append(f"No Page matched a channel name. Pages seen: {', '.join(p.get('name', '?') for p in pages[:13]) or 'none'}")
    return out


def instagram_login(token: str, s=requests) -> str:
    """'Instagram API with Instagram Login' token -> which channel it belongs to (by username) -> saved."""
    from .connect import save_meta
    r = s.get("https://graph.instagram.com/me", params={"fields": "user_id,username", "access_token": token.strip()},
              timeout=30)
    if not _ok(r):
        return "Instagram refused this token"
    d = r.json()
    uname = _norm(d.get("username"))
    ch = next((c for c in channels() if uname and uname in {_norm(h) for k, h in (c.get("handles") or {}).items()
                                                            if k.startswith("instagram")}), None)
    if not ch:
        return f"@{d.get('username')} doesn't match a channel's Instagram name in config/channels (fix the handle there)"
    save_meta(ch["id"], str(d.get("user_id") or d.get("id")), "", token.strip(), session=s, login="instagram")
    from . import links
    links.set_link(ch["id"], instagram=d.get("username"))
    return f"{ch['name']}: Instagram @{d.get('username')} connected"


def dailymotion(client_id: str, client_secret: str, profile_id: str = "", s=requests) -> str:
    """Partner API key + secret (+ profile id) -> checked with Dailymotion's token endpoint -> data/secrets."""
    from .publish import DM_TOKEN
    client_id, client_secret, profile_id = (str(x or "").strip() for x in (client_id, client_secret, profile_id))
    try:
        r = s.post(DM_TOKEN, data={"grant_type": "client_credentials", "client_id": client_id,
                                   "client_secret": client_secret, "scope": "video.upload video.write"}, timeout=30)
    except requests.RequestException as e:
        return f"Couldn't reach Dailymotion ({type(e).__name__})"
    if not _ok(r):
        return "Dailymotion refused this key + secret"
    if not profile_id:
        return "Key works. Now paste the profile id too (Studio > the channel's settings) and press Save again."
    SECRETS.mkdir(parents=True, exist_ok=True)
    rec = {"client_id": client_id, "client_secret": client_secret,
           "profiles": {c["id"]: profile_id for c in channels() if c.get("type") != "clips"}}
    (SECRETS / "dailymotion.json").write_text(json.dumps(rec), encoding="utf-8")
    return "✅ Dailymotion saved: every channel's own videos go there after your approval"


def telegram_channel(channel_id: str, handle: str, s=requests) -> str:
    """A public Telegram channel for one of our channels: is it there, and is the bot an admin who may post?"""
    tok = os.environ.get("TELEGRAM_BOT_TOKEN") or env_file_value("TELEGRAM_BOT_TOKEN")
    if not tok:
        return "Do the Telegram bot step first"
    handle = "@" + str(handle or "").strip().lstrip("@").split("/")[-1]
    api = f"https://api.telegram.org/bot{tok}"
    me = _get(s, f"{api}/getMe")
    if me is None or not _ok(me):
        return "The bot token doesn't work"
    bot_id = me.json()["result"]["id"]
    chat = _get(s, f"{api}/getChat", params={"chat_id": handle})
    if chat is None or not _ok(chat):
        return f"Telegram can't find {handle} (make it a public channel with that @name)"
    mem = _get(s, f"{api}/getChatMember", params={"chat_id": handle, "user_id": bot_id})
    st = (mem.json().get("result") or {}) if mem is not None and _ok(mem) else {}
    if st.get("status") not in ("administrator", "creator") or st.get("can_post_messages") is False:
        return f"Add the bot to {handle} as an admin with 'Post messages' on, then press Check again"
    from . import links
    links.set_link(channel_id, telegram=handle)
    return f"✅ {handle} saved: new videos post there automatically"


def pair_poll(code_file, deadline_s: int = 900, s=requests, sleep=time.sleep) -> str:
    """Wait until the owner sends the pairing code to the bot (or the running bot pairs it)."""
    from . import telegram_bot as tb
    tok = os.environ.get("TELEGRAM_BOT_TOKEN") or env_file_value("TELEGRAM_BOT_TOKEN")
    offset, end = None, time.time() + deadline_s
    while time.time() < end:
        chat = env_file_value("TELEGRAM_CHAT_ID")
        if chat:
            os.environ["TELEGRAM_CHAT_ID"] = chat
            return "✅ Paired: this phone now controls HookHouse"
        r = _get(s, f"https://api.telegram.org/bot{tok}/getUpdates", params={"timeout": 0, **({"offset": offset} if offset else {})})
        if r is not None and _ok(r):
            for upd in r.json().get("result") or []:
                offset = upd["update_id"] + 1
                msg = upd.get("message") or {}
                if msg and tb._try_pair(str(msg["chat"]["id"]), (msg.get("text") or "").strip()):
                    return "✅ Paired: this phone now controls HookHouse"
        sleep(2)                                              # 409 = the bot is running and will pair it itself
    return "Timed out. Press Pair again and send the new code."


# ----------------------------------------------------------------------------------------------- the steps
def _gc(path: str) -> str:
    proj = progress().get("gcloud_project")
    return f"https://console.cloud.google.com/{path}" + (f"{'&' if '?' in path else '?'}project={proj}" if proj else "")


def _img(ch: dict, *names: str) -> list[str]:
    return [f"output/brand/{ch['id']}/{n}" for n in names if (ROOT / "output" / "brand" / ch["id"] / n).exists()]


def steps() -> list[dict]:
    """Every setup step, grouped by platform (same groups as the to-do list)."""
    chs = {c["number"]: c for c in channels()}
    S = []

    def add(group, sid, title, **kw):
        S.append({"group": group, "id": sid, "title": title, "why": kw.pop("why", ""), "links": kw.pop("links", []),
                  "you": kw.pop("you", []), "auto": kw.pop("auto", []), "copy": kw.pop("copy", []),
                  "fields": kw.pop("fields", []), "actions": kw.pop("actions", []), "images": kw.pop("images", []),
                  "scan": kw.pop("scan", []), "rule": kw.pop("rule", "manual"), "todo": kw.pop("todo", ""),
                  "family": kw.pop("family", ""), "optional": kw.pop("optional", False)})

    add("Start here", "welcome", "How this assistant works",
        why="It opens every sign-up and key page in order and does the copying, checking and saving for you.",
        you=["Sign in, type passwords and codes, do phone/ID checks and captchas, accept terms, press Create. "
             "The sites only allow a person to do these, and your passwords never leave you.",
             "Create at most 3 new accounts per platform per day; the assistant counts for you.",
             "If Google says \"This browser or app may not be secure\", switch 'Open pages in' (top right) to "
             "'my normal browser' and paste keys into the boxes instead."],
        auto=["Opens each page", "Copy buttons for every name, handle and bio", "Picks up keys from developer pages "
              "and checks them with the service itself", "Saves keys to .env and logins to data/secrets",
              "Connects channels and writes the YouTube channel pages", "Ticks your to-do list"])

    G = "Google & Gmail"
    add(G, "gmail", "Business Gmail + backup Gmail", todo="gmail", family="google",
        links=[{"label": "Create the Gmail", "url": "https://accounts.google.com/signup"},
               {"label": "2-Step Verification", "url": "https://myaccount.google.com/signinoptions/twosv"},
               {"label": "Recovery email", "url": "https://myaccount.google.com/recovery/email"}],
        you=["Create hookhouse.media@gmail.com (else hookhousestudio, hookhouse.hq) with your real birthday and phone",
             "Turn on 2-Step Verification, then create hookhouse.backup@gmail.com and set it as the recovery email"],
        copy=[{"label": "First name", "text": "HookHouse"}, {"label": "Last name", "text": "Media"},
              {"label": "Username 1", "text": "hookhouse.media"}, {"label": "Username 2", "text": "hookhousestudio"},
              {"label": "Username 3", "text": "hookhouse.hq"}, {"label": "Backup username", "text": "hookhouse.backup"}])
    add(G, "bitwarden", "Password manager (Bitwarden, free)", links=[{"label": "Open Bitwarden", "url": "https://vault.bitwarden.com/#/register"}],
        you=["Create the account with the HookHouse Gmail; save every password and backup code there from now on"])
    add(G, "gcloud_project", "Google Cloud project", links=[{"label": "Create the project", "url": "https://console.cloud.google.com/projectcreate"}],
        you=["Sign in with the HookHouse Gmail, paste the name, press Create"],
        auto=["Reads the project id from the address bar, so every next link opens inside your project"],
        copy=[{"label": "Project name", "text": "hookhouse-media"}], rule="project")
    add(G, "gcloud_apis", "Switch on the 3 Google APIs",
        links=[{"label": "YouTube Data API", "url": _gc("apis/library/youtube.googleapis.com")},
               {"label": "YouTube Analytics API", "url": _gc("apis/library/youtubeanalytics.googleapis.com")},
               {"label": "Gmail API (outreach)", "url": _gc("apis/library/gmail.googleapis.com")}],
        you=["Open each one and press Enable"])
    add(G, "gcloud_consent", "Google sign-in screen (published)",
        links=[{"label": "Sign-in screen", "url": _gc("auth/overview")}, {"label": "Audience: Publish app", "url": _gc("auth/audience")}],
        you=["App name below, User type External, support + developer email = the HookHouse Gmail",
             "On Audience press Publish app (In production). In Testing, Google logs the system out every 7 days."],
        copy=[{"label": "App name", "text": "HookHouse Publisher"}])
    add(G, "gcloud_client", "Google sign-in key (OAuth client: Desktop app)", todo="google_oauth",
        links=[{"label": "Create the OAuth client", "url": _gc("auth/clients/create")}],
        you=["Application type Desktop app, name below, press Create, then Download JSON (or leave the dialog open)"],
        auto=["Catches the downloaded file or reads the dialog, checks both values and saves them"],
        copy=[{"label": "Client name", "text": "HookHouse PC"}],
        fields=[{"id": "YOUTUBE_CLIENT_ID", "kind": "env"}, {"id": "YOUTUBE_CLIENT_SECRET", "kind": "env"}],
        scan=["YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET"], rule="env:YOUTUBE_CLIENT_ID,YOUTUBE_CLIENT_SECRET")
    add(G, "youtube_api_key", "YouTube API key (for niche research)", todo="youtube_api_key",
        links=[{"label": "Credentials page", "url": _gc("apis/credentials")}],
        you=["Create credentials > API key; restrict it to YouTube Data API v3"],
        auto=["Reads the new key from the page, checks it with YouTube and saves it"],
        fields=[{"id": "YOUTUBE_API_KEY", "kind": "env"}], scan=["YOUTUBE_API_KEY"], rule="env:YOUTUBE_API_KEY")
    add(G, "hf_voice", "Natural Hindi voice (Indic Parler-TTS, free, no card)", todo="hf_voice",
        why="A human, conversational Hindi narrator made in India (AI4Bharat, Apache-2.0), running on this PC. "
            "Free: only a Hugging Face account, no card.",
        links=[{"label": "Sign up", "url": "https://huggingface.co/join"},
               {"label": "Model page", "url": "https://huggingface.co/ai4bharat/indic-parler-tts"},
               {"label": "Tokens", "url": "https://huggingface.co/settings/tokens"}],
        you=["Sign up with the HookHouse Gmail (free) and confirm the email",
             "Open the model page and press 'Agree and access repository'",
             "Settings > Access Tokens > Create new token > type 'Read' > copy it and paste it below"],
        auto=["Checks the token and the model access, saves it (HF_TOKEN)"],
        fields=[{"id": "HF_TOKEN", "kind": "env"}], scan=["HF_TOKEN"], rule="env:HF_TOKEN")
    add(G, "google_tts", "Natural Hindi voice (Google Text-to-Speech, free tier)", todo="google_tts",
        why="Human, conversational Hindi narration that reads numbers and English names right. Free up to 1 million "
            "characters a month (our Hindi channels use about 100,000); the system stops at 900,000, so it never bills.",
        links=[{"label": "Switch on the API", "url": _gc("apis/library/texttospeech.googleapis.com")},
               {"label": "Billing", "url": "https://console.cloud.google.com/billing"},
               {"label": "Credentials page", "url": _gc("apis/credentials")}],
        you=["Billing: link a billing account to the HookHouse project (Google asks for a card to verify you; the free "
             "tier is not charged)",
             "Switch on 'Cloud Text-to-Speech API'",
             "Credentials > Create credentials > API key; restrict it to Cloud Text-to-Speech API; paste it below"],
        auto=["Checks the key by listing Google's Hindi voices (costs nothing) and saves it"],
        fields=[{"id": "GOOGLE_TTS_API_KEY", "kind": "env"}], rule="env:GOOGLE_TTS_API_KEY")

    T = "Telegram"
    add(T, "telegram_bot", "Your control bot (BotFather)", todo="telegram",
        links=[{"label": "BotFather in Telegram Web", "url": "https://web.telegram.org/k/#@BotFather"},
               {"label": "BotFather in the app", "url": "https://t.me/BotFather"}],
        you=["Log in to Telegram Web with the QR code from your phone (or use the app)", "Send the 3 messages below, one by one"],
        auto=["Reads the token from BotFather's answer, checks it and saves it"],
        copy=[{"label": "Message 1", "text": "/newbot"}, {"label": "Message 2 (name)", "text": "HookHouse Control"},
              {"label": "Message 3 (username)", "text": "hookhouse_control_bot"},
              {"label": "If taken", "text": "hookhouse_hq_bot"}],
        fields=[{"id": "TELEGRAM_BOT_TOKEN", "kind": "env"}], scan=["TELEGRAM_BOT_TOKEN"], rule="env:TELEGRAM_BOT_TOKEN")
    add(T, "telegram_pair", "Pair your phone", todo="telegram_pair", actions=[{"id": "pair", "label": "Give me a pairing code"}],
        you=["Press the button, then send the 6-digit code to your bot from your phone"],
        auto=["Saves your chat, so only your phone controls HookHouse"], rule="env:TELEGRAM_CHAT_ID")
    tg = [c for c in channels() if c.get("type") in ("story", "brainrot")]
    add(T, "telegram_channels", "Optional: a public Telegram channel per channel", todo="telegram_channels", optional=True,
        you=["In the Telegram app: New Channel > Public > the @name below; then Administrators > Add Admin > your bot (Post messages on)"],
        auto=["Checks the channel and the bot's rights, writes config/links.yaml; videos then post there automatically"],
        fields=[{"id": f"tg:{c['id']}", "kind": "action_input", "label": c["name"],
                 "placeholder": "@" + re.sub(r"[^a-z0-9]", "", c["name"].lower())[:28]} for c in tg],
        rule=f"links:telegram:{len(tg)}")

    P = "This PC"
    add(P, "setup_pc", "Start the autopilot with Windows", todo="setup_pc", actions=[{"id": "show:scripts/setup_pc.cmd", "label": "Show setup_pc.cmd"}],
        you=["Double-click setup_pc.cmd once (it starts the autopilot whenever you sign in)"], rule="schtask:HookHouse Autopilot")
    add(P, "voice", "Pick the Hindi narrator voice", todo="voice", you=["Send /voice to the bot and pick one"], rule="choice:hindi_voice")

    Y = "YouTube"
    for n in YT_ORDER:
        ch = chs.get(n)
        if not ch:
            continue
        h = ch.get("handles") or {}
        kids = ch.get("type") == "kids"
        add(Y, f"yt_{ch['id']}", f"{ch['name']}: YouTube channel", family="youtube",
            links=[{"label": "Create the channel", "url": "https://www.youtube.com/channel_switcher"},
                   {"label": "YouTube Studio", "url": "https://studio.youtube.com"}],
            you=["Create a channel (Brand Account) with the name below; then press Connect and pick this channel on Google's page",
                 "YouTube Studio > Customization > Profile: upload the picture below (YouTube has no API for it)",
                 "Settings > Channel > Advanced: " + ("\"Yes, set this channel as made for kids\"" if kids else "\"No, it's not made for kids\""),
                 "Settings > Permissions: invite the backup Gmail as Owner"],
            auto=["Connects it, then writes the About text, keywords, banner, country and language itself",
                  "Updates config/links.yaml with the real @handle"],
            copy=[{"label": "Channel name", "text": ch["name"]}, {"label": "Handle", "text": h.get("youtube", "")},
                  {"label": "Backup handle", "text": h.get("youtube_backup", "")}],
            images=_img(ch, "avatar.png", "youtube_banner.jpg"),
            actions=[{"id": f"connect_youtube:{ch['id']}", "label": "Connect this channel"}],
            rule=f"yt:{ch['id']}", todo="youtube_channels")
    add(Y, "youtube_verify", "Verify the channels", todo="youtube_verify",
        links=[{"label": "Verify", "url": "https://www.youtube.com/verify"}, {"label": "Features", "url": "https://www.youtube.com/features"}],
        you=["Phone for a few channels a year; ID or video verification for the rest (long videos, custom thumbnails)"])

    M = "Instagram & Facebook"
    add(M, "fb_profile", "Your Facebook profile (once)", links=[{"label": "Sign up", "url": "https://www.facebook.com/r.php"},
        {"label": "Two-factor", "url": "https://accountscenter.facebook.com/password_and_security"}],
        you=["Your real name, log in with the HookHouse Gmail, turn on two-factor"])
    for n in YT_ORDER:
        ch = chs.get(n)
        if not ch or ch.get("type") == "kids":
            continue
        h = ch.get("handles") or {}
        mail = f"hookhouse.media+{ch['id'].split('_')[0]}@gmail.com"
        add(M, f"meta_{ch['id']}", f"{ch['name']}: Facebook Page + Instagram", family="meta",
            links=[{"label": "Create the Page", "url": "https://www.facebook.com/pages/create"},
                   {"label": "Instagram sign-up", "url": "https://www.instagram.com/accounts/emailsignup/"}],
            you=["Page: name below, category Digital creator, bio below, picture + cover below",
                 "Instagram (phone app is best): sign up with the email below, username + bio below, switch to "
                 "Professional > Creator (Digital creator), then link it to the Page"],
            auto=["Connected for every channel at once in the 'Connect all Pages' step below"],
            copy=[{"label": "Page / account name", "text": ch["name"]}, {"label": "Instagram username", "text": h.get("instagram", "")},
                  {"label": "Backup username", "text": h.get("instagram_backup", "")}, {"label": "Bio", "text": ch.get("bio", "")},
                  {"label": "Sign-up email", "text": mail}, {"label": "Category", "text": "Digital creator"}],
            images=_img(ch, "avatar.png", "facebook_cover.jpg"), rule=f"meta:{ch['id']}", todo="instagram")
    add(M, "meta_app", "Meta app (App ID + App Secret)", todo="meta_app",
        links=[{"label": "Create the app", "url": "https://developers.facebook.com/apps/creation/"},
               {"label": "My apps", "url": "https://developers.facebook.com/apps/"}],
        you=["Create the app (name below; use cases: manage Pages + Instagram content), then App settings > Basic and press Show next to App Secret"],
        auto=["Reads the App ID from the address bar and the secret once shown, checks the pair with Meta and saves it"],
        copy=[{"label": "App name", "text": "HookHouse Publisher"}],
        fields=[{"id": "META_APP_ID", "kind": "env"}, {"id": "META_APP_SECRET", "kind": "env"}],
        scan=["META_APP_ID", "META_APP_SECRET"], rule="env:META_APP_ID,META_APP_SECRET")
    add(M, "meta_connect", "Connect all Pages + Instagram accounts at once",
        links=[{"label": "Graph API Explorer", "url": "https://developers.facebook.com/tools/explorer/"}],
        you=["Pick the HookHouse Publisher app, add the permissions below, press Generate Access Token and allow all Pages"],
        auto=["Reads the token, turns it into a 60-day one, finds every Page and its Instagram, matches them to our channels and saves them"],
        copy=[{"label": "Permissions", "text": "pages_show_list,pages_read_engagement,pages_manage_posts,publish_video,"
                                               "instagram_basic,instagram_content_publish,instagram_manage_insights,instagram_manage_comments,"
                                               "read_insights,business_management"}],
        fields=[{"id": "meta_token", "kind": "action_input", "label": "Access token (picked up automatically)", "placeholder": "EAA..."}],
        scan=["META_USER_TOKEN"], rule="secrets:meta:13")
    add(M, "fb_monetization", "Monthly: request Facebook Content Monetization", todo="fb_monetization", optional=True,
        links=[{"label": "Professional dashboard", "url": "https://www.facebook.com/professional_dashboard"}],
        you=["On each Page: Monetization > request Content Monetization (invite-only)"])

    add("Dailymotion", "dailymotion", "Dailymotion (one more revenue share)", todo="dailymotion", family="dailymotion",
        links=[{"label": "Sign up", "url": "https://www.dailymotion.com/signup"}, {"label": "Partner HQ", "url": "https://www.dailymotion.com/partner/"}],
        you=["Sign up with the HookHouse Gmail; in Partner HQ create a private API key (Organization settings > API keys) and copy the channel's profile id"],
        auto=["Checks the key with Dailymotion and saves it; every channel's own videos then go there automatically"],
        fields=[{"id": "dm_key", "kind": "input", "label": "API key"}, {"id": "dm_secret", "kind": "input", "label": "API secret"},
                {"id": "dm_profile", "kind": "input", "label": "Profile id"}],
        actions=[{"id": "dailymotion", "label": "Check & save"}], rule="dailymotion")

    T = "Threads, Pinterest & Snapchat"
    from .threads import redirect_uri as _th_redirect
    add(T, "threads_app", "Threads posting: add Threads to the Meta app", todo="threads",
        why="Every Reel then also goes to Threads by itself, using the Reel's own Instagram video link.",
        links=[{"label": "My apps", "url": "https://developers.facebook.com/apps/"}],
        you=["Open the HookHouse Publisher app > Use cases > Add 'Access the Threads API'; add the permissions below",
             "Use cases > Threads > Settings: paste the return link below into 'Valid OAuth Redirect URIs' and save "
             "(if Meta refuses it, use your HookHouse site link + /threads and paste that link in the box below too)",
             "Copy the Threads app ID and Threads app secret from that page into the boxes below",
             "App roles > Roles > Add People > Threads Testers: add each channel's Threads name (its Instagram name)",
             "On the phone, for each channel: Threads app > Settings > Account > Website permissions > Invites > Accept"],
        auto=["Checks the app ID + secret with Threads and saves them"],
        copy=[{"label": "Permissions", "text": "threads_basic,threads_content_publish"},
              {"label": "Return link (Redirect URI)", "text": _th_redirect()}],
        fields=[{"id": "THREADS_APP_ID", "kind": "env", "placeholder": "paste from Use cases > Threads > Settings"},
                {"id": "THREADS_APP_SECRET", "kind": "env", "placeholder": "paste from Use cases > Threads > Settings"},
                {"id": "THREADS_REDIRECT_URI", "kind": "env", "placeholder": "only if Meta refused the return link above"}],
        rule="env:THREADS_APP_ID,THREADS_APP_SECRET")
    for n in YT_ORDER:
        ch = chs.get(n)
        if not ch or ch.get("type") == "kids":
            continue
        h = ch.get("handles") or {}
        add(T, f"th_{ch['id']}", f"{ch['name']}: connect Threads",          # no new account: its Instagram
            you=[f"Press Connect, log in to Threads as @{h.get('instagram', '')} (this channel's Instagram) and allow",
                 "If Threads shows another channel, log out on threads.com first",
                 "Normal-browser mode: after allowing, copy the whole address from the address bar into the box"],
            auto=["Reads the sign-in code from the address bar, swaps it for a 60-day login and renews it by itself"],
            copy=[{"label": "Threads / Instagram name", "text": h.get("instagram", "")}],
            fields=[{"id": f"threads_code:{ch['id']}", "kind": "action_input",
                     "label": "Address after allowing (normal browser only)", "placeholder": "https://...?code=..."}],
            actions=[{"id": f"connect_threads:{ch['id']}", "label": "Connect Threads"}],
            scan=[], rule=f"threads:{ch['id']}", todo="threads")
    add(T, "pinterest_claim", "Pinterest: Pins made from Instagram by Pinterest itself", todo="pinterest_claim",
        why="Pinterest turns every Instagram post of a claimed account into a Pin (video too, on business accounts).",
        links=[{"label": "Pinterest business sign-up", "url": "https://www.pinterest.com/business/create/"},
               {"label": "Claimed accounts", "url": "https://www.pinterest.com/settings/claim"}],
        you=["One Pinterest business account per story channel + Brain Snack (not the clip channels, not Bloop), "
             "3 a day at most; start with the evergreen ones: Money Cheat Codes, Cosmos Unboxed, Deep Blue Files, "
             "Wild Instinct",
             "Settings > Claimed accounts > Instagram > Claim: log in with that channel's Instagram",
             "In the claim settings, exclude posts containing: #ad (campaign clips stay off Pinterest)",
             "When every channel is claimed, press 'Mark as done'"],
        auto=["After that Pinterest leaves the evening winners pack (it posts by itself)"])
    add(T, "snapchat", "Snapchat Public Profiles", todo="snapchat",
        links=[{"label": "Snapchat", "url": "https://www.snapchat.com/"}],
        you=["In the app, create a Public Profile for each story channel, Brain Snack and the clip channels"],
        auto=["Every evening the bot sends the winners pack for Snapchat and X (no free posting API)"])

    C = "Campaign boards"
    add(C, "content_rewards", "Content Rewards (Whop)", todo="content_rewards", links=[{"label": "Open", "url": "https://contentrewards.com"}],
        you=["Sign up with the HookHouse Gmail, finish KYC, withdraw to your INR bank account"])
    add(C, "vyro", "Vyro", todo="vyro", links=[{"label": "Open", "url": "https://vyro.com"}], you=["Sign up (PayPal)"])

    B = "Books & music"
    # Digital products (engine/digital_products.py): stores in the order they pay us (research 13 Nov)
    add(B, "payhip", "Payhip + Razorpay: the store that pays first", todo="payhip",
        links=[{"label": "Payhip", "url": "https://payhip.com/"}, {"label": "Razorpay", "url": "https://razorpay.com/"}],
        actions=[{"id": "show:data/products", "label": "Show the product kits"}],
        you=["Create a free Payhip account with the HookHouse Gmail",
             "Create a Razorpay account in your name (PAN + bank KYC), then in Payhip: Settings > Payments > connect Razorpay"
             " (PayPal often refuses Indian sellers; Razorpay settles to your bank in about 2 days and takes UPI)",
             "For each folder in data/products: Add product > Digital download, upload the files, cover.jpg, and paste "
             "the Payhip block of listing.md (CATALOGUE.md lists them all)"])
    add(B, "kdp", "Amazon KDP: activity, colouring and puzzle books", todo="kdp",
        links=[{"label": "KDP", "url": "https://kdp.amazon.com"}],
        actions=[{"id": "show:data/products", "label": "Show the book files"}],
        you=["Create each paperback with the PDF and the KDP block of its listing.md (AI content: No; cover: KDP Cover"
             " Creator with cover.jpg)"])
    add(B, "pdf_stores", "Gumroad + Teachers Pay Teachers", todo="pdf_stores",
        links=[{"label": "Gumroad", "url": "https://gumroad.com/signup"}, {"label": "TPT", "url": "https://www.teacherspayteachers.com/"}],
        actions=[{"id": "show:data/products", "label": "Show the product kits"}],
        you=["Gumroad: payout method = your Indian bank (paid in INR on Tuesdays); add every kit with its Gumroad block",
             "TPT: only the kids printables (colouring and activity books)"])
    add(B, "songs", "Bloop songs to music apps (RouteNote)", todo="songs", links=[{"label": "RouteNote", "url": "https://routenote.com/"}],
        actions=[{"id": "show:data/products/music", "label": "Show the songs"}],
        you=["Upload in the order of release.md (YouTube Content ID OFF)"])

    O = "Creator outreach"
    add(O, "gmail_outreach", "Let the system send the pitches (HookHouse Gmail, send-only)", todo="gmail_outreach",
        actions=[{"id": "connect_gmail", "label": "Connect the HookHouse Gmail"}],
        you=["Press Connect and sign in with the HookHouse Gmail (Google asks: send email only)",
             "Type the postal address that goes under each email (a PO box is fine)"],
        auto=["Pitches and follow-ups get a 📧 Send for me button in Telegram; daily limit, opt-out list"],
        fields=[{"id": "POSTAL_ADDRESS", "kind": "env"}], rule="secrets:gmail:1")

    K = "AI & free keys"
    for sid, key, label, url, todo_id in (
            ("gemini", "GEMINI_API_KEY", "Gemini", "https://aistudio.google.com/apikey", "gemini_groq"),
            ("groq", "GROQ_API_KEY", "Groq", "https://console.groq.com/keys", "gemini_groq"),
            ("openrouter", "OPENROUTER_API_KEY", "OpenRouter", "https://openrouter.ai/settings/keys", ""),
            ("nvidia", "NVIDIA_API_KEY", "NVIDIA", "https://build.nvidia.com/settings/api-keys", ""),
            ("cerebras", "CEREBRAS_API_KEY", "Cerebras", "https://cloud.cerebras.ai/platform/", ""),
            ("pollinations", "POLLINATIONS_KEY", "Pollinations (free AI pictures)", "https://enter.pollinations.ai/keys", ""),
            ("pexels", "PEXELS_API_KEY", "Pexels", "https://www.pexels.com/api/", "pexels"),
            ("hf", "HF_TOKEN", "Hugging Face (read token)", "https://huggingface.co/settings/tokens", "hf")):
        add(K, sid, f"{label} key", links=[{"label": f"Open {label}", "url": url}], todo=todo_id,
            you=["Sign in (HookHouse Gmail), create a key and leave it on screen"],
            auto=["Reads the key, checks it with the service and saves it"],
            fields=[{"id": key, "kind": "env"}], scan=[key], rule=f"env:{key}")
    add(K, "cloudflare", "Cloudflare Workers AI (free AI images)", todo="cloudflare",
        links=[{"label": "Sign up", "url": "https://dash.cloudflare.com/sign-up"},
               {"label": "API tokens", "url": "https://dash.cloudflare.com/profile/api-tokens"}],
        you=["Create a token from the 'Workers AI' template and leave it on screen; open any account page once (for the account id)"],
        auto=["Reads the account id from the address bar and the token from the page, checks and saves them"],
        fields=[{"id": "CLOUDFLARE_ACCOUNT_ID", "kind": "env"}, {"id": "CLOUDFLARE_API_TOKEN", "kind": "env"}],
        scan=["CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_API_TOKEN"], rule="env:CLOUDFLARE_ACCOUNT_ID,CLOUDFLARE_API_TOKEN")

    E = "Extra income"
    add(E, "amazon_tags", "Amazon Associates tags", todo="amazon_tags", optional=True,
        links=[{"label": "amazon.com", "url": "https://affiliate-program.amazon.com"}, {"label": "amazon.in", "url": "https://affiliate.amazon.in"}],
        you=["Sign up for both; your tracking ids end in -20 (.com) and -21 (.in)"],
        fields=[{"id": "AMAZON_COM_TAG", "kind": "env"}, {"id": "AMAZON_IN_TAG", "kind": "env"}], rule="env:AMAZON_COM_TAG,AMAZON_IN_TAG")
    add(E, "contact_url", "Contact page (never an email)", todo="contact_url", links=[{"label": "Google Sites", "url": "https://sites.google.com/new"}],
        fields=[{"id": "CONTACT_URL", "kind": "env"}], rule="env:CONTACT_URL")

    add("Finish", "doctor", "Final check of every connection", actions=[{"id": "doctor", "label": "Run the check"}],
        auto=["Tests Telegram, YouTube, Meta, Dailymotion and the PC live (read-only) and lists anything left"])
    for s in S:                                    # labels for key fields
        for f in s["fields"]:
            if f["kind"] == "env":
                f.setdefault("label", KEYS[f["id"]][0])
    return S


def status(step: dict) -> tuple[bool, str]:
    """(done, what the system sees) for one step."""
    rule = step.get("rule", "manual")
    kind, _, arg = rule.partition(":")
    if kind == "yt":
        from .publish import yt_token_path
        ok = yt_token_path(arg).exists()
        return ok, "connected" if ok else "not connected yet"
    if kind == "meta":
        ok = (SECRETS / f"meta_{arg}.json").exists()
        return ok, "connected" if ok else "not connected yet"
    if kind == "threads":
        ok = (SECRETS / f"threads_{arg}.json").exists()
        return ok, "connected" if ok else "not connected yet"
    if kind == "project":
        pid = progress().get("gcloud_project")
        return bool(pid), pid or "no project yet"
    if kind == "manual":
        ok = step["id"] in progress().get("done", {})
        if not ok and step.get("todo"):
            from . import todo
            t = next((x for x in todo.items() if x.get("id") == step["todo"]), None)
            ok = bool(t and t.get("done"))
        return ok, "done" if ok else ""
    from . import todo
    return todo.auto_status(rule)
