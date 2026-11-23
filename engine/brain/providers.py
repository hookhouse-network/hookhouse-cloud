"""Connections to free AI models. Each provider turns a prompt into text.

Errors are classified so the router knows whether to wait a minute,
skip the provider for the day, or just try the next one.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess

import requests

TIMEOUT = 120


class ProviderError(Exception):
    """kind: rate_limit | daily_quota | timeout | error | unavailable | too_big | busy. retry_s: how long the provider
    itself said to wait (None = unknown: the router uses the kind's default rest)."""

    def __init__(self, kind: str, message: str, retry_s: float | None = None):
        super().__init__(message)
        self.kind = kind
        self.retry_s = retry_s


def _classify_429(text: str) -> str:
    t = text.lower()
    daily_markers = ("per day", "perday", "daily", "requests per day", "tokens per day", "rpd", "tpd")
    return "daily_quota" if any(m in t for m in daily_markers) else "rate_limit"


_UNITS = {"h": 3600.0, "m": 60.0, "s": 1.0, "ms": 0.001}


def retry_after(resp) -> float | None:
    """Seconds the provider says to wait: the Retry-After header, Google's RetryInfo ("retryDelay": "41249s") or
    Groq's message ("Please try again in 7m12.5s"). 24 Nov: Groq's gpt-oss-120b was rested 12 hours for a "tokens per
    day" limit (Groq counts a rolling 24 hours and frees tokens within minutes) and answered normally at 02:00 while
    the PC wrote scripts with weaker models."""
    try:
        h = (getattr(resp, "headers", None) or {}).get("retry-after")
        if h and str(h).strip().replace(".", "", 1).isdigit():
            return float(h)
    except (AttributeError, TypeError, ValueError):
        pass
    text = getattr(resp, "text", "") or ""
    m = re.search(r'"retryDelay"\s*:\s*"(\d+(?:\.\d+)?)s"', text)
    if m:
        return float(m.group(1))
    m = re.search(r"try again in ((?:\d+(?:\.\d+)?(?:h|ms|m|s))+)", text, re.I)
    if m:
        return sum(float(n) * _UNITS[u.lower()] for n, u in re.findall(r"(\d+(?:\.\d+)?)(ms|h|m|s)", m.group(1), re.I))
    return None


def _raise_for_status(resp: requests.Response, name: str) -> None:
    if resp.status_code == 429:
        raise ProviderError(_classify_429(resp.text), f"{name}: 429 {resp.text[:300]}", retry_s=retry_after(resp))
    if resp.status_code == 413 or "request too large" in resp.text.lower():
        raise ProviderError("too_big", f"{name}: request too large for its free per-minute limit")
    if resp.status_code == 503:
        raise ProviderError("busy", f"{name}: 503 busy (high demand)")
    if resp.status_code in (401, 403):
        raise ProviderError("unavailable", f"{name}: key rejected ({resp.status_code})")
    if resp.status_code >= 400:
        raise ProviderError("error", f"{name}: HTTP {resp.status_code} {resp.text[:300]}")


class Provider:
    name = "base"

    def available(self) -> bool:
        raise NotImplementedError

    def complete(self, prompt: str, system: str = "", temperature: float = 0.7) -> str:
        raise NotImplementedError


class GeminiProvider(Provider):
    def __init__(self, name: str, model: str, key_env: str):
        self.name, self.model, self.key_env = name, model, key_env

    def available(self) -> bool:
        return bool(os.environ.get(self.key_env))

    def complete(self, prompt: str, system: str = "", temperature: float = 0.7) -> str:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        body = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": temperature},
        }
        if system and self.model.startswith("gemma"):      # Gemma models refuse a separate system instruction
            body["contents"][0]["parts"][0]["text"] = f"{system}\n\n{prompt}"
        elif system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        try:
            resp = requests.post(url, json=body, timeout=TIMEOUT,
                                 headers={"x-goog-api-key": os.environ[self.key_env]})
        except requests.RequestException as e:
            raise ProviderError("error", f"{self.name}: {e}") from e
        _raise_for_status(resp, self.name)
        data = resp.json()
        _cut_off(((data.get("candidates") or [{}])[0] or {}).get("finishReason"), self.name)
        try:
            parts = data["candidates"][0]["content"]["parts"]
            return "".join(p.get("text", "") for p in parts).strip()
        except (KeyError, IndexError) as e:
            raise ProviderError("error", f"{self.name}: unexpected reply {str(data)[:300]}") from e


