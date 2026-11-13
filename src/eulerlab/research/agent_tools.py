"""The research loop's tools: what an agent may look up and test while it thinks (#162, ADR-186).

Before this, the autopilot asked the model once for ten rule specs and never
showed it a result before the cards were written. A researcher looks first:
what was tried near the idea, how a family has done, what a draft rule does
on the data. These tools let the model do that inside one run, through the
assistant's tool loop (`assistant.chat.ask`), under the same host, retention
and redaction locks, and each request kept in full (`llm/trace.py`).

| Tool | Reads | Writes |
|---|---|---|
| `signals` | the rule engine's vocabulary and spec shape | nothing |
| `claim_record` | the knowledge base (ADR-180), as the assistant's tool | nothing |
| `family_record` | the experiment store: per family, rules tried, passes, clean | nothing |
| `screen_rule` | the research panel, **to `discovery_end` only** | one experiment-store row |

**What keeps it honest.**

- `screen_rule` runs the engine's own screen with the data cut at the
  constitution's `discovery_end` (2023-12-31). The selection year and the forward
  test are never shown to the model (issue #152). The row it writes says so
  (`end` is the discovery end).
- Every screen is an experiment-store row (`purpose: screen`, `asked_by` the
  agent), so the firewall's count of rules tried and its noise bar grow with every
  look the agent takes. Searching more raises the agent's own bar.
- A rule already in the store is not screened again: its stored figures come back.
- At most `max_screens` screens a run; after that the tool says so.
- No tool reaches the gate, the trial ledger or the order path. This module is
  outside `agents/` so its imports are reviewed here, and an agent reaches it only
  through the runtime's `Context.converse`.

Nothing here decides anything. The cards the model writes at the end go through
the autopilot's own parse, lesson and repeat checks, and then the full screen
over the whole research window, as every other card does.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable, Collection, Mapping
from datetime import date, datetime
from typing import Any

from pydantic import ValidationError

from eulerlab.assistant import tools as assistant_tools
from eulerlab.assistant.tools import Tool
from eulerlab.intraday import rule_engine
from eulerlab.research import experiments

DEFAULT_SCREENS = 8
"""Screens one run may take. Each is a row in the store and so a little more bar."""

EngineFactory = Callable[[date], Any]
"""Builds an engine whose data ends on the given day. Tests pass a fake."""


def discovery_engine(end: date) -> rule_engine.Engine:
    """The research data with every bar after `end` dropped, not just entries.

    Cutting only the entry window would still let a swing entered in December
    2023 exit on a 2024 price, so the panel itself stops at `end`."""
    data = rule_engine.Data()
    data.panel = {
        symbol: {d: bar for d, bar in bars.items() if d <= end}
        for symbol, bars in data.panel.items()
    }
    data.sessions = [d for d in data.sessions if d <= end]
    data.index = {d: i for i, d in enumerate(data.sessions)}
    data.end = min(data.end, end)
    return rule_engine.Engine(data)


def _sharpe(block: Mapping[str, Any] | None) -> Any:
    return (block or {}).get("sharpe")


def brief(screen: Mapping[str, Any]) -> dict[str, Any]:
    """The figures a researcher reads first, from the engine's screen output."""
    years = screen.get("net_by_year") or {}
    positive = [y for y, v in years.items() if (v or {}).get("total_return", 0) > 0]
    return {
        "count": screen.get("count"),
        "net_bps_each": (screen.get("per_bps") or {}).get("net_mean"),
        "gross_bps_each": (screen.get("per_bps") or {}).get("gross_mean"),
        "net_sharpe": _sharpe(screen.get("net")),
        "halves_sharpe": [
            _sharpe((screen.get("halves") or {}).get("first")),
            _sharpe((screen.get("halves") or {}).get("second")),
        ],
        "sharpe_at_2x_costs": _sharpe(screen.get("net_at_2x_costs")),
        "years_positive": f"{len(positive)} of {len(years)}",
        "flags": [c.get("check") for c in screen.get("checks") or [] if c.get("flag")],
        "passes_screen": screen.get("passes_screen"),
        "clean": screen.get("clean"),
    }


