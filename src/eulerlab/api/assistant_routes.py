"""The assistant's two routes: can it answer, and answer this.

The work is in `assistant/chat.py`. A refusal (no key, retention not confirmed,
quota used up) is an ordinary reply with `ok: false` and the reason, because
the panel shows the reason to the operator instead of a failed request.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from eulerlab.assistant import chat
from eulerlab.llm.client import LLMUnavailable

router = APIRouter(prefix="/api/assistant")


class Turn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"]
    content: str = Field(max_length=20_000)


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    messages: list[Turn] = Field(min_length=1, max_length=40)
    provider: str = Field(default="", max_length=80)
    model: str = Field(default="", max_length=160)
    """A name from the status route's `choices`. Empty uses the default."""


@router.get("/status")
def assistant_status(provider: str = "", model: str = "") -> dict[str, Any]:
    return chat.status(provider, model)


@router.get("/models")
def assistant_models() -> dict[str, Any]:
    """Fetch the current free OpenRouter models with ZDR endpoints."""
    try:
        return {"ok": True, "models": chat.openrouter_zdr_models()}
    except (chat.Refused, LLMUnavailable) as exc:
        return {"ok": False, "models": [], "error": str(exc)}


@router.post("/chat")
def assistant_chat(request: ChatRequest) -> dict[str, Any]:
    try:
        chosen = chat.selected_provider(name=request.provider, model=request.model)
        answer = chat.ask([turn.model_dump() for turn in request.messages], chosen=chosen)
    except (chat.Refused, LLMUnavailable) as exc:
        return {"ok": False, "error": str(exc)}
    return {
        "ok": True,
        "text": answer.text,
        "provider": answer.provider,
        "model": answer.model,
        "host": answer.host,
        "used": answer.used,
    }
