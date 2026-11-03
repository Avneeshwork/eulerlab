"""Fewer, smaller, paced requests: the knowledge agent on Groq's free tier (T-4402, research 143)."""

from __future__ import annotations

import email.message
import io
import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pytest

from eulerlab.agents import runtime
from eulerlab.agents.spec import Effective, all_effective, effective
from eulerlab.agents.workers import knowledge
from eulerlab.assistant import chat, redact, tools
from eulerlab.llm.client import Provider

PACED = Provider(
    name="groq",
    base_url="https://api.groq.com/openai/v1",
    model="m",
    api_key_var="GROQ_API_KEY",
    tokens_per_minute=6000,
)


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0
        self.slept: list[float] = []

    def now(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.slept.append(round(seconds, 3))
        self.t += seconds


def test_requests_that_fit_the_minute_go_at_once() -> None:
    clock = Clock()
    assert chat.pace(PACED, 2000, now=clock.now, sleep=clock.sleep) == 0
    assert chat.pace(PACED, 4000, now=clock.now, sleep=clock.sleep) == 0
    assert clock.slept == []


def test_a_request_over_the_minute_waits_only_for_the_tokens_it_lacks() -> None:
    clock = Clock()
    chat.pace(PACED, 5000, now=clock.now, sleep=clock.sleep)
    # 1,000 left; 3,000 needed; the allowance refills at 100 tokens a second.
    assert chat.pace(PACED, 3000, now=clock.now, sleep=clock.sleep) == pytest.approx(20.0)
    clock.t += 10  # 1,000 more back
    assert chat.pace(PACED, 1000, now=clock.now, sleep=clock.sleep) == 0


def test_a_request_bigger_than_the_limit_waits_for_a_full_minute_at_most() -> None:
    clock = Clock()
    chat.pace(PACED, 6000, now=clock.now, sleep=clock.sleep)
    assert chat.pace(PACED, 9000, now=clock.now, sleep=clock.sleep) == pytest.approx(60.0)


def test_no_limit_means_no_pacing() -> None:
    clock = Clock()
    free = PACED.model_copy(update={"tokens_per_minute": None})
    for _ in range(5):
        assert chat.pace(free, 50_000, now=clock.now, sleep=clock.sleep) == 0


def test_the_hosts_own_count_corrects_the_guess() -> None:
    clock = Clock()
    chat.pace(PACED, 1000, now=clock.now, sleep=clock.sleep)
    chat.settle(PACED, "100", now=clock.now)  # another process spent the rest
    assert chat.pace(PACED, 600, now=clock.now, sleep=clock.sleep) > 0
    chat.settle(PACED, "not a number", now=clock.now)  # ignored


def test_the_committed_groq_provider_is_paced() -> None:
    from eulerlab.llm.client import load_config

    config = load_config(Path(__file__).resolve().parents[1] / "config" / "llm.yaml")
    assert config.get("groq").tokens_per_minute == 8000


# --- one retry for a tool call Groq could not parse ---


class _Response:
    headers = email.message.Message()

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def read(self) -> bytes:
        return b'{"choices": []}'


@pytest.mark.parametrize(
    ("bodies", "ok", "tries"),
    [
        ([b'{"error":{"code":"output_parse_failed"}}'], True, 2),
        ([b'{"error":{"code":"output_parse_failed"}}'] * 2, False, 2),
        ([b'{"error":{"code":"tool_use_failed"}}'], False, 1),
        ([b'{"error":{"code":"invalid_request"}}'], False, 1),
    ],
)
def test_an_unparsable_tool_call_is_sent_once_more(
    monkeypatch: pytest.MonkeyPatch, bodies: list[bytes], ok: bool, tries: int
) -> None:
    calls: list[int] = []

    def fake_open(request: Any, timeout: float = 0) -> _Response:
        calls.append(1)
        if len(calls) <= len(bodies):
            raise urllib.error.HTTPError(
                "https://api.groq.com",
                400,
                "Bad Request",
                email.message.Message(),
                io.BytesIO(bodies[len(calls) - 1]),
            )
        return _Response()

    monkeypatch.setenv("GROQ_API_KEY", "gsk_test_value_for_unit_tests")
    monkeypatch.setattr(redact, "secrets", lambda path=None: [])
    monkeypatch.setattr(urllib.request, "urlopen", fake_open)
    if ok:
        assert chat._post(PACED, {"messages": []}) == {"choices": []}
    else:
        with pytest.raises(chat.ModelUnavailable, match="400"):
            chat._post(PACED, {"messages": []})
    assert len(calls) == tries


# --- fewer tools, fewer rounds ---


def _say(text: str) -> dict[str, Any]:
    return {"choices": [{"message": {"role": "assistant", "content": text}}]}


def _want(name: str) -> dict[str, Any]:
    call = {"id": "c1", "type": "function", "function": {"name": name, "arguments": "{}"}}
    return {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [call]}}]}


