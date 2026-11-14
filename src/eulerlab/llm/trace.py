"""Every model request in full: what was sent, what came back, who asked (issue #165).

Before this, a run kept only its prompt's version hash, its request count and
the answer's length ("The model answered (N characters)"). Nobody could see why
an agent wrote a card, replay a bad night, or compare two prompts on the same
input, and the agent evals (ADR-183) had no real traffic to replay.

One line per request in `data/derived/llm_traces/YYYY-MM-DD.jsonl` (UTC day),
appended only:

    id        hash of the line's content (16 hex)
    at        when the request was sent (UTC)
    agent     the agent and run that asked (`usage.asking`), or "assistant"
    run
    provider  the configured provider and its model
    model
    request   the request body as sent: messages, tools, temperature
    response  the reply body, or null when it failed
    error     why it failed, or ""
    seconds   how long the host took
    tokens    prompt and completion tokens from the reply's usage block

Every request and reply is passed through `assistant.redact.scrub` before it is
written, so no `.env` value reaches the file, as none reaches the host.

**One hook.** `assistant.chat._post` is the only place the assistant and every
agent open a connection to a model (ADR-064), so it is the only place that
records. The tool loop (`chat.ask`) sends one request per round, so a run with
tools leaves one trace per round, each with the whole thread so far.

**Replay.** `replay(id)` sends a recorded request again, through the same
`_post` and so the same host, retention and redaction locks, optionally with a
different provider or system prompt, and returns both answers. It replays one
request: a tool loop is not re-driven, because the tools' answers today may
differ from the ones recorded. The replay leaves a trace of its own, marked
with the id it replayed.

Never raises on write: a full disk must not fail the request it describes.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import time
from collections.abc import Callable, Iterator, Sequence
from contextvars import ContextVar
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from eulerlab.llm import usage
from eulerlab.paths import data_path

ROOT = data_path("derived/llm_traces")
KEEP_DAYS = 180
"""Days of trace files `prune` keeps. A trace is for debugging, replay and evals,
not a record the ledger relies on; the agent log and usage log stay."""


def _scrub(text: str) -> str:
    from eulerlab.assistant import redact

    try:
        return redact.scrub(text)
    except Exception:  # an unreadable .env must not stop the request being recorded
        return text


def _day_file(root: Path, at: datetime) -> Path:
    return root / f"{at.astimezone(UTC).date().isoformat()}.jsonl"


def record(
    *,
    provider: str,
    model: str,
    request: dict[str, Any],
    response: dict[str, Any] | None,
    error: str = "",
    seconds: float = 0.0,
    at: datetime | None = None,
    replay_of: str = "",
    root: Path | None = None,
) -> str:
    """Append one trace and return its id, or "" when it could not be written."""
    when = at or datetime.now(UTC)
    agent, run = usage.agent_run()
    prompt, completion = usage.tokens((response or {}).get("usage"))
    row: dict[str, Any] = {
        "at": when.astimezone(UTC).isoformat(timespec="milliseconds"),
        "agent": agent or "assistant",
        "run": run,
        "provider": provider,
        "model": model,
        "request": request,
        "response": response,
        "error": error,
        "seconds": round(seconds, 3),
        "tokens": {"prompt": prompt, "completion": completion},
    }
    if replay_of:
        row["replay_of"] = replay_of
    try:
        body = _scrub(json.dumps(row, sort_keys=True, default=str))
        trace_id = hashlib.sha256(body.encode()).hexdigest()[:16]
        line = json.dumps({"id": trace_id, **json.loads(body)}, sort_keys=True)
        target = _day_file(root or ROOT, when)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except (OSError, TypeError, ValueError):
        return ""
    _remember(trace_id)
    return trace_id


def traced(
    send: Callable[[Any, dict[str, Any]], dict[str, Any]],
    chosen: Any,
    payload: dict[str, Any],
    *,
    replay_of: str = "",
    root: Path | None = None,
) -> dict[str, Any]:
    """`send(chosen, payload)`, recorded whether it answers or raises."""
    began = time.monotonic()
    at = datetime.now(UTC)
    try:
        body = send(chosen, payload)
    except Exception as exc:
        record(
            provider=str(getattr(chosen, "name", "")),
            model=str(getattr(chosen, "model", "")),
            request=payload,
            response=None,
            error=f"{type(exc).__name__}: {str(exc)[:500]}",
            seconds=time.monotonic() - began,
            at=at,
            replay_of=replay_of,
            root=root,
        )
        raise
    record(
        provider=str(getattr(chosen, "name", "")),
        model=str(getattr(chosen, "model", "")),
        request=payload,
        response=body,
        seconds=time.monotonic() - began,
        at=at,
        replay_of=replay_of,
        root=root,
    )
    return body


# --- the ids a block of code produced (Context.ask collects them for its run) ---

_COLLECTING: ContextVar[tuple[list[str], ...]] = ContextVar("trace_collect", default=())
"""The open `collect` blocks of this context. A ContextVar, so two agents in two
threads never see each other's ids; `chat._within` copies the context into its
worker thread, so ids written there still reach the caller's list."""