class ResearchTools:
    """One run's tools. Holds its screen count and the engine it loaded."""

    def __init__(
        self,
        *,
        asked_by: str,
        discovery_end: date,
        now: datetime,
        max_screens: int = DEFAULT_SCREENS,
        engine: EngineFactory = discovery_engine,
    ) -> None:
        self.asked_by = asked_by
        self.discovery_end = discovery_end
        self.now = now
        self.max_screens = max_screens
        self._factory = engine
        self._engine: Any = None
        self.screened: list[dict[str, Any]] = []
        """Every screen this run took, in order: fingerprint, rule, family, figures."""
        self.calls: Counter[str] = Counter()
        self.tools: dict[str, Tool] = {
            "signals": Tool(
                "The rule engine's signals, their minimum lags, when each one's data starts, "
                "and the shape of a rule spec. Call this first.",
                {"type": "object", "properties": {}},
                self._signals,
            ),
            "claim_record": assistant_tools.TOOLS["claim_record"],
            "family_record": Tool(
                "How each family of rules has done in the experiment store: rules tried, "
                "how many passed the screen and how many were clean. A family is the kind "
                "(intraday or swing) and the signals it conditions on, e.g. "
                "'intraday:gap+results_morning'. Give words to filter, or none for all.",
                {
                    "type": "object",
                    "properties": {"match": {"type": "string", "description": "Part of a family."}},
                },
                self._family_record,
            ),
            "screen_rule": Tool(
                "Screen one draft rule on 2016 to the discovery end (2023-12-31) and get its "
                "trades, net bps each, net Sharpe, halves, Sharpe at 2x costs, years positive "
                "and bias flags. Every screen is recorded and counted against the search, so "
                f"screen only drafts worth it; at most {max_screens} a run. The argument is "
                "the rule's engine spec, as `signals` describes.",
                {
                    "type": "object",
                    "properties": {"spec": {"type": "object", "description": "The engine spec."}},
                    "required": ["spec"],
                },
                self._screen_rule,
            ),
        }

    # --- the Toolbox protocol (`assistant.chat.ask`) ---------------------------------

    def schemas(self, names: Collection[str] | None = None) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {"name": n, "description": t.description, "parameters": t.parameters},
            }
            for n, t in self.tools.items()
            if names is None or n in names
        ]

    def call(self, name: str, raw_arguments: str) -> str:
        tool = self.tools.get(name)
        if tool is None:
            return f"There is no tool '{name}'. Tools: {', '.join(self.tools)}."
        try:
            args = json.loads(raw_arguments) if raw_arguments.strip() else {}
        except json.JSONDecodeError:
            return "The arguments were not valid JSON."
        if not isinstance(args, dict):
            args = {}
        self.calls[name] += 1
        try:
            return assistant_tools._clip(tool.run(args))
        except Exception as exc:  # a broken tool tells the model; it does not end the run
            return f"{name} failed: {type(exc).__name__}: {str(exc)[:200]}"

    # --- the tools ---------------------------------------------------------------------

    def _signals(self, _: Mapping[str, Any]) -> str:
        from eulerlab.agents.workers import autopilot

        return f"Signals:\n{autopilot.vocabulary()}\n\n{autopilot.SPEC_HELP}"

    def _family_record(self, args: Mapping[str, Any]) -> str:
        match = str(args.get("match") or "").strip().lower()
        tally: dict[str, Counter[str]] = {}
        for row in experiments.rows(purpose="screen"):
            family = str(row.get("family") or "")
            if match and match not in family.lower():
                continue
            metrics = row.get("metrics") or {}
            t = tally.setdefault(family, Counter())
            t["tried"] += 1
            t["passed"] += bool(metrics.get("passes_screen"))
            t["clean"] += bool(metrics.get("clean"))
        if not tally:
            return "No screens recorded" + (f" for families like '{match}'." if match else ".")
        lines = [
            f"{f}: {c['tried']} tried, {c['passed']} passed the screen, {c['clean']} clean"
            for f, c in sorted(tally.items(), key=lambda x: -x[1]["tried"])
        ]
        return "Source: data/derived/experiments.jsonl (screens)\n" + "\n".join(lines)

    def _screen_rule(self, args: Mapping[str, Any]) -> str:
        raw = args.get("spec")
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except json.JSONDecodeError:
                return "The spec was not valid JSON."
        try:
            spec = rule_engine.RuleSpec.model_validate(raw)
        except ValidationError as exc:
            return f"The spec does not parse: {exc.errors()[0].get('msg', 'invalid')}"
        from eulerlab.research.autopilot import family_of  # the coverage-map cell, one definition

        fp = spec.fingerprint()
        for row in experiments.rows(purpose="screen"):
            if row.get("fingerprint") == fp:
                return (
                    f"Already screened ({row.get('asked_by')}, {row.get('at')}, window "
                    f"{row.get('first')} to {row.get('end')}): "
                    + json.dumps(row.get("metrics") or {}, default=str)[:1500]
                    + "\nNot screened again. Try a different rule."
                )
        if len(self.screened) >= self.max_screens:
            return f"This run has used its {self.max_screens} screens. Write the cards now."
        if self._engine is None:
            self._engine = self._factory(self.discovery_end)
        engine = self._engine
        last = min(engine.data.end, engine.data.sessions[-1]) if engine.data.sessions else None
        if last is None or engine.data.sessions[-1] > self.discovery_end:
            msg = f"the loop's data reaches {engine.data.sessions[-1] if last else 'nothing'}, after the discovery end {self.discovery_end}"
            raise experiments.SealedPeriod(msg)
        out = engine.screen(spec)
        daily = engine.returns.pop(fp, None)
        figures = brief(out)
        experiments.record(
            purpose="screen",
            hypothesis="",
            fingerprint=fp,
            family=family_of(spec),
            first=spec.first,
            end=last,
            metrics={**figures, "explore": True},
            daily=daily,
            asked_by=self.asked_by,
            now=self.now,
        )
        self.screened.append(
            {"fingerprint": fp, "rule": spec.describe(), "family": family_of(spec), **figures}
        )
        left = self.max_screens - len(self.screened)
        return (
            f"Rule: {spec.describe()}\nWindow: {spec.first} to {last} (discovery only)\n"
            + json.dumps(figures, default=str)
            + f"\n{left} screen(s) left this run."
        )
