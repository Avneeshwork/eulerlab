"""Claude through Anthropic's own SDK, behind the assistant's chat shape.

Operator, 2026-10-29: "include claude all models as option". Choice and
sources: ADR-088, research 129.

The assistant speaks the OpenAI chat shape (`chat._post`). Anthropic's
Messages API is a different shape, so this module translates a chat payload
into a Messages request and the reply back into a chat body. Nothing else in
the assistant changes, and the same locks apply: the host must be approved,
and the payload is scrubbed of `.env` values before it is sent.

Three things the chat shape cannot carry, handled here:

- Thinking is always on for the current Claude models, and a thinking block
  must be passed back unchanged on the next round of a tool loop. The reply's
  raw content goes back in `anthropic_content`, which `chat.ask` keeps on the
  assistant turn and this module sends back as it came.
- A refusal (`stop_reason: "refusal"`) is a normal reply, not an HTTP error.
  It becomes `chat.ModelUnavailable`.
- `temperature` is not sent. Anthropic rejects sampling parameters on the
  current models (from 2026-10-21, every model).
"""

from __future__ import annotations

import json
from typing import Any

import anthropic

from eulerlab.assistant import redact
from eulerlab.llm import client

FALLBACK_BETA = "server-side-fallback-2026-07-01"
"""Server-side fallback, `"default"` form: when a model's safety classifier
declines, Anthropic re-runs the request on the model it recommends for that
refusal category. Opt-in per provider (`refusal_fallback`). Claude Haiku 5.5
has none, so it must not send it."""


class Refusal(RuntimeError):
    """The model declined, or the request could not be served."""

    def __init__(self, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.retryable = retryable
        """True when another model might answer: a refusal, a rate limit, a
        server error, a cut-off answer. False for a bad key or no credit,
        which every Claude model would fail alike."""


def _tools(openai_tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "name": t["function"]["name"],
            "description": t["function"].get("description", ""),
            "input_schema": t["function"].get("parameters") or {"type": "object"},
        }
        for t in openai_tools
    ]


def _arguments(raw: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def to_request(payload: dict[str, Any]) -> dict[str, Any]:
    """A chat payload as Messages API arguments. Pure, so it can be tested."""
    system: list[str] = []
    messages: list[dict[str, Any]] = []
    for m in payload["messages"]:
        role = m["role"]
        if role == "system":
            system.append(str(m["content"]))
        elif role == "tool":
            block = {
                "type": "tool_result",
                "tool_use_id": m["tool_call_id"],
                "content": str(m["content"]),
            }
            # All results of one round go in one user message.
            if messages and messages[-1]["role"] == "user" and messages[-1].get("_results"):
                messages[-1]["content"].append(block)
            else:
                messages.append({"role": "user", "content": [block], "_results": True})
        elif role == "assistant" and m.get("anthropic_content"):
            content = [b for b in m["anthropic_content"] if b.get("type") != "fallback"]
            messages.append({"role": "assistant", "content": content})
        elif role == "assistant" and m.get("tool_calls"):
            blocks: list[dict[str, Any]] = []
            if m.get("content"):
                blocks.append({"type": "text", "text": str(m["content"])})
            for call in m["tool_calls"]:
                function = call.get("function") or {}
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": call["id"],
                        "name": function.get("name", ""),
                        "input": _arguments(str(function.get("arguments") or "")),
                    }
                )
            messages.append({"role": "assistant", "content": blocks})
        else:
            messages.append({"role": role, "content": str(m["content"])})
    for m in messages:
        m.pop("_results", None)
    request: dict[str, Any] = {
        "model": payload["model"],
        "max_tokens": payload["max_tokens"],
        "messages": messages,
    }
    if system:
        request["system"] = "\n\n".join(system)
    if payload.get("tools"):
        request["tools"] = _tools(payload["tools"])
    return request


def to_chat_body(message: dict[str, Any]) -> dict[str, Any]:
    """A Messages API reply as a chat body, raw content kept. Pure."""
    stop = message.get("stop_reason")
    if stop == "refusal":
        details = message.get("stop_details") or {}
        category = details.get("category") or "unstated"
        msg = f"{message.get('model')} declined to answer (category: {category})."
        raise Refusal(msg, retryable=True)
    content = message.get("content") or []
    text = "\n".join(b["text"] for b in content if b.get("type") == "text").strip()
    calls = [
        {
            "id": b["id"],
            "type": "function",
            "function": {"name": b["name"], "arguments": json.dumps(b.get("input") or {})},
        }
        for b in content
        if b.get("type") == "tool_use"
    ]
    reply: dict[str, Any] = {"role": "assistant", "content": text, "anthropic_content": content}
    if calls:
        reply["tool_calls"] = calls
    finish = "length" if stop == "max_tokens" else ("tool_calls" if calls else "stop")
    return {"choices": [{"message": reply, "finish_reason": finish}]}


def post(chosen: client.Provider, payload: dict[str, Any], *, timeout: float) -> dict[str, Any]:
    """Send one chat payload to Claude. Scrubbed, like every assistant request."""
    key = client._api_key(chosen)
    request = json.loads(redact.scrub(json.dumps(to_request(payload))))
    if chosen.effort:
        request["output_config"] = {"effort": chosen.effort}
    sdk = anthropic.Anthropic(api_key=key, base_url=chosen.base_url, timeout=timeout, max_retries=1)
    try:
        if chosen.refusal_fallback:
            reply = sdk.beta.messages.create(**request, betas=[FALLBACK_BETA], fallbacks="default")
        else:
            reply = sdk.messages.create(**request)
    except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as exc:
        raise Refusal(
            f"{chosen.name}: the key was refused ({exc.status_code}).", retryable=False
        ) from exc
    except anthropic.RateLimitError as exc:
        raise Refusal(
            f"{chosen.name} is rate limited. Try again in a minute.", retryable=True
        ) from exc
    except anthropic.BadRequestError as exc:
        detail = redact.scrub(str(exc.message))[:300]
        if "credit balance" in detail.lower():
            raise Refusal(f"{chosen.name}: no API credit left. {detail}", retryable=False) from exc
        raise Refusal(f"{chosen.model} rejected the request: {detail}", retryable=True) from exc
    except anthropic.APIStatusError as exc:
        raise Refusal(f"{chosen.name} returned HTTP {exc.status_code}.", retryable=True) from exc
    except anthropic.APITimeoutError as exc:
        raise Refusal(
            f"{chosen.name} did not answer in {timeout:.0f} seconds.", retryable=True
        ) from exc
    except anthropic.APIConnectionError as exc:
        raise Refusal(
            "Could not reach api.anthropic.com. Check the internet connection.", retryable=False
        ) from exc
    return to_chat_body(reply.model_dump(mode="json", by_alias=True, exclude_none=True))
