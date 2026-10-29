"""Talking to a language model, without betting the project on any one vendor.

**Provider-agnostic by construction.** Every endpoint here speaks the same
shape — `POST {base_url}/chat/completions` with `{"model": ..., "messages":
[...]}` — which is the interface OpenAI defined and which Ollama, llama.cpp,
vLLM, OpenRouter, Groq and Together all implement. So "which model" is a line
in a config file, not a code change, and a free tier disappearing costs one
edit rather than a rewrite.

**The default is local and genuinely free.** Ollama runs on the machine, needs
no key, has no quota and sends nothing anywhere. That matters more here than
model quality, because of what the model is actually asked to do: it does not
decide anything. It drafts a strategy specification which is then validated by
code, shown to the operator, and only run if they say so. A weaker local model
produces a worse first draft; it cannot produce a wrong *result*.

**No key is ever written to disk by this module.** Keys come from the
environment via `.env`, which is gitignored, and the config file names the
variable rather than holding the value.

**On "unlimited free models".** Several hosted providers do offer free tiers,
and the ones listed in `config/llm.yaml` are there because they speak this
protocol — not because their limits have been verified. Free-tier quotas change
without notice and are recorded as an unverified assumption (A-019). The only
option here with no quota at all is the local one, because it is your own
computer.

`CLAUDE.md` forbids inventing API endpoints. The request shape above is the
documented OpenAI-compatible interface these servers publish; the specific
per-provider limits are not claimed.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

LLM_CONFIG_PATH = Path("config/llm.yaml")
TIMEOUT_SECONDS = 180


class LLMUnavailable(RuntimeError):
    """The model could not be reached, and the message says what to do.

    A distinct type because the interface treats it as an ordinary condition,
    not a crash: there is no model configured, or the local server is not
    running, and both have a one-line fix the operator can act on.
    """


class Provider(BaseModel):
    """One OpenAI-compatible endpoint."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    base_url: str
    model: str
    api_key_var: str | None = None
    """The *name* of an environment variable, never a key. A key in this file
    would be a secret in the repository, which `CLAUDE.md` forbids outright."""

    free: bool = False
    note: str = ""
    max_tokens: int = Field(default=2048, gt=0)
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    """Low by default. The model is drafting a specification that has to
    parse, not writing prose, and creativity here shows up as invalid output.
    Not sent to Anthropic, which rejects sampling parameters."""

    api: Literal["openai", "anthropic"] = "openai"
    """The request shape. `anthropic` is Claude's Messages API through the
    official SDK (`assistant/anthropic_api.py`, ADR-088); only the assistant's
    path speaks it, so the strategy translator cannot be pointed at Claude."""

    effort: Literal["low", "medium", "high", "xhigh", "max"] | None = None
    """Claude only: how hard the model thinks. Unset is the model's default."""

    refusal_fallback: bool = False
    """Claude only: re-run a declined request on Anthropic's recommended
    fallback model. Must stay off for Claude Haiku 5.5, which has none."""


class LLMConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    default: str
    providers: list[Provider]
    assistant: str | None = None
    """The provider the in-app assistant uses (`assistant/chat.py`, ADR-064).
    Named apart from `default` because the assistant sends the operator's own
    numbers, so its host must be one whose data terms were read."""

    research_agent: str | None = None
    """The provider the paper agent drafts with (`research/paper_agent.py`,
    ADR-084). It goes through the assistant's locks, so it must also name an
    approved host. Kept apart from `assistant` so the strongest free model can
    serve the long, structured drafting task without changing the chat panel."""

    offered: list[str] | None = None
    """The providers the assistant panel and Research Library list, in order.
    Unset lists every provider. Set 2026-10-29 at the operator's request, so
    the pickers show only the models they asked for; others stay in the file
    for the translator, the audit and the paper agent."""

    def get(self, name: str | None = None) -> Provider:
        wanted = name or self.default
        for provider in self.providers:
            if provider.name == wanted:
                return provider
        available = ", ".join(p.name for p in self.providers)
        msg = f"no provider named {wanted!r}. Configured: {available}"
        raise LLMUnavailable(msg)


