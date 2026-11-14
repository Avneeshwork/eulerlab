"""The trace store: every model request in full, with who asked, replayable (#165)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

from eulerlab.agents import runtime
from eulerlab.assistant import chat, redact
from eulerlab.llm import trace, usage
from eulerlab.llm.client import Provider

GROQ = Provider(
    name="groq",
    base_url="https://api.groq.com/openai/v1",
    model="openai/gpt-oss-120b",
    free=True,
)
OTHER = GROQ.model_copy(update={"name": "other", "model": "other-model"})


def _say(text: str) -> dict[str, Any]:
    return {
        "choices": [{"message": {"content": text}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 11, "completion_tokens": 3},
    }


def _request(text: str) -> dict[str, Any]:
    return {"model": GROQ.model, "messages": [{"role": "user", "content": text}]}


def test_a_request_is_kept_in_full_with_who_asked(tmp_path: Path) -> None:
    with usage.asking("autopilot", "run-1"), trace.collect() as ids:
        trace.traced(lambda c, p: _say("two cards"), GROQ, _request("write cards"), root=tmp_path)
    (row,) = list(trace.rows(root=tmp_path))
    assert ids == [row["id"]]
    assert (row["agent"], row["run"], row["model"]) == ("autopilot", "run-1", GROQ.model)
    assert row["request"]["messages"][0]["content"] == "write cards"
    assert trace.answer_text(row["response"]) == "two cards"
    assert row["tokens"] == {"prompt": 11, "completion": 3}
    assert row["error"] == ""


def test_a_failed_request_is_kept_and_still_raises(tmp_path: Path) -> None:
    def broken(chosen: Any, payload: dict[str, Any]) -> dict[str, Any]:
        raise chat.ModelUnavailable("quota")

    with pytest.raises(chat.ModelUnavailable):
        trace.traced(broken, GROQ, _request("x"), root=tmp_path)
    (row,) = list(trace.rows(root=tmp_path))
    assert row["response"] is None and "quota" in row["error"]


def test_secrets_never_reach_the_trace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(redact, "secrets", lambda path=None: ["b2-app-key-55aa"])
    trace.traced(
        lambda c, p: _say("saw b2-app-key-55aa"), GROQ, _request("b2-app-key-55aa"), root=tmp_path
    )
    text = next((tmp_path).glob("*.jsonl")).read_text(encoding="utf-8")
    assert "b2-app-key-55aa" not in text and "[redacted]" in text


def test_post_records_every_request(monkeypatch: pytest.MonkeyPatch) -> None:
    """`chat._post` is the one connection point, so it is the one recorder."""
    monkeypatch.setattr(chat, "_send", lambda chosen, payload: _say("ok"))
    chat._post(GROQ, _request("hello"))
    assert [trace.answer_text(r["response"]) for r in trace.rows()] == ["ok"]


def test_the_agent_and_run_follow_the_request_into_its_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`complete_any` answers in a worker thread; before HISTORY #90 the usage log
    called every such request the assistant's, with no run."""

    def send(chosen: Provider, payload: dict[str, Any]) -> dict[str, Any]:
        body = _say("ok")
        usage.record(chosen.name, chosen.model, body["usage"])  # as the real `_send` does
        return body

    monkeypatch.setattr(chat, "_send", send)
    monkeypatch.setattr(chat, "selected_provider", lambda name="", model="": GROQ)
    with usage.asking("research", "run-7"):
        chat.complete_any("system", "user", name="groq")
    (row,) = list(trace.rows())
    assert (row["agent"], row["run"]) == ("research", "run-7")
    assert usage.rows()[-1]["agent"] == "research"


def test_an_agent_run_lists_its_traces(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chat, "_send", lambda chosen, payload: _say("drafted"))

    def worker(ctx: runtime.Context) -> runtime.WorkerResult:
        chat._post(GROQ, _request("one"))
        chat._post(GROQ, _request("two"))
        return runtime.WorkerResult("done")

    out = runtime.run("operations", root=tmp_path, worker=worker)
    assert len(out.traces) == 2
    assert {r["id"] for r in trace.rows()} == set(out.traces)


def test_replay_sends_the_recorded_request_again_and_diffs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    trace.traced(
        lambda c, p: _say("card A\ncard B"),
        GROQ,
        {
            "model": GROQ.model,
            "messages": [{"role": "system", "content": "old"}, {"role": "user", "content": "go"}],
        },
        root=tmp_path,
    )
    (first,) = list(trace.rows(root=tmp_path))
    sent: list[dict[str, Any]] = []

    def fake(chosen: Provider, payload: dict[str, Any]) -> dict[str, Any]:
        sent.append({"model": payload["model"], "system": payload["messages"][0]["content"]})
        return _say("card A\ncard C")

    monkeypatch.setattr(chat, "selected_provider", lambda name="", model="": OTHER)
    out = trace.replay(first["id"], provider="other", system="new", post=fake, root=tmp_path)
    assert sent == [{"model": "other-model", "system": "new"}]
    assert "-card B" in out["diff"] and "+card C" in out["diff"]
    replayed = trace.get(out["trace"], root=tmp_path)
    assert replayed is not None and replayed["replay_of"] == first["id"]


def test_prune_keeps_recent_days(tmp_path: Path) -> None:
    for day in ("2026-01-01", "2026-11-01"):
        (tmp_path / f"{day}.jsonl").write_text("{}\n", encoding="utf-8")
    assert trace.prune(180, today=date(2026, 11, 13), root=tmp_path) == 1
    assert [p.stem for p in tmp_path.glob("*.jsonl")] == ["2026-11-01"]


def test_rows_by_day(tmp_path: Path) -> None:
    at = datetime(2026, 11, 13, 10, tzinfo=UTC)
    trace.record(provider="groq", model="m", request={}, response=None, at=at, root=tmp_path)
    assert len(list(trace.rows(day=date(2026, 11, 13), root=tmp_path))) == 1
    assert list(trace.rows(day=date(2026, 11, 12), root=tmp_path)) == []
