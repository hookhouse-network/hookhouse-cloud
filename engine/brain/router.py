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


def rest_minutes(e, defaults: dict) -> float:
    """How long a provider rests after an error: what the provider itself said (plus a minute), never longer than
    the kind's default (daily_quota 720 = the longest); the kind's default when it said nothing."""
    default = float(defaults.get(e.kind, 5))
    retry_s = getattr(e, "retry_s", None)
    if retry_s is None or retry_s < 0:
        return default
    return min(default if e.kind == "daily_quota" else max(default, 720.0), retry_s / 60.0 + 1.0)


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


class Usage:
    """Calls, characters in/out and errors per day (IST), task and model: the measurement for P5's model tiers.
    24 Nov: the strong models ran out of their daily quota by 01:20 while about 20 small jobs share their route, so the
    routes are re-planned from these numbers. The PC keeps its own file in data/pc (the cloud's data/state replaces
    the PC's on every loop); the cloud's lives in data/state (its memory bundle). Never stops a call."""

    def __init__(self, path: Path, keep_days: int = 8):
        self.path, self.keep_days = path, keep_days

    def add(self, task: str, provider: str, chars_in: int = 0, chars_out: int = 0, error: str = "") -> None:
        try:
            d = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}
        except (OSError, ValueError):
            d = {}
        row = d.setdefault(time.strftime("%Y-%m-%d"), {}).setdefault(f"{task}|{provider}",
                                                                       {"calls": 0, "in": 0, "out": 0})
        if error:
            row.setdefault("errors", {})[error] = row.get("errors", {}).get(error, 0) + 1
        else:
            row["calls"] += 1
            row["in"] += int(chars_in)
            row["out"] += int(chars_out)
        for day in sorted(d)[:-self.keep_days]:
            d.pop(day, None)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(d, indent=1, sort_keys=True), encoding="utf-8")
            tmp.replace(self.path)
        except OSError:
            pass


def usage_path() -> Path:
    import os
    return data_path("data/state/brain_usage.json" if os.environ.get("GITHUB_ACTIONS") else "data/pc/brain_usage.json")


class Brain:
    def __init__(self, providers: dict[str, Provider] | None = None, routes: dict | None = None,
                 cooldown_minutes: dict | None = None, cooldown_file: Path | None = None,
                 usage_file: Path | None = None):
        cfg = settings()["brain"]
        if providers is None:
            providers = {name: build(name, pcfg) for name, pcfg in cfg["providers"].items()}
        self.providers = providers
        self.routes = routes or cfg["routes"]
        self.cooldown_minutes = cooldown_minutes or cfg["cooldown_minutes"]
        self.cooldowns = Cooldowns(cooldown_file or data_path("data/state/brain_cooldowns.json"))
        # a test's own cooldown file keeps its usage next to it (never the real record)
        self.usage = Usage(usage_file or (Path(cooldown_file).parent / "brain_usage.json" if cooldown_file
                                          else usage_path()))

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

    def ask(self, task: str, prompt: str, system: str = "", temperature: float = 0.7, skip=()) -> BrainResult:
        route = self.routes.get(task)
        if not route:
            raise BrainError(f"Unknown task '{task}'. Known: {list(self.routes)}")
        tried, errors = [], []
        for name in route:
            p = self.providers.get(name)
            if name in skip or p is None or not p.available() or self.cooldowns.resting(name):
                continue
            tried.append(name)
            try:
                text = p.complete(prompt, system=system, temperature=temperature)
                if not text:
                    raise ProviderError("error", f"{name}: empty reply")
                self.usage.add(task, name, len(prompt) + len(system), len(text))
                return BrainResult(text=text, provider=name, tried=tried)
            except ProviderError as e:
                errors.append(str(e))
                self.usage.add(task, name, error=e.kind)
                if e.kind in ("unavailable", "too_big"):   # too big for this model's limit: just try the next one
                    continue
                self.cooldowns.rest(name, rest_minutes(e, self.cooldown_minutes))
        if not tried:
            raise BrainError(f"No AI model available for '{task}'. Add API keys to .env "
                             f"(status: {self.status()})")
        raise BrainError(f"All models failed for '{task}': " + " | ".join(errors))

    def ask_json(self, task: str, prompt: str, system: str = "", temperature: float = 0.4, retries: int = 2):
        """Ask for JSON. A model that replies with broken JSON is skipped and the next model on the route is asked
        (24 Nov: the retry went back to the same model, which cut its script off mid-JSON again, and Clutch Tales
        lost its slot); only when no other model is left is the same one asked again."""
        errs, skip = [], set()
        note = "\n\nIMPORTANT: Reply with valid JSON only, no other text."
        for _ in range(retries + 1):
            try:
                result = self.ask(task, prompt, system=system, temperature=temperature, skip=skip)
            except BrainError:
                if not skip:
                    raise
                skip = set()                     # no other model left: the same one once more (as before 24 Nov)
                result = self.ask(task, prompt, system=system, temperature=temperature)
            try:
                return result.json(), result
            except (BrainError, json.JSONDecodeError) as e:
                errs.append(f"{result.provider}: {e}")
                skip.add(result.provider)
                if note not in prompt:
                    prompt += note
        raise BrainError(f"Could not get valid JSON for '{task}': " + " | ".join(errs))
