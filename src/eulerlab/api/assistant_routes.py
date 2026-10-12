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


@router.get("/status")
def assistant_status() -> dict[str, Any]:
    return chat.status()


@router.post("/chat")
def assistant_chat(request: ChatRequest) -> dict[str, Any]:
    try:
        answer = chat.ask([turn.model_dump() for turn in request.messages])
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
