"""The router: sends each job to the best free AI model, and switches to the
next one automatically when a model fails or runs out of free quota."""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from ..config import data_path, settings
from .providers import Provider, ProviderError, build


class BrainError(Exception):
    pass


@dataclass
class BrainResult:
    text: str
    provider: str
    tried: list[str] = field(default_factory=list)

    def json(self):
        return extract_json(self.text)


def extract_json(text: str):
    """Pull the first JSON object/array out of a model reply (handles ```json fences and chatter)."""
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    starts = [i for i in (text.find("{"), text.find("[")) if i != -1]
    if not starts:
        raise BrainError(f"No JSON found in reply: {text[:200]}")
    start = min(starts)
    opener = text[start]
    closer = "}" if opener == "{" else "]"
    depth, in_str, escape = 0, False, False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                return json.loads(text[start:i + 1])
    raise BrainError(f"Unbalanced JSON in reply: {text[:200]}")


class Cooldowns:
    """Remembers which providers are resting (rate limit / daily quota) across runs."""

    def __init__(self, path: Path):
        self.path = path
        self.state: dict[str, float] = {}
        if path.exists():
            try:
                self.state = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                self.state = {}

    def resting(self, name: str, now: float | None = None) -> bool:
        return self.state.get(name, 0) > (now or time.time())

    def rest(self, name: str, minutes: float) -> None:
        self.state[name] = time.time() + minutes * 60
        self.path.write_text(json.dumps(self.state, indent=2), encoding="utf-8")


class Brain:
    def __init__(self, providers: dict[str, Provider] | None = None, routes: dict | None = None,
                 cooldown_minutes: dict | None = None, cooldown_file: Path | None = None):
        cfg = settings()["brain"]
        if providers is None:
            providers = {name: build(name, pcfg) for name, pcfg in cfg["providers"].items()}
        self.providers = providers
        self.routes = routes or cfg["routes"]
        self.cooldown_minutes = cooldown_minutes or cfg["cooldown_minutes"]
        self.cooldowns = Cooldowns(cooldown_file or data_path("data/state/brain_cooldowns.json"))

    def status(self) -> dict[str, str]:
        out = {}
        for name, p in self.providers.items():
            if not p.available():
                out[name] = "no key"
            elif self.cooldowns.resting(name):
                out[name] = "resting (limit reached)"
            else:
                out[name] = "ready"
        return out

    def ask(self, task: str, prompt: str, system: str = "", temperature: float = 0.7) -> BrainResult:
        route = self.routes.get(task)
        if not route:
            raise BrainError(f"Unknown task '{task}'. Known: {list(self.routes)}")
        tried, errors = [], []
        for name in route:
            p = self.providers.get(name)
            if p is None or not p.available() or self.cooldowns.resting(name):
                continue
            tried.append(name)
            try:
                text = p.complete(prompt, system=system, temperature=temperature)
                if not text:
                    raise ProviderError("error", f"{name}: empty reply")
                return BrainResult(text=text, provider=name, tried=tried)
            except ProviderError as e:
                errors.append(str(e))
                if e.kind in ("unavailable", "too_big"):   # too big for this model's limit: just try the next one
                    continue
                self.cooldowns.rest(name, self.cooldown_minutes.get(e.kind, 5))
        if not tried:
            raise BrainError(f"No AI model available for '{task}'. Add API keys to .env "
                             f"(status: {self.status()})")
        raise BrainError(f"All models failed for '{task}': " + " | ".join(errors))

    def ask_json(self, task: str, prompt: str, system: str = "", temperature: float = 0.4, retries: int = 1):
        """Ask for JSON; if a model replies with broken JSON, ask again once."""
        last_err = None
        for _ in range(retries + 1):
            result = self.ask(task, prompt, system=system, temperature=temperature)
            try:
                return result.json(), result
            except (BrainError, json.JSONDecodeError) as e:
                last_err = e
                prompt = prompt + "\n\nIMPORTANT: Reply with valid JSON only, no other text."
        raise BrainError(f"Could not get valid JSON for '{task}': {last_err}")
