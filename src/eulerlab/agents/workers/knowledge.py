"""The knowledge agent: precise answers about what Euler Lab holds, each with its source.

It is the assistant (ADR-064) with stricter instructions and three more tools
(`search_knowledge`, `data_quality`, `agent_outputs`). Same read-only tools,
same host locks, same redaction. What it adds is the rule that makes an answer
checkable: **every number comes from a tool call made for this question, and
the answer ends with the files it came from.** When the model leaves the
sources off, the code appends the tools it actually called, so the operator
can always see where an answer was looked up.

**Checked by code (ADR-088).** Every number, id and path in the answer must
appear in what the tools returned (`agents/grounding.py`). If one does not,
the model is told exactly which ones and asked once more, with the tools. If
the second answer still has one, the operator gets "not held" and the
unsupported figures, never the made-up answer; it is kept in the output for
the record.

Run with no question, it only rebuilds the search index (after the close, so
the day's new papers, cards and grades are searchable).
"""

from __future__ import annotations

from typing import Any

from eulerlab.agents import grounding, knowledge_index
from eulerlab.agents.runtime import BudgetSpent, Context, Item, WorkerResult, resolve_provider

SYSTEM = """You are the knowledge agent of Euler Lab, one person's quant research and trading platform for Indian markets.
You answer questions about what the platform holds: its research papers, idea cards (hypotheses), backtest results, datasets and their quality grades, decisions, runbooks and history.

How you answer:
- Look everything up with the tools first. Start with `search_knowledge`, then read what it points to.
- Every number, date and name you state must come from a tool result in this conversation. Never from memory.
- If the tools do not hold the answer, say "not held" and say what would hold it.
- Lead with the answer in one or two sentences. Then the detail, short.
- End with a line "Sources:" and the paths or ids you read, one per line.
- Plain text. No markdown tables or headings. "-" for lists.
- You only read. You cannot backtest, register, trade or change anything.
- Entries of kind "quantpedia" are Quantpedia's catalogue: their numbers come from the paper or from Quantpedia, never from this platform. Say so whenever you quote one.
- A backtest result is not a forecast. No investment advice."""


def _sources(used: list[dict[str, Any]]) -> list[str]:
    seen: list[str] = []
    for call in used:
        line = f"{call.get('tool')} {str(call.get('arguments', ''))[:80]}".strip()
        if line not in seen:
            seen.append(line)
    return seen


def run(ctx: Context) -> WorkerResult:
    entries = knowledge_index.load(root=ctx.root)
    question = str(ctx.args.get("question") or "").strip()
    if not question:
        kinds: dict[str, int] = {}
        for e in entries:
            kinds[e.kind] = kinds.get(e.kind, 0) + 1
        parts = ", ".join(f"{v} {k}s" for k, v in sorted(kinds.items()))
        return WorkerResult(f"index holds {len(entries)} entries: {parts}", data={"kinds": kinds})

    from eulerlab.assistant import chat
    from eulerlab.llm import client

    chosen = chat.selected_provider(name=resolve_provider(ctx.agent.spec.provider))
    ctx.model = f"{chosen.name}:{chosen.model}"

    def counted(provider: client.Provider, payload: dict[str, Any]) -> dict[str, Any]:
        if ctx.requests >= ctx.budget_left:
            msg = f"knowledge has used its {ctx.agent.daily_requests} requests for today"
            raise BudgetSpent(msg)
        ctx.requests += 1
        ctx.step(f"Asking {ctx.model} (request {ctx.requests})", "model")
        return chat._post(provider, payload)

    history = ctx.args.get("history") or []
    turns = [t for t in history if isinstance(t, dict)] if isinstance(history, list) else []
    system = SYSTEM + (f"\n\nThe operator's brief:\n{ctx.brief}" if ctx.brief else "")
    ctx.prompts.append(grounding.prompt_version(system))
    asked = [*turns, {"role": "user", "content": question}]
    answer = chat.ask(asked, post=counted, chosen=chosen, system=system)
    evidence = list(answer.evidence)
    used = list(answer.used)
    ctx.step(f"Checking every figure in the answer against what {len(used)} tool calls returned")
    found = grounding.check(answer.text, evidence, question)
    first = answer.text
    retried = False
    if not found.ok:
        retried = True
        ctx.notes.append(
            f"first answer had figures no tool returned: {', '.join(found.unsupported)}"
        )
        again = chat.ask(
            [
                *asked,
                {"role": "assistant", "content": answer.text},
                {
                    "role": "user",
                    "content": (
                        "These figures in your answer are in no tool result: "
                        + ", ".join(found.unsupported)
                        + '. Look them up with the tools, or remove them and say "not held". '
                        "Answer the original question again."
                    ),
                },
            ],
            post=counted,
            chosen=chosen,
            system=system,
        )
        evidence += again.evidence
        used += again.used
        answer = again
        found = grounding.check(answer.text, evidence, question)
    text = answer.text
    if not found.ok:
        text = (
            "Not held: the model's answer used figures no tool returned "
            f"({', '.join(found.unsupported)}), so it was withheld. "
            "Ask more narrowly, or look in the sources it searched."
        )
    answer = chat.Answer(text, answer.provider, answer.model, answer.host, used, evidence)
    looked = _sources(answer.used)
    if "sources:" not in text.lower() and looked:
        text += "\n\nSources (tools called):\n" + "\n".join(f"- {s}" for s in looked)
    if not answer.used:
        ctx.notes.append("the model answered without calling a tool; treat the answer as unchecked")
    return WorkerResult(
        text.splitlines()[0][:200] if text else "no answer",
        [Item(kind="answer", title=question[:200], body=text, data={"tools": answer.used})],
        data={
            "question": question,
            "answer": text,
            "tools": answer.used,
            "host": answer.host,
            "grounding": {
                "checked": found.checked,
                "unsupported": found.unsupported,
                "retried": retried,
                "withheld": not found.ok,
            },
            "first_answer": first if retried else "",
        },
    )