def _remember(trace_id: str) -> None:
    for bucket in _COLLECTING.get():
        bucket.append(trace_id)


class collect:
    """`with trace.collect() as ids:` — the ids of every trace written inside the block."""

    def __enter__(self) -> list[str]:
        self.ids: list[str] = []
        self._token = _COLLECTING.set((*_COLLECTING.get(), self.ids))
        return self.ids

    def __exit__(self, *_: object) -> None:
        _COLLECTING.reset(self._token)


# --- reading -------------------------------------------------------------------


def _files(root: Path, day: date | None) -> list[Path]:
    if day is not None:
        return [root / f"{day.isoformat()}.jsonl"]
    return sorted(root.glob("*.jsonl"))


def rows(
    *,
    day: date | None = None,
    agent: str = "",
    run: str = "",
    root: Path | None = None,
) -> Iterator[dict[str, Any]]:
    """Traces, oldest first, optionally for one UTC day, agent or run."""
    for path in _files(root or ROOT, day):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict):
                continue
            if agent and row.get("agent") != agent:
                continue
            if run and row.get("run") != run:
                continue
            yield row


def get(trace_id: str, root: Path | None = None) -> dict[str, Any] | None:
    return next((r for r in rows(root=root) if r.get("id") == trace_id), None)


def answer_text(response: dict[str, Any] | None) -> str:
    """The reply's text and any tool calls it asked for, as one readable string."""
    if not response:
        return ""
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    message = choices[0].get("message") or {}
    parts = [str(message.get("content") or "").strip()]
    for call in message.get("tool_calls") or []:
        function = call.get("function") or {}
        parts.append(f"[tool call] {function.get('name')}({function.get('arguments')})")
    return "\n".join(p for p in parts if p)


def prune(
    keep_days: int = KEEP_DAYS, *, today: date | None = None, root: Path | None = None
) -> int:
    """Delete trace files older than `keep_days`; returns how many went."""
    cutoff = (today or datetime.now(UTC).date()).toordinal() - keep_days
    gone = 0
    for path in (root or ROOT).glob("*.jsonl"):
        try:
            if date.fromisoformat(path.stem).toordinal() < cutoff:
                path.unlink()
                gone += 1
        except (ValueError, OSError):
            continue
    return gone


# --- replay --------------------------------------------------------------------


def _with_system(request: dict[str, Any], system: str) -> dict[str, Any]:
    messages = [dict(m) for m in request.get("messages") or []]
    if messages and messages[0].get("role") == "system":
        messages[0]["content"] = system
    else:
        messages.insert(0, {"role": "system", "content": system})
    return {**request, "messages": messages}


def replay(
    trace_id: str,
    *,
    provider: str = "",
    system: str | None = None,
    post: Callable[[Any, dict[str, Any]], dict[str, Any]] | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """Send a recorded request again; returns {before, after, diff, trace}."""
    from eulerlab.assistant import chat

    found = get(trace_id, root=root)
    if found is None:
        msg = f"no trace {trace_id}"
        raise KeyError(msg)
    request = dict(found.get("request") or {})
    if system is not None:
        request = _with_system(request, system)
    chosen = chat.selected_provider(name=provider or str(found.get("provider") or ""))
    request["model"] = chosen.model
    send = post or chat._send
    with collect() as ids:
        body = traced(send, chosen, request, replay_of=trace_id, root=root)
    before = answer_text(found.get("response"))
    after = answer_text(body)
    diff = "\n".join(
        difflib.unified_diff(
            before.splitlines(), after.splitlines(), "recorded", "replay", lineterm=""
        )
    )
    return {"before": before, "after": after, "diff": diff, "trace": ids[0] if ids else ""}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="make agent-replay", description=__doc__)
    parser.add_argument("--trace", default="", help="the trace id to send again")
    parser.add_argument("--provider", default="", help="another provider in config/llm.yaml")
    parser.add_argument("--system-file", default="", help="a file holding a new system prompt")
    parser.add_argument("--run", default="", help="list the traces of this run instead")
    args = parser.parse_args(argv)
    if args.run or not args.trace:
        for row in rows(run=args.run):
            if args.run or row.get("agent") != "assistant":
                print(
                    f"{row.get('id')}  {row.get('at')}  {row.get('agent')}/{row.get('run')}  "
                    f"{row.get('model')}  {row.get('seconds')}s  {row.get('error') or 'ok'}"
                )
        return 0
    system = Path(args.system_file).read_text(encoding="utf-8") if args.system_file else None
    out = replay(args.trace, provider=args.provider, system=system)
    print(out["diff"] or "The replay gave the same answer.")
    print(f"\nreplay trace: {out['trace']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
