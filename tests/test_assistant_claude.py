"""Claude in the assistant: the translation to Anthropic's shape and back.

No test here makes a network call. The SDK is never reached: the pure
translation functions are tested directly, and `chat.ask` gets a fake `post`
that answers in the chat shape `anthropic_api.post` returns.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from eulerlab.assistant import anthropic_api, chat
from eulerlab.llm.client import LLMConfig, LLMUnavailable, Provider, complete

CLAUDE = Provider(
    name="claude-opus",
    base_url="https://api.anthropic.com",
    api="anthropic",
    model="claude-opus-5-5",
    api_key_var="ANTHROPIC_API_KEY",
    max_tokens=16000,
    refusal_fallback=True,
)
GROQ = Provider(
    name="groq",
    base_url="https://api.groq.com/openai/v1",
    model="m",
    api_key_var="GROQ_API_KEY",
    free=True,
)


@pytest.fixture
def _keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-value-for-unit-tests")
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test_value_for_unit_tests")
    monkeypatch.setenv(chat.ZDR_ENV, "1")


def test_a_chat_payload_becomes_a_messages_request() -> None:
    thinking = {"type": "thinking", "thinking": "", "signature": "sig"}
    payload = {
        "model": "claude-opus-5-5",
        "max_tokens": 16000,
        "temperature": 0.1,
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "deployments",
                    "description": "d",
                    "parameters": {"type": "object"},
                },
            }
        ],
        "messages": [
            {"role": "system", "content": "rules"},
            {"role": "user", "content": "how are my deployments?"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [],
                "anthropic_content": [
                    {"type": "fallback", "from": {"model": "a"}, "to": {"model": "b"}},
                    thinking,
                    {"type": "tool_use", "id": "t1", "name": "deployments", "input": {}},
                    {"type": "tool_use", "id": "t2", "name": "deployments", "input": {}},
                ],
            },
            {"role": "tool", "tool_call_id": "t1", "name": "deployments", "content": "one"},
            {"role": "tool", "tool_call_id": "t2", "name": "deployments", "content": "two"},
        ],
    }
    request = anthropic_api.to_request(payload)
    assert request["system"] == "rules"
    assert "temperature" not in request  # Anthropic rejects sampling parameters
    assert request["tools"] == [
        {"name": "deployments", "description": "d", "input_schema": {"type": "object"}}
    ]
    assistant = request["messages"][1]
    # Thinking goes back unchanged; the fallback marker is dropped.
    assert assistant["content"][0] == thinking
    assert [b["type"] for b in assistant["content"]] == ["thinking", "tool_use", "tool_use"]
    # Both results of one round arrive in one user message.
    results = request["messages"][2]
    assert results["role"] == "user"
    assert [b["tool_use_id"] for b in results["content"]] == ["t1", "t2"]
    assert len(request["messages"]) == 3


def test_a_reply_becomes_a_chat_body_with_its_raw_content() -> None:
    content = [
        {"type": "thinking", "thinking": "", "signature": "s"},
        {"type": "tool_use", "id": "t1", "name": "orders", "input": {"deployment_id": 1}},
    ]
    body = anthropic_api.to_chat_body({"model": "m", "stop_reason": "tool_use", "content": content})
    message = body["choices"][0]["message"]
    assert message["anthropic_content"] == content
    call = message["tool_calls"][0]
    assert call["id"] == "t1"
    assert json.loads(call["function"]["arguments"]) == {"deployment_id": 1}

    cut = anthropic_api.to_chat_body(
        {"model": "m", "stop_reason": "max_tokens", "content": [{"type": "text", "text": "par"}]}
    )
    assert cut["choices"][0]["finish_reason"] == "length"


def test_a_refusal_is_a_model_failure_not_an_answer() -> None:
    with pytest.raises(anthropic_api.Refusal, match="category: cyber") as caught:
        anthropic_api.to_chat_body(
            {
                "model": "m",
                "stop_reason": "refusal",
                "stop_details": {"category": "cyber"},
                "content": [],
            }
        )
    assert caught.value.retryable


@pytest.mark.usefixtures("_keys")
def test_a_tool_round_keeps_claudes_thinking_for_the_next_request() -> None:
    raw = [
        {"type": "thinking", "thinking": "", "signature": "keep-me"},
        {"type": "tool_use", "id": "t1", "name": "deployments", "input": {}},
    ]
    replies = [
        anthropic_api.to_chat_body({"model": "m", "stop_reason": "tool_use", "content": raw}),
        anthropic_api.to_chat_body(
            {"model": "m", "stop_reason": "end_turn", "content": [{"type": "text", "text": "Two."}]}
        ),
    ]
    sent: list[dict[str, Any]] = []

    def post(provider: Provider, payload: dict[str, Any]) -> dict[str, Any]:
        sent.append(json.loads(json.dumps(payload)))
        return replies.pop(0)

    answer = chat.ask([{"role": "user", "content": "how many?"}], post=post, chosen=CLAUDE)
    assert answer.text == "Two." and answer.provider == "claude-opus"
    second = anthropic_api.to_request(sent[1])
    assert second["messages"][1]["content"] == raw


@pytest.mark.usefixtures("_keys")
def test_only_offered_models_are_listed_or_accepted() -> None:
    config = LLMConfig(
        default="groq",
        assistant="groq",
        offered=["groq", "claude-opus"],
        providers=[GROQ, CLAUDE, GROQ.model_copy(update={"name": "other"})],
    )
    listed = chat.choices(config)
    assert [c["name"] for c in listed] == ["groq", "claude-opus"]
    claude = listed[1]
    assert claude["ready"] and not claude["free"]
    assert claude["policy"] == "kept up to 30 days, not used for training"
    assert chat.provider(config, "claude-opus").name == "claude-opus"
    with pytest.raises(chat.Refused, match="not offered"):
        chat.provider(config, "other")


@pytest.mark.usefixtures("_keys")
def test_a_paid_model_is_never_a_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    config = LLMConfig(default="groq", assistant="groq", providers=[GROQ, CLAUDE])
    monkeypatch.setattr("eulerlab.llm.client.load_config", lambda: config)
    assert [p.name for p in chat._alternatives(GROQ)] == []


def test_the_translator_cannot_be_pointed_at_claude() -> None:
    with pytest.raises(LLMUnavailable, match="only the assistant"):
        complete("s", "u", provider=CLAUDE)


def test_the_committed_config_offers_groq_and_every_claude_model() -> None:
    from pathlib import Path

    from eulerlab.llm.client import load_config

    config = load_config(Path(__file__).resolve().parents[1] / "config" / "llm.yaml")
    assert config.offered is not None and config.offered[0] == "groq"
    models = {config.get(name).model for name in config.offered}
    assert {
        "claude-opus-5-5",
        "claude-sonnet-5-5",
        "claude-haiku-5-5",
        "claude-fable-5-1",
    } <= models
    # Claude Haiku 5.5 has no server-side fallback; sending one would be refused.
    assert not config.get("claude-haiku").refusal_fallback
    assert all(not config.get(n).free for n in config.offered if n.startswith("claude"))