def _cut_off(reason, name: str) -> None:
    """24 Nov: a script reply was cut off mid-JSON at a model's output limit ("Unbalanced JSON in reply"); the retry
    went to the same model and Clutch Tales lost its slot. A reply the model itself reports as cut off (Gemini
    finishReason MAX_TOKENS, chat-completions finish_reason "length") is "too_big" for this model: the router asks the
    next model at once, with no rest."""
    if str(reason or "").upper() in ("MAX_TOKENS", "LENGTH"):
        raise ProviderError("too_big", f"{name}: reply cut off at the model's output limit")


class OpenAICompatibleProvider(Provider):
    """Groq, NVIDIA NIM and OpenRouter all speak the same 'chat completions' format."""

    def __init__(self, name: str, base_url: str, model: str, key_env: str):
        self.name, self.base_url, self.model, self.key_env = name, base_url.rstrip("/"), model, key_env

    def _url(self) -> str:
        """base_url may name env values as ${NAME} (Cloudflare Workers AI puts the account id in the path)."""
        return os.path.expandvars(self.base_url)

    def available(self) -> bool:
        return bool(os.environ.get(self.key_env)) and "$" not in self._url()

    def complete(self, prompt: str, system: str = "", temperature: float = 0.7) -> str:
        messages = ([{"role": "system", "content": system}] if system else []) + [
            {"role": "user", "content": prompt}]
        try:
            resp = requests.post(
                f"{self._url()}/chat/completions",
                json={"model": self.model, "messages": messages, "temperature": temperature},
                headers={"Authorization": f"Bearer {os.environ[self.key_env]}"},
                timeout=TIMEOUT,
            )
        except requests.RequestException as e:
            raise ProviderError("error", f"{self.name}: {e}") from e
        _raise_for_status(resp, self.name)
        data = resp.json()
        _cut_off(((data.get("choices") or [{}])[0] or {}).get("finish_reason"), self.name)
        try:
            return (data["choices"][0]["message"]["content"] or "").strip()
        except (KeyError, IndexError) as e:
            raise ProviderError("error", f"{self.name}: unexpected reply {str(data)[:300]}") from e


class ClaudeCLIProvider(Provider):
    """Uses the Claude Code CLI on your PC. Only for building/testing (needs USE_CLAUDE_CLI=1)."""

    def __init__(self, name: str = "claude_cli", enabled_env: str = "USE_CLAUDE_CLI"):
        self.name, self.enabled_env = name, enabled_env

    def available(self) -> bool:
        return os.environ.get(self.enabled_env) == "1" and shutil.which("claude") is not None

    def complete(self, prompt: str, system: str = "", temperature: float = 0.7) -> str:
        full = f"{system}\n\n{prompt}" if system else prompt
        try:
            out = subprocess.run([shutil.which("claude"), "-p"], input=full, capture_output=True,
                                 text=True, encoding="utf-8", timeout=1800)   # long-video scripts can take 15+ min
        except subprocess.TimeoutExpired as e:          # slow, not broken: rest only briefly (settings: timeout)
            raise ProviderError("timeout", f"claude_cli: {e}") from e
        except OSError as e:
            raise ProviderError("error", f"claude_cli: {e}") from e
        if out.returncode != 0:
            raise ProviderError("error", f"claude_cli: {out.stderr[:300]}")
        return out.stdout.strip()


def build(name: str, cfg: dict) -> Provider:
    kind = cfg.get("kind")
    if kind == "gemini":
        return GeminiProvider(name, cfg["model"], cfg["key_env"])
    if kind == "openai_compatible":
        return OpenAICompatibleProvider(name, cfg["base_url"], cfg["model"], cfg["key_env"])
    if kind == "claude_cli":
        return ClaudeCLIProvider(name, cfg.get("enabled_env", "USE_CLAUDE_CLI"))
    raise ValueError(f"Unknown provider kind '{kind}' for {name}")