def load_config(path: Path = LLM_CONFIG_PATH) -> LLMConfig:
    if not path.exists():
        msg = f"no {path}. Copy the example or add a provider."
        raise LLMUnavailable(msg)
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return LLMConfig.model_validate(raw)


@dataclass(frozen=True)
class Reply:
    text: str
    provider: str
    model: str


def _api_key(provider: Provider) -> str | None:
    if not provider.api_key_var:
        return None
    import os

    from eulerlab.env import load_env

    load_env()
    value = os.environ.get(provider.api_key_var, "").strip()
    if not value:
        msg = (
            f"{provider.name} needs {provider.api_key_var} set in .env.\n"
            f"Or switch to a provider that needs no key — `ollama` runs locally."
        )
        raise LLMUnavailable(msg)
    return value


def complete(
    system: str,
    user: str,
    *,
    provider: Provider | None = None,
    config: LLMConfig | None = None,
    provider_name: str | None = None,
) -> Reply:
    """One turn. No history, no tools, no streaming.

    Deliberately the smallest useful surface. Everything this project asks a
    model for is a single translation from a description to a specification,
    and a conversation would only make it harder to say what the model was
    shown when it produced a given answer.
    """
    chosen = provider or (config or load_config()).get(provider_name)
    if chosen.api != "openai":
        msg = f"{chosen.name} speaks the {chosen.api} API, which only the assistant supports."
        raise LLMUnavailable(msg)
    key = _api_key(chosen)

    payload = json.dumps(
        {
            "model": chosen.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": chosen.temperature,
            "max_tokens": chosen.max_tokens,
            "stream": False,
        }
    ).encode()

    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"

    request = urllib.request.Request(
        f"{chosen.base_url.rstrip('/')}/chat/completions",
        data=payload,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            body = json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode()[:400]
        msg = f"{chosen.name} returned HTTP {exc.code}: {detail}"
        raise LLMUnavailable(msg) from exc
    except urllib.error.URLError as exc:
        hint = ""
        if "localhost" in chosen.base_url or "127.0.0.1" in chosen.base_url:
            hint = (
                f"\nIs it running? Install from https://ollama.com, then:\n"
                f"  ollama serve\n  ollama pull {chosen.model}"
            )
        msg = f"could not reach {chosen.name} at {chosen.base_url}: {exc.reason}{hint}"
        raise LLMUnavailable(msg) from exc
    except TimeoutError as exc:
        msg = f"{chosen.name} did not reply within {TIMEOUT_SECONDS}s"
        raise LLMUnavailable(msg) from exc

    return Reply(text=_extract(body), provider=chosen.name, model=chosen.model)


def _extract(body: dict[str, Any]) -> str:
    """Pull the message text out, or say plainly that the shape was wrong.

    Servers claiming OpenAI compatibility vary at the edges, and a
    `KeyError: 'choices'` from inside a helper tells the operator nothing about
    which server misbehaved or how.
    """
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        msg = f"reply had no choices: {json.dumps(body)[:300]}"
        raise LLMUnavailable(msg)
    message = choices[0].get("message") or {}
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        msg = f"reply had no message content: {json.dumps(body)[:300]}"
        raise LLMUnavailable(msg)
    return content.strip()


def health(config: LLMConfig | None = None) -> list[dict[str, Any]]:
    """Which providers are actually usable right now.

    Checks only what can be checked without spending anything: is the config
    valid, and is the key present. It deliberately does **not** send a probe
    request — on a metered provider that would spend the operator's quota to
    answer a question they did not ask.
    """
    loaded = config or load_config()
    out: list[dict[str, Any]] = []
    for provider in loaded.providers:
        ready, reason = True, ""
        if provider.api_key_var:
            try:
                _api_key(provider)
            except LLMUnavailable as exc:
                ready, reason = False, str(exc).splitlines()[0]
        out.append(
            {
                "name": provider.name,
                "model": provider.model,
                "free": provider.free,
                "needs_key": bool(provider.api_key_var),
                "ready": ready,
                "reason": reason,
                "note": provider.note,
                "is_default": provider.name == loaded.default,
            }
        )
    return out
