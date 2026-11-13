"""Every model request's tokens, by who asked: one line in `data/derived/llm_usage.jsonl`.

Before 2026-11-04 the agents counted requests only (`output.json` `requests`), so
an agent spending ten times its usual tokens on the same number of requests was
invisible, and so was Groq's free daily allowance running out (ADR-132). Each
successful reply's `usage` block is appended here with the agent and run that
asked, set by `agents.runtime.run` through `asking`. The watchdog agent reads it.

Never raises: a full disk must not fail the request it is describing.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from eulerlab.paths import data_path

LOG = data_path("derived/llm_usage.jsonl")
_WHO: ContextVar[tuple[str, str]] = ContextVar("llm_caller", default=("assistant", ""))


@contextmanager
def asking(agent: str, run: str) -> Iterator[None]:
    """Requests made inside the block are recorded as this agent's run."""
    token = _WHO.set((agent, run))
    try:
        yield
    finally:
        _WHO.reset(token)


def agent_run() -> tuple[str, str]:
    """(agent, run id) when this code is running inside an agent's run, else ("", "")."""
    agent, run = _WHO.get()
    return (agent, run) if run else ("", "")


def tokens(usage: Any) -> tuple[int, int]:
    """(prompt, completion) from an OpenAI-style or Anthropic-style `usage` block."""
    if not isinstance(usage, dict):
        return 0, 0

    def number(*names: str) -> int:
        for name in names:
            value = usage.get(name)
            if isinstance(value, int | float):
                return int(value)
        return 0

    return number("prompt_tokens", "input_tokens"), number("completion_tokens", "output_tokens")


def record(provider: str, model: str, usage: Any, *, now: datetime | None = None) -> None:
    prompt, completion = tokens(usage)
    agent, run = _WHO.get()
    row = {
        "at": (now or datetime.now(UTC)).isoformat(timespec="seconds"),
        "agent": agent,
        "run": run,
        "provider": provider,
        "model": model,
        "prompt": prompt,
        "completion": completion,
        "total": prompt + completion,
    }
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row) + "\n")
    except OSError:
        return


def rows(since: datetime | None = None, path: Path | None = None) -> list[dict[str, Any]]:
    """Recorded requests, oldest first, from `since` on."""
    try:
        text = (path or LOG).read_text(encoding="utf-8")
    except OSError:
        return []
    out: list[dict[str, Any]] = []
    for line in text.splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        if since is not None:
            try:
                at = datetime.fromisoformat(str(row.get("at")))
            except ValueError:
                continue
            if at < since:
                continue
        out.append(row)
    return out


def run_tokens(agent: str, run: str, path: Path | None = None) -> int:
    return sum(
        int(r.get("total") or 0)
        for r in rows(path=path)
        if r.get("agent") == agent and r.get("run") == run
    )