class Model:
    def __init__(self, *replies: dict[str, Any]) -> None:
        self.replies = list(replies)
        self.sent: list[dict[str, Any]] = []

    def __call__(self, provider: Provider, payload: dict[str, Any]) -> dict[str, Any]:
        self.sent.append(json.loads(json.dumps(payload)))
        return self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]


def test_only_the_named_tools_are_offered_and_others_are_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ran: list[str] = []

    def orders(_args: Any) -> str:
        ran.append("x")
        return ""

    monkeypatch.setitem(tools.TOOLS, "orders", tools.Tool("o", {"type": "object"}, orders))
    model = Model(_want("orders"), _say("none"))
    answer = chat.ask(
        [{"role": "user", "content": "q"}], post=model, chosen=PACED, tool_names=("study",)
    )
    assert [t["function"]["name"] for t in model.sent[0]["tools"]] == ["study"]
    assert ran == [] and answer.text == "none"
    assert "There is no tool 'orders'" in model.sent[1]["messages"][-1]["content"]


def test_rounds_cap_the_requests() -> None:
    model = Model(_want("study"))
    with pytest.raises(chat.Refused, match="never answered"):
        chat.ask([{"role": "user", "content": "q"}], post=model, chosen=PACED, rounds=2)
    assert len(model.sent) == 2 and "tools" not in model.sent[-1]


def test_the_knowledge_tools_exist_and_leave_out_live_trading_state() -> None:
    assert set(knowledge.TOOLS) <= set(tools.TOOLS)
    assert not {"orders", "positions", "deployments", "prices"} & set(knowledge.TOOLS)
    assert len(json.dumps(tools.schemas(knowledge.TOOLS))) < 0.65 * len(json.dumps(tools.schemas()))


def _knowledge() -> dict[str, Effective]:
    return {"knowledge": effective(all_effective()["knowledge"].spec, None)}


def test_a_knowledge_question_costs_six_requests_at_most(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Worst case: three lookups and an invented figure, then one lookup and another."""
    monkeypatch.setitem(
        tools.TOOLS,
        "search_knowledge",
        tools.Tool("s", {"type": "object"}, lambda _a: "noise bar 1.88"),
    )
    look = _want("search_knowledge")
    model = Model(look, look, look, _say("The bar is 2.41."), look, _say("It is 3.10."))
    monkeypatch.setattr(chat, "_post", model)
    monkeypatch.setattr(chat, "selected_provider", lambda name="": PACED)
    out = runtime.run("knowledge", args={"question": "bar?"}, root=tmp_path, agents=_knowledge())
    assert len(model.sent) == knowledge.ROUNDS + knowledge.RETRY_ROUNDS == 6
    assert out.data["grounding"]["withheld"] is True
    offered = {t["function"]["name"] for t in model.sent[0]["tools"]}
    assert offered == set(knowledge.TOOLS)


def test_the_last_round_sees_results_as_plain_text_with_no_tool_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """gpt-oss-120b kept calling tools when its own calls were in the thread (research 143)."""
    monkeypatch.setitem(
        tools.TOOLS, "study", tools.Tool("s", {"type": "object"}, lambda _a: "noise bar 1.88")
    )
    model = Model(_want("study"), _say("The bar is 1.88."))
    answer = chat.ask([{"role": "user", "content": "bar?"}], post=model, chosen=PACED, rounds=2)
    last = model.sent[-1]["messages"]
    assert answer.text == "The bar is 1.88." and answer.evidence == ["noise bar 1.88"]
    assert [m["role"] for m in last] == ["system", "user", "user"]
    assert not any("tool_calls" in m for m in last)
    assert (
        last[-1]["content"].startswith(chat.LAST_ROUND)
        and "[study]\nnoise bar 1.88" in last[-1]["content"]
    )


def test_one_round_is_a_plain_question() -> None:
    model = Model(_say("hi"))
    chat.ask([{"role": "user", "content": "q"}], post=model, chosen=PACED, rounds=1)
    assert [m["role"] for m in model.sent[0]["messages"]] == ["system", "user"]
